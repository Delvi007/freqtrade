"""Inferencia bayesiana para decidir con resultados REALES y pocas muestras.

tasa_acierto(): Beta-Binomial. Previa Beta(a0, b0) (por defecto Jeffreys 0.5/0.5). Devuelve la media posterior, el
intervalo creíble del 95 % y P(tasa > umbral) — p. ej. el punto de equilibrio de una binaria 1/(1+payout).

expectativa_r(): Normal-Gamma conjugada sobre resultados en R. Devuelve la media posterior, P(expectativa > 0) con la
t de Student posterior y el intervalo creíble. Previa débil centrada en 0 (escéptica: exige evidencia para creer en ventaja).
"""
import math

import numpy as np

from .especiales import betainc, t_cdf


def _beta_ppf(a, b, p):
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if betainc(a, b, mid) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def tasa_acierto(ganadas, perdidas, umbral=0.5, a0=0.5, b0=0.5):
    a, b = a0 + ganadas, b0 + perdidas
    return {"media": a / (a + b), "ic95": (_beta_ppf(a, b, 0.025), _beta_ppf(a, b, 0.975)), "p_sobre_umbral": 1 - betainc(a, b, umbral),
            "n": ganadas + perdidas, "modelo": f"Beta({a0},{b0}) → Beta({a:.1f},{b:.1f})"}


def expectativa_r(resultados, mu0=0.0, kappa0=1.0, alfa0=2.0, beta0=1.0):
    x = np.asarray(resultados, float)
    n = len(x)
    if n == 0:
        return {"media": mu0, "p_positiva": 0.5, "ic95": (None, None), "n": 0}
    xm = float(x.mean())
    kn = kappa0 + n
    mun = (kappa0 * mu0 + n * xm) / kn
    an = alfa0 + n / 2
    bn = beta0 + 0.5 * float(((x - xm) ** 2).sum()) + kappa0 * n * (xm - mu0) ** 2 / (2 * kn)
    escala = math.sqrt(bn / (an * kn))            # t posterior de la media: gl 2an, centro mun, escala
    gl = 2 * an
    p = t_cdf(mun / escala, gl)
    # intervalo por bisección de la t
    def ppf(q):
        lo, hi = -50.0, 50.0
        for _ in range(100):
            m = (lo + hi) / 2
            lo, hi = (m, hi) if t_cdf(m, gl) < q else (lo, m)
        return (lo + hi) / 2
    return {"media": mun, "p_positiva": p, "ic95": (mun + ppf(0.025) * escala, mun + ppf(0.975) * escala), "n": n,
            "modelo": "Normal-Gamma (previa escéptica centrada en 0)"}


def kelly_binaria(p, payout):
    """Fracción de Kelly para una apuesta binaria con pago `payout` (0.83 = 83 %)."""
    return max(0.0, (p * payout - (1 - p)) / payout)
