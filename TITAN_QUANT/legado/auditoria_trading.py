import ast
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HOME = Path.home()
PREFIX = os.environ.get("PREFIX", "")
ROOTFS = (Path(PREFIX) / "var/lib/proot-distro/installed-rootfs/ubuntu/root") if PREFIX else None
GOLD = next((c for c in (Path("/root/TITAN_GOLD_NEWS"), (ROOTFS / "TITAN_GOLD_NEWS") if ROOTFS else None) if c and c.exists()), None)
SALIDA = HOME / "auditoria_trading.txt"

TOKEN_RE = re.compile(r"\d{6,12}:[A-Za-z0-9_-]{30,}")
URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+")
IMP_RE = re.compile(r"^\s*(?:import|from)\s+([A-Za-z_]\w*)", re.M)
STR_RE = re.compile(r"[\"']([^\"'\n]{2,40})[\"']")
KV_RE = re.compile(r"[\"'](ticker|symbol|simbolo|empresa|company|nombre|name|activo|asset|instrumento)[\"']\s*[:=]\s*[\"']([^\"'\n]{1,60})[\"']", re.I)
CLAVE_RE = re.compile(r"(?i)\b(api[_-]?key|api[_-]?secret|secret[_-]?key|passw(?:or)?d|access[_-]?token|bot[_-]?token)\b\s*[=:]\s*[\"'][^\"'\n]{8,}[\"']")
ENV_RE = re.compile(r"(?:environ(?:\.get)?\(|environ\[|getenv\()\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']")
ORDEN_RE = re.compile(r"(?i)(create_order|place_order|submit_order|order_send|send_order|market_order|limit_order|new_order|close_position|open_position|live_trading|real_money|\.buy\(|\.sell\(|/api/v\d/order)")
SEGURO_RE = re.compile(r"(?i)(paper|demo|testnet|sandbox|simulaci|dry[_-]?run)")
RIESGO_RE = re.compile(r"(?i)(leverage|apalanc|stop[_-]?loss|take[_-]?profit|position[_-]?size)")
EXT = {".py", ".json", ".yaml", ".yml", ".txt", ".md", ".cfg", ".ini", ".toml", ".sh", ".csv"}
TG_METODOS = ["sendMessage", "getUpdates", "answerCallbackQuery", "editMessageText", "deleteMessage", "sendPhoto", "sendDocument", "callback_query", "inline_keyboard", "reply_markup", "CommandHandler", "CallbackQueryHandler"]

CLASES = [
    ("Telegram", ("telegram.org",)),
    ("Broker / bolsa (puede operar)", ("binance", "bybit", "kraken", "coinbase", "okx", "kucoin", "bitget", "alpaca", "oanda", "fxcm", "ig.com", "tradier", "tastytrade", "schwab", "robinhood", "interactivebrokers", "ibkr", "metaquotes", "capital.com", "deriv", "exness", "etoro")),
    ("Datos de mercado", ("yahoo", "stooq", "alphavantage", "finnhub", "polygon.io", "twelvedata", "tradingview", "fred.stlouisfed", "treasury.gov", "coingecko", "coinmarketcap", "tiingo", "quandl", "eodhd", "financialmodelingprep")),
    ("Noticias", ("news.google", "rss", "feeds.", "reuters", "bbc", "bloomberg", "cnbc", "marketwatch", "investing.com", "fxstreet", "forexlive", "newsapi", "gdeltproject", "finviz", "benzinga", "seekingalpha", "coindesk", "cointelegraph")),
    ("IA / servicios", ("openai", "anthropic", "googleapis", "huggingface", "groq", "deepseek")),
]
ORDEN_CLASES = ["Telegram", "Noticias", "Datos de mercado", "Broker / bolsa (puede operar)", "IA / servicios", "Otros"]
BROKER_LIBS = {"ccxt", "MetaTrader5", "alpaca_trade_api", "alpaca", "oandapyV20", "ib_insync", "binance", "pybit"}
LIBS = {"ccxt": "exchanges de cripto", "MetaTrader5": "MetaTrader 5 (broker)", "alpaca_trade_api": "broker Alpaca", "alpaca": "broker Alpaca", "oandapyV20": "broker OANDA", "ib_insync": "Interactive Brokers", "binance": "Binance", "pybit": "Bybit", "yfinance": "datos Yahoo", "pandas_ta": "indicadores", "talib": "indicadores", "backtrader": "backtesting", "vectorbt": "backtesting", "telegram": "Telegram", "telebot": "Telegram", "aiogram": "Telegram", "feedparser": "lectura RSS", "newsapi": "NewsAPI", "tweepy": "X/Twitter", "praw": "Reddit", "openai": "OpenAI", "anthropic": "Anthropic", "requests": "HTTP externo", "numpy": "cálculo", "pandas": "datos"}
TICK_PATS = [
    ("Cripto", re.compile(r"^[A-Z0-9]{2,10}(USDT|USDC|BUSD)$|^[A-Z]{2,6}-USD$")),
    ("Futuro / índice (formato Yahoo)", re.compile(r"^[A-Z]{1,5}=F$|^\^[A-Z]{2,6}$")),
    ("Par de divisas / metal", re.compile(r"^[A-Z]{3}/?[A-Z]{3}$")),
    ("Posible acción / ETF", re.compile(r"^[A-Z]{2,5}$")),
]
RUIDO = {"GET", "POST", "PUT", "HEAD", "HTML", "JSON", "CSV", "XML", "RSS", "URL", "API", "UTF", "OK", "ID", "UTC", "TZ", "TRUE", "FALSE", "NONE", "INFO", "DEBUG", "WARN", "ERROR", "NEWS", "BOT", "CHAT", "MENU", "TOKEN", "TXT", "PDF", "MD", "PY", "SH", "AM", "PM", "UP", "NO", "YES", "ALL", "LOG", "OS", "RE", "DB", "IP", "UI", "CPI", "PCE", "FED"}
SEGUROS = {"q", "query", "search", "keywords", "topic", "hl", "gl", "when", "ceid", "range", "interval", "s", "symbol", "symbols"}

SAL, RESULTADOS, HOSTS = [], [], set()
TOKENS = defaultdict(set)

def p(t=""):
    print(t)
    SAL.append(t)

def leer(f):
    try:
        return f.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""

def clase(host):
    h = host.lower()
    for nombre, claves in CLASES:
        if any(c in h for c in claves):
            return nombre
    return "Otros"

def url_corta(u):
    x = urlparse(u)
    q = parse_qs(x.query)
    partes = [k + "=" + (v[0][:60] if k.lower() in SEGUROS else "***") for k, v in q.items()]
    return TOKEN_RE.sub("***", x.netloc + x.path[:70] + ("?" + "&".join(partes) if partes else ""))

def archivos_de(d):
    out = []
    for f in sorted(d.rglob("*")):
        try:
            if f.is_file() and "__pycache__" not in f.parts and ".git" not in f.parts and f.stat().st_size < 3000000:
                out.append(f)
        except Exception:
            pass
    return out

def es_nucleo(f):
    n = f.name
    return n in {"titan_gold_news.py", "telegram_bot.py", "titan_bot.py", "titan_asistente.py", "resumen_noticias.py"} or n.startswith(("analisis_macro", "parche_", "auditoria"))

def tam(ruta):
    t = 0
    for f in ruta.rglob("*"):
        try:
            if f.is_file():
                t += f.stat().st_size
        except Exception:
            pass
    return f"{t / 1024:,.0f} KB"

def buscar():
    raices = [Path("/root"), HOME, Path("/sdcard"), Path("/storage")]
    if ROOTFS:
        raices.append(ROOTFS)
    cands, zips, vistos = [], [], set()
    for raiz in raices:
        if not raiz.exists():
            continue
        base = len(raiz.parts)
        for dp, dn, fn in os.walk(raiz):
            prof = len(Path(dp).parts) - base
            dn[:] = [d for d in dn if d not in ("proc", "sys", "dev", ".cache", ".git", "node_modules", "__pycache__")] if prof < 5 else []
            for d in dn:
                u = d.upper()
                if ("SISTEMA_INVERSION" in u or u.startswith("TITAN")) and "GOLD_NEWS" not in u:
                    try:
                        rr = (Path(dp) / d).resolve()
                    except Exception:
                        continue
                    if rr not in vistos:
                        vistos.add(rr)
                        cands.append(rr)
            for f in fn:
                l = f.lower()
                if l.endswith(".zip") and ("titan" in l or "sistema_inversion" in l):
                    try:
                        rr = (Path(dp) / f).resolve()
                    except Exception:
                        continue
                    if rr not in vistos:
                        vistos.add(rr)
                        zips.append(rr)
    cands.sort(key=lambda x: len(x.parts))
    final = []
    for c in cands:
        if not any(str(c).startswith(str(k) + os.sep) for k in final):
            final.append(c)
    return final, zips

def auditar(etiqueta, archivos, nota=""):
    p("")
    p("=" * 68)
    p("PROYECTO: " + etiqueta)
    p("=" * 68)
    if nota:
        p(nota)
    textos = {f: leer(f) for f in archivos if f.suffix.lower() in EXT or f.name.startswith(".env")}
    pys = {f: t for f, t in textos.items() if f.suffix == ".py"}
    R = {"nombre": etiqueta, "py": len(pys), "lineas": sum(len(t.splitlines()) for t in pys.values()),
         "telegram": False, "broker": False, "ordenes": 0, "tokens": 0}
    locales = {f.stem for f in pys}

    p("")
    p("--- 1. Archivos ---")
    tipos = Counter(f.suffix.lower() or f.name for f in archivos)
    p("Tipos: " + ", ".join(f"{k} x{v}" for k, v in tipos.most_common(10)))
    p(f"Archivos: {len(archivos)} · Python: {len(pys)} ({R['lineas']} líneas)")

    p("")
    p("--- 2. Módulos (Python) ---")
    externos = set()
    for f, t in sorted(pys.items(), key=lambda x: -len(x[1]))[:40]:
        try:
            ast.parse(t)
            sint = "OK"
        except SyntaxError as ex:
            sint = f"ERROR línea {ex.lineno}"
        mods = set(IMP_RE.findall(t))
        loc = sorted(m for m in mods if m in locales and m != f.stem)
        ext = sorted(m for m in mods if m not in locales and m not in sys.stdlib_module_names)
        externos.update(ext)
        nfun = len(re.findall(r"^\s*def ", t, re.M))
        ncls = len(re.findall(r"^class ", t, re.M))
        p(f"- {f.name}: {len(t.splitlines())} líneas, {nfun} funciones, {ncls} clases · sintaxis {sint}")
        if loc:
            p("    usa módulos locales: " + ", ".join(loc))
        if ext:
            p("    librerías externas: " + ", ".join(ext))

    p("")
    p("--- 3. Librerías externas ---")
    if externos:
        for m in sorted(externos):
            p(f"- {m}" + (f" → {LIBS[m]}" if m in LIBS else ""))
    else:
        p("Ninguna: solo librerías estándar de Python.")
    libs_broker = sorted(externos & BROKER_LIBS)

    p("")
    p("--- 4. Conexiones salientes (a dónde se conecta) ---")
    dom, http, urls = defaultdict(set), set(), defaultdict(set)
    for f, t in textos.items():
        for u in URL_RE.findall(t):
            u = u.rstrip(".,;")
            h = urlparse(u).netloc
            if not h or "{" in h or "%" in h:
                continue
            dom[h].add(f.name)
            urls[h].add(u)
            if u.startswith("http://"):
                http.add(h)
    por_clase = defaultdict(list)
    for h in sorted(dom):
        por_clase[clase(h)].append(h)
        HOSTS.add(h)
    for cl in ORDEN_CLASES:
        for h in por_clase.get(cl, []):
            p(f"- [{cl}] {h}  ← {', '.join(sorted(dom[h]))}" + ("  ⚠ sin cifrar (http)" if h in http else ""))
    if not dom:
        p("Ninguna dirección web encontrada.")
    R["broker"] = bool(por_clase.get("Broker / bolsa (puede operar)")) or bool(libs_broker)
    abre = any(re.search(r"\.(bind|listen|serve_forever)\(|HTTPServer", t) for t in pys.values())
    p("Puertos: " + ("⚠ el código abre un puerto de escucha" if abre else "no abre puertos (solo conexiones salientes)"))

    p("")
    p("--- 5. Telegram ---")
    usa = sorted({f.name for f, t in textos.items() if "api.telegram.org" in t})
    libs_tg = sorted({m for t in pys.values() for m in IMP_RE.findall(t) if m in ("telegram", "telebot", "aiogram", "pyrogram", "telethon")})
    if usa or libs_tg:
        R["telegram"] = True
        p("Se conecta desde: " + (", ".join(usa) or "librería") + ((" · librerías: " + ", ".join(libs_tg)) if libs_tg else ""))
        mets = sorted({m for t in textos.values() for m in TG_METODOS if m in t})
        p("Funciones usadas: " + (", ".join(mets) or "no identificadas"))
        envs = sorted({n for t in textos.values() for n in ENV_RE.findall(t) if re.search(r"(?i)token|telegram|chat", n)})
        p("Variables de entorno de Telegram: " + (", ".join(envs) if envs else "ninguna"))
        aut = any(re.search(r"chat_id", t) and re.search(r"(?i)autoriz|allowed|permitid|whitelist", t) for t in textos.values())
        p("¿Restringe quién puede usarlo? " + ("parece que sí (heurístico)" if aut else "no pude confirmarlo: conviene revisar que solo responda a tu chat"))
    else:
        p("No encontré conexión a Telegram.")

    p("")
    p("--- 6. Noticias que recopila ---")
    nots = [u for h in por_clase.get("Noticias", []) for u in sorted(urls[h])]
    if nots:
        for u in nots[:14]:
            p("- " + url_corta(u))
        if len(nots) > 14:
            p(f"  … y {len(nots) - 14} direcciones más")
    else:
        p("No encontré fuentes de noticias en el código.")
    kw = Counter()
    for f, t in pys.items():
        for k in ("feedparser", "xml.etree", "newsapi", "when:7d", "rss"):
            if k in t:
                kw[k] += 1
    if kw:
        p("Técnicas detectadas: " + ", ".join(sorted(kw)))

    p("")
    p("--- 7. Activos y empresas que menciona ---")
    conteo = defaultdict(Counter)
    kv = Counter()
    for f, t in textos.items():
        if f.suffix.lower() not in (".py", ".json", ".yaml", ".yml", ".txt", ".csv", ".toml", ".cfg", ".ini"):
            continue
        for s in STR_RE.findall(t):
            if s in RUIDO:
                continue
            for nom, rx in TICK_PATS:
                if rx.match(s):
                    conteo[nom][s] += 1
                    break
        for k, v in KV_RE.findall(t):
            kv[(k.lower(), v)] += 1
    hay = False
    for nom, _ in TICK_PATS:
        if conteo.get(nom):
            hay = True
            top = ", ".join(f"{s}({c})" for s, c in conteo[nom].most_common(25))
            p(f"- {nom}: {top}")
    if kv:
        hay = True
        p("- Valores declarados con clave tipo nombre/empresa/símbolo: " + ", ".join(f"{v} [{k}]" for (k, v), _ in kv.most_common(40)))
    if not hay:
        p("No encontré símbolos ni empresas escritos en el código.")
    p("Nota: es lo que está escrito en los archivos; puede incluir falsos positivos. Si el sistema obtiene sus listas de internet, no aparecen aquí.")

    p("")
    p("--- 8. ¿Opera automáticamente? ---")
    ords = []
    for f, t in pys.items():
        for i, l in enumerate(t.splitlines(), 1):
            m = ORDEN_RE.search(l)
            if m:
                ords.append((f.name, i, m.group(1)))
    R["ordenes"] = len(ords)
    seg = sum(len(SEGURO_RE.findall(t)) for t in pys.values())
    rie = sum(len(RIESGO_RE.findall(t)) for t in pys.values())
    for n, i, k in ords[:10]:
        p(f"- {n}:{i} → {k}")
    p(f"Funciones de órdenes: {len(ords)} · menciones de riesgo (stop, apalancamiento…): {rie} · menciones de demo/paper/testnet: {seg}")
    if R["broker"] and ords:
        p("⚠ POSIBLE OPERACIÓN AUTOMÁTICA: hay conexión a un broker/exchange y funciones de órdenes. Revisar antes de ejecutarlo.")
    elif ords:
        p("Hay funciones de órdenes, pero no vi conexión a un broker conocido (puede ser simulación o estar en otra ruta).")
    else:
        p("No encontré funciones de órdenes.")
    if seg:
        p("Menciona demo/paper/testnet: indicio de simulación, no garantía.")

    p("")
    p("--- 9. Secretos y permisos ---")
    claves, tk = [], []
    for f, t in textos.items():
        for i, l in enumerate(t.splitlines(), 1):
            m = CLAVE_RE.search(l)
            if m:
                claves.append(f"{f.name}:{i} ({m.group(1)})")
            for tok in TOKEN_RE.findall(l):
                TOKENS[tok].add(f.name)
                tk.append(f"{f.name}:{i}")
    R["tokens"] = len(tk)
    p("Claves o contraseñas escritas en el código: " + (", ".join(claves[:10]) if claves else "no encontradas"))
    p("Textos con forma de token de Telegram: " + (", ".join(tk[:10]) if tk else "ninguno"))
    for f in archivos:
        n = f.name.lower()
        if n.startswith(".env") or "token" in n or "secret" in n or n.startswith(".telegram"):
            modo = f.stat().st_mode & 0o777
            p(f"- {f.name}: permisos {oct(modo)[2:]}" + ("" if (modo & 0o077) == 0 else "  ⚠ legible por otros usuarios"))
    RESULTADOS.append(R)

def main():
    p("AUDITORÍA TITAN · " + datetime.now().strftime("%Y-%m-%d %H:%M") + " · SOLO LECTURA (no modifica ni borra nada)")
    cands, zips = buscar()
    p("")
    p("=== A. DÓNDE ESTÁ CADA COSA ===")
    p("Bot de noticias: " + (str(GOLD) if GOLD else "no encontré /root/TITAN_GOLD_NEWS (¿estás dentro de Ubuntu?)"))
    if cands:
        for c in cands:
            p(f"Sistema anterior (carpeta): {c} · {tam(c)} · modificada {datetime.fromtimestamp(c.stat().st_mtime):%Y-%m-%d}")
    else:
        p("Sistema anterior (carpeta): no encontré ninguna")
    for z in zips:
        try:
            with zipfile.ZipFile(z) as zf:
                malo = zf.testzip()
                p(f"Respaldo .zip: {z} · {z.stat().st_size / 1024:,.0f} KB · {len(zf.namelist())} archivos · integridad " + ("OK" if malo is None else "ERROR en " + malo))
        except Exception as ex:
            p(f"Respaldo .zip: {z} · no se pudo abrir ({type(ex).__name__})")
    if GOLD:
        todos = archivos_de(GOLD)
        nucleo = [f for f in todos if f.suffix != ".py" or es_nucleo(f)]
        heredado = [f for f in todos if f.suffix == ".py" and not es_nucleo(f)]
        auditar("BOT DE NOTICIAS (el que construimos aquí)", nucleo)
        if heredado:
            auditar("ARCHIVOS TITAN HEREDADOS en TITAN_GOLD_NEWS (no creados en esta conversación; probablemente del trabajo con ChatGPT)", heredado)
    for c in cands:
        auditar("SISTEMA ANTERIOR · " + c.name, archivos_de(c))
    if not cands and zips:
        zip_nuevo = max(zips, key=lambda x: x.stat().st_mtime)
        tmp = Path(tempfile.mkdtemp(prefix="titan_audit_"))
        try:
            with zipfile.ZipFile(zip_nuevo) as zf:
                zf.extractall(tmp)
            auditar("RESPALDO .ZIP (" + zip_nuevo.name + ", copia temporal)", archivos_de(tmp))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    p("")
    p("=== B. PRUEBA DE CONEXIÓN (no envía datos tuyos) ===")
    for h in sorted(HOSTS)[:30]:
        try:
            req = urllib.request.Request("https://" + h + "/", headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                est = f"responde ({r.status})"
        except urllib.error.HTTPError as ex:
            est = f"responde ({ex.code})"
        except Exception as ex:
            est = "sin respuesta (" + type(ex).__name__ + ")"
        p(f"- {h}: {est}")
    p("(Un 403 o 404 en la página raíz no significa caída: muchos servicios solo responden en rutas concretas.)")

    p("")
    p("=== C. TOKENS DE TELEGRAM ENCONTRADOS (nunca se imprimen) ===")
    for h in (HOME / ".bash_history", (ROOTFS / ".bash_history") if ROOTFS else None):
        if h and h.exists():
            for tok in TOKEN_RE.findall(leer(h)):
                TOKENS[tok].add("historial de comandos")
    activo = ""
    if GOLD and (GOLD / ".telegram_token").exists():
        activo = leer(GOLD / ".telegram_token").strip()
    if not TOKENS:
        p("No se encontraron tokens fuera del archivo protegido.")
    for i, (tok, donde) in enumerate(list(TOKENS.items())[:6], 1):
        try:
            with urllib.request.urlopen("https://api.telegram.org/bot" + tok + "/getMe", timeout=15) as r:
                d = json.loads(r.read().decode())
            est = "ACTIVO como @" + d["result"].get("username", "?") if d.get("ok") else "no válido"
        except urllib.error.HTTPError as ex:
            est = f"no válido o revocado (HTTP {ex.code})"
        except Exception as ex:
            est = "sin respuesta (" + type(ex).__name__ + ")"
        p(f"- Token #{i} (en: {', '.join(sorted(donde))}): {est} · ¿es el del bot actual? " + ("SÍ" if tok == activo else "no"))

    p("")
    p("=== D. RESUMEN COMPARATIVO ===")
    for r in RESULTADOS:
        p(f"- {r['nombre'][:60]}: {r['py']} archivos .py, {r['lineas']} líneas · Telegram: {'sí' if r['telegram'] else 'no'} · broker/exchange: {'sí' if r['broker'] else 'no'} · funciones de órdenes: {r['ordenes']} · tokens escritos en el código: {r['tokens']}")
    SALIDA.write_text("\n".join(SAL), encoding="utf-8")
    os.chmod(SALIDA, 0o600)
    print("\nInforme guardado en " + str(SALIDA))

if __name__ == "__main__":
    main()
