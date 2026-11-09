"""Optimización sin derivadas: Nelder-Mead (simplex adaptativo) y recocido simulado."""
import math

import numpy as np


def nelder_mead(f, x0, paso=0.1, max_iter=2000, tol=1e-9):
    x0 = np.asarray(x0, float)
    n = len(x0)
    s = [x0] + [x0 + np.eye(n)[i] * (paso if x0[i] == 0 else paso * abs(x0[i]) + paso) for i in range(n)]
    fs = [f(p) for p in s]
    a, g, r, sh = 1.0, 1 + 2 / n, 0.75 - 1 / (2 * n), 1 - 1 / n          # parámetros adaptativos (Gao & Han 2012)
    for _ in range(max_iter):
        orden = np.argsort(fs)
        s, fs = [s[i] for i in orden], [fs[i] for i in orden]
        if abs(fs[-1] - fs[0]) <= tol * (abs(fs[0]) + tol):
            break
        c = np.mean(s[:-1], axis=0)
        xr = c + a * (c - s[-1])
        fr = f(xr)
        if fs[0] <= fr < fs[-2]:
            s[-1], fs[-1] = xr, fr
            continue
        if fr < fs[0]:
            xe = c + g * (xr - c)
            fe = f(xe)
            s[-1], fs[-1] = (xe, fe) if fe < fr else (xr, fr)
            continue
        xc = c + r * ((xr if fr < fs[-1] else s[-1]) - c)
        fc = f(xc)
        if fc < min(fr, fs[-1]):
            s[-1], fs[-1] = xc, fc
            continue
        s = [s[0]] + [s[0] + sh * (p - s[0]) for p in s[1:]]
        fs = [fs[0]] + [f(p) for p in s[1:]]
    i = int(np.argmin(fs))
    return s[i], fs[i]


def recocido(energia, estado0, vecino, t0=1.0, t1=1e-3, pasos=5000, semilla=0):
    rnd = np.random.default_rng(semilla)
    x, e = estado0, energia(estado0)
    mejor, emejor = x, e
    for k in range(pasos):
        t = t0 * (t1 / t0) ** (k / max(1, pasos - 1))
        y = vecino(x, rnd)
        ey = energia(y)
        if ey < e or rnd.random() < math.exp(-(ey - e) / t):
            x, e = y, ey
            if e < emejor:
                mejor, emejor = x, e
    return mejor, emejor
