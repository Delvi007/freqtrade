"""Datos de mercado sintéticos y deterministas SOLO para pruebas (nunca se usan en producción)."""
import math
import random
import time
import zlib

SEG = {"1m": 60, "5m": 300, "15m": 900, "60m": 3600, "1d": 86400, "1wk": 604800}
N = {"5d": 120, "1mo": 500, "60d": 1200, "3mo": 1000, "6mo": 1400, "1y": 1700, "2y": 500, "5y": 1200, "10y": 2400, "max": 2400, "1d": 300}


def velas(simbolo, rango, intervalo, tendencia=None, ahora=None):
    paso = SEG.get(intervalo, 3600)
    n = N.get(rango, 600)
    if intervalo == "1d":
        n = {"1y": 252, "2y": 504, "5y": 1260, "10y": 2520}.get(rango, 252)
    rnd = random.Random(zlib.crc32(f"{simbolo}|{intervalo}".encode()))
    ahora = int(ahora or time.time())
    fin = ahora - ahora % paso - paso
    px = 50 + zlib.crc32(simbolo.encode()) % 900
    deriva = tendencia if tendencia is not None else (zlib.crc32(simbolo.encode()) % 7 - 3) * 0.0002
    out = []
    for i in range(n):
        t = fin - (n - 1 - i) * paso
        o = px
        ciclo = 0.002 * math.sin(i / 37)
        px = max(0.01, px * (1 + deriva + ciclo * 0.1 + rnd.gauss(0, 0.006)))
        h = max(o, px) * (1 + abs(rnd.gauss(0, 0.002)))
        l = min(o, px) * (1 - abs(rnd.gauss(0, 0.002)))
        out.append([t, o, h, l, px, 1000 + rnd.randint(0, 900)])
    return out, {"precio": px, "previo": out[-2][4], "bid": None, "ask": None, "zona": "UTC", "moneda": "USD"}


def noticias(a, horas=48, ahora=None):
    from datetime import datetime, timedelta, timezone
    base = datetime.now(timezone.utc)
    return [{"titulo": f"{a['nombre']} rallies on demand #{i}", "fuente": "Prueba", "fecha": (base - timedelta(hours=i * 3)).isoformat(),
             "enlace": f"https://ejemplo.test/{a['simbolo']}/{i}", "impacto": 1 if i % 3 else -1, "fuerza": 1, "motivo": "rally", "edad_h": i * 3}
            for i in range(6)]


def instalar():
    """Sustituye las fuentes de red por datos sintéticos en todo el proceso."""
    from titan_quant.motores import datos
    import agente
    import macro
    datos.PROVEEDOR_YAHOO = lambda s, r, i: velas(s, r, i)
    datos.limpiar_cache()
    agente.noticias_activo = noticias
    macro.escanear = lambda horas=24, cache_s=600, ahora_t=None: []
    macro.tasas = lambda: [{"nombre": "Rendimiento a 5 años (^FVX)", "nivel": 4.1, "cambio_pb": 2.0}]
    import chart_web
    chart_web._pedir = lambda s, r, i: velas(s, r, i)
    import quotes_web
    quotes_web._pedir = lambda s: {"precio": velas(s, "5d", "60m")[0][-1][4], "previo": velas(s, "5d", "60m")[0][-2][4]}
