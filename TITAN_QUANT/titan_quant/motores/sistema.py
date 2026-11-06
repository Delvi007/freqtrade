"""Motores de sistema: 18 ADAPTIVE PROCESSING, 19 HARDWARE DIAGNOSTICS, 20 MONITORING, 21 API, 22 WEB DASHBOARD, 23 TELEGRAM."""
import json
import threading
import time
import urllib.request

from .. import config, db, recursos
from .base import REGISTRO, Motor, SinDatos, registrar


@registrar
class MotorAdaptativo(Motor):
    numero, id, nombre = 18, "adaptive", "ADAPTIVE PROCESSING ENGINE"
    objetivo = "Ajustar la carga de cada ejecución al hardware real sin cambiar el nivel elegido por el usuario."
    metodos = "Reglas sobre memoria libre, núcleos y carga: reduce concurrencia, simulaciones y velas, y deja constancia de cada recorte."
    entradas = ("diagnóstico de hardware", "nivel", "política")
    salidas = ("parametros_efectivos", "ajustes")
    dependencias = ()

    def calcular(self, ctx):
        aj = ctx.get("ajustes_adaptativos", [])
        return {"salida": {"nivel": ctx["p"]["id"], "politica": ctx.get("politica"), "ajustes": aj,
                           "concurrencia": ctx["p"]["concurrencia"], "montecarlo_sim": ctx["p"]["montecarlo_sim"],
                           "backtest_barras": ctx["p"]["backtest_barras"]},
                "estado": "simplificado" if aj else "completado", "notas": aj}


@registrar
class MotorHardware(Motor):
    numero, id, nombre = 19, "hardware", "HARDWARE DIAGNOSTICS ENGINE"
    objetivo = "Medir CPU, memoria, almacenamiento, temperatura, red y procesos del dispositivo."
    metodos = "Lectura directa de /proc y /sys; latencia con una conexión TCP a la fuente de datos. Lo que no es accesible se informa como no disponible."
    salidas = ("diagnostico", "nivel_recomendado")

    def calcular(self, ctx):
        d = ctx.get("diagnostico") or recursos.diagnostico(red=False)
        rec = recursos.recomendar_nivel(d)
        falt = []
        if d["temperatura"]["max_c"] is None:
            falt.append("temperatura (sin sensores accesibles)")
        return {"salida": {"diagnostico": d, "recomendacion": rec}, "faltantes": falt}


@registrar
class MotorMonitoreo(Motor):
    numero, id, nombre = 20, "monitoring", "MONITORING ENGINE"
    objetivo = "Vigilar el estado de los motores, hilos de fondo y bases de datos."
    metodos = "Último estado y errores de cada motor (estado_motores), hilos vivos del servidor, vigilante de planes y laboratorio, integridad SQLite."
    en_analisis = False
    salidas = ("motores", "hilos", "bases")

    def calcular(self, ctx):
        return {"salida": estado_sistema(rapido=True)}


@registrar
class MotorAPI(Motor):
    numero, id, nombre = 21, "api", "API ENGINE"
    objetivo = "Exponer los motores y datos por HTTP con autenticación, CSRF y límites."
    metodos = "Servidor HTTP de la biblioteca estándar con sesiones, protección CSRF por doble envío y límite de peticiones por IP."
    en_analisis = False

    def calcular(self, ctx):
        from .. import servidor
        return {"salida": {"rutas": sorted(servidor.RUTAS_PUBLICAS | set(servidor.RUTAS_GET) | set(servidor.RUTAS_POST)),
                           "host": config.HOST, "puerto": config.PUERTO, "https": config.HTTPS}}


@registrar
class MotorWeb(Motor):
    numero, id, nombre = 22, "web", "WEB DASHBOARD"
    objetivo = "Servir la interfaz web integrada dentro del proyecto."
    metodos = "Archivos estáticos de web/ servidos por la API; sin secretos en el navegador."
    en_analisis = False

    def calcular(self, ctx):
        idx = config.WEB / "index.html"
        if not idx.exists():
            raise SinDatos("Falta web/index.html")
        return {"salida": {"index_kb": round(idx.stat().st_size / 1024), "archivos": sorted(p.name for p in config.WEB.iterdir())}}


# --------------------------------------------------------------------------- 23 Telegram
def _credenciales_telegram():
    """Token del propietario en la bóveda; si no, los archivos heredados .telegram_token/.telegram_chat."""
    from ..seguridad import boveda
    dueno = db.q1("SELECT id FROM usuarios WHERE rol='propietario' ORDER BY id LIMIT 1")
    if dueno:
        try:
            c = boveda.leer(dueno["id"], "telegram")
            if c.get("token") and c.get("chat_id"):
                return c["token"], c["chat_id"], "boveda"
        except Exception:
            pass
    t, ch = config.RAIZ / ".telegram_token", config.RAIZ / ".telegram_chat"
    if t.exists() and ch.exists():
        return t.read_text().strip(), ch.read_text().strip(), "archivo_heredado"
    return None, None, None


def enviar_telegram(texto, espera=15):
    try:
        token, chat, origen = _credenciales_telegram()
    except Exception as e:          # p. ej. base no disponible: no tumbar el hilo
        return False, type(e).__name__
    finally:
        if threading.current_thread() is not threading.main_thread():
            db.cerrar_hilo()
    if not token:
        return False, "Telegram no configurado"
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage",
                                 data=json.dumps({"chat_id": chat, "text": texto[:3900]}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=espera) as r:
            ok = json.loads(r.read().decode()).get("ok", False)
        return ok, origen
    except Exception as e:
        return False, type(e).__name__          # nunca el token


def enviar_telegram_fondo(texto):
    threading.Thread(target=enviar_telegram, args=(texto,), daemon=True).start()


@registrar
class MotorTelegram(Motor):
    numero, id, nombre = 23, "telegram", "TELEGRAM NOTIFICATION ENGINE"
    objetivo = "Enviar alertas importantes al chat autorizado y mantener el bot de Telegram existente."
    metodos = "API HTTP de Telegram (sendMessage) con el token de la bóveda cifrada; el bot interactivo existente (titan_bot.py) sigue igual."
    en_analisis = False

    def calcular(self, ctx):
        token, chat, origen = _credenciales_telegram()
        return {"salida": {"configurado": bool(token), "origen_credenciales": origen,
                           "nota": "El token nunca se devuelve al navegador."}}


# --------------------------------------------------------------------------- estado global
def estado_sistema(rapido=False):
    filas = {r["motor"]: r for r in db.q("SELECT * FROM estado_motores")}
    motores = []
    for m in sorted(REGISTRO.values(), key=lambda x: x.numero):
        r = filas.get(m.id) or {}
        motores.append({"numero": m.numero, "id": m.id, "nombre": m.nombre, "estado": r.get("estado", "sin_ejecutar"),
                        "ultimo_ts": r.get("ts"), "duracion_ms": r.get("duracion_ms"), "ejecuciones": r.get("ejecuciones", 0),
                        "errores": r.get("errores", 0), "ultimo_error": r.get("error"), "en_analisis": m.en_analisis})
    hilos = sorted(t.name for t in threading.enumerate())
    bases = {}
    import sqlite3
    rutas = {"titan_quant.db": config.DATOS / "titan_quant.db", "conocimiento.db": config.DATOS / "conocimiento.db",
             "cuentas/simulacion.db": config.DATOS / "cuentas" / "simulacion.db", "cuentas/demo.db": config.DATOS / "cuentas" / "demo.db",
             "cuentas/real.db": config.DATOS / "cuentas" / "real.db"}
    rutas.update({n: config.RAIZ / n for n in ("titan_activos.db", "titan_planes.db", "titan_lab.db")})
    for nombre, ruta in rutas.items():
        if not ruta.exists():
            bases[nombre] = {"existe": False}
            continue
        info = {"existe": True, "mb": round(ruta.stat().st_size / 1e6, 2)}
        if not rapido:
            try:
                c = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True, timeout=5)
                info["integridad"] = c.execute("PRAGMA quick_check").fetchone()[0]
                c.close()
            except Exception as e:
                info["integridad"] = type(e).__name__
        bases[nombre] = info
    try:
        import plan_web
        vig = {"vivo": bool(plan_web._VIG["hilo"] and plan_web._VIG["hilo"].is_alive()), "ultimo": plan_web._VIG["ultimo"]}
    except Exception:
        vig = {"vivo": False}
    return {"ts": int(time.time()), "motores": motores, "hilos": hilos, "bases": bases, "vigilante_planes": vig}
