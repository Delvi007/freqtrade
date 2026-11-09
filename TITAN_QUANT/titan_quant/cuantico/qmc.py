"""Estimación de amplitud cuántica (QAE canónica de Brassard-Høyer-Mosca-Tapp) simulada exactamente.

Problema: estimar E[f(X)] con f ∈ [0,1] y X discretizada en 2ⁿ puntos. Operador A carga la distribución y codifica f en
la amplitud del cúbit objetivo: A|0⟩ = Σ √p_i |i⟩ (√(1−f_i)|0⟩ + √f_i|1⟩), de modo que P(objetivo=1) = a = E[f].
Con m cúbits de fase, QAE estima a con error O(1/2^m) frente a O(1/√N) del Monte Carlo clásico (ventaja CUADRÁTICA teórica
en número de consultas al oráculo; en un simulador clásico no hay ventaja de tiempo).

Aquí se simula el resultado de la fase de forma exacta a partir de la amplitud θ (sin(θ)² = a): la distribución de
salida de QAE canónica sobre los 2^m valores de fase tiene forma analítica conocida (núcleo de Fejér).
"""
import numpy as np


def amplitud(probs, f):
    p = np.asarray(probs, float)
    p = p / p.sum()
    return float(p @ np.clip(np.asarray(f, float), 0, 1))


def distribucion_qae(a, m):
    """Probabilidad de medir cada y ∈ {0..2^m−1} en la QAE canónica con amplitud a."""
    M = 2 ** m
    theta = np.arcsin(np.sqrt(a)) / np.pi           # θ_a / π ∈ [0, 1/2]
    y = np.arange(M)
    out = np.zeros(M)
    for signo in (1, -1):                            # autovalores e^{±2iθ}
        d = y / M - signo * theta
        num = np.sin(np.pi * M * d) ** 2
        den = (M ** 2) * np.sin(np.pi * d) ** 2
        with np.errstate(divide="ignore", invalid="ignore"):
            out += 0.5 * np.where(np.abs(den) < 1e-300, 1.0, num / np.where(den == 0, 1, den))
    return out / out.sum()


def estimar(probs, f, m=7, disparos=200, semilla=0):
    a = amplitud(probs, f)
    d = distribucion_qae(a, m)
    rnd = np.random.default_rng(semilla)
    ys = rnd.choice(len(d), size=disparos, p=d)
    est = np.sin(np.pi * ys / 2 ** m) ** 2
    valores, cuentas = np.unique(np.round(est, 12), return_counts=True)
    moda = float(valores[np.argmax(cuentas)])
    p = np.asarray(probs, float) / np.sum(probs)
    muestras = rnd.choice(len(p), size=2 ** m, p=p)               # MC clásico con el mismo presupuesto de consultas
    clasico = float(np.mean(np.clip(np.asarray(f, float), 0, 1)[muestras]))
    return {"valor_real": a, "estimacion_qae": moda, "error_qae": abs(moda - a), "estimacion_mc_clasico": clasico,
            "error_mc_clasico": abs(clasico - a), "consultas_oraculo": 2 ** m - 1, "muestras_mc": 2 ** m, "cubits_fase": m,
            "nota": "Comparación con el mismo número de consultas (2^m). Simulación clásica: la ventaja es teórica, no de tiempo."}


def probabilidad_objetivo_antes_que_stop(mu, sigma, objetivo_r=2.0, n=6, m=7):
    """Aplicación: P(rendimiento final ≥ objetivo) con rendimientos normales discretizados en 2ⁿ puntos."""
    x = np.linspace(mu - 4 * sigma, mu + 4 * sigma, 2 ** n)
    p = np.exp(-0.5 * ((x - mu) / sigma) ** 2)
    f = (x >= objetivo_r * sigma).astype(float)
    return estimar(p, f, m)
