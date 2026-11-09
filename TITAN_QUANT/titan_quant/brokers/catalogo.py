"""Matriz de brokers y plataformas (C2).

Verificación en vivo del 09/11/2026 (sonda HTTP desde este equipo):
  · «API responde (pide credenciales)» = el endpoint oficial de DEMO/paper existe y contesta 401/400 por falta de clave.
  · «datos públicos verificados» = el endpoint público devolvió precios reales sin cuenta.
  · «docs» = la página oficial de documentación responde 200.
La regulación y la disponibilidad para República Dominicana se indican como las DECLARA cada broker y deben confirmarse
con él antes de abrir cuenta (pueden cambiar; TITAN no puede comprobarlas automáticamente).

conector:
  implementado      conector TITAN escrito según la documentación oficial (prueba con credenciales DEMO pendiente)
  datos_publicos    conector TITAN verificado en vivo para datos de mercado públicos; la operativa requiere claves
  activo            conector en producción en TITAN (cTrader, IQ Option)
  no                sin conector (sin API pública, discontinuada, o requiere pasarela/licencia que no hay aquí)
"""

VERIFICACION = "2026-11-09"

B = [
    # ---------------------------------------------------------------- Estados Unidos
    {"id": "ibkr", "nombre": "Interactive Brokers", "region": "EE. UU. / global", "mercados": "acciones, ETF, opciones, futuros, forex, bonos, cripto",
     "apis": "TWS API (socket, SDK Python/Java/C++), Client Portal Web API (REST+WebSocket), FIX", "auth": "sesión de TWS/IB Gateway o pasarela Client Portal",
     "demo": "cuenta paper", "docs": "https://interactivebrokers.github.io/tws-api/", "regulacion": "SEC/FINRA (EE. UU.), FCA, CBI y otras según entidad",
     "requisitos": "TWS o IB Gateway en ejecución local; suscripciones de datos de mercado de pago para tiempo real", "verificado": "docs 200",
     "conector": "no", "motivo": "requiere TWS/IB Gateway instalado y sesión iniciada en el equipo (pasarela local); se integrará cuando esté instalado"},
    {"id": "tastytrade", "nombre": "tastytrade", "region": "EE. UU.", "mercados": "acciones, ETF, opciones, futuros, cripto",
     "apis": "REST + WebSocket de cuenta y de cotizaciones (DXLink)", "auth": "usuario/contraseña → token de sesión; OAuth para apps",
     "demo": "entorno de certificación (sandbox)", "docs": "https://developer.tastytrade.com/", "regulacion": "SEC/FINRA (broker-dealer), NFA",
     "requisitos": "cuenta tastytrade; sandbox con alta aparte", "verificado": "docs 200", "conector": "no", "motivo": "pendiente de credenciales de sandbox"},
    {"id": "tradestation", "nombre": "TradeStation", "region": "EE. UU.", "mercados": "acciones, ETF, opciones, futuros",
     "apis": "REST v3 + streaming HTTP", "auth": "OAuth 2.0 (clave de API aprobada por TradeStation)", "demo": "entorno SIM",
     "docs": "https://api.tradestation.com/docs/", "regulacion": "SEC/FINRA, CFTC/NFA", "requisitos": "solicitud y aprobación de clave de API",
     "verificado": "docs 200", "conector": "no", "motivo": "requiere clave de API aprobada"},
    {"id": "schwab", "nombre": "Charles Schwab (Trader API)", "region": "EE. UU.", "mercados": "acciones, ETF, opciones",
     "apis": "REST + streaming", "auth": "OAuth 2.0 con app aprobada en developer.schwab.com", "demo": "no ofrece sandbox de órdenes",
     "docs": "https://developer.schwab.com/", "regulacion": "SEC/FINRA", "requisitos": "cuenta Schwab y app aprobada; sin demo",
     "verificado": "docs 200", "conector": "no", "motivo": "sin entorno DEMO: no se puede probar la ejecución sin dinero real"},
    {"id": "alpaca", "nombre": "Alpaca", "region": "EE. UU.", "mercados": "acciones y ETF de EE. UU., cripto, opciones",
     "apis": "REST Trading API + Market Data API + WebSocket", "auth": "clave y secreto de API (cabeceras APCA-API-KEY-ID / APCA-API-SECRET-KEY)",
     "demo": "paper trading gratuito (paper-api.alpaca.markets)", "docs": "https://docs.alpaca.markets/", "regulacion": "SEC/FINRA (Alpaca Securities LLC)",
     "requisitos": "cuenta Alpaca (paper gratis)", "verificado": "docs 200 · API paper responde 401 (pide claves)", "conector": "implementado"},
    {"id": "tradier", "nombre": "Tradier", "region": "EE. UU.", "mercados": "acciones, ETF, opciones",
     "apis": "REST Brokerage API + streaming", "auth": "token Bearer de la cuenta", "demo": "sandbox (sandbox.tradier.com, datos diferidos)",
     "docs": "https://documentation.tradier.com/brokerage-api", "regulacion": "SEC/FINRA", "requisitos": "cuenta Tradier o sandbox de desarrollador",
     "verificado": "docs 200 · sandbox responde (reloj de mercado sin token)", "conector": "implementado"},
    {"id": "webull", "nombre": "Webull", "region": "EE. UU. / varios", "mercados": "acciones, ETF, opciones",
     "apis": "OpenAPI (requiere solicitud)", "auth": "clave de app aprobada", "demo": "no verificado", "docs": "https://developer.webull.com/",
     "regulacion": "SEC/FINRA (EE. UU.)", "requisitos": "solicitud de acceso a OpenAPI", "verificado": "la ruta de documentación probada devolvió 404",
     "conector": "no", "motivo": "documentación pública no verificable desde aquí"},
    {"id": "ninjatrader", "nombre": "NinjaTrader", "region": "EE. UU.", "mercados": "futuros",
     "apis": "NinjaScript (C#, dentro de la plataforma) y API de la plataforma web", "auth": "cuenta NinjaTrader", "demo": "simulador de la plataforma",
     "docs": "https://developer.ninjatrader.com/", "regulacion": "CFTC/NFA (FCM)", "requisitos": "plataforma NinjaTrader", "verificado": "docs 200",
     "conector": "no", "motivo": "la automatización oficial es NinjaScript dentro de la plataforma"},
    {"id": "tradovate", "nombre": "Tradovate", "region": "EE. UU.", "mercados": "futuros",
     "apis": "REST + WebSocket", "auth": "credenciales + clave de API (complemento de pago)", "demo": "entorno demo",
     "docs": "https://api.tradovate.com/", "regulacion": "CFTC/NFA", "requisitos": "suscripción al acceso API", "verificado": "docs 200",
     "conector": "no", "motivo": "requiere suscripción de pago al API"},
    {"id": "moomoo", "nombre": "Moomoo (Futu OpenAPI)", "region": "EE. UU. / Asia", "mercados": "acciones, ETF, opciones",
     "apis": "OpenAPI vía pasarela local OpenD (SDK Python)", "auth": "cuenta moomoo + OpenD", "demo": "paper trading",
     "docs": "https://openapi.moomoo.com/moomoo-api-doc/en/", "regulacion": "SEC/FINRA (Moomoo Financial Inc.)", "requisitos": "OpenD instalado",
     "verificado": "docs 200", "conector": "no", "motivo": "requiere pasarela OpenD instalada"},
    # ---------------------------------------------------------------- Europa y Reino Unido
    {"id": "saxo", "nombre": "Saxo Bank (OpenAPI)", "region": "Europa / global", "mercados": "acciones, ETF, forex, CFD, futuros, opciones, bonos",
     "apis": "REST + streaming (WebSocket)", "auth": "OAuth 2.0 (app registrada en developer.saxo)", "demo": "entorno SIM gratuito",
     "docs": "https://www.developer.saxo/openapi/learn", "regulacion": "Finanstilsynet (Dinamarca) y entidades locales", "requisitos": "registro de app; token de 24 h en SIM",
     "verificado": "docs 200 · API SIM responde 401 (pide token)", "conector": "no", "motivo": "siguiente en la cola (OAuth con app registrada)"},
    {"id": "ig", "nombre": "IG Group", "region": "Reino Unido / Europa", "mercados": "CFD, spread betting, forex, índices, acciones",
     "apis": "REST Trading API + Lightstreamer (streaming)", "auth": "clave de API + usuario/contraseña → tokens CST/X-SECURITY-TOKEN",
     "demo": "cuenta demo (demo-api.ig.com)", "docs": "https://labs.ig.com/rest-trading-api-reference", "regulacion": "FCA (Reino Unido) y otras",
     "requisitos": "cuenta IG y clave de API", "verificado": "API demo responde 400 «api-key-missing»", "conector": "no",
     "motivo": "siguiente en la cola (API verificada, falta implementar sesión CST)"},
    {"id": "oanda", "nombre": "OANDA", "region": "EE. UU. / Reino Unido / global", "mercados": "forex, CFD (metales, índices, materias primas según entidad)",
     "apis": "REST v20 + streaming HTTP", "auth": "token personal de API (Bearer)", "demo": "cuenta practice gratuita (api-fxpractice.oanda.com)",
     "docs": "https://developer.oanda.com/rest-live-v20/introduction/", "regulacion": "CFTC/NFA (EE. UU.), FCA (RU) y otras",
     "requisitos": "cuenta practice y token", "verificado": "docs 200 · API practice responde 401 (pide token)", "conector": "implementado"},
    {"id": "cmc", "nombre": "CMC Markets", "region": "Reino Unido / global", "mercados": "CFD, spread betting, forex",
     "apis": "no publica API minorista abierta (sí FIX institucional)", "auth": "—", "demo": "cuenta demo en plataforma", "docs": "https://www.cmcmarkets.com/",
     "regulacion": "FCA y otras", "requisitos": "acceso institucional", "verificado": "página de API probada: 404", "conector": "no", "motivo": "sin API minorista pública"},
    {"id": "xtb", "nombre": "XTB", "region": "Europa", "mercados": "CFD, forex, acciones", "apis": "xStation API — DISCONTINUADA",
     "auth": "—", "demo": "cuenta demo en plataforma", "docs": "http://developers.xstore.pro/", "regulacion": "KNF (Polonia), FCA y otras",
     "requisitos": "—", "verificado": "el dominio de la API ya no resuelve (DNS)", "conector": "no", "motivo": "XTB cerró su API pública"},
    {"id": "capital", "nombre": "Capital.com", "region": "Europa / global", "mercados": "CFD, forex, índices, cripto",
     "apis": "REST + WebSocket", "auth": "clave de API + identificador/contraseña → tokens CST/X-SECURITY-TOKEN", "demo": "cuenta demo (demo-api-capital.backend-capital.com)",
     "docs": "https://open-api.capital.com/", "regulacion": "FCA, CySEC y otras", "requisitos": "clave de API generada en la cuenta",
     "verificado": "docs 200 · API demo responde 400 «client.token» (pide credenciales)", "conector": "no", "motivo": "siguiente en la cola (API verificada)"},
    {"id": "swissquote", "nombre": "Swissquote", "region": "Suiza / Europa", "mercados": "acciones, forex, CFD",
     "apis": "FIX / APIs para clientes institucionales", "auth": "—", "demo": "—", "docs": "https://www.swissquote.com/",
     "regulacion": "FINMA", "requisitos": "acceso institucional", "verificado": "página de API probada: 404", "conector": "no", "motivo": "sin API minorista pública verificable"},
    {"id": "fxcm", "nombre": "FXCM", "region": "Reino Unido / global", "mercados": "forex, CFD",
     "apis": "REST/Socket (histórica) y FIX", "auth": "token", "demo": "cuenta demo", "docs": "https://www.fxcm.com/",
     "regulacion": "FCA y otras", "requisitos": "—", "verificado": "documentación de la API probada: 404", "conector": "no", "motivo": "documentación oficial no localizable hoy"},
    {"id": "trading212", "nombre": "Trading 212", "region": "Reino Unido / Europa", "mercados": "acciones, ETF (Invest/ISA)",
     "apis": "REST pública (beta)", "auth": "clave de API generada en la app", "demo": "cuenta practice (demo.trading212.com)",
     "docs": "https://t212public-api-docs.redoc.ly/", "regulacion": "FCA, CySEC y otras", "requisitos": "clave de API; límites de frecuencia estrictos",
     "verificado": "docs 200 · API demo responde 401 (pide clave)", "conector": "no", "motivo": "siguiente en la cola"},
    # ---------------------------------------------------------------- Criptomonedas
    {"id": "coinbase", "nombre": "Coinbase Advanced", "region": "EE. UU. / global", "mercados": "cripto (spot)",
     "apis": "REST Advanced Trade + WebSocket", "auth": "clave CDP (JWT firmado ES256) para endpoints privados", "demo": "no ofrece sandbox de Advanced Trade",
     "docs": "https://docs.cdp.coinbase.com/advanced-trade/docs/welcome", "regulacion": "FinCEN (MSB), licencias estatales; MiCA en la UE",
     "requisitos": "clave CDP para operar", "verificado": "docs 200 · datos públicos verificados (precio BTC-USD)", "conector": "datos_publicos"},
    {"id": "kraken", "nombre": "Kraken", "region": "EE. UU. / Europa / global", "mercados": "cripto (spot), futuros",
     "apis": "REST + WebSocket v2, FIX", "auth": "clave + firma HMAC-SHA512 (API-Key / API-Sign)", "demo": "solo futuros tiene entorno demo",
     "docs": "https://docs.kraken.com/api/", "regulacion": "FinCEN (MSB), FCA (registro cripto), MiCA en la UE",
     "requisitos": "clave de API con permisos", "verificado": "docs 200 · datos públicos verificados (ticker XBTUSD)", "conector": "datos_publicos"},
    # ---------------------------------------------------------------- Plataformas
    {"id": "ctrader", "nombre": "cTrader (Open API)", "region": "global (vía brokers cTrader)", "mercados": "forex, CFD (según broker)",
     "apis": "Open API (Protobuf/JSON sobre TCP/WebSocket)", "auth": "OAuth 2.0 (app Spotware)", "demo": "cuentas DEMO", "docs": "https://help.ctrader.com/open-api/",
     "regulacion": "la del broker cTrader elegido", "requisitos": "app en Spotware Open API", "verificado": "en producción en TITAN (DEMO)", "conector": "activo"},
    {"id": "iqoption", "nombre": "IQ Option", "region": "global (no EE. UU.)", "mercados": "opciones binarias/digitales, CFD",
     "apis": "SIN API oficial: TITAN usa una librería comunitaria", "auth": "usuario/contraseña", "demo": "cuenta PRACTICE",
     "docs": "—", "regulacion": "CySEC (IQ Option Europe) según entidad", "requisitos": "—", "verificado": "en producción en TITAN (PRACTICE)",
     "conector": "activo", "motivo": "no oficial: puede dejar de funcionar si IQ Option cambia su protocolo"},
    {"id": "mt5", "nombre": "MetaTrader 5", "region": "global (vía brokers MT5)", "mercados": "según broker",
     "apis": "paquete oficial MetaTrader5 para Python (solo Windows, terminal local) y MQL5", "auth": "login del terminal", "demo": "cuentas demo del broker",
     "docs": "https://www.mql5.com/en/docs/python_metatrader5", "regulacion": "la del broker MT5 elegido", "requisitos": "terminal MT5 instalado y abierto",
     "verificado": "docs 200", "conector": "no", "motivo": "requiere el terminal MT5 instalado en este equipo"},
    {"id": "mt4", "nombre": "MetaTrader 4", "region": "global (vía brokers MT4)", "mercados": "según broker",
     "apis": "solo MQL4 (asesores expertos dentro del terminal); sin API externa oficial", "auth": "—", "demo": "cuentas demo del broker",
     "docs": "https://www.metatrader4.com/", "regulacion": "la del broker MT4 elegido", "requisitos": "puente propio en MQL4", "verificado": "docs 200",
     "conector": "no", "motivo": "sin API externa oficial; integración solo con un EA puente en MQL4"},
]

RD = "Confirmar con el broker: la aceptación de residentes de República Dominicana depende de la entidad y puede cambiar."


def lista():
    return [{**b, "republica_dominicana": RD, "verificacion": VERIFICACION} for b in B]


def por_id(bid):
    return next((dict(b) for b in B if b["id"] == bid), None)
