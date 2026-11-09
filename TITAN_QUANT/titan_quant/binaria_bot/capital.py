"""Capital y monto por operación para binarias. SOLO CALCULA: no envía órdenes.

Reglas confirmadas por el operador:
  * monto = riesgo_pct % del capital ACTUAL. Sin tope absoluto: el monto crece con el saldo.
  * si el monto queda por debajo de monto_minimo, no hay dinero suficiente: el bot se abstiene.
  * el capital se recalcula antes de cada decisión.
  * sin martingala: el monto sigue al capital; tras pérdidas baja y nunca sube para recuperar.
  * los límites diario y de drawdown se expresan en porcentaje del capital de referencia.

Lectura de saldo (PRACTICE): solo lectura, con tiempo máximo. iqoptionapi.get_balance() puede
quedarse esperando sin límite si el broker no responde; por eso la consulta va en un hilo con timeout.
"""
import math
import threading
from dataclasses import dataclass


class CapitalNoFiable(Exception):
    """El saldo no se puede usar para decidir: no está disponible, no es válido o la cuenta no es PRACTICE."""


@dataclass(frozen=True)
class PoliticaCapital:
    riesgo_pct: float = 1.0          # % del capital actual por operación (sin tope absoluto)
    monto_minimo: float = 1.0        # mínimo del broker: confirmado por el operador en 1 USD
    perdida_diaria_pct: float = 3.0  # % del capital al inicio del día
    drawdown_pct: float = 5.0        # % del pico de capital

    def __post_init__(self):
        if not (0 < self.riesgo_pct <= 5):
            raise ValueError("riesgo_pct debe estar en (0, 5]")
        if self.monto_minimo <= 0:
            raise ValueError("monto_minimo debe ser positivo")
        if not (0 < self.perdida_diaria_pct <= 50):
            raise ValueError("perdida_diaria_pct debe estar en (0, 50]")
        if not (0 < self.drawdown_pct <= 100):
            raise ValueError("drawdown_pct debe estar en (0, 100]")


def describir(politica):
    return (f"riesgo {politica.riesgo_pct}% | sin tope | mínimo {politica.monto_minimo} "
            f"| pérdida diaria {politica.perdida_diaria_pct}% | drawdown {politica.drawdown_pct}%")


def monto_para(capital, politica):
    """Devuelve (monto, motivo). monto es None si no se debe operar; motivo indica la regla."""
    if (capital is None or isinstance(capital, bool) or not isinstance(capital, (int, float))
            or not math.isfinite(capital)):
        return None, "capital_no_fiable"
    if capital <= 0:
        return None, "capital_insuficiente"
    monto = round(capital * politica.riesgo_pct / 100.0, 2)
    if monto < politica.monto_minimo:
        return None, "capital_insuficiente"
    return monto, ""


def leer_capital_practica(iq, timeout_s=10.0):
    """Saldo de la cuenta PRACTICE, solo lectura. Falla si la cuenta no es PRACTICE,
    si el broker no responde a tiempo, si hay error o si el valor no es válido."""
    resultado = {}

    def _consulta():
        try:
            resultado["modo"] = iq.get_balance_mode()
            resultado["valor"] = iq.get_balance()
        except Exception as e:  # noqa: BLE001
            resultado["error"] = type(e).__name__

    hilo = threading.Thread(target=_consulta, daemon=True)
    hilo.start()
    hilo.join(timeout_s)
    if hilo.is_alive():
        raise CapitalNoFiable("el broker no respondió a tiempo")
    if "error" in resultado:
        raise CapitalNoFiable(f"error al leer el saldo ({resultado['error']})")
    if resultado.get("modo") != "PRACTICE":
        raise CapitalNoFiable(f"la cuenta activa no es PRACTICE ({resultado.get('modo')!r}); no se lee capital")
    valor = resultado.get("valor")
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor) or valor <= 0:
        raise CapitalNoFiable("saldo no válido")
    return float(valor)


def verificar_coherencia(nuevo, anterior, umbral_pct=20.0):
    """Devuelve '' si la lectura es coherente, o el motivo si el saldo cambió más de umbral_pct %
    respecto de la última lectura aceptada. anterior=None significa primera lectura (se acepta)."""
    if not (0 < umbral_pct <= 100):
        raise ValueError("umbral_pct debe estar en (0, 100]")
    if anterior is None:
        return ""
    if anterior <= 0:
        return "saldo anterior no válido"
    cambio = abs(nuevo - anterior) / anterior * 100.0
    if cambio > umbral_pct:
        return (f"saldo cambió {cambio:.1f}% respecto de la última lectura aceptada "
                f"({anterior:.2f} -> {nuevo:.2f}); umbral {umbral_pct}%")
    return ""
