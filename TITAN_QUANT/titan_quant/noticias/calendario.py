"""Calendario económico.

Fuente: calendario semanal público de Fair Economy (formato ForexFactory) — SECUNDARIA: trae hora, país/moneda,
impacto, previsión y dato anterior, pero NO el dato publicado. El dato publicado se deja vacío (no se inventa); cuando
la fuente oficial (BLS, BEA, Eurostat, bancos centrales) lo publica, la noticia correspondiente aparece en el panel.
"""
import hashlib
import time

from . import almacen, recolector

TIPOS = [("tipos_interes", ("rate decision", "interest rate", "cash rate", "bank rate", "policy rate", "monetary policy", "fomc", "main refinancing")),
         ("inflacion", ("cpi", "pce", "inflation", "ppi", "price index", "hicp")),
         ("empleo", ("non-farm", "nonfarm", "employment change", "unemployment", "jobless", "payroll", "claimant", "adp", "jolts", "average hourly")),
         ("pib", ("gdp",)), ("pmi", ("pmi", "ism")), ("ventas_minoristas", ("retail sales",)),
         ("discurso", ("speaks", "speech", "testifies", "press conference", "minutes", "statement")),
         ("bonos", ("bond auction", "note auction", "bill auction", "auction")), ]
MONEDA_PAIS = {"USD": "Estados Unidos", "EUR": "Zona euro", "GBP": "Reino Unido", "JPY": "Japón", "CHF": "Suiza", "CAD": "Canadá", "AUD": "Australia",
               "NZD": "Nueva Zelanda", "CNY": "China", "ALL": "Global"}
IMPACTO = {"High": "alto", "Medium": "medio", "Low": "bajo", "Holiday": "festivo", "Non-Economic": "no económico"}


def tipo(titulo):
    t = str(titulo or "").lower()
    for k, pal in TIPOS:
        if any(p in t for p in pal):
            return k
    return "otro"


def ingerir(fuente, datos, ahora=None):
    ahora = int(ahora or time.time())
    n = 0
    with almacen.tx() as c:
        for e in datos if isinstance(datos, list) else []:
            ts = recolector.fecha(e.get("date"))
            tit = str(e.get("title") or "").strip()[:200]
            if not ts or not tit:
                continue
            mon = str(e.get("country") or "").upper()[:4]
            eid = hashlib.sha1(f"{mon}|{tit}|{ts}".encode()).hexdigest()[:16]
            c.execute("""INSERT INTO calendario(id,titulo,pais,moneda,ts,impacto,prevision,anterior,publicado,tipo,fuente_id,actualizado_ts)
                         VALUES(?,?,?,?,?,?,?,?,NULL,?,?,?)
                         ON CONFLICT(id) DO UPDATE SET impacto=excluded.impacto, prevision=excluded.prevision, anterior=excluded.anterior,
                         actualizado_ts=excluded.actualizado_ts""",
                      (eid, tit, MONEDA_PAIS.get(mon, mon), mon, ts, IMPACTO.get(e.get("impact"), str(e.get("impact") or "")).lower(),
                       str(e.get("forecast") or "") or None, str(e.get("previous") or "") or None, tipo(tit), fuente["id"], ahora))
            n += 1
    return n


def eventos(desde=None, hasta=None, impacto=None, monedas=None):
    ahora = int(time.time())
    desde = int(desde if desde is not None else ahora - 86400)
    hasta = int(hasta if hasta is not None else ahora + 7 * 86400)
    sql, args = "SELECT * FROM calendario WHERE ts BETWEEN ? AND ?", [desde, hasta]
    if impacto:
        sql += " AND impacto IN (%s)" % ",".join("?" * len(impacto))
        args += list(impacto)
    if monedas:
        sql += " AND moneda IN (%s)" % ",".join("?" * len(monedas))
        args += list(monedas)
    return almacen.q(sql + " ORDER BY ts", args)


ALERTAS_DEF = {"activo": True, "impactos": ["alto"], "minutos_antes": 30, "monedas": []}


def config_alertas():
    return {**ALERTAS_DEF, **(almacen.ajuste("alertas_calendario", {}) or {})}


def guardar_alertas(cfg):
    imp = [x for x in (cfg.get("impactos") or []) if x in ("alto", "medio", "bajo")]
    mon = [str(x).upper()[:4] for x in (cfg.get("monedas") or []) if str(x).strip()]
    nuevo = {"activo": bool(cfg.get("activo", True)), "impactos": imp or ["alto"],
             "minutos_antes": max(1, min(1440, int(cfg.get("minutos_antes", 30)))), "monedas": mon}
    almacen.guardar_ajuste("alertas_calendario", nuevo)
    return nuevo


def alertas_proximas(ahora=None):
    """Eventos que entran en la ventana de aviso configurada (desde X minutos antes hasta 15 minutos después)."""
    cfg = config_alertas()
    if not cfg["activo"]:
        return []
    ahora = int(ahora or time.time())
    return eventos(ahora - 15 * 60, ahora + cfg["minutos_antes"] * 60, cfg["impactos"], cfg["monedas"] or None)


def alto_impacto_cerca(monedas, antes_min=60, despues_min=30, ahora=None):
    """Eventos de ALTO impacto de esas monedas en la ventana [−despues, +antes] minutos (para el motor de riesgo/macro)."""
    ahora = int(ahora or time.time())
    return eventos(ahora - despues_min * 60, ahora + antes_min * 60, ["alto"], monedas or None)
