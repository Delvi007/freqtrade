# -*- coding: utf-8 -*-
"""Agente multi-activo de TITAN: noticias por activo + análisis técnico + horas de mayor movimiento
+ registro y verificación de cada hipótesis. Solo biblioteca estándar.
INFORMATIVO: no opera, no da órdenes y NO predice; produce hipótesis que se miden después."""
from __future__ import annotations
import hashlib, json, re, sqlite3, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path


BASE = Path(__file__).resolve().parent
DB = BASE / "titan_activos.db"
HORIZONTE_H = 4
MIN_NOTICIAS = 3

# ---------------------------------------------------------------- red
def descargar(url, espera=25):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=espera) as r:
        return r.read()

def barras(simbolo, rango="1mo", intervalo="60m"):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(simbolo, safe="=^-.")
           + f"?range={rango}&interval={intervalo}")
    r = json.loads(descargar(url).decode("utf-8", "replace"))["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    vol = q.get("volume") or [0] * len(q["close"])
    out = []
    for t, o, h, l, c, v in zip(r["timestamp"], q["open"], q["high"], q["low"], q["close"], vol):
        if None not in (o, h, l, c):
            out.append({"t": t, "o": o, "h": h, "l": l, "c": c, "v": v or 0})
    if len(out) < 30:
        raise ValueError("pocos datos")
    return out

# ---------------------------------------------------------------- indicadores
def ema(v, n):
    k, e, out = 2 / (n + 1), v[0], [v[0]]
    for x in v[1:]:
        e = x * k + e * (1 - k)
        out.append(e)
    return out

def rsi(v, n=14):
    if len(v) <= n:
        raise ValueError("pocos datos")
    ga = sum(max(v[i] - v[i - 1], 0) for i in range(1, n + 1)) / n
    pe = sum(max(v[i - 1] - v[i], 0) for i in range(1, n + 1)) / n
    for i in range(n + 1, len(v)):
        d = v[i] - v[i - 1]
        ga = (ga * (n - 1) + max(d, 0)) / n
        pe = (pe * (n - 1) + max(-d, 0)) / n
    return 100.0 if pe == 0 else 100 - 100 / (1 + ga / pe)

def macd_hist(v):
    m = [a - b for a, b in zip(ema(v, 12), ema(v, 26))]
    return m[-1] - ema(m, 9)[-1]

def atr_pct(b, n=14):
    u = b[-n:]
    return sum((x["h"] - x["l"]) / x["c"] * 100 for x in u) / len(u)

def sgn(x):
    return (x > 0) - (x < 0)

def estacionalidad(b, zona):
    """Por hora local del día: n días, retorno medio %, % de días en que sube, rango medio %."""
    g = {}
    for x in b:
        h = datetime.fromtimestamp(x["t"], timezone.utc).astimezone(zona).hour
        g.setdefault(h, []).append(((x["c"] / x["o"] - 1) * 100, (x["h"] - x["l"]) / x["o"] * 100))
    est = {}
    for h, lst in g.items():
        if len(lst) >= 8:
            est[h] = {"n": len(lst), "media": sum(a for a, _ in lst) / len(lst),
                      "sube": sum(a > 0 for a, _ in lst) / len(lst) * 100,
                      "rango": sum(r for _, r in lst) / len(lst)}
    return est

def proxima_ventana(est, ahora_local, horas=8):
    cand = [(est[(ahora_local + timedelta(hours=k)).hour], (ahora_local + timedelta(hours=k)).hour)
            for k in range(1, horas + 1) if (ahora_local + timedelta(hours=k)).hour in est]
    if not cand:
        return None
    e, h = max(cand, key=lambda x: x[0]["rango"])
    return {"hora": h, **e}

# ---------------------------------------------------------------- noticias
GEN_ALZA = ["surge", "surges", "soar", "soars", "rally", "rallies", "jump", "jumps", "climb", "climbs", "rise", "rises",
            "gain", "gains", "record high", "all-time high", "beat", "beats", "upgrade", "upgrades", "approval",
            "approved", "inflow", "inflows", "bullish", "breakout", "rebound", "rebounds", "recovers",
            "sube", "suben", "alza", "récord", "máximo histórico", "repunta", "rebote", "alcista", "supera expectativas"]
GEN_BAJA = ["plunge", "plunges", "tumble", "tumbles", "slump", "slumps", "drop", "drops", "fall", "falls", "sink",
            "sinks", "slide", "slides", "crash", "sell-off", "selloff", "downgrade", "downgrades", "lawsuit", "probe",
            "investigation", "hack", "ban", "outflow", "outflows", "bearish", "miss", "misses", "warning",
            "cae", "caen", "baja", "caída", "desplome", "bajista", "venta masiva", "investigación", "demanda"]
POR_CLASE = {
    "metal": (["safe haven", "rate cut", "rate cuts", "dovish", "weak dollar", "central bank buying", "war", "geopolitical"],
              ["rate hike", "rate hikes", "hawkish", "strong dollar", "higher yields", "rising yields", "real yields rise"]),
    "energia": (["opec cut", "production cut", "supply cut", "inventories fall", "stockpiles fall", "draw", "sanctions",
                 "supply disruption", "war", "attack"],
                ["raise output", "oversupply", "stockpiles rise", "inventories rise", "glut", "demand fears",
                 "demand weakens", "recession"]),
    "cripto": (["etf approval", "etf inflows", "halving", "adoption", "institutional buying", "accumulation"],
               ["exchange hack", "sec lawsuit", "liquidations", "crackdown", "delisting", "rug pull"]),
    "accion": (["raises guidance", "record earnings", "buyback", "rate cut", "soft landing", "stimulus"],
               ["cuts guidance", "layoffs", "tariffs", "recession", "rate hike", "recall", "antitrust"]),
    "indice": (["soft landing", "stimulus", "rate cut", "rate cuts", "record earnings"],
               ["recession", "tariffs", "rate hike", "rate hikes", "layoffs", "hot inflation"]),
    "divisa": ([], []),
}
USD_FUERTE = ["rate hike", "rate hikes", "hawkish", "strong dollar", "dollar rallies", "dollar gains", "higher yields"]
USD_DEBIL = ["rate cut", "rate cuts", "dovish", "weak dollar", "dollar falls", "dollar slides", "lower yields"]

def _rx(terminos):
    return re.compile(r"\b(?:" + "|".join(re.escape(t) for t in sorted(set(terminos), key=len, reverse=True)) + r")\b", re.I) if terminos else None

def clasificar(a, texto):
    """Devuelve (impacto -1/0/1, fuerza, motivos) de un titular para ese activo."""
    alza, baja = list(GEN_ALZA), list(GEN_BAJA)
    ca, cb = POR_CLASE.get(a["clase"], ([], []))
    alza += ca
    baja += cb
    pts, motivos = 0, []
    for lista, signo in ((alza, 1), (baja, -1)):
        rx = _rx(lista)
        hallados = sorted({m.group(0).lower() for m in rx.finditer(texto)}) if rx else []
        pts += signo * len(hallados)
        motivos += hallados[:2]
    if a["usd"]:
        for lista, signo in ((USD_FUERTE, 1), (USD_DEBIL, -1)):
            hallados = sorted({m.group(0).lower() for m in _rx(lista).finditer(texto)})
            if a["clase"] == "divisa":  # en metales ya está en sus propias listas
                pts += signo * a["usd"] * len(hallados)
                motivos += hallados[:1]
    pts = max(-2, min(2, pts))
    return sgn(pts), abs(pts), motivos[:3]

def _limpia(t):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", unescape(t or ""))).strip()

def noticias_activo(a, horas=48, ahora=None):
    ahora = ahora or datetime.now(timezone.utc)
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": a["consulta"] + " when:2d", "hl": "en-US", "gl": "US", "ceid": "US:en"})
    raiz = ET.fromstring(descargar(url))
    rx = _rx(a["claves"])
    vistos, out = set(), []
    for it in raiz.findall(".//item"):
        g = lambda e: _limpia((it.find(e).text if it.find(e) is not None else ""))
        titulo, enlace, desc = g("title"), g("link"), g("description")
        try:
            f = parsedate_to_datetime(g("pubDate"))
            f = f if f.tzinfo else f.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        edad = (ahora - f).total_seconds() / 3600
        clave = re.sub(r"\W+", " ", titulo.lower()).strip()
        if not titulo or not enlace or edad > horas or edad < -1 or clave in vistos:
            continue
        vistos.add(clave)
        txt = titulo + ". " + desc
        if not rx.search(txt):
            continue
        imp, fuerza, mot = clasificar(a, txt)
        out.append({"titulo": titulo, "fuente": g("source"), "fecha": f.astimezone(timezone.utc).isoformat(),
                    "enlace": enlace, "impacto": imp, "fuerza": fuerza, "motivo": ", ".join(mot), "edad_h": edad})
    return out

def puntaje_noticias(lista):
    """-2..+2 según el promedio ponderado por frescura; 0 si hay menos de MIN_NOTICIAS relevantes."""
    if len(lista) < MIN_NOTICIAS:
        return 0
    pesos = [1.0 if n["edad_h"] < 12 else 0.6 if n["edad_h"] < 24 else 0.3 for n in lista]
    prom = sum(p * n["impacto"] for p, n in zip(pesos, lista)) / sum(pesos)
    return max(-2, min(2, round(prom * 3)))

# ---------------------------------------------------------------- base de datos
def conectar():
    c = sqlite3.connect(DB)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS noticias_activo(huella TEXT PRIMARY KEY, simbolo TEXT, titulo TEXT, fuente TEXT,
        fecha TEXT, enlace TEXT, impacto INTEGER, motivo TEXT, guardada_en TEXT);
    CREATE TABLE IF NOT EXISTS analisis(id INTEGER PRIMARY KEY AUTOINCREMENT, simbolo TEXT, creado_en TEXT,
        precio REAL, punt_tecnico INTEGER, punt_noticias INTEGER, total INTEGER, direccion TEXT, confianza TEXT,
        horizonte_h INTEGER, atr_pct REAL, detalle TEXT, precio_final REAL, evaluado_en TEXT, mov_pct REAL,
        resultado TEXT);
    """)
    return c

def guardar_noticias(c, simbolo, lista):
    ahora = datetime.now(timezone.utc).isoformat()
    for n in lista:
        h = hashlib.sha1((simbolo + n["enlace"]).encode()).hexdigest()
        c.execute("INSERT OR IGNORE INTO noticias_activo VALUES (?,?,?,?,?,?,?,?,?)",
                  (h, simbolo, n["titulo"], n["fuente"], n["fecha"], n["enlace"], n["impacto"], n["motivo"], ahora))

# ---------------------------------------------------------------- veredicto
def etiqueta(total):
    return ("alcista" if total >= 2 else "ligeramente alcista" if total == 1 else "lateral" if total == 0
            else "ligeramente bajista" if total == -1 else "bajista")

def analizar(a, zona, ahora=None, guardar=True):
    ahora = ahora or datetime.now(timezone.utc)
    r = {"activo": a, "error": None, "notas": []}
    try:
        b = barras(a["simbolo"], "1mo", "60m")
    except Exception as e:
        r["error"] = f"sin datos de precio ({type(e).__name__})"
        return r
    cierres = [x["c"] for x in b]
    precio = cierres[-1]
    e20, e50 = ema(cierres, 20)[-1], ema(cierres, 50)[-1]
    rs, mh = rsi(cierres), macd_hist(cierres)
    pt = sgn(precio - e20) + sgn(e20 - e50) + sgn(mh)
    if rs > 75 and pt > 0:
        pt -= 1
        r["notas"].append("RSI muy alto: riesgo de corrección")
    elif rs < 25 and pt < 0:
        pt += 1
        r["notas"].append("RSI muy bajo: posible rebote")
    try:
        d = barras(a["simbolo"], "6mo", "1d")
        dc = [x["c"] for x in d]
        r["diaria"] = "alcista" if dc[-1] > ema(dc, 50)[-1] else "bajista"
    except Exception:
        r["diaria"] = None
    try:
        nots = noticias_activo(a, 48, ahora)
    except Exception as e:
        nots = []
        r["notas"].append(f"noticias no disponibles ({type(e).__name__})")
    pn = puntaje_noticias(nots)
    total = pt + pn
    if pt and pn and sgn(pt) == sgn(pn) and abs(total) >= 3:
        conf = "media"
    else:
        conf = "baja"
    est = estacionalidad(b, zona)
    r.update(precio=precio, rsi=rs, ema20=e20, ema50=e50, macd=mh, punt_t=pt, punt_n=pn, total=total,
             direccion=etiqueta(total), confianza=conf, atr=atr_pct(b), noticias=nots,
             soporte=min(x["l"] for x in b[-48:]), resistencia=max(x["h"] for x in b[-48:]),
             ventana=proxima_ventana(est, ahora.astimezone(zona)), pocas=len(nots) < MIN_NOTICIAS,
             barras=b, est=est)
    if guardar:
        c = conectar()
        guardar_noticias(c, a["simbolo"], nots)
        detalle = json.dumps({"rsi": round(rs, 1), "ema20": e20, "ema50": e50, "noticias": len(nots)})
        c.execute("INSERT INTO analisis(simbolo,creado_en,precio,punt_tecnico,punt_noticias,total,direccion,confianza,"
                  "horizonte_h,atr_pct,detalle) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (a["simbolo"], ahora.isoformat(), precio, pt, pn, total, r["direccion"], conf, HORIZONTE_H,
                   r["atr"], detalle))
        c.commit(); c.close()
    return r

def _num(x):
    return f"{x:,.2f}" if abs(x) >= 1 else f"{x:.5f}"

def texto(r, zona=None):
    a = r["activo"]
    if r["error"]:
        return f"⚠️ {a['nombre']} ({a['simbolo']}): {r['error']}."
    n = r["noticias"]
    fav, adv = sum(x["impacto"] > 0 for x in n), sum(x["impacto"] < 0 for x in n)
    L = [f"📌 {a['nombre']} ({a['simbolo']}) · {_num(r['precio'])}",
         f"Hipótesis ({HORIZONTE_H} h): {r['direccion']} · confianza {r['confianza']}",
         f"• Técnico (1 h): precio {'sobre' if r['precio'] > r['ema20'] else 'bajo'} EMA20, EMA20 {'>' if r['ema20'] > r['ema50'] else '<'} EMA50, "
         f"MACD {'+' if r['macd'] > 0 else '−'}, RSI {r['rsi']:.0f} → {r['punt_t']:+d}"
         + (f" · diario {r['diaria']}" if r.get("diaria") else ""),
         (f"• Noticias (48 h): {len(n)} relevantes ({fav} favorables, {adv} adversas) → {r['punt_n']:+d}"
          if not r["pocas"] else f"• Noticias (48 h): solo {len(n)} relevantes; no puntúan")]
    for x in sorted(n, key=lambda x: -x["fuerza"])[:2]:
        if x["impacto"]:
            L.append(f"   {'▲' if x['impacto'] > 0 else '▼'} {x['titulo'][:90]}")
    if r["ventana"]:
        v = r["ventana"]
        sesgo = "sin sesgo claro" if 45 <= v["sube"] <= 55 else f"sube en {v['sube']:.0f}% de los días"
        L.append(f"• Hora de más movimiento próxima: {v['hora']:02d}:00 ({zona.key if zona else 'hora local'}) · rango medio {v['rango']:.2f}% · {sesgo} (n={v['n']})")
    L.append(f"• Niveles 48 h: soporte {_num(r['soporte'])} · resistencia {_num(r['resistencia'])} · rango típico/h {r['atr']:.2f}%")
    d = r["direccion"]
    L.append("• Se invalida si cierra bajo " + _num(r["soporte"]) if "alcista" in d else
             "• Se invalida si cierra sobre " + _num(r["resistencia"]) if "bajista" in d else
             f"• Rango probable entre {_num(r['soporte'])} y {_num(r['resistencia'])}")
    L += [f"• {x}" for x in r["notas"]]
    s = estadisticas(a["simbolo"])
    L.append(f"Acierto histórico del bot en este activo: {s['tasa']:.0f}% (n={s['n']})" if s["n"] >= 5
            else "Aún no hay suficientes hipótesis evaluadas para medir su acierto.")
    L.append("⚠️ Hipótesis informativa, no predicción ni consejo financiero.")
    return "\n".join(L)

# ---------------------------------------------------------------- verificación
def evaluar_pendientes(ahora=None):
    ahora = ahora or datetime.now(timezone.utc)
    c = conectar()
    filas = c.execute("SELECT id,simbolo,creado_en,precio,direccion,horizonte_h,atr_pct FROM analisis "
                      "WHERE evaluado_en IS NULL").fetchall()
    hechos, cache = 0, {}
    for i, sim, creado, precio, dire, h, atr in filas:
        t0 = datetime.fromisoformat(creado)
        obj = t0 + timedelta(hours=h)
        if ahora < obj:
            continue
        try:
            if sim not in cache:
                cache[sim] = barras(sim, "5d", "60m")
            ok = [x for x in cache[sim] if t0.timestamp() < x["t"] <= obj.timestamp()]
        except Exception:
            continue
        if not ok:
            if ahora > t0 + timedelta(hours=72):
                c.execute("UPDATE analisis SET evaluado_en=?, resultado='sin_datos' WHERE id=?", (ahora.isoformat(), i))
                hechos += 1
            continue
        pf = ok[-1]["c"]
        mov = (pf / precio - 1) * 100
        if abs(mov) < 0.1 * atr:
            res = "neutro"
        elif "alcista" in dire:
            res = "acierto" if mov > 0 else "fallo"
        elif "bajista" in dire:
            res = "acierto" if mov < 0 else "fallo"
        else:
            res = "acierto" if abs(mov) < atr else "fallo"
        c.execute("UPDATE analisis SET precio_final=?, evaluado_en=?, mov_pct=?, resultado=? WHERE id=?",
                  (pf, ahora.isoformat(), mov, res, i))
        hechos += 1
    c.commit(); c.close()
    return hechos

def estadisticas(simbolo=None):
    c = conectar()
    q = "SELECT resultado, COUNT(*) FROM analisis WHERE resultado IN ('acierto','fallo')"
    p = ()
    if simbolo:
        q += " AND simbolo=?"; p = (simbolo,)
    d = dict(c.execute(q + " GROUP BY resultado", p).fetchall())
    pend = c.execute("SELECT COUNT(*) FROM analisis WHERE evaluado_en IS NULL").fetchone()[0]
    c.close()
    n = d.get("acierto", 0) + d.get("fallo", 0)
    return {"n": n, "aciertos": d.get("acierto", 0), "tasa": (d.get("acierto", 0) / n * 100) if n else 0.0, "pendientes": pend}

def texto_precision():
    c = conectar()
    filas = c.execute("SELECT simbolo, SUM(resultado='acierto'), SUM(resultado='fallo') FROM analisis "
                      "WHERE resultado IN ('acierto','fallo') GROUP BY simbolo ORDER BY simbolo").fetchall()
    c.close()
    g = estadisticas()
    L = ["🎯 Precisión del bot (hipótesis a 4 h)"]
    if not g["n"]:
        L.append(f"Todavía no hay hipótesis evaluadas. Pendientes: {g['pendientes']}. Se evalúan solas {HORIZONTE_H} h después.")
    else:
        L.append(f"Global: {g['tasa']:.0f}% de acierto en {g['n']} hipótesis (pendientes: {g['pendientes']})")
        for s, a, f in filas:
            L.append(f"• {s}: {a}/{a + f} ({a / (a + f) * 100:.0f}%)")
        L.append("Con menos de ~30 hipótesis por activo, la cifra no es concluyente; el azar daría ~50%.")
    return "\n".join(L)

def validar_simbolo(s):
    barras(s, "1mo", "60m")
    return True
