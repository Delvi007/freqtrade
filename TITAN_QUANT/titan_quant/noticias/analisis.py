"""Análisis de noticias: transparente, determinista y revisable (reglas y léxicos propios de TITAN).

Qué hace:
    · categoría económica y subtipo (decisión de tipos, inflación, empleo, PIB, PMI, comercio, geopolítica, regulación…)
    · entidades: monedas, países, bancos centrales, materias primas, criptoactivos, índices, empresas y sectores
    · sentimiento financiero (léxico con negación) y tono monetario (restrictivo / expansivo) — NUNCA señal de compra/venta
    · rumores y noticias no verificadas («según fuentes», «podría», «reportedly»…)
    · urgencia (última hora, emergencia, decisiones imprevistas) y sorpresa frente a la previsión cuando el texto la cita
    · seis puntuaciones 0-100: confiabilidad de la fuente, confiabilidad de la información, relevancia financiera,
      impacto potencial, urgencia y nivel de confirmación
    · impacto potencial por mercado (forex, acciones/ETF, cripto, materias primas) con horizonte e incertidumbre

Limitación declarada: no es un modelo de lenguaje; no entiende ironía ni contexto largo. Por eso sus salidas son
información para los motores, con pesos bajos, y nunca disparan una operación por sí solas.
"""
import re
import unicodedata

VERSION = "1.4"          # cambia cuando cambian las reglas: recolector.reanalizar() recalcula lo guardado

# ----------------------------------------------------------------------------------------------- normalización
STOP = set("""a an the of to in on for and or but with by at from as is are was were be been it its this that these those
into over after before about than then up down out new says say said will would could may might can just more most
de la el los las un una y o en por para con del al se que su sus es son lo""".split())


def normal(t):
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", t).strip()


def tokens(t):
    return {w for w in re.findall(r"[a-z0-9$]+", normal(t)) if len(w) > 2 and w not in STOP}


def _rx(*palabras):
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(palabras) + r")(?![a-z0-9])")


# ----------------------------------------------------------------------------------------------- categorías
CATEGORIAS = [   # (id, nombre, patrón, peso de impacto 0-100, horizonte típico)
    ("tipos_interes", "Decisión de tipos / política monetaria", _rx(r"rate (?:cut|hike|decision)s?", r"interest rates?", r"bank rate", r"policy rate", r"fomc",
                                                                   r"monetary policy", r"rate[- ]setting", r"basis points?", r"bps", r"quantitative (?:easing|tightening)",
                                                                   r"tipos? de interes", r"politica monetaria"), 90, "días a semanas"),
    ("inflacion", "Inflación", _rx(r"inflation", r"cpi", r"pce", r"consumer prices?", r"producer prices?", r"ppi", r"hicp", r"deflation", r"inflacion",
                                  r"core prices?"), 80, "horas a días"),
    ("empleo", "Empleo", _rx(r"payrolls?", r"nonfarm", r"non-farm", r"nfp", r"unemployment", r"jobless", r"labor market", r"labour market", r"jobs report",
                            r"employment", r"empleo", r"desempleo", r"wages?"), 80, "horas a días"),
    ("crecimiento", "Crecimiento / PIB", _rx(r"gdp", r"gross domestic product", r"recession", r"economic growth", r"contraction", r"pib", r"recesion"), 70, "días a semanas"),
    ("actividad", "Actividad (PMI, ventas, producción)", _rx(r"pmi", r"purchasing managers", r"retail sales", r"industrial production", r"factory orders",
                                                            r"consumer confidence", r"sentiment index", r"housing starts", r"durable goods"), 55, "horas a días"),
    ("bonos", "Bonos y subastas", _rx(r"treasur(?:y|ies)", r"bond auctions?", r"yields?", r"gilts?", r"bunds?", r"jgbs?", r"debt ceiling", r"bonos"), 60, "horas a días"),
    ("comercio", "Comercio y aranceles", _rx(r"tariffs?", r"trade war", r"trade deal", r"trade deficit", r"trade balance", r"exports?", r"imports?", r"aranceles?"), 60, "días a semanas"),
    ("geopolitica", "Geopolítica", _rx(r"war", r"invasion", r"missile", r"sanctions?", r"military", r"ceasefire", r"conflict", r"attack", r"election",
                                       r"guerra", r"sanciones"), 65, "días"),
    ("regulacion", "Regulación y supervisión", _rx(r"sec", r"cftc", r"finra", r"esma", r"fca", r"regulat\w*", r"enforcement", r"lawsuit", r"fine[ds]?",
                                                  r"charges?", r"settlement", r"mica", r"rule(?:making|s)?", r"supervis\w*"), 50, "días a semanas"),
    ("resultados", "Resultados empresariales", _rx(r"earnings", r"revenue", r"quarterly results", r"guidance", r"profit warning", r"eps", r"dividend",
                                                  r"buyback", r"q[1-4] \d{4}"), 45, "horas a días"),
    ("materias_primas", "Materias primas", _rx(r"oil", r"crude", r"brent", r"wti", r"opec\+?", r"natural gas", r"lng", r"gold", r"silver", r"copper"), 55, "horas a días"),
    ("cripto", "Criptomonedas", _rx(r"bitcoin", r"btc", r"ether(?:eum)?", r"eth", r"crypto\w*", r"stablecoins?", r"blockchain", r"defi", r"etf flows?",
                                   r"token\w*", r"hack(?:ed)?", r"exploit"), 50, "horas a días"),
    ("tecnologia", "Tecnología / IA", _rx(r"artificial intelligence", r"ai", r"semiconductors?", r"chips?", r"nvidia", r"data cent(?:er|re)s?"), 35, "días"),
]

# ----------------------------------------------------------------------------------------------- entidades
MONEDAS = {
    "USD": _rx(r"dollar", r"greenback", r"fed", r"federal reserve", r"fomc", r"powell", r"u\.s\.?", r"united states", r"america\w*", r"treasur(?:y|ies)",
               r"payrolls?", r"nonfarm", r"bls", r"bea", r"wall street", r"washington"),
    "EUR": _rx(r"euro", r"eurozone", r"euro area", r"ecb", r"lagarde", r"germany", r"german", r"france", r"french", r"ital(?:y|ian)", r"spain", r"spanish",
               r"eurostat", r"bund"),
    "GBP": _rx(r"sterling", r"pound", r"boe", r"bank of england", r"bailey", r"u\.?k\.?", r"britain", r"british", r"gilts?"),
    "JPY": _rx(r"yen", r"boj", r"bank of japan", r"ueda", r"japan\w*", r"jgbs?", r"tokyo"),
    "CHF": _rx(r"franc", r"snb", r"swiss national bank", r"switzerland", r"swiss"),
    "CAD": _rx(r"loonie", r"canad\w*", r"bank of canada", r"boc", r"macklem"),
    "AUD": _rx(r"aussie", r"australia\w*", r"rba", r"reserve bank of australia", r"bullock"),
    "NZD": _rx(r"kiwi", r"new zealand", r"rbnz", r"reserve bank of new zealand"),
}
PAISES = {"Estados Unidos": MONEDAS["USD"], "Zona euro": _rx(r"eurozone", r"euro area", r"ecb", r"eurostat"), "Alemania": _rx(r"germany", r"german"),
          "Francia": _rx(r"france", r"french"), "Reino Unido": MONEDAS["GBP"], "Japón": MONEDAS["JPY"], "Suiza": MONEDAS["CHF"], "Canadá": MONEDAS["CAD"],
          "Australia": MONEDAS["AUD"], "Nueva Zelanda": MONEDAS["NZD"], "China": _rx(r"china", r"chinese", r"beijing", r"pboc", r"yuan", r"renminbi"),
          "Rusia": _rx(r"russia\w*", r"moscow", r"kremlin"), "Ucrania": _rx(r"ukrain\w*", r"kyiv"), "Oriente Medio": _rx(r"israel\w*", r"iran\w*", r"gaza",
          r"saudi", r"middle east", r"opec"), "India": _rx(r"india\w*", r"rbi"), "México": _rx(r"mexic\w*", r"banxico"), "Brasil": _rx(r"brazil\w*")}
MATERIAS = {"XAU (oro)": _rx(r"gold", r"bullion", r"xau"), "XAG (plata)": _rx(r"silver", r"xag"), "Petróleo": _rx(r"oil", r"crude", r"brent", r"wti", r"opec\+?"),
            "Gas natural": _rx(r"natural gas", r"lng", r"ttf"), "Cobre": _rx(r"copper")}
CRIPTO = {"BTC": _rx(r"bitcoin", r"btc"), "ETH": _rx(r"ether(?:eum)?", r"eth"), "SOL": _rx(r"solana", r"sol"), "XRP": _rx(r"xrp", r"ripple"),
          "Stablecoins": _rx(r"stablecoins?", r"usdt", r"usdc", r"tether", r"circle"), "Exchanges": _rx(r"binance", r"coinbase", r"kraken", r"okx", r"bybit"),
          "Regulación cripto": _rx(r"mica", r"crypto (?:bill|law|regulation|rules?)", r"sec (?:sues|charges|approves)", r"genius act", r"clarity act")}
INDICES = {"S&P 500": _rx(r"s&p 500", r"s&p", r"spx", r"spy"), "Nasdaq 100": _rx(r"nasdaq", r"qqq"), "Dow Jones": _rx(r"dow jones", r"the dow", r"djia"),
           "DAX (GERMANY 40)": _rx(r"dax"), "FTSE 100": _rx(r"ftse"), "Nikkei 225": _rx(r"nikkei"), "Euro Stoxx 50": _rx(r"stoxx"),
           "ASX 200 (AUSTRALIA 200)": _rx(r"asx")}
EMPRESAS = {"NVDA": _rx(r"nvidia"), "AAPL": _rx(r"apple"), "MSFT": _rx(r"microsoft"), "AMZN": _rx(r"amazon"), "GOOGL": _rx(r"alphabet", r"google"),
            "META": _rx(r"meta platforms", r"facebook"), "TSLA": _rx(r"tesla"), "JPM": _rx(r"jpmorgan"), "GS": _rx(r"goldman sachs"), "BAC": _rx(r"bank of america"),
            "AMD": _rx(r"advanced micro devices", r"amd"), "INTC": _rx(r"intel"), "TSM": _rx(r"tsmc", r"taiwan semiconductor"), "BRK": _rx(r"berkshire"),
            "XOM": _rx(r"exxon"), "CVX": _rx(r"chevron"), "GM": _rx(r"general motors"), "COIN": _rx(r"coinbase"), "MSTR": _rx(r"microstrategy", r"strategy inc")}
SECTORES = {"Banca": _rx(r"banks?", r"banking", r"lenders?"), "Semiconductores": _rx(r"semiconductors?", r"chipmakers?", r"chips?"),
            "Energía": _rx(r"energy", r"oil majors?", r"refiners?"), "Tecnología": _rx(r"tech\w*", r"software"), "Inmobiliario": _rx(r"real estate", r"housing", r"mortgages?"),
            "Salud": _rx(r"pharma\w*", r"biotech", r"healthcare"), "Consumo": _rx(r"retailers?", r"consumer spending")}
TICKER = re.compile(r"\((?:nasdaq|nyse|amex|lse|tsx)\s*:\s*([A-Z.]{1,6})\)|\$([A-Z]{1,5})\b", re.I)

# ----------------------------------------------------------------------------------------------- léxicos
POSITIVO = set("""beat beats surge surged surges soar soared rally rallied rallies gain gains gained rise rises rose jump jumped record strong stronger
strength growth grew expand expanded expansion improve improved improves upgrade upgraded optimism optimistic boost boosted rebound rebounded recovery
recover recovered outperform outperformed profit profits profitable approve approved approval breakthrough resilient robust exceed exceeded exceeds
higher bullish upbeat accelerate accelerated easing eased
sube suben subio alza alzas gana ganan ganancia ganancias crecimiento crece crecio mejora mejoro repunte repunta repunto avanza avanzo
optimismo fortaleza superavit supera supero""".split())
NEGATIVO = set("""miss missed misses plunge plunged plunges slump slumped tumble tumbled fall falls fell drop dropped drops decline declined declines loss
losses weak weaker weakness contraction contract contracted shrink shrank recession crisis default defaults downgrade downgraded fear fears concern
concerns risk risks warn warned warning lawsuit fraud hack hacked exploit sanction sanctions war attack layoffs layoff cut cuts bankrupt bankruptcy
selloff sell-off crash crashed volatile turmoil probe investigation charged fine fined lower bearish slowdown slowed stall stalled worse worst
deteriorate deteriorated pessimism
cae caen cayo caida caidas baja bajan bajo desplome desploma perdida perdidas recesion crisis quiebra impago alerta advertencia
sancion sanciones guerra ataque despidos recorte recortes deficit desaceleracion pesimismo hundimiento""".split())
NEGACION = set("not no never without fails fail failed lack lacks barely hardly".split())
_TASA = r"(?:the )?(?:policy |bank |interest |cash |benchmark |key |official )?(?:interest )?rates?"
RESTRICTIVO = _rx(r"hike\w*", r"rate increases?", r"rais(?:e|es|ed|ing) " + _TASA, r"increas(?:e|es|ed|ing) " + _TASA, r"bank rate increased", r"tighten\w*", r"hawkish", r"higher for longer", r"inflation (?:remains|stays) (?:high|elevated|sticky)",
                  r"bank rate increased", r"increase(?:s|d)? (?:the )?(?:bank|policy) rate", r"quantitative tightening")
EXPANSIVO = _rx(r"rate cuts?", r"cut(?:s|ting)? " + _TASA, r"lower(?:ed|s|ing)? " + _TASA, r"reduc(?:e|es|ed|ing) " + _TASA, r"eas(?:e|ing) policy", r"dovish",
                r"stimulus", r"quantitative easing", r"bank rate (?:cut|reduced|lowered)", r"pause[ds]? (?:rate )?hikes?")
RUMOR = _rx(r"reportedly", r"rumou?rs?", r"sources? (?:said|say|familiar)", r"people familiar", r"according to (?:people|sources|a person)",
            r"unconfirmed", r"speculat\w*", r"could", r"might", r"considering", r"in talks", r"weighs?", r"mulls?", r"seg[uú]n fuentes")
URGENTE = _rx(r"breaking", r"urgent", r"flash", r"just in", r"emergency", r"unscheduled", r"surprise (?:cut|hike|move|decision)", r"halts?", r"suspends?",
              r"intervention", r"default", r"collapse[ds]?", r"declares? war", r"martial law", r"circuit breaker", r"exploit(?:ed)?", r"hack(?:ed)?")
SORPRESA = re.compile(r"(-?\d+(?:\.\d+)?)\s*%[^.]{0,80}?(?:expected|forecast|consensus|estimates?|economists? (?:polled|surveyed)?\s*(?:had )?(?:expected|forecast))"
                      r"[^\d-]{0,25}(-?\d+(?:\.\d+)?)\s*%", re.I)


def _encontrar(texto, tabla):
    return sorted(k for k, rx in tabla.items() if rx.search(texto))


def sentimiento(texto):
    """−1..+1 a partir del léxico financiero con negación (ventana de 3 palabras). 0 si no hay términos."""
    pal = re.findall(r"[a-z\-]+", normal(texto))
    pos = neg = 0
    for i, w in enumerate(pal):
        s = 1 if w in POSITIVO else -1 if w in NEGATIVO else 0
        if not s:
            continue
        if any(p in NEGACION for p in pal[max(0, i - 3):i]):
            s = -s
        pos, neg = (pos + 1, neg) if s > 0 else (pos, neg + 1)
    tot = pos + neg
    return round((pos - neg) / tot, 3) if tot else 0.0


def tono_monetario(texto):
    """+1 restrictivo (hawkish) · −1 expansivo (dovish) · 0 sin señal."""
    t = normal(texto)
    r, e = len(RESTRICTIVO.findall(t)), len(EXPANSIVO.findall(t))
    return round((r - e) / (r + e), 3) if (r + e) else 0.0


def categoria(texto):
    t = normal(texto)
    encontradas = [(c, n, p, h) for c, n, rx, p, h in CATEGORIAS if rx.search(t)]
    if not encontradas:
        return None, [], 10, "incierto"
    principal = max(encontradas, key=lambda x: x[2])
    return principal[0], [c for c, *_ in encontradas], principal[2], principal[3]


def entidades(texto):
    t = normal(texto)
    tick = sorted({(a or b).upper() for a, b in TICKER.findall(str(texto or ""))})
    return {"monedas": _encontrar(t, MONEDAS), "paises": _encontrar(t, PAISES), "materias": _encontrar(t, MATERIAS), "cripto": _encontrar(t, CRIPTO),
            "indices": _encontrar(t, INDICES), "empresas": sorted(set(_encontrar(t, EMPRESAS)) | set(tick)), "sectores": _encontrar(t, SECTORES)}


SORPRESA2 = re.compile(r"(-?\d+(?:\.\d+)?)\s*%[^.]{0,60}?(?:above|below|versus|vs\.?|compared with|against|beating|missing)\s+(?:the |an? )?"
                       r"(?:expected |forecast |consensus |estimated? )?(-?\d+(?:\.\d+)?)\s*%(?:[^.]{0,40}?(?:expected|forecast|consensus|estimate))", re.I)


def sorpresa(texto):
    m = SORPRESA.search(str(texto or "")) or SORPRESA2.search(str(texto or ""))
    if not m:
        return None
    real, prev = float(m.group(1)), float(m.group(2))
    return {"publicado": real, "prevision": prev, "diferencia": round(real - prev, 4),
            "lectura": "por encima de lo previsto" if real > prev else "por debajo de lo previsto" if real < prev else "en línea con lo previsto",
            "metodo": "extraído del texto (heurístico)"}


def impacto_mercados(ent, cat, horizonte, incertidumbre):
    """Mercados potencialmente afectados. Describe EXPOSICIÓN, no dirección: no es una señal de compra o venta."""
    out = []
    for m in ent["monedas"]:
        out.append({"mercado": "forex", "activo": m, "horizonte": horizonte, "incertidumbre": incertidumbre})
    for k in ent["indices"] + ent["empresas"] + ent["sectores"]:
        out.append({"mercado": "acciones_etf", "activo": k, "horizonte": horizonte, "incertidumbre": incertidumbre})
    for k in ent["cripto"]:
        out.append({"mercado": "cripto", "activo": k, "horizonte": horizonte, "incertidumbre": incertidumbre})
    for k in ent["materias"]:
        out.append({"mercado": "materias_primas", "activo": k, "horizonte": horizonte, "incertidumbre": incertidumbre})
    if cat in ("tipos_interes", "inflacion", "empleo") and "XAU (oro)" not in ent["materias"] and "USD" in ent["monedas"]:
        out.append({"mercado": "materias_primas", "activo": "XAU (oro)", "horizonte": horizonte, "incertidumbre": "alta",
                    "motivo": "sensibilidad del oro a los tipos reales del dólar (relación indirecta)"})
    return out[:30]


# Moneda de cada fuente institucional: un comunicado del BoE afecta a la GBP aunque el texto no la nombre.
MONEDA_FUENTE = {"fed_press": "USD", "fed_speeches": "USD", "nyfed": "USD", "bls": "USD", "bea": "USD",
                 "ecb_press": "EUR", "ecb_blog": "EUR", "eurostat": "EUR", "boe_news": "GBP",
                 "boj": "JPY", "boc": "CAD", "rba": "AUD", "rbnz": "NZD", "snb": "CHF"}


def analizar(titulo, resumen, fuente, n_fuentes=1, edad_h=None):
    """Análisis completo de una noticia. `fuente` = fila de la tabla fuentes (estrellas, primaria, categoria)."""
    texto = f"{titulo}. {resumen or ''}"
    t = normal(texto)
    cat, subcats, peso, horizonte = categoria(texto)
    ent = entidades(texto)
    mon = MONEDA_FUENTE.get(fuente.get("id"))
    if mon and mon not in ent["monedas"]:
        ent["monedas"] = sorted(ent["monedas"] + [mon])
    rumor = bool(RUMOR.search(normal(titulo))) and not fuente.get("primaria")
    urgente = bool(URGENTE.search(normal(titulo)))
    sent = sentimiento(texto)
    tono = tono_monetario(texto) if cat in ("tipos_interes", "inflacion", "bonos") or fuente.get("categoria") == "banco_central" else 0.0
    estrellas = int(fuente.get("estrellas") or 3)
    primaria = bool(fuente.get("primaria"))
    confirmacion = 100 if primaria else min(100, 25 + 30 * (max(1, n_fuentes) - 1))
    conf_fuente = round(estrellas / 6 * 100)
    conf_info = max(0, min(100, round(0.55 * conf_fuente + 0.35 * confirmacion + (10 if not rumor else -25))))
    n_ent = sum(len(v) for v in ent.values())
    relevancia = 0 if not cat and n_ent == 0 else min(100, (40 if cat else 10) + 8 * n_ent + (10 if primaria else 0))
    impacto = min(100, round(peso * (1.0 if (primaria or n_fuentes >= 2) else 0.75) * (0.6 if rumor else 1.0) + (10 if urgente else 0)))
    reciente = 0 if edad_h is None else (30 if edad_h <= 1 else 15 if edad_h <= 6 else 0)
    urgencia = min(100, (60 if urgente else 0) + reciente + (20 if cat == "tipos_interes" and primaria else 0))
    incert = "baja" if primaria or n_fuentes >= 3 else "media" if n_fuentes == 2 and not rumor else "alta"
    verificada = primaria or (n_fuentes >= 2 and not rumor) or (estrellas >= 5 and not rumor)
    return {"categoria": cat, "subcategorias": subcats, "entidades": ent, "paises": ent["paises"], "sentimiento": sent, "tono_monetario": tono,
            "rumor": rumor, "urgente": urgente, "sorpresa": sorpresa(texto), "verificada": verificada,
            "impacto": impacto_mercados(ent, cat, horizonte, incert),
            "puntuaciones": {"confiabilidad_fuente": conf_fuente, "confiabilidad_informacion": conf_info, "relevancia": relevancia,
                             "impacto_potencial": impacto, "urgencia": urgencia, "confirmacion": confirmacion},
            "nota": "Sentimiento y tono son descriptivos: no son una señal de compra ni de venta."}


def activos_de(analisis):
    e = analisis["entidades"]
    return sorted(set(e["monedas"] + e["materias"] + e["cripto"] + e["indices"] + e["empresas"]))


def similitud(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
