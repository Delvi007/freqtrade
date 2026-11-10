"""Supervisor de procesos de TITAN (C9).

  · Registro de todos los procesos de fondo con su PRIORIDAD: 1 crítico (ejecución, riesgo, sincronización con brokers),
    2 datos (velas, noticias), 3 investigación (cerebro autónomo, laboratorio). Lo crítico nunca cede recursos a lo experimental.
  · Mide en tiempo real CPU (por hilo, con psutil) y memoria del proceso y del equipo.
  · Recuperación automática: si un proceso que debe estar en marcha se cae, lo reinicia con espera creciente.
  · Carga dinámica: si el equipo pasa del 85 % de CPU o le quedan menos de 400 MB de RAM libre, PAUSA la investigación
    (prioridad 3) y la reanuda con CPU < 60 % y más de 700 MB libres. Se mide la memoria LIBRE real y no el porcentaje:
    en equipos de 8 GB Windows suele estar al 85–90 % de forma normal y un umbral por porcentaje la pausaba para siempre.
    Nunca fuerza el equipo al 100 % artificialmente.
  · Controles: iniciar, detener, pausar y reanudar cada proceso, respetando dependencias.
"""
import threading
import time
from collections import deque

from . import db

CLAVE = "supervisor_deseado"
EVENTOS = deque(maxlen=400)
ESTADO = {"vivo": False, "ts": None, "sistema": {}, "pausa_por_carga": False, "error": None}
_PARAR = threading.Event()
_REINICIOS = {}
_PAUSADOS = set()
_CPU_PREV = {"t": None, "hilos": {}}
CPU_PAUSA, CPU_REANUDA = 85, 60            # % de CPU del equipo
LIBRE_PAUSA, LIBRE_REANUDA = 400, 700      # MB de RAM libre del equipo


def _evento(proceso, tipo, detalle):
    EVENTOS.appendleft({"ts": int(time.time()), "proceso": proceso, "tipo": tipo, "detalle": str(detalle)[:300]})


# ------------------------------------------------------------------------------------------------ registro de procesos
def _autotrader():
    from .trader import autotrader as a
    return {"iniciar": a.iniciar_hilo, "detener": lambda: a._HILO.__setitem__("parar", True), "vivo": a.hilo_vivo,
            "error": lambda: a._HILO.get("error")}


def _recolector():
    from . import recolector_continuo as r
    return {"iniciar": r.iniciar, "detener": r.detener, "vivo": lambda: any(v["vivo"] for v in r.estado().values()),
            "error": lambda: "; ".join(f"{k}: {v['error']}" for k, v in r.estado().items() if v.get("error")) or None}


def _noticias():
    from .noticias import recolector as r
    return {"iniciar": r.iniciar, "detener": r.detener, "vivo": lambda: r.ESTADO["vivo"], "error": lambda: r.ESTADO.get("error")}


def _brokers():
    from .brokers import centro as c
    return {"iniciar": c.iniciar, "detener": c.detener, "vivo": lambda: c.ESTADO["vivo"], "error": lambda: c.ESTADO.get("error")}


def _cerebro():
    from .ia import cerebro as c
    return {"iniciar": c.iniciar, "detener": c.detener, "vivo": lambda: c.ESTADO["vivo"], "error": lambda: c.ESTADO.get("error")}


def _laboratorio():
    import lab_engine
    return {"iniciar": lab_engine.iniciar, "detener": None, "vivo": lambda: any(h and h.is_alive() for h in lab_engine._HILOS.values()),
            "error": lambda: None}


def _planes():
    import plan_web
    return {"iniciar": plan_web.iniciar_vigilante, "detener": None,
            "vivo": lambda: any(t.name == "titan-vigilante-planes" and t.is_alive() for t in threading.enumerate()), "error": lambda: None}


PROCESOS = {
    "autotrader": {"nombre": "Bots operadores (autotrader)", "prioridad": 1, "prefijos": ("titan-autotrader",), "f": _autotrader, "depende": (),
                   "funcion": "Ciclo de los 4 bots: escáner, controles de riesgo, envío y conciliación de órdenes con cTrader e IQ Option."},
    "brokers": {"nombre": "Sincronización de brokers", "prioridad": 1, "prefijos": ("titan-brokers-sync",), "f": _brokers, "depende": (),
                "funcion": "Trae de cada broker encendido su cuenta, posiciones, órdenes y ejecuciones (el broker es la fuente de verdad)."},
    "recolector": {"nombre": "Recolector de velas", "prioridad": 2, "prefijos": ("titan-recolector-",), "f": _recolector, "depende": (),
                   "funcion": "Descarga continua de velas de cTrader e IQ Option en todas las temporalidades."},
    "noticias": {"nombre": "Centro de noticias", "prioridad": 2, "prefijos": ("titan-noticias",), "f": _noticias, "depende": (),
                 "funcion": "Recopila y analiza fuentes oficiales, medios y cripto; calendario económico."},
    "cerebro": {"nombre": "Cerebro autónomo", "prioridad": 3, "prefijos": ("titan-cerebro",), "f": _cerebro, "depende": (),
                "funcion": "Evaluación bayesiana de estrategias con resultados reales, deterioro, patrones de pérdida, régimen y recomendaciones."},
    "laboratorio": {"nombre": "Laboratorio heredado", "prioridad": 3, "prefijos": ("titan-lab-",), "f": _laboratorio, "depende": (),
                    "funcion": "Laboratorio de aprendizaje anterior (motores A/B desactivados; archivo)."},
    "planes": {"nombre": "Vigilante de planes", "prioridad": 3, "prefijos": ("titan-vigilante-planes",), "f": _planes, "depende": (),
               "funcion": "Vigila los planes de análisis guardados."},
}


def deseado():
    d = db.cfg_sistema(CLAVE, None) or {}
    return {k: bool(d.get(k, True)) for k in PROCESOS}


def _poner_deseado(nombre, valor):
    d = deseado()
    d[nombre] = bool(valor)
    db.set_cfg_sistema(CLAVE, d)


def permitido(nombre):
    """Los procesos de investigación consultan esto antes de cada tarea pesada (pausa manual o por carga)."""
    if nombre in _PAUSADOS:
        return False
    return not (ESTADO["pausa_por_carga"] and PROCESOS.get(nombre, {}).get("prioridad", 3) >= 3)


def _vivo(nombre):
    try:
        return bool(PROCESOS[nombre]["f"]()["vivo"]())
    except Exception:
        return False


# ------------------------------------------------------------------------------------------------ métricas reales
def metricas():
    out = {"cpu_sistema": None, "ram_sistema": None, "ram_libre_mb": None, "ram_proceso_mb": None, "hilos": threading.active_count(), "por_proceso": {}, "nucleos": None}
    try:
        import psutil
    except ImportError:
        out["nota"] = "psutil no instalado: sin métricas de CPU/RAM"
        return out
    p = psutil.Process()
    vm = psutil.virtual_memory()
    out.update(cpu_sistema=psutil.cpu_percent(interval=None), ram_sistema=vm.percent, ram_libre_mb=round(vm.available / 2 ** 20),
               ram_proceso_mb=round(p.memory_info().rss / 1e6, 1), nucleos=psutil.cpu_count())
    ahora = time.time()
    tiempos = {t.id: t.user_time + t.system_time for t in p.threads()}
    nombres = {t.native_id: t.name for t in threading.enumerate() if t.native_id}
    prev, dt = _CPU_PREV["hilos"], (ahora - _CPU_PREV["t"]) if _CPU_PREV["t"] else None
    for clave, proc in PROCESOS.items():
        ids = [tid for tid, n in nombres.items() if any(n.startswith(pf) for pf in proc["prefijos"])]
        cpu = None
        if dt and dt > 0:
            cpu = round(sum(max(0.0, tiempos.get(i, 0) - prev.get(i, tiempos.get(i, 0))) for i in ids) / dt * 100, 1)
        out["por_proceso"][clave] = {"hilos": len(ids), "cpu_pct": cpu}
    _CPU_PREV.update(t=ahora, hilos=tiempos)
    return out


# ------------------------------------------------------------------------------------------------ control
def controlar(nombre, accion, uid=None):
    if nombre not in PROCESOS:
        raise ValueError("Proceso desconocido.")
    p = PROCESOS[nombre]
    f = p["f"]()
    if accion == "iniciar":
        for dep in p["depende"]:
            if not _vivo(dep):
                raise ValueError(f"Inicia antes «{PROCESOS[dep]['nombre']}» (dependencia).")
        _poner_deseado(nombre, True)
        _PAUSADOS.discard(nombre)
        f["iniciar"]()
    elif accion == "detener":
        dependientes = [k for k, v in PROCESOS.items() if nombre in v["depende"] and _vivo(k)]
        if dependientes:
            raise ValueError("Detén antes: " + ", ".join(PROCESOS[k]["nombre"] for k in dependientes))
        if not f.get("detener"):
            raise ValueError("Este proceso heredado no admite detención en caliente (se detiene al reiniciar TITAN).")
        _poner_deseado(nombre, False)
        f["detener"]()
    elif accion == "pausar":
        _PAUSADOS.add(nombre)
    elif accion == "reanudar":
        _PAUSADOS.discard(nombre)
    else:
        raise ValueError("Acción no válida.")
    _evento(nombre, accion, "por el usuario")
    if uid:
        db.auditar(uid, f"proceso_{accion}", "supervisor", nombre)
    return estado()


def estado():
    d = deseado()
    if not ESTADO.get("ts") or time.time() - ESTADO["ts"] > 30:       # supervisor parado o atrasado: se mide bajo demanda
        ESTADO["metricas"] = metricas()
        ESTADO["ts"] = int(time.time())
    m = ESTADO.get("metricas") or {}
    out = []
    for k, p in PROCESOS.items():
        try:
            err = p["f"]()["error"]()
        except Exception as e:
            err = f"{type(e).__name__}"
        vivo = _vivo(k)
        out.append({"id": k, "nombre": p["nombre"], "prioridad": p["prioridad"], "funcion": p["funcion"], "deseado": d[k], "vivo": vivo,
                    "pausado": k in _PAUSADOS or (ESTADO["pausa_por_carga"] and p["prioridad"] >= 3), "error": err,
                    "reinicios": _REINICIOS.get(k, {}).get("n", 0), "depende": list(p["depende"]),
                    **(m.get("por_proceso", {}).get(k) or {})})
    return {"procesos": out, "sistema": {k: v for k, v in m.items() if k != "por_proceso"}, "pausa_por_carga": ESTADO["pausa_por_carga"],
            "vivo": ESTADO["vivo"], "eventos": list(EVENTOS)[:80]}


def vigilar():
    """Un paso de supervisión: métricas, carga dinámica y recuperación de procesos caídos."""
    m = metricas()
    ESTADO["metricas"] = m
    cpu, ram, libre = m.get("cpu_sistema"), m.get("ram_sistema"), m.get("ram_libre_mb")
    if cpu is not None:
        if libre is None:                                    # métricas antiguas/simuladas en pruebas: deduce por porcentaje
            libre = LIBRE_REANUDA + 1 if (ram or 0) < 90 else 0
        if not ESTADO["pausa_por_carga"] and (cpu > CPU_PAUSA or libre < LIBRE_PAUSA):
            ESTADO["pausa_por_carga"] = True
            _evento("sistema", "carga_alta", f"CPU {cpu} % · RAM {ram} % ({libre} MB libres): se pausa la investigación (prioridad 3)")
        elif ESTADO["pausa_por_carga"] and cpu < CPU_REANUDA and libre > LIBRE_REANUDA:
            ESTADO["pausa_por_carga"] = False
            _evento("sistema", "carga_normal", f"CPU {cpu} % · RAM {ram} % ({libre} MB libres): se reanuda la investigación")
    d = deseado()
    ahora = time.time()
    for k, p in PROCESOS.items():
        if not d[k] or _vivo(k):
            continue
        r = _REINICIOS.setdefault(k, {"n": 0, "proximo": 0})
        if ahora < r["proximo"]:
            continue
        try:
            p["f"]()["iniciar"]()
            r["n"] += 1
            r["proximo"] = ahora + min(600, 30 * 2 ** min(5, r["n"]))
            _evento(k, "reinicio", f"proceso caído: reiniciado (intento {r['n']})")
        except Exception as e:
            r["proximo"] = ahora + 120
            _evento(k, "error", f"no se pudo reiniciar: {type(e).__name__}: {str(e)[:150]}")
    ESTADO["ts"] = int(ahora)


def _bucle():
    ESTADO["vivo"] = True
    try:
        import psutil
        psutil.cpu_percent(interval=None)        # primera lectura de referencia
    except ImportError:
        pass
    while not _PARAR.is_set():
        try:
            vigilar()
            ESTADO["error"] = None
        except Exception as e:
            ESTADO["error"] = f"{type(e).__name__}: {e}"[:200]
        _PARAR.wait(15)
    ESTADO["vivo"] = False


def iniciar():
    if not ESTADO["vivo"]:
        _PARAR.clear()
        threading.Thread(target=_bucle, name="titan-supervisor", daemon=True).start()
        _evento("supervisor", "inicio", "supervisor en marcha")


def detener():
    _PARAR.set()
