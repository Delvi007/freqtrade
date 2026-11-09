"""Procesos estocásticos para Monte Carlo."""
import numpy as np


def gbm(s0, mu, sigma, pasos, trayectorias, dt=1.0, semilla=0):
    rnd = np.random.default_rng(semilla)
    z = rnd.standard_normal((trayectorias, pasos))
    inc = (mu - 0.5 * sigma ** 2) * dt + sigma * np.sqrt(dt) * z
    return s0 * np.exp(np.cumsum(inc, axis=1))


def merton(s0, mu, sigma, lam, mu_j, sigma_j, pasos, trayectorias, dt=1.0, semilla=0):
    """Difusión con saltos de Merton (1976): colas gruesas y huecos de precio."""
    rnd = np.random.default_rng(semilla)
    z = rnd.standard_normal((trayectorias, pasos))
    n = rnd.poisson(lam * dt, (trayectorias, pasos))
    saltos = n * mu_j + np.sqrt(n) * sigma_j * rnd.standard_normal((trayectorias, pasos))
    k = np.exp(mu_j + 0.5 * sigma_j ** 2) - 1
    inc = (mu - 0.5 * sigma ** 2 - lam * k) * dt + sigma * np.sqrt(dt) * z + saltos
    return s0 * np.exp(np.cumsum(inc, axis=1))


def ou(x0, theta, mu, sigma, pasos, trayectorias, dt=1.0, semilla=0):
    rnd = np.random.default_rng(semilla)
    x = np.empty((trayectorias, pasos))
    a = np.exp(-theta * dt)
    sd = sigma * np.sqrt((1 - a * a) / (2 * theta))
    prev = np.full(trayectorias, float(x0))
    for t in range(pasos):
        prev = mu + (prev - mu) * a + sd * rnd.standard_normal(trayectorias)
        x[:, t] = prev
    return x


def prob_toque(trayectorias, s0, stop, objetivo):
    """Probabilidad de tocar el objetivo antes que el stop (posición larga) en las trayectorias simuladas."""
    tp = (trayectorias >= objetivo)
    sl = (trayectorias <= stop)
    i_tp = np.where(tp.any(1), tp.argmax(1), np.inf)
    i_sl = np.where(sl.any(1), sl.argmax(1), np.inf)
    gana = (i_tp < i_sl).mean()
    pierde = (i_sl < i_tp).mean()
    return {"p_objetivo": float(gana), "p_stop": float(pierde), "p_ninguno": float(1 - gana - pierde)}
