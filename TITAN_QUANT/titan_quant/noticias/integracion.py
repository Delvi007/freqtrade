"""Entrega de noticias a los motores de TITAN.

Cada motor recibe SOLO lo relevante para su responsabilidad, solo noticias VERIFICADAS (fuente primaria, confirmada por
≥ 2 fuentes o fuente ★5+ sin rasgos de rumor) y queda registrado qué noticias usó cada análisis (tabla uso_motor).
Una noticia nunca decide por sí sola: los motores la usan como contexto con peso limitado.
"""
import json
import time

from . import almacen, calendario

# responsabilidad de cada motor → categorías que le interesan (None = todas las del activo)
RESPONSABILIDAD = {
    "macro": ("tipos_interes", "inflacion", "empleo", "crecimiento", "actividad", "bonos", "comercio", "geopolitica"),
    "news": None,
    "risk": ("tipos_interes", "geopolitica", "regulacion", "cripto", "inflacion", "empleo"),
    "forex": ("tipos_interes", "inflacion", "empleo", "crecimiento", "actividad", "bonos", "comercio", "geopolitica"),
    "cripto": ("cripto", "regulacion", "tipos_interes"),
    "acciones": ("resultados", "regulacion", "tecnologia", "tipos_interes", "actividad", "crecimiento"),
    "aprendizaje": None,
}

# símbolo del activo → claves de entidades con las que se buscan noticias
ALIAS = {"XAUUSD": ["XAU (oro)", "USD"], "XAGUSD": ["XAG (plata)", "USD"], "GOLD": ["XAU (oro)"], "BTCUSD": ["BTC"], "ETHUSD": ["ETH"],
         "AUSTRALIA 200": ["ASX 200 (AUSTRALIA 200)", "AUD"], "GERMANY 40": ["DAX (GERMANY 40)", "EUR"], "US 500": ["S&P 500", "USD"],
         "US TECH 100": ["Nasdaq 100", "USD"], "WTI": ["Petróleo"], "BRENT": ["Petróleo"], "XBRUSD": ["Petróleo"], "XTIUSD": ["Petróleo"],
         "NATGAS": ["Gas natural"], "XNGUSD": ["Gas natural"]}
MONEDAS = ("USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD")


def claves_activo(simbolo):
    s = str(simbolo or "").upper().replace("-OTC", "").replace("-OP", "").replace("/", "").strip()
    if s in ALIAS:
        return ALIAS[s]
    if len(s) == 6 and s[:3] in MONEDAS and s[3:] in MONEDAS:
        return [s[:3], s[3:]]
    if s.endswith("USD") and len(s) <= 10:
        return [s[:-3], "USD"]
    return [s]


def para_motor(motor, simbolo=None, horas=48, limite=15, registrar=True, ahora=None):
    ahora = int(ahora or time.time())
    cats = RESPONSABILIDAD.get(motor, None)
    sql, args = "SELECT n.*, f.nombre fuente, f.estrellas FROM noticias n JOIN fuentes f ON f.id=n.fuente_id WHERE n.verificada=1 AND n.publicada_ts>=?", [ahora - horas * 3600]
    if cats:
        sql += " AND n.categoria IN (%s)" % ",".join("?" * len(cats))
        args += list(cats)
    filas = almacen.q(sql + " ORDER BY n.publicada_ts DESC LIMIT 600", args)
    claves = claves_activo(simbolo) if simbolo else []
    if claves:
        filas = [r for r in filas if set(json.loads(r["activos"] or "[]")) & set(claves)]
    filas.sort(key=lambda r: (json.loads(r["puntuaciones"])["impacto_potencial"], r["publicada_ts"]), reverse=True)
    filas = filas[:limite]
    out = [{"id": r["id"], "titulo": r["titulo"], "fuente": r["fuente"], "estrellas": r["estrellas"], "fecha": r["publicada_ts"],
            "categoria": r["categoria"], "sentimiento": r["sentimiento"], "tono_monetario": r["tono_monetario"], "urgente": bool(r["urgente"]),
            "puntuaciones": json.loads(r["puntuaciones"]), "enlace": r["enlace"]} for r in filas]
    eventos = []
    if motor in ("macro", "risk", "forex"):
        mon = [c for c in claves if c in MONEDAS] if claves else None
        eventos = [{"titulo": e["titulo"], "moneda": e["moneda"], "ts": e["ts"], "impacto": e["impacto"], "prevision": e["prevision"],
                    "anterior": e["anterior"]} for e in calendario.alto_impacto_cerca(mon, antes_min=360, despues_min=120, ahora=ahora)]
    if registrar and out:
        try:
            with almacen.tx() as c:
                c.execute("INSERT INTO uso_motor(ts,motor,activo,noticias) VALUES(?,?,?,?)", (ahora, motor, simbolo, json.dumps([x["id"] for x in out])))
        except Exception:
            pass
    return {"noticias": out, "calendario_alto_impacto": eventos, "claves": claves,
            "nota": "Solo noticias verificadas; contexto informativo, nunca señal de compra/venta por sí solo."}
