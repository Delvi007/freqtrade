"""Señal CALL/PUT sobre velas M1 cerradas, usando la estrategia Keltner + RCI existente.

La lógica de la estrategia NO se reescribe: se llama a `estrategias.keltner_rci.senales`.
Solo se añade el vencimiento de 5 minutos y la entrada en la vela siguiente al cierre.

Reglas de tiempo (sin anticipación):
  * La señal se confirma con el CIERRE de la vela j.
  * La entrada es la apertura de la vela j+1 (ts_j + 60 s).
  * El vencimiento es ts_entrada + 5 min. Su precio de referencia es el cierre de la vela j+5.
"""
from ..estrategias.keltner_rci import senales as _senales_keltner_rci

SEGUNDOS_VELA = 60
VENCIMIENTO_VELAS = 5  # 5 velas M1 = 5 minutos de vencimiento
ESTRATEGIA = "keltner_rci_m1"


def segmentos_continuos(velas):
    """Parte la serie en tramos sin huecos. Un hueco (fin de semana, cierre, dato faltante) corta el tramo."""
    tramos, actual = [], []
    for v in velas:
        if actual and v[0] - actual[-1][0] != SEGUNDOS_VELA:
            tramos.append(actual)
            actual = []
        actual.append(v)
    if actual:
        tramos.append(actual)
    return tramos


def generar(velas):
    """Señales sobre una serie CONTIGUA y cerrada. velas: lista de (ts, o, h, l, c)."""
    if len(velas) < 2:
        return []
    highs = [v[2] for v in velas]
    lows = [v[3] for v in velas]
    cierres = [v[4] for v in velas]
    eventos = _senales_keltner_rci(highs, lows, cierres)
    salida = []
    for e in eventos:
        j = e["indice"]
        ts_j = velas[j][0]
        salida.append({
            "indice": j,
            "ts_senal": ts_j,
            "ts_entrada": ts_j + SEGUNDOS_VELA,
            "vencimiento_ts": ts_j + SEGUNDOS_VELA + VENCIMIENTO_VELAS * SEGUNDOS_VELA,
            "direccion": "CALL" if e["direccion"] == "compra" else "PUT",
            "precio_ref": e["precio"],
            "rci": e["rci"],
            "banda": e["banda"],
            "estrategia": ESTRATEGIA,
        })
    return salida


def resultado(direccion, precio_entrada, precio_vencimiento, pago):
    """Resultado de una binaria. Empate = devolución (retorno 0). Pérdida = -1 unidad."""
    if precio_vencimiento == precio_entrada:
        return "empate", 0.0
    gana = (direccion == "CALL" and precio_vencimiento > precio_entrada) or \
           (direccion == "PUT" and precio_vencimiento < precio_entrada)
    if gana:
        return "ganada", float(pago)
    return "perdida", -1.0
