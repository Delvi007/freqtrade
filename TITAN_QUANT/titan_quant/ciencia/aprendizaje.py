"""Aprendizaje supervisado reproducible: regresión logística L2 por IRLS (Newton) con validación walk-forward.

Se compara SIEMPRE contra la referencia ingenua (frecuencia base) con la puntuación de Brier: un modelo solo es útil si
mejora a la referencia fuera de muestra. Si XGBoost o LightGBM están instalados se pueden evaluar con el mismo protocolo.
"""
import numpy as np


def _sig(z):
    return 1 / (1 + np.exp(-np.clip(z, -35, 35)))


class Logistica:
    def __init__(self, l2=1.0, iter_max=50):
        self.l2, self.iter_max = l2, iter_max

    def ajustar(self, X, y):
        X = np.asarray(X, float)
        y = np.asarray(y, float)
        self.mu, self.sd = X.mean(0), X.std(0) + 1e-12
        Z = np.column_stack([np.ones(len(X)), (X - self.mu) / self.sd])
        w = np.zeros(Z.shape[1])
        reg = np.eye(len(w)) * self.l2
        reg[0, 0] = 0
        for _ in range(self.iter_max):
            p = _sig(Z @ w)
            W = p * (1 - p)
            g = Z.T @ (p - y) + reg @ w
            H = (Z * W[:, None]).T @ Z + reg
            paso = np.linalg.solve(H + np.eye(len(w)) * 1e-9, g)
            w -= paso
            if np.abs(paso).max() < 1e-8:
                break
        self.w = w
        return self

    def prob(self, X):
        Z = np.column_stack([np.ones(len(X)), (np.asarray(X, float) - self.mu) / self.sd])
        return _sig(Z @ self.w)


def brier(p, y):
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def walk_forward(X, y, ventanas=5, minimo=100, l2=1.0):
    """Entrena en el pasado, evalúa en el siguiente bloque; nunca mira el futuro."""
    X, y = np.asarray(X, float), np.asarray(y, float)
    n = len(y)
    cortes = np.linspace(minimo, n, ventanas + 1).astype(int)
    pm, pb, ys = [], [], []
    for a, b in zip(cortes[:-1], cortes[1:]):
        if b <= a:
            continue
        m = Logistica(l2).ajustar(X[:a], y[:a])
        pm.append(m.prob(X[a:b]))
        pb.append(np.full(b - a, y[:a].mean()))
        ys.append(y[a:b])
    if not ys:
        return {"util": False, "motivo": "datos insuficientes"}
    pm, pb, ys = np.concatenate(pm), np.concatenate(pb), np.concatenate(ys)
    bm, bb = brier(pm, ys), brier(pb, ys)
    acierto = float(((pm > 0.5) == (ys > 0.5)).mean())
    return {"brier_modelo": bm, "brier_referencia": bb, "mejora_brier": bb - bm, "acierto": acierto, "n_fuera": int(len(ys)),
            "util": bm < bb * 0.995, "motivo": "mejora a la referencia fuera de muestra" if bm < bb * 0.995 else "no mejora a la referencia: no se usa"}
