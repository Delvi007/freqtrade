"""Señal Keltner + RCI (según la descripción del usuario).

COMPRA en la vela j:
  1. La vela anterior cerró por debajo de la banda inferior: close[j-1] < lower[j-1].
  2. La vela j cierra de nuevo dentro del canal desde abajo: close[j] >= lower[j].
  3. El RCI sale de la sobreventa: RCI[j] > RCI[j-1] y el RCI estuvo <= -umbral en
     las últimas `ventana` velas (incluida la j-1).
VENTA en la vela j: simétrico con la banda superior, el RCI en sobrecompra (+umbral).

Supuestos explícitos (no confirmados por el usuario, se pueden cambiar):
  - Par?metros aplicados seg?n la orden del usuario del 2026-11-09: umbral = 70, periodo RCI = 9,
    ventana = 4 velas, Keltner con multiplicador 1.5 y periodo 20. Antes estaban 80, 14, 3 y 2.0.
Las velas sin valor de indicador (calentamiento) nunca generan señal.
"""
from ..indicadores.keltner import keltner
from ..indicadores.rci import rci


def senales(high, low, close, periodo_keltner=20, multiplicador=1.5, periodo_rci=9,
            umbral=70.0, ventana=4):
    if ventana < 1:
        raise ValueError("La ventana debe ser >= 1")
    k = keltner(high, low, close, periodo=periodo_keltner, multiplicador=multiplicador)
    r = rci(close, periodo=periodo_rci)
    out = []
    for j in range(1, len(close)):
        up, lo, rj, rp = k["upper"][j], k["lower"][j], r[j], r[j - 1]
        up_p, lo_p = k["upper"][j - 1], k["lower"][j - 1]
        if None in (up, lo, rj, rp, up_p, lo_p):
            continue
        inicio = max(0, j - ventana)
        ventana_rci = [x for x in r[inicio:j] if x is not None]
        # COMPRA
        if close[j - 1] < lo_p and close[j] >= lo and rj > rp and ventana_rci and min(ventana_rci) <= -umbral:
            out.append({"indice": j, "direccion": "compra", "precio": close[j], "rci": rj, "banda": lo})
        # VENTA
        if close[j - 1] > up_p and close[j] <= up and rj < rp and ventana_rci and max(ventana_rci) >= umbral:
            out.append({"indice": j, "direccion": "venta", "precio": close[j], "rci": rj, "banda": up})
    return out
