# -*- coding: utf-8 -*-
"""Catálogo de activos para seguimiento y análisis de mercado."""

CATEGORIAS = [
    "Futuros",
    "Cripto",
    "Divisas",
    "ETF",
    "Acciones",
    "Personalizado",
]


def _a(cat, nombre, simbolo, claves, consulta, clase, usd=0):
    return {
        "categoria": cat,
        "nombre": nombre,
        "simbolo": simbolo,
        "claves": claves,
        "consulta": consulta,
        "clase": clase,
        "usd": usd,
    }


CATALOGO = [
    # FUTUROS
    _a("Futuros", "Oro", "GC=F",
       ["gold", "xau", "oro"], "gold price XAU", "metal", -1),
    _a("Futuros", "Plata", "SI=F",
       ["silver", "plata"], "silver price", "metal", -1),
    _a("Futuros", "Petróleo WTI", "CL=F",
       ["oil", "wti", "crude", "petróleo"], "crude oil WTI OPEC", "energia"),
    _a("Futuros", "Gas natural", "NG=F",
       ["natural gas", "gas natural"], "natural gas prices", "energia"),
    _a("Futuros", "S&P 500 (fut.)", "ES=F",
       ["s&p", "wall street", "stocks"], "S&P 500 Wall Street stocks", "indice"),
    _a("Futuros", "Nasdaq (fut.)", "NQ=F",
       ["nasdaq", "tech stocks"], "Nasdaq tech stocks", "indice"),

    # CRIPTOMONEDAS
    _a("Cripto", "Bitcoin", "BTC-USD",
       ["bitcoin", "btc"], "Bitcoin BTC", "cripto"),
    _a("Cripto", "Ethereum", "ETH-USD",
       ["ethereum", "ether", "eth"], "Ethereum ETH", "cripto"),
    _a("Cripto", "Solana", "SOL-USD",
       ["solana"], "Solana SOL", "cripto"),
    _a("Cripto", "XRP", "XRP-USD",
       ["xrp", "ripple"], "XRP Ripple", "cripto"),

    # DIVISAS
    _a("Divisas", "EUR/USD", "EURUSD=X",
       ["euro", "eur/usd", "eurusd"], "euro dollar EUR/USD", "divisa", -1),
    _a("Divisas", "GBP/USD", "GBPUSD=X",
       ["pound", "sterling", "gbp"], "pound sterling GBP/USD", "divisa", -1),
    _a("Divisas", "USD/JPY", "JPY=X",
       ["yen", "usd/jpy"], "dollar yen USD/JPY", "divisa", 1),
    _a("Divisas", "USD/DOP", "DOP=X",
       ["dominican peso", "peso dominicano", "usd/dop"],
       "peso dominicano dólar", "divisa", 1),

    # ETF
    _a("ETF", "Invesco Nasdaq-100", "QQQ",
       ["qqq", "nasdaq 100", "invesco"], "QQQ Invesco Nasdaq 100 ETF", "indice"),
    _a("ETF", "SPDR S&P 500", "SPY",
       ["spy", "s&p 500", "spdr"], "SPY SPDR S&P 500 ETF", "indice"),

    # ACCIONES SOLICITADAS
    _a("Acciones", "Advanced Micro Devices", "AMD",
       ["amd", "advanced micro devices"], "AMD semiconductor stock", "accion"),
    _a("Acciones", "Apple", "AAPL",
       ["apple", "aapl"], "Apple AAPL stock", "accion"),
    _a("Acciones", "Nvidia", "NVDA",
       ["nvidia", "nvda"], "Nvidia NVDA stock", "accion"),
    _a("Acciones", "Boeing", "BA",
       ["boeing", "ba"], "Boeing BA stock", "accion"),
    _a("Acciones", "Alibaba", "BABA",
       ["alibaba", "baba"], "Alibaba BABA stock", "accion"),
    _a("Acciones", "Microsoft", "MSFT",
       ["microsoft", "msft"], "Microsoft MSFT stock", "accion"),
    _a("Acciones", "Alphabet / Google", "GOOGL",
       ["google", "alphabet", "googl"], "Alphabet Google GOOGL stock", "accion"),
    _a("Acciones", "Meta Platforms", "META",
       ["meta", "facebook", "meta platforms"], "Meta Platforms META stock", "accion"),
    _a("Acciones", "Vistra", "VST",
       ["vistra", "vst"], "Vistra VST stock", "accion"),

    # OTROS ACTIVOS QUE YA EXISTÍAN
    _a("Acciones", "Tesla", "TSLA",
       ["tesla", "tsla"], "Tesla TSLA stock", "accion"),
    _a("Acciones", "Amazon", "AMZN",
       ["amazon", "amzn"], "Amazon AMZN stock", "accion"),
]


def personalizado(simbolo):
    s = simbolo.upper().strip()
    base = s.split("-")[0].split("=")[0].lower()

    clase = (
        "cripto" if s.endswith("-USD")
        else "divisa" if s.endswith("=X")
        else "energia" if s.endswith("=F")
        else "accion"
    )

    return _a(
        "Personalizado",
        s,
        s,
        [base],
        f"{base} {'crypto' if clase == 'cripto' else 'stock'}",
        clase,
    )


def buscar(simbolo, personalizados=()):
    s = simbolo.upper().strip()

    for activo in CATALOGO:
        if activo["simbolo"] == s:
            return activo

    if s in [p.upper().strip() for p in personalizados]:
        return personalizado(s)

    return None


def por_categoria(cat, personalizados=()):
    if cat == "Personalizado":
        return [personalizado(s) for s in personalizados]

    return [
        activo for activo in CATALOGO
        if activo["categoria"] == cat
    ]
