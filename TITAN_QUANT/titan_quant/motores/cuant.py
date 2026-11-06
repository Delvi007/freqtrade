"""Motores cuantitativos: 7 STATISTICAL, 8 MACHINE LEARNING, 12 RISK, 13 BACKTESTING, 14 MONTE CARLO, 15 PORTFOLIO."""
import math
import random
from concurrent.futures import ThreadPoolExecutor

from . import datos, mat
from .base import Motor, SinDatos, registrar, resultado
from .. import niveles

ANUAL = {"5m": 252 * 78, "15m": 252 * 26, "60m": 252 * 7, "1d": 252, "1wk": 52}
COSTO_PCT = {"divisa": 0.01, "metal": 0.03, "energia": 0.04, "indice": 0.02, "accion": 0.05, "cripto": 0.10}  # por lado, supuesto


def _ctx_serie(ctx):
    s, f = ctx.get("serie"), ctx.get("feat")
    if not s or not f:
        raise SinDatos("Faltan serie o características.")
    return s, f


# --------------------------------------------------------------------------- 7
@registrar
class MotorEstadistico(Motor):
    numero, id, nombre = 7, "statistical", "STATISTICAL INTELLIGENCE ENGINE"
    objetivo = "Describir la distribución de retornos y si hay persistencia o reversión medible."
    metodos = ("Media y t-estadístico, volatilidad anualizada, asimetría, curtosis, Jarque-Bera (normalidad), "
               "autocorrelación (1 y 5), exponente de Hurst (R/S) y ratio de varianza de Lo-MacKinlay.")
    entradas = ("retornos logarítmicos",)
    salidas = ("estadisticos", "lectura")
    dependencias = ("features",)

    def calcular(self, ctx):
        s, f = _ctx_serie(ctx)
        r = f["logret"]
        if len(r) < 100:
            raise SinDatos("Menos de 100 retornos.")
        m, sd = mat.media(r), mat.desv(r)
        t = m / (sd / math.sqrt(len(r))) if sd else None
        k = ANUAL.get(s["intervalo"], 252)
        hu, vr = mat.hurst(r), mat.ratio_varianza(r, 4)
        ac1 = mat.autocorrelacion(r, 1)
        lect = []
        if hu is not None:
            lect.append("persistencia (Hurst %.2f)" % hu if hu > 0.55 else "reversión a la media (Hurst %.2f)" % hu if hu < 0.45 else "cercano a paseo aleatorio (Hurst %.2f)" % hu)
        if t is not None and abs(t) < 2:
            lect.append("la deriva media NO es estadísticamente distinta de cero")
        jb = mat.jarque_bera(r)
        if jb and jb > 5.99:
            lect.append("colas gruesas: los retornos no son normales (usar riesgo histórico, no gaussiano)")
        return {"salida": {"n": len(r), "media": m, "t_media": t, "vol_anual_pct": sd * math.sqrt(k) * 100 if sd else None,
                           "asimetria": mat.asimetria(r), "curtosis_exceso": mat.curtosis_exceso(r), "jarque_bera": jb,
                           "autocorr_1": ac1, "autocorr_5": mat.autocorrelacion(r, 5), "hurst": hu, "ratio_varianza_4": vr,
                           "lectura": lect}}


# --------------------------------------------------------------------------- 8
def _features_en(i, c, f, v):
    e = f["emas"]
    ks = sorted(e)
    rsi = f["rsi"][i]
    vm = mat.media([x for x in v[max(0, i - 20):i] if x]) if any(v[max(0, i - 20):i]) else None
    return [math.log(c[i] / c[i - 1]), math.log(c[i] / c[i - 5]), math.log(c[i] / c[i - 20]),
            ((rsi if rsi is not None else 50) - 50) / 50,
            (c[i] / e[ks[0]][i] - 1) * 100, (c[i] / e[ks[-1]][i] - 1) * 100,
            f["atr"][i] / c[i] * 100, f["macd_hist"][i] / c[i] * 100,
            (v[i] / vm - 1) if vm and v[i] else 0.0]


NOMBRES_X = ["ret1", "ret5", "ret20", "rsi", "dist_ema_rapida", "dist_ema_lenta", "atr_pct", "macd", "vol_rel"]


@registrar
class MotorML(Motor):
    numero, id, nombre = 8, "ml", "MACHINE LEARNING ENGINE"
    objetivo = "Estimar la probabilidad de que el precio suba en el horizonte, validada fuera de muestra."
    metodos = ("Regresión logística con L2 (y Bayes ingenuo gaussiano en niveles altos) sobre 9 variables técnicas. "
               "Validación walk-forward con purga de k velas entre entrenamiento y prueba para evitar fuga de etiquetas. "
               "La probabilidad solo se declara CALIBRADA si el Brier fuera de muestra mejora al de la tasa base.")
    entradas = ("serie", "caracteristicas")
    salidas = ("probabilidad_alcista", "calibrada", "metricas_fuera_de_muestra")
    dependencias = ("features",)
    consumo = "alto (CPU)"
    niveles = "Más épocas, más cortes de validación y un segundo modelo (Bayes) en avanzado/súper."

    def calcular(self, ctx):
        s, f = _ctx_serie(ctx)
        c, v = s["c"], s["v"]
        p = ctx["p"]
        k = niveles.HORIZONTES[ctx["horizonte"]]["barras_adelante"]
        idx = list(range(25, len(c) - k))     # 25: hace falta c[i-20] para ret20
        if len(idx) < p["ml_minimo"]:
            raise SinDatos(f"{len(idx)} ejemplos etiquetados; el nivel exige {p['ml_minimo']}.")
        X = [_features_en(i, c, f, v) for i in idx]
        y = [1 if c[i + k] > c[i] else 0 for i in idx]
        cortes = p["walk_forward_cortes"]
        tam = len(idx) // (cortes + 1)
        oos_p, oos_pb, oos_y = [], [], []
        for j in range(1, cortes + 1):
            fin_tr = j * tam - k                 # purga: las etiquetas de entrenamiento no tocan la prueba
            ini_te, fin_te = j * tam, min((j + 1) * tam, len(idx))
            if fin_tr < 50 or fin_te - ini_te < 10:
                continue
            Xtr, ms = mat.estandarizar(X[:fin_tr])
            w, b = mat.logistica_entrenar(Xtr, y[:fin_tr], epocas=p["ml_epocas"])
            Xte = [mat.aplicar_estandar(x, ms) for x in X[ini_te:fin_te]]
            oos_p += [mat.logistica_prob(w, b, x) for x in Xte]
            if "bayes" in p["modelos_ml"]:
                nb = mat.bayes_entrenar(Xtr, y[:fin_tr])
                oos_pb += [mat.bayes_prob(nb, x) for x in Xte]
            oos_y += y[ini_te:fin_te]
        if len(oos_y) < 30:
            raise SinDatos("Muestra fuera de muestra demasiado pequeña.")
        base = sum(y[:len(y) - len(oos_y)]) / max(1, len(y) - len(oos_y))
        brier_base = mat.brier([base] * len(oos_y), oos_y)
        brier_m = mat.brier(oos_p, oos_y)
        acierto = sum((pp > 0.5) == bool(t) for pp, t in zip(oos_p, oos_y)) / len(oos_y)
        Xall, ms = mat.estandarizar(X)
        w, b = mat.logistica_entrenar(Xall, y, epocas=p["ml_epocas"])
        x_ult = mat.aplicar_estandar(_features_en(len(c) - 1, c, f, v), ms)
        prob = mat.logistica_prob(w, b, x_ult)
        modelos = {"logistica": {"brier_oos": brier_m, "auc_oos": mat.auc(oos_p, oos_y), "acierto_oos": acierto,
                                 "pesos": dict(zip(NOMBRES_X, [round(x, 4) for x in w]))}}
        if oos_pb:
            modelos["bayes"] = {"brier_oos": mat.brier(oos_pb, oos_y), "auc_oos": mat.auc(oos_pb, oos_y)}
        calibrada = len(oos_y) >= 60 and brier_m < brier_base * 0.98
        notas = [] if calibrada else ["El modelo NO supera a la tasa base fuera de muestra: su probabilidad no se usa como señal."]
        return {"salida": {"probabilidad_alcista": prob, "calibrada": calibrada, "metodo_calibracion":
                           "Brier fuera de muestra (walk-forward con purga) frente a la tasa base",
                           "brier_oos": brier_m, "brier_base": brier_base, "tasa_base_alcista": base,
                           "n_entrenamiento": len(y), "n_oos": len(oos_y), "horizonte_velas": k, "modelos": modelos},
                "notas": notas}


# --------------------------------------------------------------------------- 13
def simular_estrategia(s, f, k, costo_pct, atr_stop=1.5, atr_obj=2.0):
    """Regla técnica (alineación EMA + RSI) evaluada SOLO con datos pasados; entrada en la apertura siguiente."""
    c, o, h, l = s["c"], s["o"], s["h"], s["l"]
    ks = sorted(f["emas"])
    if len(ks) < 2:
        return []
    er, el = f["emas"][ks[0]], f["emas"][ks[-1]]
    trades, i, prev = [], max(ks[-1], 30), 0
    while i < len(c) - 2:
        rsi = f["rsi"][i] or 50
        sig = 1 if er[i] > el[i] and c[i] > er[i] and 45 < rsi < 72 else -1 if er[i] < el[i] and c[i] < er[i] and 28 < rsi < 55 else 0
        if sig and sig != prev:
            ent = o[i + 1]
            atr = f["atr"][i]
            stop, obj = ent - sig * atr_stop * atr, ent + sig * atr_obj * atr
            riesgo = atr_stop * atr
            salida, j, motivo = None, i + 1, "tiempo"
            for j in range(i + 1, min(len(c), i + 1 + 2 * k)):
                if (sig > 0 and l[j] <= stop) or (sig < 0 and h[j] >= stop):
                    salida, motivo = stop, "stop"
                    break
                if (sig > 0 and h[j] >= obj) or (sig < 0 and l[j] <= obj):
                    salida, motivo = obj, "objetivo"
                    break
            if salida is None:
                salida = c[j]
            costo = 2 * costo_pct / 100 * ent
            r = (sig * (salida - ent) - costo) / riesgo if riesgo else 0
            trades.append({"i": i, "dir": sig, "entrada": ent, "salida": salida, "r": r, "motivo": motivo})
            i = j
        prev = sig
        i += 1
    return trades


def metricas(trades):
    if not trades:
        return {"n": 0}
    rs = [t["r"] for t in trades]
    g = [x for x in rs if x > 0]
    p = [x for x in rs if x <= 0]
    curva, acc = [], 0
    for x in rs:
        acc += x
        curva.append(acc)
    lo, hi = mat.wilson(len(g), len(rs))
    return {"n": len(rs), "tasa_acierto": len(g) / len(rs), "tasa_ic95": [lo, hi], "expectativa_r": mat.media(rs),
            "profit_factor": (sum(g) / -sum(p)) if p and sum(p) < 0 else None, "max_drawdown_r": mat.max_drawdown(curva),
            "r_total": acc}


@registrar
class MotorBacktest(Motor):
    numero, id, nombre = 13, "backtesting", "BACKTESTING ENGINE"
    objetivo = "Medir cómo habría funcionado la regla técnica en la historia, con costes y separando dentro/fuera de muestra."
    metodos = ("Simulación vela a vela sin mirar al futuro: señal con datos hasta t, entrada en la apertura de t+1, stop 1,5·ATR, "
               "objetivo 2·ATR, salida por tiempo a 2k velas, coste de ida y vuelta. 70 % dentro de muestra / 30 % fuera. "
               "Intervalo de Wilson para la tasa de acierto.")
    entradas = ("serie", "caracteristicas", "microestructura")
    salidas = ("metricas_dentro", "metricas_fuera", "operaciones_R")
    dependencias = ("features", "microstructure")
    niveles = "Número de velas evaluadas: 300 / 800 / 1500 / 3000."

    def calcular(self, ctx):
        s, f = _ctx_serie(ctx)
        n = ctx["p"]["backtest_barras"]
        k = niveles.HORIZONTES[ctx["horizonte"]]["barras_adelante"]
        costo = COSTO_PCT.get(ctx["activo"].get("clase"), 0.05)
        ms = resultado(ctx, "microstructure") or {}
        est = (ms.get("spread_estimado_pct") or {}).get("corwin_schultz")
        if est:
            costo = max(costo, est / 2)
        trades = simular_estrategia(s, f, k, costo)
        corte = len(s["c"]) - n
        trades = [t for t in trades if t["i"] >= corte] or trades
        if len(trades) < 5:
            raise SinDatos(f"Solo {len(trades)} operaciones históricas: no hay muestra.")
        div = int(len(trades) * 0.7)
        dentro, fuera = metricas(trades[:div]), metricas(trades[div:])
        notas = []
        if fuera["n"] < 30:
            notas.append(f"Fuera de muestra solo {fuera['n']} operaciones: resultado poco concluyente.")
        if dentro.get("expectativa_r", 0) > 0 and fuera.get("expectativa_r", 0) <= 0:
            notas.append("Posible sobreajuste: gana dentro de muestra y no fuera.")
        notas.append("El rendimiento histórico no garantiza resultados futuros.")
        ctx["trades_bt"] = [t["r"] for t in trades]
        return {"salida": {"regla": "EMA rápida/lenta + RSI, stop 1,5 ATR, objetivo 2 ATR", "costo_por_lado_pct": costo,
                           "dentro_muestra": dentro, "fuera_muestra": fuera, "total": metricas(trades),
                           "ultimas": [{"dir": t["dir"], "r": round(t["r"], 2), "motivo": t["motivo"]} for t in trades[-10:]]},
                "notas": notas}


# --------------------------------------------------------------------------- 12
@registrar
class MotorRiesgo(Motor):
    numero, id, nombre = 12, "risk", "RISK INTELLIGENCE ENGINE"
    objetivo = "Cuantificar el riesgo del horizonte y dimensionar una posición coherente con el capital del usuario."
    metodos = ("VaR y Expected Shortfall históricos (95 % y 99 %) de retornos acumulados a k velas (no gaussianos), "
               "stop por ATR y tamaño = capital·riesgo% / distancia al stop.")
    entradas = ("serie", "caracteristicas", "configuración de riesgo del usuario")
    salidas = ("var", "es", "stop_atr", "tamano_posicion")
    dependencias = ("features",)

    def calcular(self, ctx):
        s, f = _ctx_serie(ctx)
        k = niveles.HORIZONTES[ctx["horizonte"]]["barras_adelante"]
        r = f["logret"]
        acum = [sum(r[i:i + k]) for i in range(0, len(r) - k + 1)]
        if len(acum) < 50:
            raise SinDatos("Pocos datos para riesgo histórico.")
        perd = sorted(-x for x in acum)

        def var(q):
            return mat.cuantil(perd, q)

        def es(q):
            v = var(q)
            cola = [x for x in perd if x >= v]
            return mat.media(cola)
        precio, atr = s["c"][-1], f["atr"][-1]
        cfg = ctx.get("riesgo_usuario") or {"capital": 1000.0, "riesgo_pct": 1.0}
        dist = 1.5 * atr
        importe = cfg["capital"] * cfg["riesgo_pct"] / 100
        unidades = importe / dist if dist else None
        return {"salida": {"var95_pct": var(0.95) * 100, "var99_pct": var(0.99) * 100, "es95_pct": es(0.95) * 100,
                           "es99_pct": es(0.99) * 100, "horizonte_velas": k, "atr": atr, "stop_distancia": dist,
                           "capital": cfg["capital"], "riesgo_pct": cfg["riesgo_pct"], "riesgo_importe": importe,
                           "unidades": unidades, "nocional": unidades * precio if unidades else None,
                           "nota_margen": "El margen y el apalancamiento dependen del broker: verifica el tamaño mínimo y el valor por punto."}}


# --------------------------------------------------------------------------- 14
@registrar
class MotorMonteCarlo(Motor):
    numero, id, nombre = 14, "montecarlo", "MONTE CARLO ENGINE"
    objetivo = "Mostrar el rango de resultados posibles: precio al horizonte y curva de resultados de la estrategia."
    metodos = ("Bootstrap por bloques de 5 retornos históricos (conserva rachas de volatilidad) para el precio al horizonte; "
               "remuestreo de las operaciones del backtest para la distribución de R, drawdown y probabilidad de pérdida.")
    entradas = ("retornos", "operaciones del backtest")
    salidas = ("precio_cuantiles", "prob_cierre_superior", "estrategia")
    dependencias = ("features", "backtesting")
    consumo = "medio-alto"
    niveles = "Simulaciones: 300 / 1000 / 3000 / 10 000."

    def calcular(self, ctx):
        s, f = _ctx_serie(ctx)
        n = ctx["p"]["montecarlo_sim"]
        k = niveles.HORIZONTES[ctx["horizonte"]]["barras_adelante"]
        r = f["logret"][-1000:]
        if len(r) < 60:
            raise SinDatos("Pocos retornos para simular.")
        rnd = random.Random(12345)          # reproducible
        p0, finales, bloque = s["c"][-1], [], 5
        for _ in range(n):
            acc, paso = 0.0, 0
            while paso < k:
                i = rnd.randrange(0, len(r) - bloque)
                for x in r[i:i + bloque]:
                    if paso >= k:
                        break
                    acc += x
                    paso += 1
            finales.append(p0 * math.exp(acc))
        out = {"simulaciones": n, "precio_inicial": p0, "horizonte_velas": k,
               "precio_cuantiles": {q: mat.cuantil(finales, q / 100) for q in (5, 25, 50, 75, 95)},
               "prob_cierre_superior": sum(1 for x in finales if x > p0) / n}
        tr = ctx.get("trades_bt") or []
        if len(tr) >= 10:
            m = max(30, len(tr))
            res, dds = [], []
            for _ in range(min(n, 3000)):
                curva, acc = [], 0.0
                for _ in range(m):
                    acc += tr[rnd.randrange(len(tr))]
                    curva.append(acc)
                res.append(acc)
                dds.append(mat.max_drawdown(curva))
            out["estrategia"] = {"operaciones_por_simulacion": m, "r_final_p5": mat.cuantil(res, 0.05),
                                 "r_final_p50": mat.cuantil(res, 0.5), "r_final_p95": mat.cuantil(res, 0.95),
                                 "prob_perdida": sum(1 for x in res if x < 0) / len(res),
                                 "drawdown_p95_r": mat.cuantil(dds, 0.95)}
        return {"salida": out, "notas": ["Supone que el futuro se parece a la muestra histórica; no anticipa eventos nuevos."]}


# --------------------------------------------------------------------------- 15
@registrar
class MotorCartera(Motor):
    numero, id, nombre = 15, "portfolio", "PORTFOLIO INTELLIGENCE ENGINE"
    objetivo = "Repartir el riesgo entre los activos seguidos por el usuario y medir la diversificación."
    metodos = ("Pesos por volatilidad inversa y por mínima varianza (descenso de gradiente proyectado sobre la matriz de "
               "covarianzas de retornos diarios); ratio de diversificación y contribución al riesgo.")
    entradas = ("activos seguidos (Mis activos)",)
    salidas = ("pesos_vol_inversa", "pesos_min_varianza", "diversificacion")
    consumo = "medio (red)"
    niveles = "Máximo de activos: 3 / 6 / 10 / 16."

    def calcular(self, ctx):
        sims = [x for x in (ctx.get("cartera") or []) if x][:ctx["p"]["activos_max"]]
        if ctx["activo"]["simbolo"] not in sims:
            sims = [ctx["activo"]["simbolo"]] + sims[:ctx["p"]["activos_max"] - 1]
        if len(sims) < 2:
            raise SinDatos("Marca al menos 2 activos en 'Mis activos' para el análisis de cartera.")

        def bajar(x):
            try:
                return datos.obtener(x, "1y", "1d")
            except Exception:
                return None
        with ThreadPoolExecutor(max_workers=max(1, ctx["p"]["concurrencia"])) as ex:
            series = [x for x in ex.map(bajar, sims) if x]
        if len(series) < 2:
            raise SinDatos("No se obtuvieron series suficientes para la cartera.")
        from .mercado import _por_dia
        dd = [_por_dia(x) for x in series]
        dias = sorted(set.intersection(*[set(d) for d in dd]))[-250:]
        if len(dias) < 60:
            raise SinDatos("Pocos días comunes entre los activos.")
        R = [mat.retornos([d[x] for x in dias]) for d in dd]
        n = len(R)
        mu = [mat.media(x) for x in R]
        cov = [[sum((a - mu[i]) * (b - mu[j]) for a, b in zip(R[i], R[j])) / (len(R[i]) - 1) for j in range(n)] for i in range(n)]
        vol = [math.sqrt(cov[i][i]) for i in range(n)]
        inv = [1 / v if v else 0 for v in vol]
        w_iv = [x / sum(inv) for x in inv]
        w = list(w_iv)
        for _ in range(500):
            g = [2 * sum(cov[i][j] * w[j] for j in range(n)) for i in range(n)]
            w = [max(0.0, wi - 0.5 * gi / (max(cov[i][i] for i in range(n)) * 4)) for i, (wi, gi) in enumerate(zip(w, g))]
            sm = sum(w) or 1
            w = [x / sm for x in w]

        def vol_cartera(ws):
            return math.sqrt(sum(ws[i] * ws[j] * cov[i][j] for i in range(n) for j in range(n)))
        vp = vol_cartera(w_iv)
        dr = sum(wi * vi for wi, vi in zip(w_iv, vol)) / vp if vp else None
        nombres = [x["simbolo"] for x in series]
        return {"salida": {"activos": nombres, "dias": len(dias),
                           "pesos_vol_inversa": dict(zip(nombres, [round(x, 4) for x in w_iv])),
                           "pesos_min_varianza": dict(zip(nombres, [round(x, 4) for x in w])),
                           "vol_anual_pct": {a: v * math.sqrt(252) * 100 for a, v in zip(nombres, vol)},
                           "vol_cartera_iv_pct": vp * math.sqrt(252) * 100, "ratio_diversificacion": dr},
                "estado": "completado" if len(series) == len(sims) else "simplificado",
                "faltantes": [x for x in sims if x not in nombres]}
