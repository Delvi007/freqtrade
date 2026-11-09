"""Teoría de la información y memoria de la serie."""
import math
from collections import Counter
from itertools import permutations

import numpy as np

from .especiales import norm_cdf


def entropia_shannon(x, bins=20):
    """Entropía (bits) del histograma, normalizada a [0,1] por log2(bins)."""
    h, _ = np.histogram(np.asarray(x, float), bins=bins)
    p = h[h > 0] / h.sum()
    return float(-(p * np.log2(p)).sum() / math.log2(bins))


def entropia_permutacion(x, orden=3, retardo=1):
    """Bandt & Pompe (2002). 1 = aleatorio puro, valores bajos = estructura predecible."""
    x = np.asarray(x, float)
    n = len(x) - (orden - 1) * retardo
    if n <= 0:
        return None
    patrones = Counter(tuple(np.argsort(x[i:i + orden * retardo:retardo])) for i in range(n))
    p = np.array(list(patrones.values()), float) / n
    return float(-(p * np.log2(p)).sum() / math.log2(math.factorial(orden)))


def informacion_mutua(x, y, bins=8):
    """I(X;Y) en bits por histograma 2D (p. ej. señal vs rendimiento futuro)."""
    h, _, _ = np.histogram2d(np.asarray(x, float), np.asarray(y, float), bins=bins)
    p = h / h.sum()
    px, py = p.sum(1, keepdims=True), p.sum(0, keepdims=True)
    m = p > 0
    return float((p[m] * np.log2(p[m] / (px @ py)[m])).sum())


def hurst(x, min_ventana=8):
    """Exponente de Hurst por R/S. ≈0.5 aleatorio, >0.5 persistente (tendencia), <0.5 antipersistente (reversión)."""
    x = np.asarray(x, float)
    n = len(x)
    tam = np.unique(np.floor(np.logspace(math.log10(min_ventana), math.log10(n // 2), 12)).astype(int))
    rs = []
    for w in tam:
        vals = []
        for i in range(0, n - w + 1, w):
            s = x[i:i + w]
            z = np.cumsum(s - s.mean())
            sd = s.std()
            if sd > 0:
                vals.append((z.max() - z.min()) / sd)
        if vals:
            rs.append((w, np.mean(vals)))
    if len(rs) < 3:
        return None
    w, v = np.log([a for a, _ in rs]), np.log([b for _, b in rs])
    return float(np.polyfit(w, v, 1)[0])


def razon_varianzas(r, q=4):
    """Lo & MacKinlay (1988) con estadístico robusto a heterocedasticidad. VR>1 tendencia, VR<1 reversión."""
    r = np.asarray(r, float)
    n = len(r)
    mu = r.mean()
    v1 = ((r - mu) ** 2).sum() / (n - 1)
    rq = np.convolve(r, np.ones(q), "valid")
    m = q * (n - q + 1) * (1 - q / n)
    vq = ((rq - q * mu) ** 2).sum() / m
    vr = vq / v1
    d = (r - mu) ** 2
    theta = sum((2 * (q - j) / q) ** 2 * ((d[j:] * d[:-j]).sum() / d.sum() ** 2) * n for j in range(1, q))
    z = (vr - 1) / math.sqrt(theta) if theta > 0 else 0.0
    return {"vr": float(vr), "z": float(z), "p_valor": float(2 * (1 - norm_cdf(abs(z))))}
