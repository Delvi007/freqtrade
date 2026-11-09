"""Detección de cambios en el rendimiento de una estrategia (resultados reales, en R)."""
import numpy as np


def cusum(x, objetivo=0.0, k=0.25, h=4.0):
    """CUSUM unilateral inferior (Page 1954) sobre resultados estandarizados: alarma cuando la suma acumulada de
    desviaciones por DEBAJO del objetivo supera h desviaciones típicas. Devuelve índice de alarma o None."""
    x = np.asarray(x, float)
    if len(x) < 5:
        return {"alarma": None, "estadistico": 0.0}
    sd = x.std() or 1.0
    s = 0.0
    for i, v in enumerate(x):
        s = max(0.0, s + (objetivo - v) / sd - k)
        if s > h:
            return {"alarma": i, "estadistico": s}
    return {"alarma": None, "estadistico": s}


def page_hinkley(x, delta=0.05, lam=3.0):
    """Page-Hinkley para caída de la media: alarma cuando la media reciente cae más de lam por debajo de su máximo."""
    x = np.asarray(x, float)
    media, m, mmax = 0.0, 0.0, 0.0
    for i, v in enumerate(x):
        media += (v - media) / (i + 1)
        m += media - v - delta
        mmax = max(mmax, m) if i else m
        if m - min(0.0, mmax) > lam and i >= 5:
            return {"alarma": i}
    return {"alarma": None}


def deterioro(resultados_r):
    """Diagnóstico combinado: deterioro si CUSUM alarma y la media de la última mitad es peor que la de la primera."""
    x = np.asarray(resultados_r, float)
    if len(x) < 10:
        return {"deterioro": False, "motivo": f"muestra insuficiente ({len(x)})"}
    c = cusum(x)
    mitad = len(x) // 2
    a, b = float(x[:mitad].mean()), float(x[mitad:].mean())
    d = c["alarma"] is not None and b < a and b < 0
    return {"deterioro": d, "media_antes": a, "media_reciente": b, "cusum": c,
            "motivo": "caída persistente del resultado (CUSUM)" if d else "sin evidencia de deterioro"}
