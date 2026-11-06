"""Adaptador de SIMULACIÓN: operaciones ficticias con precios reales del proveedor de datos.

- Ejecución al precio actual ± medio spread supuesto y deslizamiento supuesto (documentados por clase).
- Cierre por stop/objetivo usando máximos y mínimos de velas de 1 minuto desde la apertura (no solo el último precio).
- Binarias: se resuelven al vencimiento con el cierre de la vela de vencimiento y el payout configurado.
Las operaciones se registran con modalidad 'simulacion': nunca se presentan como reales.
"""
import time

from ..motores import datos
from .base import Adaptador, ErrorAdaptador

SPREAD_PCT = {"divisa": 0.01, "metal": 0.03, "energia": 0.04, "indice": 0.02, "accion": 0.05, "cripto": 0.10}
SLIP_PCT = {"divisa": 0.005, "metal": 0.01, "energia": 0.02, "indice": 0.01, "accion": 0.02, "cripto": 0.05}


class Simulador(Adaptador):
    id, nombre = "simulador", "Simulador TITAN"
    mercados = ("forex", "cripto", "acciones", "etf", "indices", "futuros", "commodities", "metales", "energia", "binarias")
    tipos_orden = ("binaria", "mercado")
    modalidades = ("simulacion",)
    autenticacion = "No requiere"
    comisiones = "Supuesto: incluido en el spread simulado"
    spreads = "Supuestos por clase de activo (no medidos): " + ", ".join(f"{k} {v}%" for k, v in SPREAD_PCT.items())
    limites_api = "Los del proveedor de datos (Yahoo)"
    restricciones = "Sin ejecución real; precios con posible retraso del proveedor"
    compatibilidad = "Probado (pruebas automáticas)"

    def __init__(self, clase_por_simbolo=None):
        self._clase = clase_por_simbolo or {}

    def conectado(self):
        return True

    def cotizacion(self, simbolo):
        s = datos.obtener(simbolo, "1d", "1m")
        ahora = time.time()
        return {"precio": s["c"][-1], "bid": None, "ask": None, "spread": None, "ts": s["t"][-1],
                "edad_s": int(ahora - s["t"][-1] - 60), "proveedor": s["proveedor"], "instrumento": s["tipo"]}

    def _clase_de(self, simbolo):
        return self._clase.get(simbolo, "accion")

    def abrir(self, sol):
        q = self.cotizacion(sol["instrumento"])
        clase = sol.get("clase") or self._clase_de(sol["instrumento"])
        sp, sl = SPREAD_PCT.get(clase, 0.05) / 100, SLIP_PCT.get(clase, 0.02) / 100
        sg = 1 if sol["direccion"] == "alcista" else -1
        if sol["tipo"] == "binaria":
            precio = q["precio"]
            costo = 0.0
        else:
            precio = q["precio"] * (1 + sg * (sp / 2 + sl))
            costo = sol["monto"] * (sp + 2 * sl)
        return {"id_externo": f"SIM-{int(time.time() * 1000)}", "precio_entrada": precio, "costo": costo,
                "fuente_precio": f"{q['proveedor']}:{q['instrumento']}", "edad_s": q["edad_s"]}

    def actualizar(self, op, ahora=None):
        ahora = ahora or time.time()
        s = datos.obtener(op["instrumento"], "5d", "1m")
        sg = 1 if op["direccion"] == "alcista" else -1
        velas = [(t, h, l, c) for t, h, l, c in zip(s["t"], s["h"], s["l"], s["c"]) if t >= op["abierta_ts"]]   # solo velas iniciadas tras la entrada
        if op["tipo"] == "binaria":
            if ahora < op["expira_ts"]:
                return None
            cand = [v for v in velas if v[0] <= op["expira_ts"]]
            if not cand:
                return None
            fin = cand[-1][3]
            gano = (fin - op["precio_entrada"]) * sg > 0
            empate = fin == op["precio_entrada"]
            res = 0.0 if empate else op["monto"] * op["payout"] if gano else -op["monto"]
            return {"precio_salida": fin, "resultado": res, "motivo": "vencimiento", "r": res / op["monto"]}
        for t, h, l, c in velas:
            if (sg > 0 and l <= op["stop"]) or (sg < 0 and h >= op["stop"]):
                return self._cierre(op, op["stop"], "stop")
            if (sg > 0 and h >= op["objetivo"]) or (sg < 0 and l <= op["objetivo"]):
                return self._cierre(op, op["objetivo"], "objetivo")
        if op.get("expira_ts") and ahora >= op["expira_ts"] and velas:
            return self._cierre(op, velas[-1][3], "tiempo")
        return None

    def _cierre(self, op, precio, motivo):
        sg = 1 if op["direccion"] == "alcista" else -1
        unidades = op["monto"] / op["precio_entrada"]
        bruto = sg * (precio - op["precio_entrada"]) * unidades
        res = bruto - (op["costo"] or 0)
        riesgo = abs(op["precio_entrada"] - op["stop"]) * unidades if op.get("stop") else None
        return {"precio_salida": precio, "resultado": res, "motivo": motivo, "r": res / riesgo if riesgo else None}

    def cerrar(self, op, motivo):
        q = self.cotizacion(op["instrumento"])
        if op["tipo"] == "binaria":
            raise ErrorAdaptador("Una binaria no se puede cerrar antes del vencimiento.")
        return self._cierre(op, q["precio"], motivo)


def ficha_estatica():
    return Simulador().ficha()
