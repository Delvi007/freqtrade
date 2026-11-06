# -*- coding: utf-8 -*-
"""Cotizaciones en vivo (solo lectura) para la lista de seguimiento de TITAN QUANT.
Fuente: Yahoo Finance (gráfico de 1 minuto). No escribe en bases de datos ni opera."""
import json, time, urllib.parse
from concurrent.futures import ThreadPoolExecutor

import agente

CACHE_S = 3
# Para mostrar XAU/USD (oro spot) se intenta primero XAUUSD=X y, si falla, se usa GC=F (futuros).
ALTERNATIVAS = {"GC=F": ["XAUUSD=X", "GC=F"]}
ETIQUETA = {"GC=F": "XAU/USD"}


def etiqueta(sim, fuente=None):
    """Nombre a mostrar según la fuente REAL: si el oro sale de GC=F son futuros, no XAU/USD spot."""
    if sim == "GC=F" and fuente and fuente != "XAUUSD=X":
        return "Oro futuros (GC=F)"
    return ETIQUETA.get(sim, sim)
_CACHE = {}


def _pedir(sim_fuente):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(sim_fuente, safe="=^-.")
           + "?range=1d&interval=1m")
    r = json.loads(agente.descargar(url, 10).decode("utf-8", "replace"))["chart"]["result"][0]
    meta, q = r["meta"], r["indicators"]["quote"][0]
    velas = [(o, c) for o, c in zip(q.get("open") or [], q.get("close") or []) if o is not None and c is not None]
    if not velas:
        raise ValueError("sin velas")
    o, c = velas[-1]
    precio = meta.get("regularMarketPrice") or c
    previo = meta.get("chartPreviousClose") or meta.get("previousClose")
    cambio = (precio / previo - 1) * 100 if previo else None
    return {"precio": precio, "previo": previo, "cambio_pct": cambio,
            "vela": "alcista" if c >= o else "bajista", "hora": meta.get("regularMarketTime")}


def cotizar(activo):
    sim = activo["simbolo"]
    ahora = time.time()
    hit = _CACHE.get(sim)
    if hit and ahora - hit[0] < CACHE_S:
        return hit[1]
    fuentes = ALTERNATIVAS.get(sim, [sim])
    ultimo_error = "sin datos"
    out = None
    for f in fuentes:
        try:
            out = _pedir(f)
            out["fuente"] = f
            break
        except Exception as e:
            ultimo_error = type(e).__name__
    base = {"simbolo": sim, "nombre": activo["nombre"], "mostrar": ETIQUETA.get(sim, sim)}
    if out is None:
        base["error"] = ultimo_error
    else:
        base.update(out)
        base["mostrar"] = etiqueta(sim, out.get("fuente"))
    _CACHE[sim] = (ahora, base)
    return base


def cotizar_varios(activos_lista):
    with ThreadPoolExecutor(max_workers=6) as ex:
        return list(ex.map(cotizar, activos_lista))
