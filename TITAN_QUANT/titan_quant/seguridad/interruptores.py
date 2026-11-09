"""Interruptores de seguridad de TITAN (C10): PARADA TOTAL (kill switch global) e interruptor por broker.

Reglas que nada puede saltarse (ni los bots ni una inteligencia autónoma futura):
  · DETENER es siempre fácil: lo puede hacer el usuario o el propio sistema (protección automática).
  · REANUDAR solo lo puede hacer el USUARIO, con su contraseña de TITAN y desde este dispositivo.
    Cualquier otro origen ('sistema', 'ia', 'bot', 'automatico'…) recibe PermissionError: no existe ruta de código
    para que un proceso automático levante una protección.
  · Con la parada activa, ninguna orden nueva llega a ningún broker (control en el punto único de envío) y los bots
    quedan detenidos. Las posiciones abiertas se siguen vigilando y conciliando; opcionalmente se piden cerrar.
  · Todo queda en la auditoría y genera una alerta crítica.
"""
import time

from .. import alertas, db

CLAVE = "interruptores_seguridad"
BROKERS = {"ctrader": "cTrader", "iqoption": "IQ Option"}
ORIGEN_USUARIO = "usuario"


def _leer():
    e = db.cfg_sistema(CLAVE, None) or {}
    e.setdefault("global", {"parada": False})
    e.setdefault("brokers", {})
    for b in BROKERS:
        e["brokers"].setdefault(b, {"bloqueado": False})
    return e


def estado():
    e = _leer()
    return {"parada_global": bool(e["global"].get("parada")), "global": e["global"], "brokers": e["brokers"],
            "nombres": BROKERS, "regla": "Detener: cualquiera (usuario o protección automática). Reanudar: solo el usuario con su contraseña."}


def permitido(broker=None):
    """(ok, motivo). Lo consultan el ciclo de los bots y el punto único de envío de órdenes."""
    e = _leer()
    if e["global"].get("parada"):
        return False, "PARADA TOTAL activa: " + (e["global"].get("motivo") or "sin motivo")
    b = e["brokers"].get(broker or "", {})
    if b.get("bloqueado"):
        return False, f"Broker {BROKERS.get(broker, broker)} bloqueado: " + (b.get("motivo") or "sin motivo")
    return True, ""


def _avisar(uid, titulo, texto):
    try:
        alertas.crear(uid, "riesgo", titulo, "critica", justificacion=texto, motores=["risk"], clave_dedupe=f"intr|{titulo}|{int(time.time())}")
    except Exception as ex:                      # la alerta es informativa: la protección ya quedó guardada
        db.auditar(uid, "alerta_fallida", "seguridad", None, {"error": str(ex)[:200]})


def parada_total(uid, motivo, cerrar_posiciones=False, origen=ORIGEN_USUARIO):
    """Activa la PARADA TOTAL: bloquea toda orden nueva y detiene los 4 bots (o los pone en emergencia, que pide al broker
    el cierre de sus posiciones, si cerrar_posiciones=True)."""
    from ..trader import autotrader
    e = _leer()
    e["global"] = {"parada": True, "motivo": str(motivo or "parada manual")[:300], "ts": int(time.time()), "por": origen,
                   "cerrar_posiciones": bool(cerrar_posiciones)}
    db.set_cfg_sistema(CLAVE, e)
    db.auditar(uid, "parada_total_activada", "seguridad", "global", {"motivo": e["global"]["motivo"], "origen": origen, "cerrar": bool(cerrar_posiciones)})
    resultados = {}
    for m in autotrader.MODALIDADES:
        try:
            est = autotrader.estado(uid, m)["estado"]
            if cerrar_posiciones:
                autotrader.cambiar_estado(uid, m, "emergencia")
                resultados[m] = "emergencia (cierre de posiciones pedido al broker)"
            elif est in ("activo", "pausado"):
                autotrader.cambiar_estado(uid, m, "detenido")
                resultados[m] = "detenido"
            else:
                resultados[m] = est
        except Exception as ex:
            resultados[m] = f"error: {type(ex).__name__}: {str(ex)[:120]}"
    _avisar(uid, "PARADA TOTAL ACTIVADA", f"{e['global']['motivo']} · origen {origen}. Ninguna orden nueva llegará a ningún broker.")
    return {**estado(), "bots": resultados}


def reanudar(uid, clave_ok, local, origen=ORIGEN_USUARIO):
    """Levanta la PARADA TOTAL. Solo el usuario, con contraseña y desde este dispositivo. Los bots NO se reinician solos."""
    if origen != ORIGEN_USUARIO:
        db.auditar(uid, "intento_reanudar_denegado", "seguridad", "global", {"origen": origen})
        raise PermissionError("Solo el usuario puede levantar la PARADA TOTAL: un proceso automático nunca puede desactivar una protección.")
    if not local:
        raise PermissionError("La PARADA TOTAL solo se puede levantar desde el dispositivo donde corre TITAN.")
    if not clave_ok:
        raise PermissionError("Contraseña incorrecta.")
    e = _leer()
    antes = dict(e["global"])
    e["global"] = {"parada": False, "ts": int(time.time()), "por": origen, "levantada_tras": antes.get("motivo")}
    db.set_cfg_sistema(CLAVE, e)
    db.auditar(uid, "parada_total_levantada", "seguridad", "global", {"antes": antes})
    _avisar(uid, "PARADA TOTAL levantada", "Los bots siguen detenidos: inícialos uno a uno cuando quieras.")
    return estado()


def bloquear_broker(uid, broker, motivo, origen=ORIGEN_USUARIO):
    if broker not in BROKERS:
        raise ValueError("Broker desconocido.")
    e = _leer()
    if e["brokers"][broker].get("bloqueado"):
        return estado()
    e["brokers"][broker] = {"bloqueado": True, "motivo": str(motivo or "bloqueo manual")[:300], "ts": int(time.time()), "por": origen}
    db.set_cfg_sistema(CLAVE, e)
    db.auditar(uid, "broker_bloqueado", "seguridad", broker, {"motivo": e["brokers"][broker]["motivo"], "origen": origen})
    _avisar(uid, f"Broker {BROKERS[broker]} BLOQUEADO", f"{e['brokers'][broker]['motivo']} · origen {origen}. No se enviarán órdenes a este broker.")
    return estado()


def desbloquear_broker(uid, broker, clave_ok, local, origen=ORIGEN_USUARIO):
    if broker not in BROKERS:
        raise ValueError("Broker desconocido.")
    if origen != ORIGEN_USUARIO:
        db.auditar(uid, "intento_desbloqueo_denegado", "seguridad", broker, {"origen": origen})
        raise PermissionError("Solo el usuario puede desbloquear un broker: un proceso automático nunca puede desactivar una protección.")
    if not local:
        raise PermissionError("Solo se puede desbloquear desde el dispositivo donde corre TITAN.")
    if not clave_ok:
        raise PermissionError("Contraseña incorrecta.")
    e = _leer()
    antes = dict(e["brokers"][broker])
    e["brokers"][broker] = {"bloqueado": False, "ts": int(time.time()), "por": origen}
    db.set_cfg_sistema(CLAVE, e)
    db.auditar(uid, "broker_desbloqueado", "seguridad", broker, {"antes": antes})
    return estado()


# ------------------------------------------------------------------------------------------------- ajustes protegidos
# Límites de riesgo que solo el USUARIO puede cambiar. Un origen automático (IA, optimizador, aprendizaje) no puede
# modificarlos, ni para aflojarlos ni para desactivarlos.
PROTEGIDOS = ("riesgo_pct", "perdida_diaria_max_pct", "perdida_semanal_max_pct", "drawdown_max_pct", "exposicion_max_pct", "max_abiertas",
              "max_perdidas_consecutivas", "pausa_racha_min", "sin_limites_perdida", "spread_max_pct", "slippage_max_pct", "duplicado_ventana_s",
              "confirmar_motores", "umbral_contra", "veto_macro", "datos_max_edad_s", "capital_desde_broker")


def comprobar_cambio(origen, antes, cambios):
    """Lanza PermissionError si un origen no humano intenta tocar un ajuste protegido."""
    if origen == ORIGEN_USUARIO:
        return
    tocados = [k for k in PROTEGIDOS if k in cambios and cambios[k] != antes.get(k)]
    if tocados:
        raise PermissionError(f"El origen '{origen}' no puede modificar protecciones de riesgo ({', '.join(tocados)}): solo el usuario.")


# ------------------------------------------------------------------------------------------------- protección automática
ERRORES_PARA_BLOQUEO = 3
VENTANA_ERRORES_S = 1800


def vigilar_errores(uid, broker, n_errores_recientes):
    """Si un broker acumula órdenes sin confirmar en poco tiempo, el SISTEMA lo bloquea (solo el usuario lo levanta)."""
    if n_errores_recientes >= ERRORES_PARA_BLOQUEO and permitido(broker)[0]:
        bloquear_broker(uid, broker, f"{n_errores_recientes} órdenes sin confirmar por el broker en {VENTANA_ERRORES_S // 60} min: "
                                     "posible desconexión o fallo del broker. Concilia y revisa antes de desbloquear.", origen="sistema")
        return True
    return False
