"""Recolección del histórico de cTrader (DEMO). Solo lectura: no envía órdenes.

    recopilar(uid, cuenta_ctid, simbolo, intervalo, dias)  trendbars incrementales + bid/ask actual del símbolo
"""
import time

from . import PROVEEDOR, almacen
from ..historico import SEG


def recopilar(uid, cuenta_ctid, simbolo, intervalo="15m", dias=60, adaptador=None, ahora=None):
    from ..trader.ctrader import CTrader
    from ..trader.ctrader_ws import ErrorCTrader
    from ..trader.base import ErrorAdaptador
    if intervalo not in SEG:
        raise ValueError("Intervalo no soportado: " + str(intervalo))
    simbolo = str(simbolo).upper()
    ad = adaptador or CTrader(uid, "demo", cuenta_ctid, simbolo)      # siempre la cuenta DEMO
    s = ad._abrir()
    try:
        sim, _ = ad._simbolo(s, simbolo)
        ahora = int(ahora or time.time())
        fin = ahora - ahora % SEG[intervalo]                       # solo velas cerradas
        alm = almacen()
        r = alm.descargar_incremental(s, PROVEEDOR, simbolo, sim["id"], intervalo, fin - int(dias) * 86400, fin, lote=1000)
        spread = None
        try:
            q = s.cotizacion(sim["id"])
            if q.get("bid") and q.get("ask"):
                spread = q["ask"] - q["bid"]
                with alm.tx() as c:
                    c.execute("INSERT OR REPLACE INTO spreads(simbolo,ts,bid,ask,spread,fuente) VALUES(?,?,?,?,?,?)",
                              (simbolo, int(time.time()), q["bid"], q["ask"], spread, "cTrader DEMO spot (bid/ask)"))
        except ErrorCTrader:
            pass                                                  # mercado cerrado: sin bid/ask, no se inventa
    except ErrorCTrader as e:
        raise ErrorAdaptador(ad._explicar(e)) from None
    finally:
        s.cerrar()
    return {"simbolo": simbolo, "intervalo": intervalo, "proveedor": PROVEEDOR, **r, "spread_observado": spread,
            "huecos": len(alm.huecos(PROVEEDOR, simbolo, intervalo))}


def spread_observado(simbolo):
    """(mediana del spread observado en unidades de precio, nº de observaciones) o (None, 0)."""
    filas = [r["spread"] for r in almacen().q("SELECT spread FROM spreads WHERE simbolo=? ORDER BY spread", (str(simbolo).upper(),))]
    if not filas:
        return None, 0
    m = len(filas) // 2
    return (filas[m] if len(filas) % 2 else (filas[m - 1] + filas[m]) / 2), len(filas)
