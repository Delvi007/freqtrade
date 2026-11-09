"""VQE con ansatz eficiente para hardware (capas RY + cadena de CZ) sobre un hamiltoniano diagonal (Ising/QUBO)."""
import numpy as np

from ..ciencia.optimizacion import nelder_mead
from . import simulador as sim


def _estado(th, n, capas):
    s = sim.estado_cero(n)
    k = 0
    for c in range(capas):
        for q in range(n):
            s = sim.puerta1(s, n, q, sim.ry(th[k]))
            k += 1
        if c < capas - 1:
            for q in range(n - 1):
                s = sim.cz(s, n, q, q + 1)
    return s


def resolver(coste_diagonal, n, capas=2, reinicios=4, semilla=0):
    c = np.asarray(coste_diagonal, float)
    cn = (c - c.mean()) / (c.std() or 1.0)
    rnd = np.random.default_rng(semilla)
    mejor = None
    for _ in range(reinicios):
        par, val = nelder_mead(lambda th: float(sim.probabilidades(_estado(th, n, capas)) @ cn), rnd.uniform(0, np.pi, n * capas),
                               paso=0.4, max_iter=3000)
        if mejor is None or val < mejor[1]:
            mejor = (par, val)
    pr = sim.probabilidades(_estado(mejor[0], n, capas))
    i = int(np.argmax(pr))
    i_opt = int(np.argmin(c))
    return {"energia": float(pr @ c), "energia_minima": float(c[i_opt]), "estado": sim.bits(i, n), "p_optimo": float(pr[i_opt]),
            "acierta": i == i_opt, "capas": capas}
