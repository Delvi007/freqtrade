"""Ejecución DEMO de la señal Keltner + RCI en cTrader (paso 1).

Reglas confirmadas por el usuario:
  - Solo modalidad DEMO. La REAL no se ejecuta desde este módulo.
  - Volumen: el mínimo del broker para el símbolo (XAUUSD por defecto).
  - Stop = 1.5 x ATR(14) y objetivo = 3 x ATR(14), medidos desde el precio de entrada real.

Garantías de seguridad:
  - Cada decisión tiene un id único (uuid). Una decisión confirmada nunca se reenvía.
  - Estados: pendiente -> enviada -> confirmada | rechazada | incierta.
    Una orden 'incierta' (sin confirmación por timeout o error de red) BLOQUEA nuevos envíos de esa
    decisión hasta revisión manual: no se reenvía a ciegas.
  - La orden solo se considera abierta cuando cTrader devuelve ORDER_FILLED (lo hace orden_mercado).
  - Si la cotización está vieja o el precio ya cruzó el stop/objetivo planeado, no se envía.
"""
import json
import math
import time
import uuid

from .. import db
from ..indicadores.suavizado import rma, true_range
from .base import ErrorAdaptador
from .ctrader_ws import ErrorCTrader

MODALIDAD = "demo"
SIMBOLO_DEFECTO = "XAUUSD"
STOP_ATR = 1.5
OBJETIVO_ATR = 3.0
PERIODO_ATR = 14
EDAD_MAX_COTIZACION_S = 30


def _asegurar():
    with db.tx() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS ejecuciones_demo(
            id TEXT PRIMARY KEY, ts INTEGER NOT NULL, simbolo TEXT NOT NULL, direccion TEXT NOT NULL,
            estado TEXT NOT NULL, ref_cliente TEXT, posicion_id TEXT, precio_entrada REAL,
            volumen INTEGER, decision TEXT NOT NULL, error TEXT, actualizado_ts INTEGER NOT NULL)""")


def atr(high, low, close, periodo=PERIODO_ATR):
    v = rma(true_range(high, low, close), periodo)[-1]
    if v is None or not math.isfinite(v) or v <= 0:
        raise ValueError("ATR no disponible: se necesitan más velas que el periodo")
    return v


def crear_decision(senal, precio_ref, atr_valor, simbolo=SIMBOLO_DEFECTO, timeframe=None):
    """Convierte una señal de estrategias.keltner_rci en una decisión ejecutable (sin enviarla)."""
    if senal.get("direccion") not in ("compra", "venta"):
        raise ValueError("Dirección no válida")
    if not (isinstance(atr_valor, (int, float)) and math.isfinite(atr_valor) and atr_valor > 0):
        raise ValueError("ATR inválido")
    if not (isinstance(precio_ref, (int, float)) and math.isfinite(precio_ref) and precio_ref > 0):
        raise ValueError("Precio de referencia inválido")
    if not timeframe:
        raise ValueError("Indica la temporalidad de la señal")
    sg = 1 if senal["direccion"] == "compra" else -1
    return {
        "id": uuid.uuid4().hex, "ts": int(time.time()), "modalidad": MODALIDAD, "broker": "ctrader",
        "simbolo": simbolo, "timeframe": timeframe, "direccion": senal["direccion"],
        "precio_ref": float(precio_ref), "atr": float(atr_valor),
        "stop": float(precio_ref) - sg * STOP_ATR * atr_valor,
        "objetivo": float(precio_ref) + sg * OBJETIVO_ATR * atr_valor,
        "volumen": "minimo_broker",
        "justificacion": {"indice_senal": senal.get("indice"), "rci": senal.get("rci"), "banda": senal.get("banda")},
    }


def _estado(id_):
    _asegurar()
    return db.q1("SELECT * FROM ejecuciones_demo WHERE id=?", (id_,))


def _guardar(d, estado, **campos):
    _asegurar()
    previo = _estado(d["id"]) or {}
    fila = {"id": d["id"], "ts": d["ts"], "simbolo": d["simbolo"], "direccion": d["direccion"], "estado": estado,
            "ref_cliente": campos.get("ref_cliente", previo.get("ref_cliente")),
            "posicion_id": campos.get("posicion_id", previo.get("posicion_id")),
            "precio_entrada": campos.get("precio_entrada", previo.get("precio_entrada")),
            "volumen": campos.get("volumen", previo.get("volumen")), "decision": json.dumps(d, ensure_ascii=False),
            "error": campos.get("error"), "actualizado_ts": int(time.time())}
    with db.tx() as c:
        c.execute("""INSERT OR REPLACE INTO ejecuciones_demo(id,ts,simbolo,direccion,estado,ref_cliente,posicion_id,
                     precio_entrada,volumen,decision,error,actualizado_ts) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (fila["id"], fila["ts"], fila["simbolo"], fila["direccion"], fila["estado"], fila["ref_cliente"],
                   fila["posicion_id"], fila["precio_entrada"], fila["volumen"], fila["decision"], fila["error"], fila["actualizado_ts"]))
    return fila


def ejecutar_con_sesion(s, sid, nombre, d, cotizacion_max_s=EDAD_MAX_COTIZACION_S):
    """Núcleo de ejecución. `s` es una SesionCTrader ya abierta; `sid`/`nombre` identifican el símbolo."""
    if d.get("modalidad") != MODALIDAD:
        raise ErrorAdaptador("Este ejecutor solo opera en DEMO.")
    previo = _estado(d["id"])
    if previo and previo["estado"] in ("confirmada", "incierta", "enviada"):
        if previo["estado"] == "confirmada":
            return {"estado": "confirmada", "posicion_id": previo["posicion_id"], "nota": "ya ejecutada; no se reenvía"}
        raise ErrorAdaptador("Decisión " + previo["estado"] + ": requiere revisión manual en el broker antes de reintentar.")
    det = s.simbolo(sid)
    q = s.cotizacion(sid)
    if q.get("edad_s", 0) > cotizacion_max_s:
        raise ErrorAdaptador(f"Cotización desactualizada ({q.get('edad_s')} s); no se envía la orden.")
    compra = d["direccion"] == "compra"
    entrada = q["ask"] if compra else q["bid"]
    if compra and not (d["stop"] < entrada < d["objetivo"]):
        raise ErrorAdaptador("El precio se movió fuera del rango de la decisión (stop/objetivo cruzados); no se envía.")
    if not compra and not (d["objetivo"] < entrada < d["stop"]):
        raise ErrorAdaptador("El precio se movió fuera del rango de la decisión (stop/objetivo cruzados); no se envía.")
    vol = int(det["vol_min"] or 1)
    rel_s = _rel(abs(entrada - d["stop"]), det["digitos"])
    rel_o = _rel(abs(d["objetivo"] - entrada), det["digitos"])
    ref = f"TQ{d['id'][:24]}"
    _guardar(d, "pendiente", ref_cliente=ref, volumen=vol)
    _guardar(d, "enviada", ref_cliente=ref, volumen=vol)
    lado = "BUY" if compra else "SELL"
    try:
        r = s.orden_mercado(sid, lado, vol, rel_s, rel_o, "TITAN", ref, f"TITAN demo {d['id'][:8]}")
    except ErrorCTrader as e:
        if e.codigo in ("TIEMPO_AGOTADO",) or "timeout" in str(e).lower():
            _guardar(d, "incierta", error=str(e)[:300])
            raise ErrorAdaptador("Sin confirmación de cTrader: la orden queda INCIERTA y bloqueada hasta revisión manual.") from None
        _guardar(d, "rechazada", error=str(e)[:300])
        raise ErrorAdaptador("cTrader rechazó la orden: " + str(e)[:200]) from None
    except OSError as e:
        _guardar(d, "incierta", error=type(e).__name__)
        raise ErrorAdaptador("Conexión interrumpida durante el envío: orden INCIERTA, revisión manual.") from None
    if not r.get("posicion"):
        _guardar(d, "incierta", error="confirmación sin identificador de posición")
        raise ErrorAdaptador("La confirmación no trae identificador de posición: revisión manual.")
    precio = float(r.get("precio") or entrada)
    _guardar(d, "confirmada", posicion_id=str(r["posicion"]), precio_entrada=precio, volumen=vol)
    return {"estado": "confirmada", "posicion_id": str(r["posicion"]), "precio_entrada": precio, "volumen": vol}


def _rel(distancia, digitos):
    from .ctrader import CTrader
    return CTrader._relativo(distancia, digitos)


def ejecutar(adaptador, d):
    """Abre la sesión de cTrader DEMO y ejecuta la decisión. `adaptador` debe ser CTrader con modalidad demo."""
    if getattr(adaptador, "modalidad", None) != MODALIDAD:
        raise ErrorAdaptador("Este ejecutor solo opera en DEMO.")
    s = adaptador._abrir()
    try:
        sim, _cat = adaptador._simbolo(s, d.get("simbolo") or SIMBOLO_DEFECTO)
        return ejecutar_con_sesion(s, sim["id"], sim["nombre"], d)
    finally:
        s.cerrar()
