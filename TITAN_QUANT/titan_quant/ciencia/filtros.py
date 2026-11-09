"""Filtro de Kalman (nivel + tendencia local) y ajuste de Ornstein-Uhlenbeck."""
import math

import numpy as np


def kalman_tendencia(y, q_nivel=1e-5, q_tend=1e-7, r=None):
    """Modelo de tendencia local: x=[nivel, pendiente]. Devuelve nivel y pendiente filtrados (estimación causal)."""
    y = np.asarray(y, float)
    r = r if r is not None else float(np.var(np.diff(y))) or 1e-8
    F = np.array([[1.0, 1.0], [0.0, 1.0]])
    H = np.array([[1.0, 0.0]])
    Q = np.diag([q_nivel * r * 1e4, q_tend * r * 1e4])
    x = np.array([y[0], 0.0])
    P = np.eye(2) * r * 10
    niv, pen = np.empty(len(y)), np.empty(len(y))
    for t, z in enumerate(y):
        x = F @ x
        P = F @ P @ F.T + Q
        S = float((H @ P @ H.T)[0, 0]) + r
        K = (P @ H.T).ravel() / S
        x = x + K * (z - x[0])
        P = (np.eye(2) - np.outer(K, H)) @ P
        niv[t], pen[t] = x
    return {"nivel": niv, "pendiente": pen}


def ornstein_uhlenbeck(x, dt=1.0):
    """Ajuste por regresión AR(1): dx = θ(μ − x)dt + σ dW. Vida media = ln 2 / θ (en unidades de dt)."""
    x = np.asarray(x, float)
    a, b = np.polyfit(x[:-1], x[1:], 1)
    if not 0 < a < 1:
        return {"theta": None, "mu": None, "sigma": None, "vida_media": None, "reversion": False, "phi": float(a)}
    theta = -math.log(a) / dt
    mu = b / (1 - a)
    res = x[1:] - (a * x[:-1] + b)
    sigma = float(np.std(res)) * math.sqrt(2 * theta / (1 - a * a))
    return {"theta": theta, "mu": mu, "sigma": sigma, "vida_media": math.log(2) / theta, "reversion": True, "phi": float(a)}
