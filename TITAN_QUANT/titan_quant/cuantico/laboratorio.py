"""Experimentos del laboratorio cuántico con DATOS REALES (velas de cTrader) y registro de resultados."""
import json
import sqlite3
import time

import numpy as np

from .. import config
from . import VERSION, qaoa, qmc, vqe

ACTIVOS = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD", "GERMANY 40", "US 500", "USDCAD")


def _db():
    r = config.DATOS / "cuantico" / "laboratorio.db"
    r.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(r), timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE IF NOT EXISTS experimentos(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, tipo TEXT, version TEXT, entrada TEXT, resultado TEXT, ms INTEGER)")
    return c


def rendimientos_reales(n_activos=6, intervalo="1d", n=250):
    from ..backtest_ctrader import almacen
    a = almacen()
    series = {}
    for s in ACTIVOS:
        filas = a.q("SELECT ts, c FROM velas_historicas WHERE proveedor='ctrader-demo' AND simbolo=? AND intervalo=? ORDER BY ts DESC LIMIT ?", (s, intervalo, n + 1))
        if len(filas) > n * 0.8:
            series[s] = {f["ts"]: f["c"] for f in filas}
        if len(series) >= n_activos:
            break
    if len(series) < 3:
        return None, None
    comunes = sorted(set.intersection(*[set(v) for v in series.values()]))
    nombres = list(series)
    P = np.array([[series[s][t] for s in nombres] for t in comunes], float)
    return nombres, np.diff(np.log(P), axis=0)


def experimento_cartera(k=3, capas=3):
    from ..ciencia import cartera
    nombres, R = rendimientos_reales()
    if R is None:
        raise ValueError("No hay velas diarias suficientes de cTrader para el experimento.")
    S, delta = cartera.ledoit_wolf(R)
    mu = R.mean(0)
    escala = 1 / np.sqrt(np.diag(S)).mean()
    t0 = time.time()
    r = qaoa.resolver(mu * escala * 10, S * escala ** 2, k, p=capas)
    coste, _ = qaoa.qubo_cartera(mu * escala * 10, S * escala ** 2, k)
    v = vqe.resolver(coste, len(nombres), capas=2)
    res = {"activos": nombres, "k": k, "contraccion_ledoit_wolf": delta, "qaoa": r, "vqe": v,
           "seleccion_qaoa": [nombres[i] for i, b in enumerate(r["mas_probable"]) if b],
           "seleccion_optima": [nombres[i] for i, b in enumerate(r["optimo_clasico"]) if b]}
    return _guardar("cartera_qaoa_vqe", {"k": k, "capas": capas, "activos": nombres}, res, t0)


def experimento_amplitud(m=7):
    t0 = time.time()
    res = qmc.probabilidad_objetivo_antes_que_stop(0.0, 1.0, 2.0, n=6, m=m)
    return _guardar("estimacion_amplitud", {"m": m}, res, t0)


def _guardar(tipo, entrada, res, t0):
    ms = int((time.time() - t0) * 1000)
    c = _db()
    c.execute("INSERT INTO experimentos(ts,tipo,version,entrada,resultado,ms) VALUES(?,?,?,?,?,?)",
              (int(time.time()), tipo, VERSION, json.dumps(entrada), json.dumps(res, default=float), ms))
    c.commit()
    c.close()
    return {**res, "ms": ms, "tipo": tipo, "experimental": True}


def historial(limite=20):
    c = _db()
    filas = [dict(r) for r in c.execute("SELECT * FROM experimentos ORDER BY id DESC LIMIT ?", (limite,))]
    c.close()
    for f in filas:
        f["entrada"], f["resultado"] = json.loads(f["entrada"]), json.loads(f["resultado"])
    return filas
