"""Motores de mercado: 2 DATA, 3 FEATURE ENGINEERING, 4 TECHNICAL, 5 CROSS-ASSET, 9 MARKET REGIME, 10 MICROSTRUCTURE."""
import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from . import datos, mat
from .base import Motor, SinDatos, registrar, resultado
from .. import niveles


def _serie(ctx):
    s = ctx.get("serie")
    if not s:
        raise SinDatos("Serie de precios no disponible (DATA ENGINE no obtuvo datos).")
    return s


# --------------------------------------------------------------------------- 2
@registrar
class MotorDatos(Motor):
    numero, id, nombre = 2, "data", "DATA ENGINE"
    objetivo = "Obtener velas y cotizaciones con proveedor, instrumento, hora, antigüedad y calidad; sincronizar precios entre proveedores."
    metodos = ("Descarga con caché por intervalo; evaluación de frescura (edad de la última vela frente al intervalo), huecos y volumen. "
               "Sincronización (TITAN PRICE SYNCHRONIZATION): compara el último precio de cada proveedor disponible sin ajustarlos, "
               "porque futuros, CFD y spot son instrumentos distintos.")
    entradas = ("activo", "horizonte", "nivel")
    salidas = ("serie", "calidad", "sincronizacion")
    consumo = "bajo (red)"
    niveles = "Más historia por nivel (p. ej. 60m: 1 mes → 1 año)."

    def calcular(self, ctx):
        a, hz = ctx["activo"], niveles.HORIZONTES[ctx["horizonte"]]
        intervalo = hz["intervalo"]
        rango = datos.rango_para(intervalo, ctx["p"]["id"])
        serie = ctx.get("serie_externa")
        if serie is not None:
            intervalo, rango = serie.get("intervalo", intervalo), serie.get("rango", rango)
        else:
            try:
                serie = datos.obtener(a["simbolo"], rango, intervalo)
            except Exception as e:
                raise SinDatos(f"No se pudieron obtener velas de {a['simbolo']} ({type(e).__name__}).")
        if len(serie["c"]) < 60:
            raise SinDatos(f"Solo {len(serie['c'])} velas: insuficiente para analizar.")
        ctx["serie"] = serie
        cal = datos.calidad(serie)
        sync = sincronizar(a["simbolo"], serie, ctx.get("proveedores_extra", ())) if ctx.get("serie_externa") is None else \
            {"proveedores": [{"proveedor": serie["proveedor"], "simbolo": serie["simbolo_proveedor"], "instrumento": serie["tipo"],
                              "precio": serie["c"][-1], "bid": None, "ask": None, "mid": None, "spread": None, "ts": serie["t"][-1], "zona": "UTC",
                              "edad_s": int(time.time() - serie["t"][-1]), "retraso": "precios del propio broker (los mismos de la ejecución)",
                              "calidad": cal["calidad"]}], "bid_ask_disponible": False}
        notas = list(cal["motivos"])
        if ctx.get("serie_externa") is not None:
            notas.append(f"Velas del broker ({serie['proveedor']} {serie['simbolo_proveedor']}): análisis y ejecución usan el mismo precio.")
        if serie["tipo"] == "futuro":
            notas.append("Precio de FUTUROS: puede diferir del spot y de los CFD del broker.")
        return {"salida": {"proveedor": serie["proveedor"], "simbolo_proveedor": serie["simbolo_proveedor"], "tipo": serie["tipo"],
                           "intervalo": intervalo, "rango": rango, "velas": len(serie["c"]), "ultimo": serie["c"][-1],
                           "ultimo_ts": serie["t"][-1], "calidad": cal, "sincronizacion": sync},
                "notas": notas, "estado": "completado"}


def sincronizar(simbolo, serie_yahoo, extra=()):
    """Una fila por proveedor con bid/ask/mid/spread SOLO si el proveedor los da; diferencias sin ajustar."""
    ahora = time.time()
    meta = serie_yahoo["meta"]
    filas = [{"proveedor": "yahoo", "simbolo": serie_yahoo["simbolo_proveedor"], "instrumento": serie_yahoo["tipo"],
              "precio": meta.get("precio") or serie_yahoo["c"][-1], "bid": meta.get("bid"), "ask": meta.get("ask"),
              "mid": None, "spread": None, "ts": serie_yahoo["t"][-1], "zona": meta.get("zona"),
              "edad_s": int(ahora - serie_yahoo["t"][-1]), "retraso": "Yahoo puede retrasar hasta 15 min según la bolsa",
              "calidad": datos.calidad(serie_yahoo)["calidad"]}]
    for prov in extra:
        try:
            s = datos.obtener(simbolo, "1d", "1m", proveedor=prov)
            m = s["meta"]
            bid, ask = m.get("bid"), m.get("ask")
            filas.append({"proveedor": prov, "simbolo": s["simbolo_proveedor"], "instrumento": s["tipo"], "precio": s["c"][-1],
                          "bid": bid, "ask": ask, "mid": (bid + ask) / 2 if bid and ask else None,
                          "spread": (ask - bid) if bid and ask else None, "ts": s["t"][-1], "zona": "UTC",
                          "edad_s": int(ahora - s["t"][-1]), "retraso": None, "calidad": datos.calidad(s)["calidad"]})
        except Exception as e:
            filas.append({"proveedor": prov, "error": type(e).__name__})
    for f in filas:
        if f.get("bid") and f.get("ask"):
            f["mid"], f["spread"] = (f["bid"] + f["ask"]) / 2, f["ask"] - f["bid"]
    base = filas[0]["precio"]
    for f in filas[1:]:
        if f.get("precio") and base:
            f["diferencia_pct"] = round((f["precio"] / base - 1) * 100, 4)
            f["advertencia"] = ("Instrumentos distintos (" + filas[0]["instrumento"] + " vs " + f.get("instrumento", "?") +
                                "): la diferencia es real, no se ajusta.") if f.get("instrumento") != filas[0]["instrumento"] else None
    return {"proveedores": filas, "bid_ask_disponible": any(f.get("bid") for f in filas)}


# --------------------------------------------------------------------------- 3
@registrar
class MotorCaracteristicas(Motor):
    numero, id, nombre = 3, "features", "FEATURE ENGINEERING"
    objetivo = "Transformar velas en variables comparables entre activos y temporalidades, sin información futura."
    metodos = "Retornos simples y logarítmicos, EMA por ventana, RSI de Wilder, MACD, ATR, volatilidad realizada, z-score del precio y volumen relativo."
    entradas = ("serie",)
    salidas = ("caracteristicas", "series_derivadas")
    dependencias = ("data",)
    niveles = "Las ventanas de EMA crecen con el nivel (20/50 → 20/50/100/200)."

    def calcular(self, ctx):
        s = _serie(ctx)
        c, h, l, v = s["c"], s["h"], s["l"], s["v"]
        ventanas = [w for w in ctx["p"]["ventanas"] if w < len(c)]
        emas = {w: mat.ema(c, w) for w in ventanas}
        rsi = mat.rsi_serie(c, 14)
        atr = mat.atr_serie(h, l, c, 14)
        _, _, hist = mat.macd(c)
        r = mat.log_retornos(c)
        vol_real = (mat.desv(r[-50:]) or 0)
        w20 = c[-20:]
        z = (c[-1] - mat.media(w20)) / (mat.desv(w20) or 1)
        vm = mat.media([x for x in v[-50:] if x]) or 0
        vol_rel = (v[-1] / vm) if vm and v[-1] else None
        ctx["feat"] = {"emas": emas, "rsi": rsi, "atr": atr, "macd_hist": hist, "logret": r}
        faltantes = [] if vol_rel is not None else ["volumen del proveedor"]
        return {"salida": {"precio": c[-1], "ema": {str(w): emas[w][-1] for w in ventanas},
                           "dist_ema_pct": {str(w): (c[-1] / emas[w][-1] - 1) * 100 for w in ventanas},
                           "rsi14": rsi[-1], "atr14": atr[-1], "atr_pct": atr[-1] / c[-1] * 100, "macd_hist": hist[-1],
                           "vol_realizada_50": vol_real, "zscore_20": z, "volumen_relativo": vol_rel, "velas": len(c)},
                "faltantes": faltantes}


def _pivotes(h, l, k=3):
    altos, bajos = [], []
    for i in range(k, len(h) - k):
        if h[i] == max(h[i - k:i + k + 1]):
            altos.append(h[i])
        if l[i] == min(l[i - k:i + k + 1]):
            bajos.append(l[i])
    return altos, bajos


def _agrupar(niveles_, tol):
    niveles_ = sorted(niveles_)
    grupos = []
    for x in niveles_:
        if grupos and abs(x - grupos[-1][-1]) <= tol:
            grupos[-1].append(x)
        else:
            grupos.append([x])
    return [(sum(g) / len(g), len(g)) for g in grupos]


# --------------------------------------------------------------------------- 4
@registrar
class MotorTecnico(Motor):
    numero, id, nombre = 4, "technical", "TECHNICAL INTELLIGENCE ENGINE"
    objetivo = "Leer tendencia, estructura, soportes/resistencias e impulso."
    metodos = ("Alineación de EMAs, estructura de máximos/mínimos (pivotes de 3 velas), soportes y resistencias por "
               "agrupación de pivotes con tolerancia de 0,5·ATR, RSI, MACD, Bollinger y ADX.")
    entradas = ("serie", "caracteristicas")
    salidas = ("tendencia", "puntuacion", "soportes", "resistencias", "estructura")
    dependencias = ("features",)

    def calcular(self, ctx):
        s, f = _serie(ctx), ctx.get("feat")
        if not f:
            raise SinDatos("Faltan características.")
        c, h, l = s["c"], s["h"], s["l"]
        precio, atr = c[-1], f["atr"][-1]
        ws = sorted(f["emas"])
        puntos, razones = 0, []
        for a, b in zip(ws, ws[1:]):
            if f["emas"][a][-1] > f["emas"][b][-1]:
                puntos += 1
                razones.append(f"EMA{a} > EMA{b}")
            else:
                puntos -= 1
                razones.append(f"EMA{a} < EMA{b}")
        rsi = f["rsi"][-1]
        if rsi is not None:
            if rsi > 55:
                puntos += 1
                razones.append(f"RSI {rsi:.0f} con impulso alcista")
            elif rsi < 45:
                puntos -= 1
                razones.append(f"RSI {rsi:.0f} con impulso bajista")
        mh = f["macd_hist"]
        if mh[-1] > 0 and mh[-1] > mh[-2]:
            puntos += 1
            razones.append("MACD creciente por encima de cero")
        elif mh[-1] < 0 and mh[-1] < mh[-2]:
            puntos -= 1
            razones.append("MACD decreciente por debajo de cero")
        altos, bajos = _pivotes(h[-300:], l[-300:])
        estructura = "indefinida"
        if len(altos) >= 2 and len(bajos) >= 2:
            if altos[-1] > altos[-2] and bajos[-1] > bajos[-2]:
                estructura, puntos = "máximos y mínimos crecientes", puntos + 1
            elif altos[-1] < altos[-2] and bajos[-1] < bajos[-2]:
                estructura, puntos = "máximos y mínimos decrecientes", puntos - 1
            else:
                estructura = "mixta (posible rango)"
        tol = 0.5 * atr
        niveles_ = _agrupar(altos + bajos, tol)
        res = sorted([(n, k) for n, k in niveles_ if n > precio], key=lambda x: x[0])[:3]
        sop = sorted([(n, k) for n, k in niveles_ if n < precio], key=lambda x: -x[0])[:3]
        bb = mat.bollinger(c)
        dx = mat.adx(h, l, c)
        tendencia = "alcista" if puntos >= 2 else "bajista" if puntos <= -2 else "lateral"
        return {"salida": {"tendencia": tendencia, "puntuacion": puntos, "puntuacion_max": len(ws) + 2, "razones": razones,
                           "estructura": estructura, "rsi14": rsi, "atr": atr,
                           "resistencias": [{"precio": n, "toques": k} for n, k in res],
                           "soportes": [{"precio": n, "toques": k} for n, k in sop],
                           "bollinger": bb, "adx": dx}}


# --------------------------------------------------------------------------- 5
REFERENCIAS = {
    "metal": ["DX-Y.NYB", "^TNX", "^GSPC", "CL=F", "SI=F", "BTC-USD", "EURUSD=X", "^VIX", "HG=F", "JPY=X", "^IXIC", "ETH-USD"],
    "energia": ["DX-Y.NYB", "^GSPC", "GC=F", "^TNX", "NG=F", "^VIX", "EURUSD=X", "HG=F", "BTC-USD", "^IXIC", "SI=F", "JPY=X"],
    "indice": ["^VIX", "^TNX", "DX-Y.NYB", "GC=F", "CL=F", "BTC-USD", "^IXIC", "EURUSD=X", "HG=F", "JPY=X", "SI=F", "ETH-USD"],
    "accion": ["^GSPC", "^IXIC", "^VIX", "^TNX", "DX-Y.NYB", "GC=F", "CL=F", "BTC-USD", "EURUSD=X", "HG=F", "JPY=X", "ETH-USD"],
    "cripto": ["^IXIC", "^GSPC", "DX-Y.NYB", "GC=F", "ETH-USD", "BTC-USD", "^VIX", "^TNX", "EURUSD=X", "CL=F", "JPY=X", "SI=F"],
    "divisa": ["DX-Y.NYB", "^TNX", "GC=F", "^GSPC", "EURUSD=X", "JPY=X", "GBPUSD=X", "CL=F", "^VIX", "BTC-USD", "HG=F", "SI=F"],
}


def _por_dia(serie):
    out = {}
    for t, c in zip(serie["t"], serie["c"]):
        out[datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")] = c
    return out


@registrar
class MotorCruzado(Motor):
    numero, id, nombre = 5, "cross_asset", "CROSS-ASSET INTELLIGENCE ENGINE"
    objetivo = "Medir cómo se mueve el activo frente al dólar, tipos, renta variable, volatilidad y materias primas."
    metodos = "Correlación de Pearson de retornos diarios alineados por fecha (últimos 120 días) y beta frente a cada referencia; tendencia de 20 días de cada referencia."
    entradas = ("activo",)
    salidas = ("correlaciones", "sesgo_cruzado")
    consumo = "medio (red)"
    niveles = "Número de activos de referencia: 3 / 5 / 8 / 12."

    def calcular(self, ctx):
        a = ctx["activo"]
        refs = [r for r in REFERENCIAS.get(a.get("clase"), REFERENCIAS["accion"]) if r != a["simbolo"]][:ctx["p"]["correlacion_activos"]]
        rango = "1y" if ctx["p"]["id"] in ("basico", "intermedio") else "2y"

        def bajar(sim):
            try:
                return datos.obtener(sim, rango, "1d")
            except Exception:
                return None
        with ThreadPoolExecutor(max_workers=max(1, ctx["p"]["concurrencia"])) as ex:
            series = list(ex.map(bajar, [a["simbolo"]] + refs))
        base = series[0]
        if not base:
            raise SinDatos("Sin serie diaria del activo para correlaciones.")
        bd = _por_dia(base)
        filas, faltan, sesgo, peso = [], [], 0.0, 0.0
        for sim, s in zip(refs, series[1:]):
            if not s:
                faltan.append(sim)
                continue
            rd = _por_dia(s)
            dias = sorted(set(bd) & set(rd))[-121:]
            if len(dias) < 40:
                faltan.append(sim)
                continue
            ra = mat.retornos([bd[d] for d in dias])
            rb = mat.retornos([rd[d] for d in dias])
            rho = mat.correlacion(ra, rb)
            vb = mat.desv(rb)
            beta = rho * (mat.desv(ra) / vb) if rho is not None and vb else None
            tend = (rd[dias[-1]] / rd[dias[-21]] - 1) * 100 if len(dias) > 21 else None
            filas.append({"referencia": sim, "correlacion": rho, "beta": beta, "tendencia_20d_pct": tend, "dias": len(dias)})
            if rho is not None and tend is not None and abs(rho) >= 0.3:
                sesgo += rho * (1 if tend > 0 else -1) * abs(rho)
                peso += abs(rho)
        if not filas:
            raise SinDatos("No se pudo alinear ninguna referencia.")
        s = sesgo / peso if peso else 0.0
        return {"salida": {"correlaciones": sorted(filas, key=lambda x: -abs(x["correlacion"] or 0)),
                           "sesgo_cruzado": s, "lectura": "favorable" if s > 0.2 else "desfavorable" if s < -0.2 else "neutral"},
                "faltantes": [f"referencia {x}" for x in faltan],
                "estado": "completado" if not faltan else "simplificado"}


# --------------------------------------------------------------------------- 9
@registrar
class MotorRegimen(Motor):
    numero, id, nombre = 9, "regime", "MARKET REGIME ENGINE"
    objetivo = "Clasificar el estado del mercado: tendencia, rango o alta volatilidad, para adaptar las reglas."
    metodos = ("Ratio de eficiencia de Kaufman (20), ADX de Wilder y percentil de la volatilidad realizada actual frente "
               "a su historia; reglas explícitas y auditables en lugar de un clasificador opaco.")
    entradas = ("serie", "caracteristicas")
    salidas = ("regimen", "percentil_volatilidad")
    dependencias = ("features",)

    def calcular(self, ctx):
        s, f = _serie(ctx), ctx.get("feat")
        c = s["c"]
        r = f["logret"]
        if len(r) < 120:
            raise SinDatos("Historia insuficiente para medir régimen.")
        vols = [mat.desv(r[i - 20:i]) for i in range(20, len(r) + 1)]
        actual = vols[-1]
        pct = sum(1 for v in vols if v <= actual) / len(vols)
        er = mat.eficiencia(c, 20)
        dx = mat.adx(s["h"], s["l"], c) or {}
        adxv = dx.get("adx")
        if pct >= 0.9:
            reg = "alta_volatilidad"
        elif (er or 0) >= 0.35 and (adxv or 0) >= 22:
            reg = "tendencia_alcista" if dx.get("di_mas", 0) >= dx.get("di_menos", 0) else "tendencia_bajista"
        elif (er or 0) <= 0.2:
            reg = "rango"
        else:
            reg = "transicion"
        return {"salida": {"regimen": reg, "eficiencia": er, "adx": adxv, "percentil_volatilidad": pct, "vol_actual": actual}}


# --------------------------------------------------------------------------- 10
@registrar
class MotorMicroestructura(Motor):
    numero, id, nombre = 10, "microstructure", "MARKET MICROSTRUCTURE ENGINE"
    objetivo = "Estimar costes de transacción y liquidez: spread, profundidad y comportamiento por hora."
    metodos = ("Spread REAL solo si el proveedor da bid/ask. Si no, estimadores académicos a partir de velas: "
               "Corwin-Schultz (máximos/mínimos de 2 velas) y Roll (autocovarianza). Volumen medio por hora UTC.")
    entradas = ("serie", "sincronizacion")
    salidas = ("spread", "spread_estimado_pct", "liquidez_horaria")
    dependencias = ("data",)
    niveles = "Igual en todos: depende de los datos, no del cálculo."

    def calcular(self, ctx):
        s = _serie(ctx)
        h, l, c = s["h"], s["l"], s["c"]
        sync = (resultado(ctx, "data") or {}).get("sincronizacion", {})
        real = [f for f in sync.get("proveedores", []) if f.get("spread")]
        k = 3 - 2 * math.sqrt(2)
        cs = []
        for i in range(max(1, len(c) - 200), len(c)):
            if min(l[i], l[i - 1]) <= 0:
                continue
            beta = math.log(h[i - 1] / l[i - 1]) ** 2 + math.log(h[i] / l[i]) ** 2
            gamma = math.log(max(h[i], h[i - 1]) / min(l[i], l[i - 1])) ** 2
            alfa = (math.sqrt(2 * beta) - math.sqrt(beta)) / k - math.sqrt(gamma / k)
            sp = 2 * (math.exp(alfa) - 1) / (1 + math.exp(alfa))
            cs.append(max(sp, 0.0))
        dc = [c[i] - c[i - 1] for i in range(1, len(c))][-200:]
        cov = None
        if len(dc) > 20:
            a, b = dc[:-1], dc[1:]
            ma, mb = mat.media(a), mat.media(b)
            cov = sum((x - ma) * (y - mb) for x, y in zip(a, b)) / len(a)
        roll = (2 * math.sqrt(-cov) / c[-1] * 100) if cov is not None and cov < 0 else None
        horas = {}
        for t, v in zip(s["t"], s["v"]):
            if v:
                horas.setdefault(datetime.fromtimestamp(t, timezone.utc).hour, []).append(v)
        liq = {str(hh): mat.media(vs) for hh, vs in sorted(horas.items())}
        faltan = [] if real else ["bid/ask del proveedor (Yahoo no los publica): el spread es una ESTIMACIÓN"]
        return {"salida": {"spread_real": [{"proveedor": f["proveedor"], "spread": f["spread"]} for f in real],
                           "spread_estimado_pct": {"corwin_schultz": (mat.media(cs) or 0) * 100 if cs else None, "roll": roll},
                           "liquidez_horaria_utc": liq},
                "faltantes": faltan, "estado": "completado" if real else "simplificado"}
