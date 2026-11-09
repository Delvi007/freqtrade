"""Teoría de carteras robusta."""
import numpy as np


def ledoit_wolf(R):
    """Covarianza con contracción hacia identidad escalada (Ledoit & Wolf 2004). R: T×N rendimientos."""
    X = np.asarray(R, float)
    X = X - X.mean(0)
    t, n = X.shape
    S = X.T @ X / t
    mu = np.trace(S) / n
    F = mu * np.eye(n)
    d2 = np.linalg.norm(S - F, "fro") ** 2
    b2 = sum(np.linalg.norm(np.outer(x, x) - S, "fro") ** 2 for x in X) / t ** 2
    delta = min(1.0, b2 / d2) if d2 > 0 else 1.0
    return delta * F + (1 - delta) * S, delta


def minima_varianza(S, largo=True):
    n = len(S)
    inv = np.linalg.pinv(S)
    w = inv @ np.ones(n)
    w /= w.sum()
    if largo and (w < 0).any():                 # proyección iterativa a pesos ≥ 0
        activos = np.ones(n, bool)
        for _ in range(n):
            Si = S[np.ix_(activos, activos)]
            wi = np.linalg.pinv(Si) @ np.ones(activos.sum())
            wi /= wi.sum()
            if (wi >= 0).all():
                w = np.zeros(n)
                w[activos] = wi
                break
            idx = np.where(activos)[0][wi < 0]
            activos[idx] = False
    return w


def paridad_riesgo(S, iter_max=1000, tol=1e-10):
    """Contribuciones de riesgo iguales (Maillard, Roncalli & Teïletche 2010), algoritmo de punto fijo de Spinu."""
    n = len(S)
    w = np.ones(n) / n
    for _ in range(iter_max):
        sw = S @ w
        nuevo = (1.0 / n) / sw
        nuevo /= nuevo.sum()
        w_prev, w = w, 0.5 * w + 0.5 * nuevo
        if np.abs(w - w_prev).max() < tol:
            break
    return w


def contribuciones_riesgo(w, S):
    v = float(w @ S @ w)
    return w * (S @ w) / v


def cvar(rendimientos, alfa=0.95):
    """CVaR (Expected Shortfall) histórico: pérdida media en el peor (1−α) de los casos (Rockafellar & Uryasev 2000)."""
    r = np.sort(np.asarray(rendimientos, float))
    k = max(1, int(np.floor(len(r) * (1 - alfa))))
    return {"var": float(-r[k - 1]), "cvar": float(-r[:k].mean())}


def kelly(media, varianza, fraccion=0.25):
    """Kelly continuo f* = μ/σ², con fracción de seguridad (por defecto ¼ Kelly) y tope 1."""
    if varianza <= 0:
        return 0.0
    return float(max(0.0, min(1.0, fraccion * media / varianza)))
