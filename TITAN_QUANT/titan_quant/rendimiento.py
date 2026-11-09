"""Pruebas de rendimiento reproducibles (python -m titan_quant.rendimiento). Mide en ESTE equipo, con datos sintéticos
de tamaño realista y semillas fijas, el tiempo de los componentes cuantitativos y de plataforma."""
import json
import os
import platform
import tempfile
import time

import numpy as np


def medir(nombre, fn, repeticiones=3):
    tiempos = []
    for _ in range(repeticiones):
        t0 = time.perf_counter()
        fn()
        tiempos.append((time.perf_counter() - t0) * 1000)
    return {"prueba": nombre, "ms_mediana": round(float(np.median(tiempos)), 1), "ms_min": round(min(tiempos), 1), "repeticiones": repeticiones}


def main():
    os.environ.setdefault("TITAN_DATOS", tempfile.mkdtemp(prefix="titan_rend_"))
    from .ciencia import bayes, cartera, informacion, regimen, volatilidad
    from .cuantico import qaoa, qmc
    rnd = np.random.default_rng(0)
    r = rnd.standard_normal(1000) * 0.01
    R = rnd.standard_normal((500, 20)) * 0.01
    A = rnd.normal(0, 1, (8, 8))
    S8 = A @ A.T / 8 + np.eye(8) * 0.1
    res = [
        medir("HMM 2 estados · 1.000 velas", lambda: regimen.ajustar(r, 2)),
        medir("GARCH(1,1) MLE · 1.000 velas", lambda: volatilidad.garch11(r)),
        medir("Hurst + entropía de permutación · 1.000", lambda: (informacion.hurst(r), informacion.entropia_permutacion(r, 4))),
        medir("Ledoit-Wolf + paridad de riesgo · 20 activos", lambda: cartera.paridad_riesgo(cartera.ledoit_wolf(R)[0])),
        medir("Inferencia bayesiana · 1.000 resultados", lambda: bayes.expectativa_r(r * 100)),
        medir("QAOA p=2 · 8 cúbits", lambda: qaoa.resolver(rnd.normal(0.2, 0.2, 8), S8, 3, p=2, reinicios=2), 1),
        medir("Estimación de amplitud · 8 cúbits de fase", lambda: qmc.estimar(np.ones(64), (np.arange(64) > 50).astype(float), m=8)),
    ]
    from .noticias import analisis
    titulos = ["Fed cuts interest rates by 25 basis points as inflation cools", "Bitcoin surges after ETF inflows", "Oil falls as OPEC+ boosts output"] * 334
    res.append(medir("Análisis de 1.000 noticias", lambda: [analisis.analizar(t, "", {"id": "cnbc", "estrellas": 4, "primaria": 0}) for t in titulos]))
    from . import supervisor
    supervisor.metricas()
    res.append(medir("Métricas CPU/RAM por hilo (psutil)", supervisor.metricas))
    info = {"python": platform.python_version(), "sistema": platform.platform(), "cpus": os.cpu_count(), "numpy": np.__version__}
    print(json.dumps({"equipo": info, "resultados": res}, ensure_ascii=False, indent=1))
    return res


if __name__ == "__main__":
    main()
