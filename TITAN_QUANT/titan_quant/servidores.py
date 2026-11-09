"""TITAN QUANT ENGINE SERVER CENTER (C8): estado REAL de cada motor, proceso y broker como un «servidor» con 5 LED.

LED (siempre a partir de datos reales; nunca actividad simulada):
    1 ejecución       ok = funcionando · error = última ejecución con error / proceso caído · espera = sin ejecutar aún
    2 datos           actividad = procesó datos hace < 2 min · ok = < 1 h · espera = más antiguo
    3 inteligencia    actividad/ok según la última inferencia (motores de análisis, cerebro, noticias)
    4 conectividad    ok = su fuente externa responde · error = desconectada · apagado = no usa red
    5 aprendizaje     ok = escribió resultados/estado · advertencia = errores acumulados · apagado = no aplica
Estados: ok · actividad (parpadea) · espera · advertencia · error · apagado.
"""
import inspect
import json
import time

from . import db

INICIO = int(time.time())
ANALITICOS = {"technical", "cross_asset", "macro", "statistical", "ml", "regime", "microstructure", "news", "risk", "backtesting", "montecarlo",
              "portfolio", "research", "fusion", "adaptive"}
APRENDEN = {"ml", "backtesting", "research", "adaptive", "fusion"}


def _led(estado, texto):
    return {"estado": estado, "texto": texto}


def _reciente(ts, ahora):
    if not ts:
        return "espera"
    d = ahora - ts
    return "actividad" if d < 120 else "ok" if d < 3600 else "espera"


def motores(ahora):
    from .motores import base as mb, nucleo  # noqa: F401 (registra los motores)
    est = {r["motor"]: r for r in db.q("SELECT * FROM estado_motores")}
    conect = {"datos": None}
    try:
        from . import recolector_continuo
        conect["datos"] = any(v["vivo"] for v in recolector_continuo.estado().values())
    except Exception:
        pass
    try:
        from .noticias import almacen as na
        conect["noticias"] = (na.q1("SELECT COUNT(*) n FROM fuentes WHERE estado='conectada'") or {}).get("n", 0) > 0
    except Exception:
        conect["noticias"] = None
    out = []
    for m in sorted(mb.REGISTRO.values(), key=lambda x: x.numero):
        e = est.get(m.id) or {}
        ts = e.get("ts")
        red = "red" in (m.consumo or "")
        if not e:
            l1 = _led("espera", "aún sin ejecutar (se ejecuta bajo demanda)")
        elif e.get("estado") == "error":
            l1 = _led("error", (e.get("error") or "error en la última ejecución")[:160])
        elif e.get("estado") in ("sin_datos", "aplazado"):
            l1 = _led("advertencia", f"última ejecución: {e['estado']}")
        else:
            l1 = _led("ok", f"última ejecución {e.get('estado')} en {e.get('duracion_ms')} ms")
        l2 = _led(_reciente(ts, ahora), f"último proceso de datos hace {int((ahora - ts) / 60)} min" if ts else "sin datos procesados")
        l3 = _led(_reciente(ts, ahora) if m.id in ANALITICOS else "apagado", "inferencia en el último análisis" if m.id in ANALITICOS else "no hace inferencia")
        if not red:
            l4 = _led("apagado", "no usa red")
        else:
            fuente = conect["noticias"] if m.id in ("news", "macro") else conect["datos"]
            l4 = _led("ok" if fuente else "error" if fuente is False else "espera", "fuente externa conectada" if fuente else "fuente externa sin conexión" if fuente is False else "sin comprobar")
        if m.id in APRENDEN:
            l5 = _led("advertencia" if (e.get("errores") or 0) > 0 else ("ok" if e else "espera"), f"{e.get('ejecuciones', 0)} ejecuciones · {e.get('errores', 0)} errores")
        else:
            l5 = _led("ok" if e else "espera", f"estado guardado ({e.get('ejecuciones', 0)} ejecuciones)")
        out.append({"id": "motor:" + m.id, "tipo": "motor", "numero": m.numero, "nombre": m.nombre, "version": "7.2.1", "leds": [l1, l2, l3, l4, l5],
                    "resumen": {"ejecuciones": e.get("ejecuciones", 0), "errores": e.get("errores", 0), "ultimo_ts": ts, "duracion_ms": e.get("duracion_ms")}})
    return out


def procesos(ahora):
    from . import supervisor
    s = supervisor.estado()
    out = []
    for p in s["procesos"]:
        vivo, pausado = p["vivo"], p["pausado"]
        l1 = _led("ok" if vivo and not pausado else "advertencia" if pausado else ("error" if p["deseado"] else "apagado"),
                  "en marcha" if vivo and not pausado else "pausado" if pausado else ("caído: el supervisor lo reiniciará" if p["deseado"] else "detenido"))
        cpu = p.get("cpu_pct")
        l2 = _led("actividad" if (cpu or 0) > 0.5 else ("ok" if vivo else "apagado"), f"CPU {cpu} % · {p.get('hilos', 0)} hilos" if cpu is not None else "sin medición aún")
        l3 = _led(("actividad" if (cpu or 0) > 0.5 else "ok") if vivo and p["id"] in ("cerebro", "autotrader", "noticias") else "apagado",
                  "inferencia/decisión activa" if p["id"] in ("cerebro", "autotrader", "noticias") else "no hace inferencia")
        l4 = _led("error" if p.get("error") else ("ok" if vivo else "apagado"), (p.get("error") or "sin errores")[:160])
        l5 = _led("advertencia" if p["reinicios"] else ("ok" if vivo else "apagado"), f"{p['reinicios']} reinicios automáticos")
        out.append({"id": "proceso:" + p["id"], "tipo": "proceso", "nombre": p["nombre"], "version": "7.2.1", "prioridad": p["prioridad"],
                    "leds": [l1, l2, l3, l4, l5], "control": True, "vivo": vivo, "pausado": pausado, "deseado": p["deseado"],
                    "resumen": {"funcion": p["funcion"], "cpu_pct": cpu, "hilos": p.get("hilos"), "reinicios": p["reinicios"], "error": p.get("error")}})
    return out, s


def brokers(uid, ahora):
    from .brokers import centro
    from .seguridad import interruptores
    out = []
    try:
        filas = centro.panel(uid)
    except Exception:
        filas = []
    for b in filas:
        if not (b["habilitado"] or b["id"] in ("ctrader", "iqoption")):
            continue
        activo = b["id"] in ("ctrader", "iqoption")
        ok = b["conectado"] or activo
        perm = interruptores.permitido(b["id"])[0]
        out.append({"id": "broker:" + b["id"], "tipo": "broker", "nombre": b["nombre"], "version": b["verificacion"],
                    "leds": [_led("ok" if perm else "error", "habilitado" if perm else "bloqueado por seguridad"),
                             _led(_reciente(b.get("ultima_sync_ts"), ahora) if not activo else "ok", "sincronización con el broker"),
                             _led("apagado", "no hace inferencia"),
                             _led("ok" if ok else ("error" if b.get("ultimo_error") else "espera"), (b.get("ultimo_error") or b.get("detalle_estado") or "en producción" if activo else b.get("ultimo_error") or "sin probar")[:160]),
                             _led("ok" if b.get("ejecuciones") or activo else "espera", f"{b.get('ejecuciones', 0)} ejecuciones sincronizadas")],
                    "resumen": {"conector": b["conector"], "entorno": b["entorno"], "latencia_ms": b.get("latencia_ms"), "capacidades": b.get("capacidades")}})
    return out


def centro(uid):
    ahora = int(time.time())
    procs, sup = procesos(ahora)
    return {"servidores": procs + motores(ahora) + brokers(uid, ahora), "sistema": sup["sistema"], "pausa_por_carga": sup["pausa_por_carga"],
            "eventos": sup["eventos"], "inicio_ts": INICIO, "ahora": ahora}


def detalle(uid, sid):
    tipo, _, clave = sid.partition(":")
    if tipo == "motor":
        from .motores import base as mb
        m = mb.REGISTRO.get(clave)
        if not m:
            raise ValueError("Motor desconocido.")
        e = db.q1("SELECT * FROM estado_motores WHERE motor=?", (clave,)) or {}
        ficha = m.ficha()
        mod = inspect.getmodule(type(m))
        return {"id": sid, "tipo": "motor", "identidad": {"numero": m.numero, "id": m.id, "nombre": m.nombre, "version": "7.2.1"}, "ficha": ficha,
                "archivo": (mod.__file__ or "").split("TITAN_QUANT")[-1] if mod else None, "estado": e,
                "detalle_ultimo": json.loads(e["detalle"]) if (e.get("detalle") or "").startswith(("{", "[")) else e.get("detalle"),
                "recursos": "Se ejecuta bajo demanda dentro del proceso de análisis: su coste es la duración por ejecución (latencia).",
                "tiempo_activo_s": int(time.time()) - INICIO}
    if tipo == "proceso":
        from . import supervisor
        p = next((x for x in supervisor.estado()["procesos"] if x["id"] == clave), None)
        if not p:
            raise ValueError("Proceso desconocido.")
        return {"id": sid, "tipo": "proceso", "identidad": {"id": clave, "nombre": p["nombre"], "prioridad": p["prioridad"]}, "estado": p,
                "eventos": [e for e in supervisor.EVENTOS if e["proceso"] == clave][:50], "sistema": supervisor.estado()["sistema"],
                "tiempo_activo_s": int(time.time()) - INICIO}
    if tipo == "broker":
        from .brokers import catalogo, centro as bc
        return {"id": sid, "tipo": "broker", "identidad": catalogo.por_id(clave), "actividad": bc.actividad(uid, clave, 50),
                "estado": next((b for b in bc.panel(uid) if b["id"] == clave), None)}
    raise ValueError("Servidor desconocido.")
