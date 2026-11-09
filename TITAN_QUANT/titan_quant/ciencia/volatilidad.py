"""Modelos de volatilidad."""
import math

import numpy as np

from .optimizacion import nelder_mead


def rendimientos(precios, log=True):
    p = np.asarray(precios, float)
    return np.diff(np.log(p)) if log else np.diff(p) / p[:-1]


def ewma(r, lam=0.94):
    """Varianza EWMA (RiskMetrics). Devuelve la serie de volatilidades."""
    r = np.asarray(r, float)
    v = np.empty_like(r)
    v[0] = r[:20].var() if len(r) > 1 else r[0] ** 2
    for t in range(1, len(r)):
        v[t] = lam * v[t - 1] + (1 - lam) * r[t - 1] ** 2
    return np.sqrt(v)


def parkinson(h, l):
    h, l = np.asarray(h, float), np.asarray(l, float)
    return math.sqrt(np.mean(np.log(h / l) ** 2) / (4 * math.log(2)))


def garman_klass(o, h, l, c):
    o, h, l, c = (np.asarray(x, float) for x in (o, h, l, c))
    return math.sqrt(np.mean(0.5 * np.log(h / l) ** 2 - (2 * math.log(2) - 1) * np.log(c / o) ** 2))


def _garch_nll(par, r):
    w, a, b = par
    if w <= 0 or a < 0 or b < 0 or a + b >= 0.9999:
        return 1e12
    v = np.empty_like(r)
    v[0] = r.var()
    for t in range(1, len(r)):
        v[t] = w + a * r[t - 1] ** 2 + b * v[t - 1]
    return 0.5 * float(np.sum(np.log(2 * math.pi * v) + r ** 2 / v))


def garch11(r):
    """GARCH(1,1) por máxima verosimilitud gaussiana (Bollerslev 1986). σ²_t = ω + α r²_{t-1} + β σ²_{t-1}."""
    r = np.asarray(r, float)
    r = r - r.mean()
    var = r.var()
    escala = 1.0 / math.sqrt(var) if var > 0 else 1.0
    rs = r * escala                                            # escala unitaria: optimización estable
    (w, a, b), nll = nelder_mead(lambda p: _garch_nll(p, rs), [0.05, 0.08, 0.88], paso=0.05, max_iter=3000)
    w = w / escala ** 2
    v = np.empty_like(r)
    v[0] = r.var()
    for t in range(1, len(r)):
        v[t] = w + a * r[t - 1] ** 2 + b * v[t - 1]
    sig_sig = w + a * r[-1] ** 2 + b * v[-1]
    larga = w / (1 - a - b) if a + b < 1 else None
    return {"omega": w, "alfa": a, "beta": b, "persistencia": a + b, "vol_siguiente": math.sqrt(sig_sig),
            "vol_largo_plazo": math.sqrt(larga) if larga else None, "vida_media": math.log(0.5) / math.log(a + b) if 0 < a + b < 1 else None,
            "nll": nll, "serie_vol": np.sqrt(v)}


def pronostico_garch(m, h=10):
    """Varianza esperada a h pasos: converge a la de largo plazo."""
    out, v = [], m["vol_siguiente"] ** 2
    lp = (m["vol_largo_plazo"] or 0) ** 2
    for _ in range(h):
        out.append(math.sqrt(v))
        v = lp + m["persistencia"] * (v - lp)
    return out
