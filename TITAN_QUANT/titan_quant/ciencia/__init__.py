"""Biblioteca científica TITAN (C5) — algoritmos cuantitativos con fundamento matemático, implementados en numpy,
versionados y con pruebas de corrección (titan_quant/pruebas/test_ciencia.py).

    especiales.py     funciones especiales (beta incompleta regularizada, t de Student, normal) — base de la inferencia
    bayes.py          inferencia bayesiana: Beta-Binomial (tasa de acierto) y Normal-Gamma (expectativa en R)
    volatilidad.py    GARCH(1,1) por máxima verosimilitud, EWMA (RiskMetrics), Parkinson, Garman-Klass
    regimen.py        modelo oculto de Markov gaussiano (Baum-Welch con escalado + Viterbi) para regímenes de mercado
    filtros.py        filtro de Kalman (nivel y tendencia) y ajuste de Ornstein-Uhlenbeck (vida media de reversión)
    informacion.py    entropía de Shannon y de permutación, información mutua, exponente de Hurst, razón de varianzas
    cartera.py        covarianza con contracción de Ledoit-Wolf, mínima varianza, paridad de riesgo, CVaR, Kelly fraccionado
    deterioro.py      detección de cambios: CUSUM y Page-Hinkley sobre resultados reales (deterioro de estrategias)
    estocastico.py    simulación Monte Carlo: movimiento browniano geométrico, saltos de Merton, Ornstein-Uhlenbeck
    aprendizaje.py    regresión logística regularizada (IRLS) con validación walk-forward y calibración (Brier)
    optimizacion.py   Nelder-Mead (sin derivadas) y recocido simulado

Referencias: Bollerslev (1986) GARCH; Rabiner (1989) HMM; Kalman (1960); Ledoit & Wolf (2004); Maillard, Roncalli &
Teïletche (2010) paridad de riesgo; Rockafellar & Uryasev (2000) CVaR; Kelly (1956); Page (1954) CUSUM; Bandt & Pompe
(2002) entropía de permutación; Hurst (1951); Lo & MacKinlay (1988) razón de varianzas; Merton (1976) saltos.
Implementación propia (sin copiar código de terceros).
"""
VERSION = "1.0.0"
