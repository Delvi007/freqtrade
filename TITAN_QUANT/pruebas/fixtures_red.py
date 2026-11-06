"""Simula internet (Google News, Yahoo, Tesoro) SOLO para las pruebas. No se usa en producción."""
import os, urllib.error, urllib.request, json, zlib
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime
from xml.sax.saxutils import escape

class _Resp:
    def __init__(self, datos):
        self._d = datos if isinstance(datos, bytes) else datos.encode("utf-8")
    def read(self): return self._d
    def __enter__(self): return self
    def __exit__(self, *a): return False

def _rss(url):
    ahora = datetime.now(timezone.utc)
    from urllib.parse import unquote_plus
    q = unquote_plus(url.split("q=")[1].split("&")[0]).replace(" when:2d", "")
    nombre = q
    items = ""
    for i in range(8):
        f = format_datetime(ahora - timedelta(hours=3 * i + 1))
        items += (f"<item><title>{nombre} {'surges on strong demand' if i % 3 == 0 else 'falls as sell-off deepens' if i % 3 == 1 else 'steady ahead of data'} #{i}</title>"
                  f"<link>https://ejemplo.test/n/{zlib.crc32(q.encode())}-{i}</link>"
                  f"<description>&lt;p&gt;Strong dollar and rising yields weigh on gold; oil and inflation in focus {i}&lt;/p&gt;</description>"
                  f"<pubDate>{f}</pubDate><source>FuenteDePrueba</source></item>")
    return f'<?xml version="1.0"?><rss><channel>{items}</channel></rss>'

def _yahoo(url):
    import math, re
    ahora = int(datetime.now(timezone.utc).timestamp())
    rango = re.search(r"range=(\w+)", url).group(1)
    paso = 3600 if "interval=60m" in url else 86400
    n = {"1mo": 720, "5d": 120, "6mo": 126, "15d": 15}.get(rango, 120)
    ts = [ahora - paso * k for k in range(n, 0, -1)]
    base = 50.0 + (zlib.crc32(url.split("chart/")[1].split("?")[0].encode()) % 400)
    abre = [round(base * (1 + 0.004 * math.sin(i / 6) + 0.0004 * i), 4) for i in range(n)]
    cierra = [round(base * (1 + 0.004 * math.sin((i + 1) / 6) + 0.0004 * (i + 1)), 4) for i in range(n)]
    alto = [round(max(o, c) * 1.001, 4) for o, c in zip(abre, cierra)]
    bajo = [round(min(o, c) * 0.999, 4) for o, c in zip(abre, cierra)]
    vol = [int(1000 * (1 + 2 * ((t // 3600) % 24 in (8, 13, 14, 15)))) for t in ts]
    return json.dumps({"chart": {"result": [{"timestamp": ts, "indicators": {"quote": [
        {"open": abre, "close": cierra, "high": alto, "low": bajo, "volume": vol}]}}]}})

def _tesoro():
    hoy = datetime.now(timezone.utc)
    filas = ["Date,5 YR,7 YR,10 YR,20 YR,30 YR"]
    for i in range(10):
        d = hoy - timedelta(days=i)
        filas.append(f"{d.strftime('%m/%d/%Y')},2.1,2.3,{2.66 + 0.02 * i:.2f},2.7,2.8")
    return "\n".join(filas)

def install():
    def falso(req, *a, **k):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if os.environ.get("TITAN_FIXTURES") == "caida":
            raise urllib.error.URLError("sin red (simulado)")
        if "news.google.com" in url: return _Resp(_rss(url))
        if "finance.yahoo.com" in url: return _Resp(_yahoo(url))
        if "treasury.gov" in url: return _Resp(_tesoro())
        raise urllib.error.URLError("host no simulado: " + url)
    urllib.request.urlopen = falso
