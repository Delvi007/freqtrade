"""Motor de backtesting del bot cTrader. RESULTADOS HISTÓRICOS CALCULADOS, nunca operaciones de cTrader.

Estrategias (las reglas que usa TITAN con cTrader):
  ema_rsi_atr      regla técnica del motor 13 (BACKTESTING ENGINE) que valida los escenarios del FUSION ENGINE:
                   alineación EMA rápida/lenta + RSI, stop 1,5·ATR, objetivo 2·ATR, salida por tiempo a 2k velas.
                   (El FUSION ENGINE completo — 23 motores, noticias, macro — no se reproduce vela a vela: el informe
                   lo indica. Lo que se valida es su regla técnica.)
  keltner_rci_atr  señal Keltner + RCI de la ejecución DEMO (trader/ejecucion_demo.py): stop 1,5·ATR, objetivo 3·ATR.
Ejecución: señal con datos hasta la vela i CERRADA, entrada en la apertura de i+1; si en una vela se tocan stop y
objetivo, cuenta el STOP (conservador). Coste de ida y vuelta = spread medido en cTrader (mediana de lo observado),
o el que indique el usuario (se marca como supuesto). Resultados en R (1 R = distancia al stop).

Validación: 70 % dentro de muestra / 30 % fuera; walk-forward en K tramos; ventaja estadística (IC 95 % de la
expectativa en R > 0 con ≥ 30 operaciones fuera de muestra); sobreoptimización (rejilla optimizada dentro de muestra
→ rango de la mejor combinación fuera de muestra).
"""
import json
import math
import statistics
import time
from itertools import product

from . import ETIQUETA, PROVEEDOR, almacen
from .. import niveles
from ..estrategias.keltner_rci import senales as senales_keltner
from ..motores import cuant, mat

ESTRATEGIAS = {
    "ema_rsi_atr": {"ema_rapida": 20, "ema_lenta": 50, "atr_stop": 1.5, "atr_obj": 2.0},
    "keltner_rci_atr": {"periodo_keltner": 20, "multiplicador": 1.5, "periodo_rci": 9, "umbral": 70.0, "ventana": 4,
                        "atr_stop": 1.5, "atr_obj": 3.0},
}
REJILLAS = {
    "ema_rsi_atr": {"ema_rapida": (10, 20), "ema_lenta": (50, 100), "atr_stop": (1.0, 1.5, 2.0), "atr_obj": (1.5, 2.0, 3.0)},
    "keltner_rci_atr": {"periodo_keltner": (14, 20, 30), "multiplicador": (1.5, 2.0), "atr_stop": (1.0, 1.5), "atr_obj": (2.0, 3.0)},
}
FRACCION_DENTRO = 0.7
MIN_OPS = 30


class SinDatosBacktest(ValueError):
    pass


def _serie(simbolo, intervalo, desde=None, hasta=None):
    filas = almacen().leer(PROVEEDOR, simbolo, intervalo, desde, hasta)
    return {"t": [f[0] for f in filas], "o": [f[1] for f in filas], "h": [f[2] for f in filas], "l": [f[3] for f in filas],
            "c": [f[4] for f in filas], "v": [f[5] for f in filas]}


def _salida(s, i, sig, atr, atr_stop, atr_obj, k):
    o, h, l, c = s["o"], s["h"], s["l"], s["c"]
    ent = o[i + 1]
    stop, obj = ent - sig * atr_stop * atr, ent + sig * atr_obj * atr
    salida, motivo, j = None, "tiempo", i + 1
    for j in range(i + 1, min(len(c), i + 1 + 2 * k)):
        if (sig > 0 and l[j] <= stop) or (sig < 0 and h[j] >= stop):
            salida, motivo = stop, "stop"
            break
        if (sig > 0 and h[j] >= obj) or (sig < 0 and l[j] <= obj):
            salida, motivo = obj, "objetivo"
            break
    if salida is None:
        salida = c[j]
    return ent, salida, motivo, j


def operaciones(s, estrategia, params, k, costo_frac):
    """Lista de operaciones calculadas {i, dir, entrada, salida, r, motivo} sin solapes."""
    c = s["c"]
    if len(c) < 60:
        return []
    atr = mat.atr_serie(s["h"], s["l"], c, 14)
    if estrategia == "ema_rsi_atr":
        f = {"emas": {params["ema_rapida"]: mat.ema(c, params["ema_rapida"]), params["ema_lenta"]: mat.ema(c, params["ema_lenta"])},
             "rsi": mat.rsi_serie(c, 14), "atr": atr}
        return cuant.simular_estrategia(s, f, k, costo_frac * 100, params["atr_stop"], params["atr_obj"])
    if estrategia != "keltner_rci_atr":
        raise ValueError("Estrategia desconocida: " + str(estrategia))
    kw = {x: params[x] for x in ("periodo_keltner", "multiplicador", "periodo_rci", "umbral", "ventana")}
    out, libre = [], 0
    for e in senales_keltner(s["h"], s["l"], c, **kw):
        i = e["indice"]
        if i < libre or i >= len(c) - 2 or not atr[i]:
            continue
        sig = 1 if e["direccion"] == "compra" else -1
        ent, salida, motivo, j = _salida(s, i, sig, atr[i], params["atr_stop"], params["atr_obj"], k)
        riesgo = params["atr_stop"] * atr[i]
        r = (sig * (salida - ent) - 2 * costo_frac * ent) / riesgo if riesgo else 0.0
        out.append({"i": i, "dir": sig, "entrada": ent, "salida": salida, "r": r, "motivo": motivo})
        libre = j + 1
    return out


def operaciones_simple(s, estrategia, params, k, costo_frac, atr_stop=1.5, atr_obj=2.0):
    """Operaciones calculadas para una estrategia básica (estrategias/simples.py) con stop/objetivo por ATR."""
    from ..estrategias import simples
    c = s["c"]
    if len(c) < 60:
        return []
    atr = mat.atr_serie(s["h"], s["l"], c, 14)
    out, libre = [], 0
    for e in simples.senales(estrategia, s["o"], s["h"], s["l"], c, params):
        i = e["indice"]
        if i < libre or i >= len(c) - 2 or not atr[i]:
            continue
        sig = 1 if e["direccion"] == "compra" else -1
        ent, salida, motivo, j = _salida(s, i, sig, atr[i], atr_stop, atr_obj, k)
        riesgo = atr_stop * atr[i]
        r = (sig * (salida - ent) - 2 * costo_frac * ent) / riesgo if riesgo else 0.0
        out.append({"i": i, "dir": sig, "entrada": ent, "salida": salida, "r": r, "motivo": motivo})
        libre = j + 1
    return out


def metricas(trades):
    m = cuant.metricas(trades)
    if m.get("n", 0) >= 2:
        rs = [t["r"] for t in trades]
        sd = statistics.stdev(rs)
        e = m["expectativa_r"]
        m["ic95_expectativa_r"] = [e - 1.96 * sd / math.sqrt(len(rs)), e + 1.96 * sd / math.sqrt(len(rs))]
        m["t_estadistico"] = e / (sd / math.sqrt(len(rs))) if sd else None
    m["ventaja_significativa"] = bool(m.get("n", 0) >= MIN_OPS and (m.get("ic95_expectativa_r") or [0])[0] > 0)
    return m


def _combos(estrategia):
    rej = REJILLAS[estrategia]
    claves = list(rej)
    for valores in product(*(rej[x] for x in claves)):
        prm = {**ESTRATEGIAS[estrategia], **dict(zip(claves, valores))}
        if estrategia == "ema_rsi_atr" and prm["ema_rapida"] >= prm["ema_lenta"]:
            continue
        yield prm


def sobreoptimizacion(s, estrategia, k, costo_frac, corte):
    filas = []
    for prm in _combos(estrategia):
        ops = operaciones(s, estrategia, prm, k, costo_frac)
        di, fu = [t for t in ops if t["i"] < corte], [t for t in ops if t["i"] >= corte]
        filas.append({"params": prm, "dentro": metricas(di), "fuera": metricas(fu)})
    validas = [f for f in filas if f["dentro"].get("n", 0) >= 10]
    if not validas:
        return {"evaluable": False, "motivo": "menos de 10 operaciones dentro de muestra en todas las combinaciones", "combinaciones": len(filas)}
    mejor = max(validas, key=lambda f: f["dentro"]["expectativa_r"])
    ev_fuera = sorted(f["fuera"]["expectativa_r"] for f in filas if f["fuera"].get("n"))
    e_mf = mejor["fuera"].get("expectativa_r")
    mediana = statistics.median(ev_fuera) if ev_fuera else None
    motivos = []
    if e_mf is None:
        motivos.append("la mejor combinación no opera fuera de muestra")
    else:
        if mejor["dentro"]["expectativa_r"] > 0 >= e_mf:
            motivos.append("gana dentro de muestra y pierde fuera")
        if mediana is not None and e_mf < mediana:
            motivos.append("la mejor combinación dentro de muestra queda por debajo de la mediana fuera de muestra")
    return {"evaluable": True, "combinaciones": len(filas),
            "mejor_dentro": {"params": mejor["params"], "expectativa_dentro_r": mejor["dentro"]["expectativa_r"], "expectativa_fuera_r": e_mf,
                             "n_dentro": mejor["dentro"]["n"], "n_fuera": mejor["fuera"].get("n", 0)},
            "percentil_fuera_de_la_mejor": (sum(1 for x in ev_fuera if x <= e_mf) / len(ev_fuera)) if ev_fuera and e_mf is not None else None,
            "mediana_expectativa_fuera_r": mediana, "sobreoptimizacion_probable": bool(motivos), "motivos": motivos}


def ejecutar(simbolo, intervalo="15m", estrategia="ema_rsi_atr", horizonte="intradia", k_tramos=4, costo_por_lado_pct=None,
             desde=None, hasta=None, params=None, guardar=True):
    simbolo = str(simbolo).upper()
    if estrategia not in ESTRATEGIAS:
        raise ValueError("Estrategia no válida: " + ", ".join(ESTRATEGIAS))
    params = {**ESTRATEGIAS[estrategia], **(params or {})}
    k = niveles.HORIZONTES[horizonte]["barras_adelante"] if horizonte in niveles.HORIZONTES else 8
    s = _serie(simbolo, intervalo, desde, hasta)
    n = len(s["c"])
    if n < 300:
        raise SinDatosBacktest(f"Solo {n} velas {intervalo} de {simbolo} en el histórico de cTrader: recopila más datos.")
    if costo_por_lado_pct is None:
        from .recolector import spread_observado
        sp, nobs = spread_observado(simbolo)
        if sp is None:
            raise SinDatosBacktest(f"No hay spread observado de {simbolo} en cTrader: recopila con el mercado abierto o indica el coste.")
        costo_frac = (sp / 2) / statistics.median(s["c"])
        fuente = f"medio spread medido en cTrader DEMO (mediana de {nobs} observación(es): {sp:.6g})"
    else:
        costo_frac = float(costo_por_lado_pct) / 100
        fuente = "SUPUESTO indicado por el usuario"
    ops = operaciones(s, estrategia, params, k, costo_frac)
    corte = int(n * FRACCION_DENTRO)
    dentro, fuera = [t for t in ops if t["i"] < corte], [t for t in ops if t["i"] >= corte]
    tam = max(1, n // k_tramos)
    wf = []
    for b in range(k_tramos):
        lo, hi = b * tam, (b + 1) * tam if b < k_tramos - 1 else n
        m = metricas([t for t in ops if lo <= t["i"] < hi])
        wf.append({"tramo": b, "desde": s["t"][lo], "hasta": s["t"][hi - 1], **m})
    mf = metricas(fuera)
    sobre = sobreoptimizacion(s, estrategia, k, costo_frac, corte)
    res = {"etiqueta": ETIQUETA, "simbolo": simbolo, "intervalo": intervalo, "proveedor_datos": PROVEEDOR, "estrategia": estrategia,
           "parametros": params, "horizonte": horizonte, "salida_por_tiempo_velas": 2 * k, "velas": n,
           "desde": s["t"][0], "hasta": s["t"][-1], "huecos": len(almacen().huecos(PROVEEDOR, simbolo, intervalo, desde, hasta)),
           "costo_por_lado_frac": costo_frac, "costo_fuente": fuente,
           "global": metricas(ops), "dentro_de_muestra": metricas(dentro), "fuera_de_muestra": mf, "walk_forward": wf,
           "ventaja_fuera_de_muestra": {"significativa": mf["ventaja_significativa"],
                                        "motivo": "IC 95 % de la expectativa fuera de muestra > 0 con ≥ 30 operaciones" if mf["ventaja_significativa"]
                                        else f"sin ventaja demostrada fuera de muestra ({mf.get('n', 0)} operaciones)"},
           "sobreoptimizacion": sobre,
           "alcance": ("Regla técnica del motor 13; el FUSION ENGINE completo no se reproduce vela a vela." if estrategia == "ema_rsi_atr"
                       else "Señal Keltner+RCI de la ejecución DEMO con stop/objetivo por ATR."),
           "ultimas_operaciones_calculadas": [{"ts": s["t"][t["i"]], "dir": t["dir"], "entrada": t["entrada"], "salida": t["salida"],
                                               "r": round(t["r"], 3), "motivo": t["motivo"]} for t in ops[-20:]],
           "nota": "Resultados calculados sobre velas pasadas. El rendimiento histórico no garantiza resultados futuros."}
    if guardar:
        alm = almacen()
        with alm.tx() as c:
            cur = c.execute("""INSERT INTO informes(ts,etiqueta,simbolo,intervalo,proveedor,estrategia,desde,hasta,velas,costo_por_lado,costo_fuente,parametros,resultado)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (int(time.time()), ETIQUETA, simbolo, intervalo, PROVEEDOR, estrategia, res["desde"], res["hasta"], n, costo_frac, fuente,
                             json.dumps(params), json.dumps(res, ensure_ascii=False, default=str)))
            res["informe_id"] = cur.lastrowid
    return res


def informes(limite=20):
    filas = almacen().q("""SELECT id, ts, etiqueta, simbolo, intervalo, estrategia, desde, hasta, velas, costo_por_lado, costo_fuente, resultado
                           FROM informes ORDER BY id DESC LIMIT ?""", (int(limite),))
    for f in filas:
        r = json.loads(f.pop("resultado"))
        f["global"] = r.get("global")
        f["fuera_de_muestra"] = r.get("fuera_de_muestra")
        f["sobreoptimizacion_probable"] = (r.get("sobreoptimizacion") or {}).get("sobreoptimizacion_probable")
    return filas
