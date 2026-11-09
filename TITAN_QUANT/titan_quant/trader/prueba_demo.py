"""Prueba DEMO manual de la señal Keltner + RCI.

Uso (desde la carpeta del proyecto):
    python -m titan_quant.trader.prueba_demo                 # solo muestra la señal (no envía nada)
    python -m titan_quant.trader.prueba_demo --enviar        # pide confirmación escrita y envía a DEMO

- Usa la última vela CERRADA (descarta la vela en formación).
- Solo cuenta DEMO del dueño. Nunca REAL.
- Si no hay señal en esa vela, no hace nada.
"""
import sys

from .. import db
from ..estrategias.keltner_rci import senales
from . import ejecucion_demo as ed
from .ctrader import CTrader

INTERVALO = "1h"
SIMBOLO = ed.SIMBOLO_DEFECTO
HISTORIA_S = 60 * 60 * 24 * 30


def _dueno():
    u = db.q1("SELECT id FROM usuarios ORDER BY (rol='propietario') DESC, id LIMIT 1")
    if not u:
        raise SystemExit("No hay usuarios en TITAN QUANT.")
    return u["id"]


def principal(enviar=False):
    import os
    if not os.environ.get("TITAN_CLAVE_MAESTRA", "").strip():
        raise SystemExit("Falta TITAN_CLAVE_MAESTRA en esta ventana de PowerShell: usa la MISMA clave con la que arrancas "
                         "el servidor. No se creó ninguna clave nueva.")
    uid = _dueno()
    from . import autotrader
    aj = autotrader.estado(uid, "demo")["ajustes"]
    if not aj.get("cuenta_ctid"):
        raise SystemExit("No hay cuenta cTrader DEMO elegida en el Bot Operador (modalidad demo). Elígela en su configuración y vuelve a ejecutar.")
    ad = CTrader(uid, "demo", aj.get("cuenta_ctid"), aj.get("simbolo_broker"))
    v = ad.serie(SIMBOLO, INTERVALO, HISTORIA_S)
    h, l, c = v["h"][:-1], v["l"][:-1], v["c"][:-1]          # descarta la vela en formación
    ev = [e for e in senales(h, l, c) if e["indice"] == len(c) - 1]
    if not ev:
        print("Sin señal en la última vela cerrada. No se envía nada.")
        return 0
    senal = ev[0]
    d = ed.crear_decision(senal, c[-1], ed.atr(h, l, c), simbolo=SIMBOLO, timeframe=INTERVALO)
    print("Señal:", senal["direccion"], "| precio:", round(c[-1], 2), "| stop:", round(d["stop"], 2),
          "| objetivo:", round(d["objetivo"], 2), "| ATR:", round(d["atr"], 3), "| RCI:", round(senal["rci"], 1))
    if not enviar:
        print("Modo simulación: no se envió. Para enviar a DEMO: python -m titan_quant.trader.prueba_demo --enviar")
        return 0
    if input("Escribe SI para enviar UNA orden DEMO de volumen mínimo: ").strip() != "SI":
        print("Cancelado. No se envió nada.")
        return 0
    r = ed.ejecutar(ad, d)
    print("Resultado:", r)
    return 0


if __name__ == "__main__":
    sys.exit(principal(enviar="--enviar" in sys.argv))
