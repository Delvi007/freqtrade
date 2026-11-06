# -*- coding: utf-8 -*-
"""Velas con volumen e historial largo, y mapa de direcciones por temporalidad.
Solo lectura. Fuente: Yahoo Finance. No escribe en bases de datos ni opera."""
import json, time, urllib.parse
from concurrent.futures import ThreadPoolExecutor

import agente
from quotes_web import ALTERNATIVAS, ETIQUETA, etiqueta

# tf -> (rango completo, intervalo Yahoo, horas por bloque si se agrupa, rango "reciente" para actualizar en vivo)
TF = {"1m": ("7d", "1m", 0, "1d"), "5m": ("60d", "5m", 0, "1d"), "15m": ("60d", "15m", 0, "5d"),
      "30m": ("60d", "30m", 0, "5d"), "1h": ("730d", "60m", 0, "5d"), "4h": ("730d", "60m", 4, "1mo"),
      "1d": ("max", "1d", 0, "1mo"), "1w": ("max", "1wk", 0, "6mo"), "1mo": ("max", "1mo", 0, "2y")}
MAX_HIST, MAX_RECIENTE = 6000, 40
CACHE_COMPLETO_S, CACHE_RECIENTE_S = 20, 1
_CACHE = {}

MTF_TFS = ["1m", "5m", "15m", "1h", "4h", "1d"]
MTF_RANGO = {"1m": "1d", "5m": "1d", "15m": "5d", "1h": "1mo", "4h": "3mo", "1d": "1y"}
MTF_PESO = {"1m": 0.5, "5m": 0.75, "15m": 1.0, "1h": 1.5, "4h": 2.0, "1d": 2.5}


def _r(x):
    return None if x is None else round(float(x), 6)


def _agrupar(velas, horas):
    if not horas:
        return velas
    salto, out = horas * 3600, []
    for v in velas:
        k = v[0] // salto
        if out and out[-1][6] == k:
            u = out[-1]
            u[2] = max(u[2], v[2]); u[3] = min(u[3], v[3]); u[4] = v[4]; u[5] += v[5]
        else:
            out.append([k * salto, v[1], v[2], v[3], v[4], v[5], k])
    return [u[:6] for u in out]


def _pedir(sim, rango, intervalo):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(sim, safe="=^-.")
           + f"?range={rango}&interval={intervalo}")
    r = json.loads(agente.descargar(url, 20).decode("utf-8", "replace"))["chart"]["result"][0]
    q, meta = r["indicators"]["quote"][0], r["meta"]
    vol = q.get("volume") or [0] * len(r["timestamp"])
    velas = [[t, o, h, l, c, (v or 0)] for t, o, h, l, c, v in
             zip(r["timestamp"], q["open"], q["high"], q["low"], q["close"], vol) if None not in (o, h, l, c)]
    if not velas:
        raise ValueError("sin velas")
    return velas, meta


def _con_fuentes(sim, funcion):
    error = "sin datos"
    for f in ALTERNATIVAS.get(sim, [sim]):
        try:
            return f, funcion(f)
        except Exception as e:
            error = type(e).__name__
    raise RuntimeError("No se pudieron obtener velas (" + error + ")")


def grafico(activo, tf, reciente=False):
    if tf not in TF:
        raise ValueError("Temporalidad no válida: " + str(tf)[:10])
    sim = activo["simbolo"]
    clave = (sim, tf, bool(reciente))
    ahora = time.time()
    hit = _CACHE.get(clave)
    if hit and ahora - hit[0] < (CACHE_RECIENTE_S if reciente else CACHE_COMPLETO_S):
        return hit[1]
    rango_c, intervalo, horas, rango_r = TF[tf]
    rango = rango_r if reciente else rango_c

    def traer(f):
        return _pedir(f, rango, intervalo)
    fuente, (velas, meta) = _con_fuentes(sim, traer)
    velas = _agrupar(velas, horas)
    vol_fuente = None
    if not any(v[5] for v in velas) and fuente != sim:      # p. ej. oro spot sin volumen: usa el de futuros
        try:
            v2, _m = _pedir(sim, rango, intervalo)
            v2 = _agrupar(v2, horas)
            mapa = {x[0]: x[5] for x in v2}
            for v in velas:
                v[5] = mapa.get(v[0], 0)
            if any(v[5] for v in velas):
                vol_fuente = sim
        except Exception:
            pass
    velas = velas[-(MAX_RECIENTE if reciente else MAX_HIST):]
    precio = meta.get("regularMarketPrice") or velas[-1][4]
    previo = meta.get("chartPreviousClose") or meta.get("previousClose")
    nf = meta.get("shortName") or meta.get("longName")
    out = {"simbolo": sim, "nombre": nf if activo.get("categoria") == "Personalizado" and nf else activo["nombre"],
           "mostrar": etiqueta(sim, fuente), "tf": tf, "fuente": fuente, "reciente": bool(reciente),
           "velas": [[v[0], _r(v[1]), _r(v[2]), _r(v[3]), _r(v[4]), int(v[5])] for v in velas],
           "precio": precio, "previo": previo,
           "cambio_pct": (precio / previo - 1) * 100 if previo else None,
           "vela": "alcista" if velas[-1][4] >= velas[-1][1] else "bajista",
           "con_volumen": any(v[5] for v in velas), "vol_fuente": vol_fuente}
    _CACHE[clave] = (ahora, out)
    return out


# ---------------- Mapa de direcciones por temporalidad ----------------
def _etiqueta(s):
    return "alcista" if s >= 2 else "bajista" if s <= -2 else "lateral"


def _fuerza(s):
    a = abs(s)
    return "fuerte" if a >= 4 else "buena" if a == 3 else "moderada" if a == 2 else "débil"


def _lectura(sim, tf):
    def traer(f):
        return _pedir(f, MTF_RANGO[tf], TF[tf][1])
    _f, (velas, _meta) = _con_fuentes(sim, traer)
    velas = _agrupar(velas, TF[tf][2])
    c = [v[4] for v in velas]
    if len(c) < 35:
        return {"tf": tf, "disponible": False}
    e20, e50 = agente.ema(c, 20)[-1], agente.ema(c, 50)[-1]
    rs, mh = agente.rsi(c, 14), agente.macd_hist(c)
    s = (1 if e20 > e50 else -1) + (1 if c[-1] > e50 else -1) + (1 if mh > 0 else -1) + (1 if rs >= 55 else -1 if rs <= 45 else 0)
    return {"tf": tf, "disponible": True, "score": s, "direccion": _etiqueta(s), "fuerza": _fuerza(s),
            "rsi": round(rs, 1), "precio": c[-1]}


def mapa_temporalidades(activo):
    sim = activo["simbolo"]

    def uno(tf):
        try:
            return _lectura(sim, tf)
        except Exception as e:
            return {"tf": tf, "disponible": False, "error": type(e).__name__}
    with ThreadPoolExecutor(max_workers=6) as ex:
        tfs = list(ex.map(uno, MTF_TFS))
    ok = [t for t in tfs if t["disponible"]]
    if not ok:
        raise RuntimeError("No se pudieron calcular las temporalidades (sin datos).")
    peso = sum(MTF_PESO[t["tf"]] for t in ok)
    gs = sum(MTF_PESO[t["tf"]] * t["score"] for t in ok) / peso
    gdir = "alcista" if gs >= 1.0 else "bajista" if gs <= -1.0 else "lateral"
    alineadas = sum(1 for t in ok if t["direccion"] == gdir) if gdir != "lateral" else sum(1 for t in ok if t["direccion"] == "lateral")
    fuerte = max(ok, key=lambda t: (abs(t["score"]), MTF_PESO[t["tf"]]))
    return {"simbolo": sim, "mostrar": ETIQUETA.get(sim, sim), "tfs": tfs,
            "general": {"direccion": gdir, "score": round(gs, 2), "fuerza": _fuerza(round(gs)), "alineadas": alineadas, "total": len(ok)},
            "mas_fuerte": {"tf": fuerte["tf"], "direccion": fuerte["direccion"], "score": fuerte["score"], "fuerza": fuerte["fuerza"]},
            "pesos": MTF_PESO}
