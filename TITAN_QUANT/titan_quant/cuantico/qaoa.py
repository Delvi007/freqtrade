"""QAOA para selección de cartera (Markowitz binario con cardinalidad) en forma QUBO.

Minimizar  C(x) = q·xᵀΣx − μᵀx + P·(Σx − K)²   con x ∈ {0,1}ⁿ  (elegir K activos)
El coste es diagonal en la base computacional: e^{−iγC} es una fase por estado. Mezclador: e^{−iβΣX}.
"""
import itertools

import numpy as np

from ..ciencia.optimizacion import nelder_mead, recocido
from . import simulador as sim


def qubo_cartera(mu, S, k, aversion=1.0, penal=None):
    mu, S = np.asarray(mu, float), np.asarray(S, float)
    n = len(mu)
    penal = penal if penal is not None else 2.0 * (np.abs(mu).max() + aversion * np.abs(S).max()) * n
    idx = np.arange(2 ** n)
    X = ((idx[:, None] >> np.arange(n)[None, :]) & 1).astype(float)
    coste = aversion * np.einsum("bi,ij,bj->b", X, S, X) - X @ mu + penal * (X.sum(1) - k) ** 2
    return coste, X


def fuerza_bruta(coste):
    i = int(np.argmin(coste))
    return i, float(coste[i])


def _estado(params, coste, n, p):
    g, b = params[:p], params[p:]
    s = sim.hadamard_todos(n)
    for capa in range(p):
        s = s * np.exp(-1j * g[capa] * coste)
        U = sim.rx(2 * b[capa])
        for q in range(n):
            s = sim.puerta1(s, n, q, U)
    return s


def resolver(mu, S, k, p=3, aversion=1.0, reinicios=6, semilla=0):
    coste, X = qubo_cartera(mu, S, k, aversion)
    n = len(mu)
    cn = (coste - coste.mean()) / (coste.std() or 1.0)           # coste normalizado: paisaje de parámetros estable
    rnd = np.random.default_rng(semilla)
    mejor = None
    for _ in range(reinicios):
        x0 = np.r_[rnd.uniform(0, 1.0, p), rnd.uniform(0, 0.8, p)]
        par, val = nelder_mead(lambda th: float(sim.probabilidades(_estado(th, cn, n, p)) @ cn), x0, paso=0.2, max_iter=1500)
        if mejor is None or val < mejor[1]:
            mejor = (par, val)
    pr = sim.probabilidades(_estado(mejor[0], cn, n, p))
    i_opt, c_opt = fuerza_bruta(coste)
    i_q = int(np.argmax(pr))
    vecino = lambda x, r: x ^ (1 << int(r.integers(n)))
    i_sa, c_sa = recocido(lambda i: float(coste[i]), int(rnd.integers(2 ** n)), vecino, pasos=3000, semilla=semilla)
    return {"n_cubits": n, "capas": p, "parametros": mejor[0].tolist(), "energia_esperada": float(pr @ coste),
            "mas_probable": sim.bits(i_q, n), "coste_mas_probable": float(coste[i_q]), "p_optimo": float(pr[i_opt]),
            "p_uniforme": 1 / 2 ** n, "amplificacion": float(pr[i_opt] * 2 ** n),
            "optimo_clasico": sim.bits(i_opt, n), "coste_optimo": c_opt, "recocido": sim.bits(i_sa, n), "coste_recocido": c_sa,
            "acierta": i_q == i_opt,
            "nota": "Simulación clásica exacta del circuito. El óptimo clásico por fuerza bruta es exacto a este tamaño: no hay ventaja cuántica."}
