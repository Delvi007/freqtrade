"""Acceso a datos de mercado con origen identificado (lo usan DATA ENGINE y PRICE SYNCHRONIZATION).

Todas las descargas pasan por `obtener()`; las pruebas sustituyen `PROVEEDOR_YAHOO` por datos sintéticos.
Cada serie lleva su proveedor, símbolo del proveedor, tipo de instrumento y hora: los motores y el bot
saben siempre de dónde vienen los precios.
"""
import threading
import time

_CACHE = {}
_L = threading.Lock()
CACHE_S = {"1m": 30, "5m": 60, "15m": 120, "60m": 300, "1d": 1800, "1wk": 3600}
SEG = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "60m": 3600, "1h": 3600, "1d": 86400, "1wk": 604800}

RANGOS = {  # intervalo -> rango por nivel (límites reales de Yahoo: 5m/15m ≤ 60 días, 60m ≤ 730 días)
    "5m": {"basico": "5d", "intermedio": "1mo", "avanzado": "60d", "super": "60d"},
    "15m": {"basico": "1mo", "intermedio": "60d", "avanzado": "60d", "super": "60d"},
    "60m": {"basico": "1mo", "intermedio": "3mo", "avanzado": "6mo", "super": "1y"},
    "1d": {"basico": "1y", "intermedio": "2y", "avanzado": "5y", "super": "10y"},
    "1wk": {"basico": "5y", "intermedio": "10y", "avanzado": "max", "super": "max"},
}


def _yahoo(simbolo, rango, intervalo):
    import chart_web  # módulo heredado: ya maneja el formato de Yahoo
    velas, meta = chart_web._pedir(simbolo, rango, intervalo)
    return velas, {"precio": meta.get("regularMarketPrice"), "previo": meta.get("chartPreviousClose") or meta.get("previousClose"),
                   "moneda": meta.get("currency"), "bolsa": meta.get("exchangeName"), "zona": meta.get("exchangeTimezoneName"),
                   "bid": None, "ask": None}


PROVEEDOR_YAHOO = _yahoo


def tipo_instrumento(simbolo, proveedor="yahoo"):
    s = simbolo.upper()
    if proveedor == "iqoption":
        return "cfd"
    if s.endswith("=F"):
        return "futuro"
    if s.endswith("=X"):
        return "divisa_spot"
    if s.endswith("-USD"):
        return "cripto_spot"
    if s.startswith("^") or s.endswith(".NYB"):
        return "indice"
    return "accion_o_etf"


def rango_para(intervalo, nivel):
    return RANGOS.get(intervalo, RANGOS["60m"]).get(nivel, "3mo")


def obtener(simbolo, rango, intervalo, proveedor="yahoo"):
    """Devuelve dict Serie: {simbolo, proveedor, simbolo_proveedor, tipo, intervalo, t,o,h,l,c,v, meta, obtenido_ts}."""
    k = (proveedor, simbolo, rango, intervalo)
    ahora = time.time()
    with _L:
        hit = _CACHE.get(k)
        if hit and ahora - hit["obtenido_ts"] < CACHE_S.get(intervalo, 300):
            return hit
    if proveedor == "yahoo":
        velas, meta = PROVEEDOR_YAHOO(simbolo, rango, intervalo)
        sim_prov = simbolo
    elif proveedor == "iqoption":
        import iqoption_data
        velas, m = iqoption_data.history(simbolo, rango, intervalo)
        meta = {"precio": m.get("regularMarketPrice"), "previo": m.get("chartPreviousClose"), "bid": m.get("bid"), "ask": m.get("ask")}
        sim_prov = m.get("symbol")
    else:
        raise ValueError("Proveedor desconocido: " + proveedor)
    velas = [v for v in velas if None not in v[:5]]
    if not velas:
        raise ValueError("sin velas")
    serie = {"simbolo": simbolo, "proveedor": proveedor, "simbolo_proveedor": sim_prov,
             "tipo": tipo_instrumento(simbolo, proveedor), "intervalo": intervalo, "rango": rango,
             "t": [int(v[0]) for v in velas], "o": [float(v[1]) for v in velas], "h": [float(v[2]) for v in velas],
             "l": [float(v[3]) for v in velas], "c": [float(v[4]) for v in velas], "v": [float(v[5] or 0) for v in velas],
             "meta": meta, "obtenido_ts": ahora}
    with _L:
        _CACHE[k] = serie
        if len(_CACHE) > 300:
            for kk in sorted(_CACHE, key=lambda x: _CACHE[x]["obtenido_ts"])[:100]:
                _CACHE.pop(kk, None)
    return serie


def calidad(serie, ahora=None):
    """Frescura, huecos y volumen. No corrige nada: solo describe."""
    ahora = ahora or time.time()
    t = serie["t"]
    paso = SEG.get(serie["intervalo"], 3600)
    edad = ahora - (t[-1] + paso)          # la última vela cierra en t+paso
    huecos = sum(1 for a, b in zip(t, t[1:]) if b - a > 3 * paso and (b - a) < 2 * 86400)  # ignora fines de semana
    sin_vol = sum(1 for x in serie["v"] if not x) / len(serie["v"])
    motivos = []
    puntos = 3
    if edad > max(4 * paso, 1800):
        puntos -= 1
        motivos.append(f"última vela con {int(edad // 60)} min de antigüedad (mercado cerrado o retraso)")
    if huecos > len(t) * 0.02:
        puntos -= 1
        motivos.append(f"{huecos} huecos en la serie")
    if sin_vol > 0.5:
        motivos.append("sin volumen fiable (habitual en divisas spot)")
    if len(t) < 100:
        puntos -= 1
        motivos.append(f"solo {len(t)} velas")
    nivel = "alta" if puntos == 3 else "media" if puntos == 2 else "baja"
    return {"calidad": nivel, "edad_s": int(edad), "obsoleto": edad > max(6 * paso, 3600) and serie["intervalo"] in ("1m", "5m", "15m", "60m"),
            "huecos": huecos, "fraccion_sin_volumen": round(sin_vol, 3), "velas": len(t), "motivos": motivos,
            "proveedor": serie["proveedor"], "tipo": serie["tipo"]}


def alinear(series):
    """Alinea varias series por marca de tiempo común (para correlaciones). Devuelve (ts, {simbolo: cierres})."""
    comunes = None
    for s in series:
        ts = set(s["t"])
        comunes = ts if comunes is None else comunes & ts
    comunes = sorted(comunes or [])
    out = {}
    for s in series:
        m = dict(zip(s["t"], s["c"]))
        out[s["simbolo"]] = [m[t] for t in comunes]
    return comunes, out


def limpiar_cache():
    with _L:
        _CACHE.clear()
