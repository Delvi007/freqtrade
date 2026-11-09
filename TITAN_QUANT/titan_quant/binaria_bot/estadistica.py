"""Estadística de binarias: equilibrio, valor esperado e intervalos de confianza.

Fórmulas:
  Equilibrio:       p* = 1 / (1 + payout)          (payout 0.86 -> p* = 0.5376)
  Valor esperado:   EV = p * ganancia - (1 - p) * pérdida
                    con ganancia = payout * monto, pérdida = monto  (por unidad: EV = p*payout - (1-p))
  Intervalo Wilson: Wilson (1927), válido también con n pequeño y p cerca de 0 o 1.
"""
import math

Z_95 = 1.959963984540054


def punto_equilibrio(payout):
    if payout <= 0:
        raise ValueError("payout debe ser positivo")
    return 1.0 / (1.0 + payout)


def valor_esperado_unitario(p, payout):
    """EV por unidad apostada. Empate (devolución) no se modela aquí: el backtest lo cuenta aparte."""
    if not (0.0 <= p <= 1.0):
        raise ValueError("p fuera de [0, 1]")
    return p * payout - (1.0 - p)


def intervalo_wilson(aciertos, n, z=Z_95):
    """Intervalo de confianza de Wilson para una proporción. Devuelve (bajo, alto)."""
    if n <= 0:
        return (0.0, 1.0)
    if not (0 <= aciertos <= n):
        raise ValueError("aciertos fuera de [0, n]")
    p = aciertos / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centro = (p + z2 / (2 * n)) / denom
    margen = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    return (max(0.0, centro - margen), min(1.0, centro + margen))


def ventaja_significativa(aciertos, n, payout, z=Z_95):
    """True solo si el límite INFERIOR de Wilson supera el punto de equilibrio.
    Esto evita declarar ventaja con muestras pequeñas o por azar."""
    bajo, _ = intervalo_wilson(aciertos, n, z)
    return bajo > punto_equilibrio(payout)
