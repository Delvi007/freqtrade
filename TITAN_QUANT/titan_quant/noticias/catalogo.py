"""Catálogo inicial de fuentes de información.

ACCESO (resultado de la sonda en vivo del 09/11/2026, se vuelve a comprobar en cada prueba):
    rss_publico          RSS/Atom público y gratuito con titulares y resumen
    titulares_suscripcion RSS público de titulares; el artículo completo exige suscripción (no se intenta eludir)
    json_publico         archivo JSON público (calendario)
    sin_rss_publico      no publica RSS gratuito (requiere licencia o no existe): NO se conecta
    bloqueado            el servidor rechaza clientes automáticos (403): NO se conecta ni se intenta eludir

CALIFICACIÓN TITAN (escala interna de 6 puntos, NO es una certificación oficial):
    6  ★★★★★★  fuente PRIMARIA institucional (banco central, estadística oficial, regulador): máxima prioridad
    5  ★★★★★   alta confiabilidad (medio financiero de referencia con equipo editorial y correcciones públicas)
    4  ★★★★    confiable con matices (medio especializado / agregador con fuentes identificadas)
    3  ★★★     útil, verificar (agregador, contenido patrocinado o línea editorial de defensa de un sector)
La puntuación sale de 10 criterios (0-5): autoridad, transparencia, autor, documental, exactitud, correcciones,
velocidad, independencia, primarias y errores (5 = pocos errores detectados). La popularidad NO cuenta.
"""

CRITERIOS = ("autoridad", "transparencia", "autor", "documental", "exactitud", "correcciones", "velocidad",
             "independencia", "primarias", "errores")

# Perfiles de criterios (0-5) por tipo de fuente; cada fuente puede ajustarlos en la configuración.
_PRIMARIA = dict(autoridad=5, transparencia=5, autor=4, documental=5, exactitud=5, correcciones=5, velocidad=4, independencia=5, primarias=5, errores=5)
_REFERENCIA = dict(autoridad=5, transparencia=4, autor=5, documental=4, exactitud=5, correcciones=5, velocidad=5, independencia=4, primarias=3, errores=4)
_GENERALISTA = dict(autoridad=3, transparencia=4, autor=4, documental=3, exactitud=4, correcciones=4, velocidad=5, independencia=4, primarias=2, errores=4)
_AGREGADOR = dict(autoridad=2, transparencia=3, autor=3, documental=3, exactitud=3, correcciones=3, velocidad=5, independencia=3, primarias=2, errores=3)
_CRIPTO_ESP = dict(autoridad=3, transparencia=4, autor=4, documental=3, exactitud=4, correcciones=4, velocidad=5, independencia=3, primarias=2, errores=4)
_CRIPTO_DEF = dict(autoridad=2, transparencia=3, autor=3, documental=3, exactitud=3, correcciones=3, velocidad=4, independencia=2, primarias=2, errores=3)
_EMPRESA = dict(autoridad=4, transparencia=4, autor=3, documental=4, exactitud=5, correcciones=4, velocidad=4, independencia=2, primarias=5, errores=5)


def f(id, nombre, categoria, url, criterios, acceso="rss_publico", primaria=False, idioma="en", frecuencia_min=15,
      prioridad=3, nota="", tipo="rss", activo=True, estrellas=None):
    return {"id": id, "nombre": nombre, "categoria": categoria, "url": url, "tipo": tipo, "acceso": acceso, "primaria": primaria,
            "idioma": idioma, "frecuencia_min": frecuencia_min, "prioridad": prioridad, "nota": nota, "criterios": dict(criterios),
            "activo": activo and acceso in ("rss_publico", "titulares_suscripcion", "json_publico"), "estrellas": estrellas}


CATALOGO = [
    # --- Bancos centrales y estadística oficial (fuentes PRIMARIAS) ---------------------------------------------
    f("fed_press", "Federal Reserve · comunicados", "banco_central", "https://www.federalreserve.gov/feeds/press_all.xml", _PRIMARIA, primaria=True, frecuencia_min=10, prioridad=1),
    f("fed_speeches", "Federal Reserve · discursos", "banco_central", "https://www.federalreserve.gov/feeds/speeches.xml", _PRIMARIA, primaria=True, frecuencia_min=30, prioridad=1),
    f("ecb_press", "Banco Central Europeo · prensa", "banco_central", "https://www.ecb.europa.eu/rss/press.html", _PRIMARIA, primaria=True, frecuencia_min=10, prioridad=1),
    f("ecb_blog", "Banco Central Europeo · blog y publicaciones", "banco_central", "https://www.ecb.europa.eu/rss/blog.html", _PRIMARIA, primaria=True, frecuencia_min=60, prioridad=2),
    f("boe_news", "Bank of England · noticias", "banco_central", "https://www.bankofengland.co.uk/rss/news", _PRIMARIA, primaria=True, frecuencia_min=10, prioridad=1),
    f("boj", "Bank of Japan · novedades", "banco_central", "https://www.boj.or.jp/en/rss/whatsnew.xml", _PRIMARIA, primaria=True, frecuencia_min=15, prioridad=1),
    f("boc", "Bank of Canada · comunicados", "banco_central", "https://www.bankofcanada.ca/content_type/press-releases/feed/", _PRIMARIA, primaria=True, frecuencia_min=15, prioridad=2),
    f("rba", "Reserve Bank of Australia · comunicados", "banco_central", "https://www.rba.gov.au/rss/rss-cb-media-releases.xml", _PRIMARIA, primaria=True, frecuencia_min=15, prioridad=2),
    f("rbnz", "Reserve Bank of New Zealand · noticias", "banco_central", "https://www.rbnz.govt.nz/feeds/news", _PRIMARIA, primaria=True, frecuencia_min=15, prioridad=2),
    f("snb", "Swiss National Bank · comunicados", "banco_central", "https://www.snb.ch/public/en/rss/pressrel", _PRIMARIA, primaria=True, frecuencia_min=15, prioridad=2),
    f("nyfed", "Federal Reserve Bank of New York", "banco_central", "https://www.newyorkfed.org/newsevents", _PRIMARIA, primaria=True, acceso="sin_rss_publico",
      nota="Las URL de RSS probadas devuelven una página HTML, no un feed (sonda 09/11/2026). Sus comunicados clave también salen en el RSS de la Fed."),
    f("bls", "U.S. Bureau of Labor Statistics · últimos datos", "estadistica", "https://www.bls.gov/feed/bls_latest.rss", _PRIMARIA, primaria=True, frecuencia_min=30, prioridad=1),
    f("bea", "U.S. Bureau of Economic Analysis", "estadistica", "https://apps.bea.gov/rss/rss.xml", _PRIMARIA, primaria=True, acceso="bloqueado",
      nota="El RSS existe, pero su robots.txt no permite lectores automáticos: TITAN lo respeta. El PIB y el PCE llegan por el calendario y los medios."),
    f("eurostat", "Eurostat · actualizaciones estadísticas", "estadistica",
      "https://ec.europa.eu/eurostat/api/dissemination/catalogue/rss/en/statistics-update.rss", _PRIMARIA, primaria=True, frecuencia_min=60, prioridad=4, activo=False,
      nota="Publica cientos de actualizaciones de conjuntos de datos con códigos técnicos: desactivada por defecto (activable)."),
    f("imf", "Fondo Monetario Internacional", "organismo", "https://www.imf.org/en/News/RSS?language=eng", _PRIMARIA, primaria=True, acceso="bloqueado",
      nota="Responde 403 a clientes automáticos (sonda 09/11/2026). No se intenta eludir."),
    f("worldbank", "Banco Mundial", "organismo", "https://www.worldbank.org/en/news", _PRIMARIA, primaria=True, acceso="sin_rss_publico",
      nota="No se encontró un RSS público válido (las URL probadas devuelven HTML o 404)."),
    f("oecd", "OCDE", "organismo", "https://www.oecd.org/newsroom/", _PRIMARIA, primaria=True, acceso="bloqueado",
      nota="Responde 403 a clientes automáticos (sonda 09/11/2026)."),
    # --- Reguladores y operadores de mercado ---------------------------------------------------------------------
    f("sec_press", "SEC · comunicados de prensa", "regulador", "https://www.sec.gov/news/pressreleases.rss", _PRIMARIA, primaria=True, frecuencia_min=30, prioridad=2,
      nota="La SEC exige un User-Agent identificado y un máximo de 10 peticiones/s; TITAN hace 1 cada 30 min."),
    f("cftc_press", "CFTC · comunicados", "regulador", "https://www.cftc.gov/RSS/RSSGP/rssgp.xml", _PRIMARIA, primaria=True, frecuencia_min=30, prioridad=2),
    f("finra", "FINRA · novedades", "regulador", "https://www.finra.org/rss.xml", _PRIMARIA, primaria=True, frecuencia_min=60, prioridad=3),
    f("esma", "ESMA · novedades", "regulador", "https://www.esma.europa.eu/rss.xml", _PRIMARIA, primaria=True, frecuencia_min=60, prioridad=3,
      nota="Sus elementos no traen fecha: se fecha por la hora de recepción."),
    f("fca", "FCA · noticias", "regulador", "https://www.fca.org.uk/news/rss.xml", _PRIMARIA, primaria=True, frecuencia_min=60, prioridad=3,
      nota="Sus elementos no traen fecha: se fecha por la hora de recepción."),
    f("cme", "CME Group · comunicados (relación con inversores)", "mercado", "https://investor.cmegroup.com/rss/news-releases.xml", _EMPRESA, frecuencia_min=60, prioridad=3),
    f("cboe", "Cboe Global Markets", "mercado", "https://www.cboe.com/", _EMPRESA, acceso="sin_rss_publico", nota="Sin RSS público localizado (404)."),
    f("nyse", "NYSE / ICE", "mercado", "https://ir.theice.com/", _EMPRESA, acceso="sin_rss_publico", nota="Sin RSS público localizado (404)."),
    f("nasdaq", "Nasdaq · mercados", "mercado", "https://www.nasdaq.com/feed/rssoutbound?category=Markets", _AGREGADOR, frecuencia_min=15, prioridad=4,
      nota="Mezcla contenido propio y de socios."),
    # --- Medios financieros -------------------------------------------------------------------------------------
    f("bloomberg", "Bloomberg · mercados (titulares)", "medio", "https://feeds.bloomberg.com/markets/news.rss", _REFERENCIA, acceso="titulares_suscripcion", frecuencia_min=10, prioridad=2,
      nota="Solo titulares; el artículo exige suscripción."),
    f("ft", "Financial Times (titulares)", "medio", "https://www.ft.com/rss/home", _REFERENCIA, acceso="titulares_suscripcion", frecuencia_min=10, prioridad=2,
      nota="Solo titulares; el artículo exige suscripción."),
    f("wsj_markets", "The Wall Street Journal · mercados (titulares)", "medio", "https://feeds.content.dowjones.io/public/rss/RSSMarketsMain", _REFERENCIA,
      acceso="titulares_suscripcion", frecuencia_min=10, prioridad=2, nota="Solo titulares; el artículo exige suscripción."),
    f("economist", "The Economist · finanzas y economía", "analisis", "https://www.economist.com/finance-and-economics/rss.xml", _REFERENCIA,
      acceso="titulares_suscripcion", frecuencia_min=60, prioridad=3, nota="Análisis semanal; el artículo exige suscripción."),
    f("cnbc", "CNBC · noticias principales", "medio", "https://www.cnbc.com/id/100003114/device/rss/rss.html", _GENERALISTA, frecuencia_min=10, prioridad=3),
    f("marketwatch", "MarketWatch · principales", "medio", "https://feeds.content.dowjones.io/public/rss/mw_topstories", _GENERALISTA, frecuencia_min=10, prioridad=3,
      nota="Incluye contenido de finanzas personales (relevancia filtrada por el análisis)."),
    f("yahoo", "Yahoo Finance · titulares", "medio", "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EGSPC&region=US&lang=en-US", _AGREGADOR,
      acceso="bloqueado", nota="Su robots.txt no permite lectores automáticos en el RSS: TITAN lo respeta."),
    f("investing", "Investing.com · noticias", "medio", "https://www.investing.com/rss/news.rss", _AGREGADOR, frecuencia_min=15, prioridad=4),
    f("reuters", "Reuters", "medio", "https://www.reuters.com/", _REFERENCIA, acceso="sin_rss_publico",
      nota="Reuters retiró sus RSS públicos en 2020; el acceso es por licencia (Reuters Connect)."),
    f("barrons", "Barron's", "medio", "https://www.barrons.com/", _REFERENCIA, acceso="bloqueado", nota="Responde 403 a clientes automáticos."),
    # --- Criptomonedas ------------------------------------------------------------------------------------------
    f("coindesk", "CoinDesk", "cripto", "https://www.coindesk.com/arc/outboundfeeds/rss/", _CRIPTO_ESP, frecuencia_min=10, prioridad=2),
    f("theblock", "The Block", "cripto", "https://www.theblock.co/rss.xml", _CRIPTO_ESP, frecuencia_min=10, prioridad=2),
    f("decrypt", "Decrypt", "cripto", "https://decrypt.co/feed", _CRIPTO_ESP, frecuencia_min=15, prioridad=3),
    f("cointelegraph", "Cointelegraph", "cripto", "https://cointelegraph.com/rss", _CRIPTO_DEF, frecuencia_min=15, prioridad=3,
      nota="Incluye contenido patrocinado: verificar con otra fuente."),
    f("bitcoinmag", "Bitcoin Magazine", "cripto", "https://bitcoinmagazine.com/.rss/full/", _CRIPTO_DEF, frecuencia_min=30, prioridad=4,
      nota="Línea editorial de defensa de Bitcoin (independencia baja)."),
    # --- Calendario económico -----------------------------------------------------------------------------------
    f("calendario_ff", "Calendario económico semanal (Fair Economy / ForexFactory)", "calendario",
      "https://nfs.faireconomy.media/ff_calendar_thisweek.json", _AGREGADOR, tipo="calendario", acceso="json_publico", frecuencia_min=60, prioridad=1,
      nota="Fuente SECUNDARIA pública: hora, impacto, previsión y dato anterior; NO trae el dato publicado (se toma de las fuentes oficiales)."),
]


def estrellas(criterios, primaria=False):
    """Puntuación TITAN (1-6): 6 solo para fuentes primarias institucionales con criterios altos."""
    vals = [max(0, min(5, int(criterios.get(k, 0)))) for k in CRITERIOS]
    media = sum(vals) / len(vals)
    if primaria and media >= 4.5:
        return 6
    return 5 if media >= 4.3 else 4 if media >= 3.5 else 3 if media >= 2.7 else 2 if media >= 2.0 else 1


def texto_estrellas(n):
    n = int(n or 0)
    return "★" * n + "☆" * (6 - n)


ACCESO_TEXTO = {"rss_publico": "RSS público gratuito", "titulares_suscripcion": "Titulares gratis · artículo de pago",
                "json_publico": "JSON público gratuito", "sin_rss_publico": "Sin RSS público (licencia)", "bloqueado": "Bloquea clientes automáticos"}
