"""Modelo oculto de Markov gaussiano (Rabiner 1989): Baum-Welch con escalado, Viterbi y probabilidades filtradas.
Aplicado a rendimientos detecta regímenes (p. ej. calma / turbulencia, alcista / bajista) sin etiquetas previas."""
import numpy as np


def _gauss(x, mu, var):
    return np.exp(-0.5 * (x[:, None] - mu[None, :]) ** 2 / var[None, :]) / np.sqrt(2 * np.pi * var[None, :])


def ajustar(x, k=2, iter_max=200, tol=1e-6, semilla=0):
    x = np.asarray(x, float)
    n = len(x)
    rnd = np.random.default_rng(semilla)
    qs = np.quantile(x, np.linspace(0.2, 0.8, k))
    mu = qs + rnd.normal(0, x.std() * 0.01, k)
    var = np.full(k, x.var()) * np.linspace(0.5, 2.0, k)
    A = np.full((k, k), 0.1 / max(1, k - 1))
    np.fill_diagonal(A, 0.9)
    pi = np.full(k, 1.0 / k)
    prev = -np.inf
    for _ in range(iter_max):
        B = np.maximum(_gauss(x, mu, var), 1e-300)
        alfa = np.empty((n, k))
        c = np.empty(n)
        alfa[0] = pi * B[0]
        c[0] = alfa[0].sum()
        alfa[0] /= c[0]
        for t in range(1, n):
            alfa[t] = (alfa[t - 1] @ A) * B[t]
            c[t] = alfa[t].sum()
            alfa[t] /= c[t]
        beta = np.empty((n, k))
        beta[-1] = 1.0
        for t in range(n - 2, -1, -1):
            beta[t] = (A @ (B[t + 1] * beta[t + 1])) / c[t + 1]
        gamma = alfa * beta
        gamma /= gamma.sum(1, keepdims=True)
        xi = (alfa[:-1, :, None] * A[None] * (B[1:] * beta[1:])[:, None, :]) / c[1:, None, None]
        pi = gamma[0]
        A = xi.sum(0) / np.maximum(gamma[:-1].sum(0)[:, None], 1e-300)
        A /= A.sum(1, keepdims=True)
        w = gamma.sum(0)
        mu = (gamma * x[:, None]).sum(0) / w
        var = np.maximum((gamma * (x[:, None] - mu) ** 2).sum(0) / w, 1e-12)
        ll = float(np.log(c).sum())
        if ll - prev < tol:
            break
        prev = ll
    orden = np.argsort(var)                     # estado 0 = el de menor volatilidad
    return {"mu": mu[orden], "var": var[orden], "A": A[np.ix_(orden, orden)], "pi": pi[orden], "loglik": ll,
            "filtrada": alfa[:, orden], "suavizada": gamma[:, orden], "k": k}


def viterbi(x, m):
    x = np.asarray(x, float)
    B = np.log(np.maximum(_gauss(x, m["mu"], m["var"]), 1e-300))
    lA = np.log(np.maximum(m["A"], 1e-300))
    n, k = B.shape
    d = np.log(np.maximum(m["pi"], 1e-300)) + B[0]
    ptr = np.zeros((n, k), int)
    for t in range(1, n):
        s = d[:, None] + lA
        ptr[t] = s.argmax(0)
        d = s.max(0) + B[t]
    camino = np.empty(n, int)
    camino[-1] = int(d.argmax())
    for t in range(n - 1, 0, -1):
        camino[t - 1] = ptr[t, camino[t]]
    return camino


def describir(m):
    nombres = ["calma", "turbulencia"] if m["k"] == 2 else ["calma", "normal", "turbulencia"][:m["k"]]
    p = m["filtrada"][-1]
    e = int(p.argmax())
    dur = [1 / max(1e-9, 1 - m["A"][i, i]) for i in range(m["k"])]
    return {"regimen_actual": nombres[e], "prob_actual": float(p[e]), "probabilidades": {nombres[i]: float(p[i]) for i in range(m["k"])},
            "vol_por_regimen": {nombres[i]: float(np.sqrt(m["var"][i])) for i in range(m["k"])},
            "media_por_regimen": {nombres[i]: float(m["mu"][i]) for i in range(m["k"])},
            "duracion_esperada_velas": {nombres[i]: float(dur[i]) for i in range(m["k"])}}
