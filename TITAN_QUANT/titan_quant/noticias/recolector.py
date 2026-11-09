"""Recopilación de fuentes: RSS 2.0, Atom, RDF y JSON de calendario.

Reglas de cortesía y seguridad:
    · frecuencia mínima por fuente (≥ 5 min) y separación mínima entre peticiones al mismo servidor
    · petición condicional (ETag / If-Modified-Since): si no hay cambios, el servidor responde 304 y no se descarga nada
    · robots.txt consultado y respetado (caché 24 h); límite de peticiones por hora configurable por fuente
    · reintentos con espera creciente; tras fallos seguidos la fuente pasa a «degradada»/«desconectada» (no se insiste)
    · solo http/https hacia servidores públicos (nada de localhost ni redes privadas)
    · el contenido es DATO: se limpia el HTML, se recorta el resumen (≤ 400 caracteres) y nunca se ejecuta ni se obedece
"""
import email.utils
import hashlib
import html
import ipaddress
import json
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from . import almacen, analisis

UA = "TITAN-QUANT/7.2 (news-intelligence; RSS reader; respectful polling)"
TIMEOUT = 20
MAX_BYTES = 4_000_000
FRECUENCIA_MIN = 5
SEPARACION_HOST_S = 2.0
RESUMEN_MAX = 400
VENTANA_DEDUPE_H = 48
FECHA_DESCONOCIDA_S = 30 * 86400
UMBRAL_DEDUPE = 0.55
EDAD_MAX_H = {"analisis": 24 * 10, "medio": 72, "cripto": 72, "banco_central": 24 * 45, "estadistica": 24 * 30, "regulador": 24 * 45, "organismo": 24 * 60,
              "mercado": 24 * 30, "calendario": 24 * 8}
_HOSTS = {}
_ROBOTS = {}
_L = threading.Lock()


def _ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())     # algunos servidores (BCE, Eurostat) no envían la cadena completa
    except Exception:
        return ssl.create_default_context()


def url_permitida(url):
    """Solo http(s) a servidores públicos: evita que una fuente configurada apunte a la red local (SSRF)."""
    p = urllib.parse.urlparse(str(url or ""))
    if p.scheme not in ("http", "https") or not p.hostname:
        return False, "solo se admiten URL http:// o https://"
    host = p.hostname.lower()
    if host in ("localhost",) or host.endswith(".local") or host.endswith(".localhost"):
        return False, "no se admiten direcciones locales"
    try:
        for info in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False, "la URL apunta a una red privada o local"
    except socket.gaierror:
        return False, "el nombre del servidor no existe"
    return True, ""


def _robots_ok(url):
    p = urllib.parse.urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    ent = _ROBOTS.get(base)
    if ent is None or time.time() - ent[0] > 86400:
        rp = urllib.robotparser.RobotFileParser()
        try:
            req = urllib.request.Request(base + "/robots.txt", headers={"User-Agent": UA})
            txt = urllib.request.urlopen(req, timeout=10, context=_ctx()).read(500_000).decode("utf-8", "replace")
            rp.parse(txt.splitlines())
        except Exception:
            rp = None                         # sin robots.txt accesible: se permite (norma habitual)
        ent = _ROBOTS[base] = (time.time(), rp)
    rp = ent[1]
    return True if rp is None else rp.can_fetch(UA, url)


def _esperar_host(url):
    host = urllib.parse.urlparse(url).netloc
    with _L:
        espera = _HOSTS.get(host, 0) + SEPARACION_HOST_S - time.time()
        _HOSTS[host] = max(time.time(), _HOSTS.get(host, 0) + SEPARACION_HOST_S)
    if espera > 0:
        time.sleep(espera)


def descargar(url, etag=None, modificado=None, abrir=None):
    """(estado_http, bytes|None, cabeceras). 304 = sin cambios."""
    cab = {"User-Agent": UA, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, application/json;q=0.9, */*;q=0.5"}
    if etag:
        cab["If-None-Match"] = etag
    if modificado:
        cab["If-Modified-Since"] = modificado
    req = urllib.request.Request(url, headers=cab)
    try:
        r = (abrir or (lambda rq: urllib.request.urlopen(rq, timeout=TIMEOUT, context=_ctx())))(req)
        return getattr(r, "status", 200), r.read(MAX_BYTES), dict(getattr(r, "headers", {}) or {})
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return 304, None, dict(e.headers or {})
        raise


# ----------------------------------------------------------------------------------------------- análisis XML
def _texto(x):
    t = html.unescape(re.sub(r"<[^>]+>", " ", str(x or "")))
    return re.sub(r"\s+", " ", t).strip()


def fecha(t):
    if not t:
        return None
    t = str(t).strip()
    try:
        d = email.utils.parsedate_to_datetime(t)
    except Exception:
        d = None
    if d is None:
        try:
            d = datetime.fromisoformat(t.replace("Z", "+00:00"))
        except Exception:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return int(d.timestamp())


def _hijo(e, *nombres):
    for n in nombres:
        for c in e:
            tag = c.tag.split("}", 1)[-1].lower()
            if tag == n:
                return c
    return None


def _items_xml(b):
    root = ET.fromstring(b)
    items = [e for e in root.iter() if e.tag.split("}", 1)[-1].lower() in ("item", "entry")]
    out = []
    for it in items:
        tit = _hijo(it, "title")
        link = _hijo(it, "link")
        enlace = (link.get("href") if link is not None and link.get("href") else (link.text if link is not None else None))
        desc = _hijo(it, "description", "summary", "content", "encoded")
        aut = _hijo(it, "author", "creator")
        if aut is not None and len(aut):
            nombre = _hijo(aut, "name")
            aut = nombre if nombre is not None else aut
        pub = _hijo(it, "pubdate", "published", "date", "issued")
        act = _hijo(it, "updated", "modified")
        guid = _hijo(it, "guid", "id")
        out.append({"titulo": _texto(tit.text if tit is not None else ""), "enlace": (enlace or "").strip(), "resumen": _texto(desc.text if desc is not None else ""),
                    "autor": _texto(aut.text if aut is not None else "") or None, "publicada": fecha(pub.text if pub is not None else None),
                    "actualizada": fecha(act.text if act is not None else None), "guid": (guid.text or "").strip() if guid is not None else None})
    return out


def _items_tolerante(b):
    """Para XML mal formado (p. ej. caracteres no válidos): extrae <item>/<entry> con expresiones regulares."""
    t = b.decode("utf-8", "replace")
    out = []
    for m in re.finditer(r"<(item|entry)\b(.*?)</\1>", t, re.S | re.I):
        s = m.group(2)

        def campo(*tags):
            for tg in tags:
                x = re.search(rf"<{tg}\b[^>]*>(.*?)</{tg}>", s, re.S | re.I)
                if x:
                    v = re.sub(r"^<!\[CDATA\[(.*)\]\]>$", r"\1", x.group(1).strip(), flags=re.S)
                    return v
            return None
        href = re.search(r"<link\b[^>]*href=\"([^\"]+)\"", s, re.I)
        out.append({"titulo": _texto(campo("title")), "enlace": (href.group(1) if href else _texto(campo("link")) or ""),
                    "resumen": _texto(campo("description", "summary", "content")), "autor": _texto(campo("author", "dc:creator")) or None,
                    "publicada": fecha(campo("pubDate", "published", "dc:date")), "actualizada": fecha(campo("updated")), "guid": _texto(campo("guid", "id"))})
    return out


def items(b):
    try:
        return _items_xml(b), "xml"
    except ET.ParseError:
        return _items_tolerante(b), "tolerante"


# ----------------------------------------------------------------------------------------------- ingesta
def _id(fuente_id, it):
    base = it.get("guid") or it.get("enlace") or it.get("titulo")
    return hashlib.sha1(f"{fuente_id}|{base}".encode("utf-8", "replace")).hexdigest()[:20]


def _grupo(c, titulo, ts, fuente_id, sent):
    """Deduplicación entre fuentes: mismo acontecimiento si el titular coincide ≥ 55 % (Jaccard) en 48 h.
    Conserva todas las fuentes que lo confirman y marca contradicción si el sentimiento se opone con claridad."""
    tk = analisis.tokens(titulo)
    mejor, sim = None, 0.0
    for g in c.execute("SELECT * FROM grupos WHERE ultima_ts>=? ORDER BY ultima_ts DESC LIMIT 800", (ts - VENTANA_DEDUPE_H * 3600,)).fetchall():
        s = analisis.similitud(tk, set(json.loads(g["tokens"])))
        if s > sim:
            mejor, sim = g, s
    if mejor is not None and sim >= UMBRAL_DEDUPE:
        fuentes = set(json.loads(mejor["fuentes"])) | {fuente_id}
        contra = mejor["contradiccion"]
        if abs(sent) >= 0.4:
            otros = [r["sentimiento"] for r in c.execute("SELECT sentimiento FROM noticias WHERE grupo_id=?", (mejor["id"],)).fetchall()]
            if any(o is not None and abs(o) >= 0.4 and (o > 0) != (sent > 0) for o in otros):
                contra = 1
        c.execute("UPDATE grupos SET ultima_ts=MAX(ultima_ts,?), fuentes=?, n_fuentes=?, contradiccion=? WHERE id=?",
                  (ts, json.dumps(sorted(fuentes)), len(fuentes), contra, mejor["id"]))
        return mejor["id"], len(fuentes), True
    gid = hashlib.sha1(f"{titulo}|{ts}".encode("utf-8", "replace")).hexdigest()[:16]
    c.execute("INSERT OR IGNORE INTO grupos(id,titulo,tokens,primera_ts,ultima_ts,fuentes,n_fuentes,contradiccion) VALUES(?,?,?,?,?,?,1,0)",
              (gid, titulo[:300], json.dumps(sorted(tk)), ts, ts, json.dumps([fuente_id])))
    return gid, 1, False


def ingerir(fuente, lista, ahora=None):
    """Guarda las noticias nuevas analizadas. Devuelve {'nuevas', 'duplicadas', 'repetidas_otra_fuente'}."""
    ahora = int(ahora or time.time())
    nuevas = dup = conf = 0
    palabras = [p.strip().lower() for p in (fuente.get("palabras_clave") or "").split(",") if p.strip()]
    with almacen.tx() as c:
        primera_carga = c.execute("SELECT 1 FROM noticias WHERE fuente_id=? LIMIT 1", (fuente["id"],)).fetchone() is None
        for it in lista:
            titulo = (it.get("titulo") or "").strip()[:400]
            if not titulo:
                continue
            nid = _id(fuente["id"], it)
            if c.execute("SELECT 1 FROM noticias WHERE id=?", (nid,)).fetchone():
                dup += 1
                continue
            resumen = (it.get("resumen") or "")[:RESUMEN_MAX]
            if palabras and not any(p in analisis.normal(titulo + " " + resumen) for p in palabras):
                continue
            pub = it.get("publicada")
            estimada = 0
            if not pub or pub > ahora + 3600:
                # Sin fecha: en la PRIMERA carga son publicaciones antiguas de antigüedad desconocida (no se presentan como
                # recientes: estimada=2, fuera de las vistas de 72 h); después, la hora de recepción es una buena aproximación.
                pub, estimada = (ahora - FECHA_DESCONOCIDA_S, 2) if primera_carga else (ahora, 1)
            sent = analisis.sentimiento(titulo + ". " + resumen)
            gid, n_fuentes, repetida = _grupo(c, titulo, pub, fuente["id"], sent)
            conf += int(repetida)
            an = analisis.analizar(titulo, resumen, fuente, n_fuentes, (ahora - pub) / 3600)
            c.execute("""INSERT INTO noticias(id,fuente_id,titulo,resumen,enlace,autor,publicada_ts,actualizada_ts,recogida_ts,fecha_estimada,grupo_id,
                         categoria,subcategoria,paises,activos,entidades,sentimiento,tono_monetario,rumor,urgente,sorpresa,impacto,puntuaciones,verificada)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (nid, fuente["id"], titulo, resumen, (it.get("enlace") or "")[:600], (it.get("autor") or None), pub, it.get("actualizada"), ahora, estimada,
                       gid, an["categoria"], ",".join(an["subcategorias"]), json.dumps(an["paises"]), json.dumps(analisis.activos_de(an)),
                       json.dumps(an["entidades"]), an["sentimiento"], an["tono_monetario"], int(an["rumor"]), int(an["urgente"]),
                       json.dumps(an["sorpresa"]) if an["sorpresa"] else None, json.dumps(an["impacto"]), json.dumps(an["puntuaciones"]), int(an["verificada"])))
            if repetida:   # la confirmación por otra fuente sube la verificación de TODAS las noticias del grupo
                c.execute("UPDATE noticias SET verificada=1 WHERE grupo_id=? AND rumor=0", (gid,))
            nuevas += 1
    return {"nuevas": nuevas, "duplicadas": dup, "confirmadas_por_otra_fuente": conf}


def reanalizar():
    """Recalcula el análisis de TODAS las noticias guardadas con las reglas actuales (tras mejorar léxicos o entidades)."""
    fuentes = {f["id"]: f for f in almacen.q("SELECT * FROM fuentes")}
    n = 0
    with almacen.tx() as c:
        for r in c.execute("SELECT n.id, n.fuente_id, n.titulo, n.resumen, n.publicada_ts, n.recogida_ts, g.n_fuentes FROM noticias n "
                           "JOIN grupos g ON g.id=n.grupo_id").fetchall():
            f = fuentes.get(r["fuente_id"]) or {"id": r["fuente_id"], "estrellas": 3, "primaria": 0}
            an = analisis.analizar(r["titulo"], r["resumen"], f, r["n_fuentes"], (r["recogida_ts"] - r["publicada_ts"]) / 3600)
            c.execute("""UPDATE noticias SET categoria=?, subcategoria=?, paises=?, activos=?, entidades=?, sentimiento=?, tono_monetario=?, rumor=?,
                         urgente=?, sorpresa=?, impacto=?, puntuaciones=?, verificada=CASE WHEN ? THEN 1 ELSE verificada END WHERE id=?""",
                      (an["categoria"], ",".join(an["subcategorias"]), json.dumps(an["paises"]), json.dumps(analisis.activos_de(an)),
                       json.dumps(an["entidades"]), an["sentimiento"], an["tono_monetario"], int(an["rumor"]), int(an["urgente"]),
                       json.dumps(an["sorpresa"]) if an["sorpresa"] else None, json.dumps(an["impacto"]), json.dumps(an["puntuaciones"]),
                       int(an["verificada"]), r["id"]))
            n += 1
        _migrar_fechas(c)
        c.execute("INSERT OR REPLACE INTO ajustes(clave,valor) VALUES('version_analisis',?)", (json.dumps(analisis.VERSION),))
    return n


def _migrar_fechas(c):
    """Noticias sin fecha de la carga inicial de cada fuente → «fecha no publicada» (no recientes)."""
    c.execute(f"""UPDATE noticias SET publicada_ts=recogida_ts-{FECHA_DESCONOCIDA_S}, fecha_estimada=2 WHERE fecha_estimada=1
                 AND recogida_ts=(SELECT MIN(n2.recogida_ts) FROM noticias n2 WHERE n2.fuente_id=noticias.fuente_id)""")


def reanalizar_si_cambio():
    if almacen.ajuste("version_analisis") != analisis.VERSION and almacen.q1("SELECT 1 FROM noticias LIMIT 1"):
        return reanalizar()
    return 0


# ----------------------------------------------------------------------------------------------- recogida y prueba
def recoger(fuente, abrir=None, ahora=None, forzar=False):
    """Recoge una fuente y registra la prueba. Una fuente queda 'conectada' solo si responde, entrega elementos con
    titular y, cuando traen fecha, alguno es reciente para su categoría."""
    from . import calendario
    ahora = int(ahora or time.time())
    if fuente["acceso"] in ("sin_rss_publico", "bloqueado"):
        return {"ok": False, "detalle": "fuente no disponible: " + (fuente.get("nota") or fuente["acceso"])}
    ok_url, motivo = url_permitida(fuente["url"]) if abrir is None else (True, "")
    t0 = time.time()
    res = {"ok": False, "http": None, "items": 0, "con_fecha": 0, "edad_h": None, "duplicados": 0, "detalle": ""}
    try:
        if not ok_url:
            raise ValueError(motivo)
        if abrir is None and not _robots_ok(fuente["url"]):
            raise PermissionError("robots.txt del sitio no permite esta ruta a lectores automáticos")
        hechas = almacen.q1("SELECT COUNT(*) n FROM pruebas WHERE fuente_id=? AND ts>?", (fuente["id"], ahora - 3600))["n"]
        if not forzar and hechas >= int(fuente.get("limite_hora") or 12):
            return {"ok": False, "detalle": "límite de consultas por hora alcanzado"}
        ultimo = None
        for intento in range(3):
            try:
                if abrir is None:
                    _esperar_host(fuente["url"])
                http, cuerpo, cab = descargar(fuente["url"], None if forzar else fuente.get("etag"), None if forzar else fuente.get("last_modified"), abrir)
                break
            except (urllib.error.URLError, TimeoutError, ConnectionError, socket.timeout) as e:
                ultimo = e
                if isinstance(e, urllib.error.HTTPError) and e.code in (401, 403, 404, 410):
                    raise
                if abrir is None:
                    time.sleep(2 * (intento + 1))
        else:
            raise ultimo
        res["http"] = http
        if http == 304:
            res.update(ok=True, detalle="sin cambios (304)")
            nuevas = {"nuevas": 0}
        elif fuente["tipo"] == "calendario":
            n = calendario.ingerir(fuente, json.loads(cuerpo), ahora)
            res.update(ok=n > 0, items=n, con_fecha=n, detalle=f"{n} eventos de calendario")
            nuevas = {"nuevas": n}
        else:
            lista, modo = items(cuerpo)
            lista = [x for x in lista if x.get("titulo")]
            fechas = [x["publicada"] for x in lista if x.get("publicada")]
            edad = (ahora - max(fechas)) / 3600 if fechas else None
            limite = EDAD_MAX_H.get(fuente["categoria"], 24 * 30)
            res.update(items=len(lista), con_fecha=len(fechas), edad_h=round(edad, 2) if edad is not None else None)
            if not lista:
                raise ValueError("la respuesta no contiene elementos con titular (¿no es un RSS/Atom?)")
            nuevas = ingerir(fuente, lista, ahora)
            res["duplicados"] = nuevas["duplicadas"]
            reciente = edad is None or edad <= limite
            res["ok"] = reciente
            res["detalle"] = (f"{len(lista)} elementos ({modo}); {nuevas['nuevas']} nuevas, {nuevas['duplicadas']} ya guardadas, "
                              f"{nuevas['confirmadas_por_otra_fuente']} confirman noticias de otra fuente"
                              + ("" if fechas else "; sin fechas: se usa la hora de recepción")
                              + ("" if reciente else f"; lo más reciente tiene {edad:.0f} h (máx {limite} h): no se considera al día"))
        cab_l = {k.lower(): v for k, v in (cab or {}).items()}
        etag, lm = cab_l.get("etag"), cab_l.get("last-modified")
    except Exception as e:
        res["detalle"] = f"{type(e).__name__}: {str(e)[:200]}"
        etag = lm = None
        nuevas = {"nuevas": 0}
    lat = int((time.time() - t0) * 1000)
    with almacen.tx() as c:
        c.execute("INSERT INTO pruebas(fuente_id,ts,ok,http,items,con_fecha,edad_h,latencia_ms,duplicados,detalle) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (fuente["id"], ahora, int(res["ok"]), res["http"], res["items"], res["con_fecha"], res["edad_h"], lat, res["duplicados"], res["detalle"]))
        fallos = 0 if res["ok"] else int(fuente.get("fallos_seguidos") or 0) + 1
        estado = "conectada" if res["ok"] else ("degradada" if fallos < 3 and fuente.get("ultima_ok_ts") else "desconectada")
        c.execute("""UPDATE fuentes SET estado=?, ultimo_intento_ts=?, ultimo_error=?, ultima_latencia_ms=?, fallos_seguidos=?,
                     ultima_ok_ts=CASE WHEN ? THEN ? ELSE ultima_ok_ts END, items_ultima=?, ultimo_item_ts=COALESCE(?, ultimo_item_ts),
                     etag=COALESCE(?, etag), last_modified=COALESCE(?, last_modified) WHERE id=?""",
                  (estado, ahora, None if res["ok"] else res["detalle"], lat, fallos, int(res["ok"]), ahora, res["items"],
                   int(ahora - res["edad_h"] * 3600) if res["edad_h"] is not None else None, etag, lm, fuente["id"]))
    res.update(latencia_ms=lat, estado=estado, nuevas=nuevas.get("nuevas", 0))
    return res


def pendientes(ahora=None):
    ahora = int(ahora or time.time())
    out = []
    for f in almacen.q("SELECT * FROM fuentes WHERE activo=1 AND acceso NOT IN ('sin_rss_publico','bloqueado') ORDER BY prioridad, id"):
        freq = max(FRECUENCIA_MIN, int(f["frecuencia_min"] or 15)) * 60
        espera = freq * min(8, 2 ** max(0, int(f["fallos_seguidos"] or 0) - 2)) if (f["fallos_seguidos"] or 0) >= 3 else freq
        if not f["ultimo_intento_ts"] or ahora - f["ultimo_intento_ts"] >= espera:
            out.append(f)
    return out


# ----------------------------------------------------------------------------------------------- hilo de fondo
ESTADO = {"vivo": False, "rondas": 0, "ultima_ronda_ts": None, "ultima_duracion_s": None, "error": None, "recogidas": 0}
_PARAR = threading.Event()


def alertar(ahora=None):
    """Alertas en la campana (y Telegram según preferencias): eventos de calendario en la ventana de aviso y noticias
    URGENTES y VERIFICADAS de alto impacto. Sin duplicados (clave por evento / acontecimiento)."""
    from .. import alertas, db
    from . import calendario
    ahora = int(ahora or time.time())
    usuarios = [u["id"] for u in db.q("SELECT id FROM usuarios")]
    n = 0
    for e in calendario.alertas_proximas(ahora):
        mins = int((e["ts"] - ahora) / 60)
        for uid in usuarios:
            n += bool(alertas.crear(uid, "macro", f"{e['moneda']} · {e['titulo']}", "alta" if e["impacto"] == "alto" else "media",
                                    justificacion=(f"en {mins} min" if mins >= 0 else f"hace {-mins} min") + f" · impacto {e['impacto']} · previsión "
                                    f"{e['prevision'] or '—'} · anterior {e['anterior'] or '—'} (calendario, fuente secundaria)",
                                    clave_dedupe=f"cal|{e['id']}"))
    for r in almacen.q("""SELECT n.titulo, n.grupo_id, n.enlace, f.nombre fuente, n.puntuaciones FROM noticias n JOIN fuentes f ON f.id=n.fuente_id
                          WHERE n.urgente=1 AND n.verificada=1 AND n.recogida_ts>=?""", (ahora - 900,)):
        if json.loads(r["puntuaciones"]).get("impacto_potencial", 0) < 60:
            continue
        for uid in usuarios:
            n += bool(alertas.crear(uid, "noticia", r["titulo"][:140], "alta", justificacion=f"{r['fuente']} · noticia urgente verificada · {r['enlace'] or ''}",
                                    clave_dedupe=f"not|{r['grupo_id']}"))
    return n


def ronda(hilos=4):
    import concurrent.futures as cf
    t0 = time.time()
    lista = pendientes()
    with cf.ThreadPoolExecutor(max_workers=hilos, thread_name_prefix="titan-noticias") as ex:
        list(ex.map(lambda f: recoger(f), lista))
    for paso in ("oficiales", "alertas"):
        try:
            if paso == "oficiales":
                from . import oficiales
                oficiales.actualizar_si_toca()
            else:
                alertar()
        except Exception as e:
            ESTADO["error"] = f"{paso}: {type(e).__name__}: {e}"[:300]
    ESTADO.update(rondas=ESTADO["rondas"] + 1, ultima_ronda_ts=int(time.time()), ultima_duracion_s=round(time.time() - t0, 1),
                  recogidas=ESTADO["recogidas"] + len(lista))
    return len(lista)


def _bucle():
    ESTADO["vivo"] = True
    try:
        reanalizar_si_cambio()
    except Exception as e:
        ESTADO["error"] = f"reanálisis: {type(e).__name__}: {e}"[:300]
    while not _PARAR.is_set():
        try:
            ronda()
            ESTADO["error"] = None
        except Exception as e:
            ESTADO["error"] = f"{type(e).__name__}: {e}"[:300]
        _PARAR.wait(60)
    ESTADO["vivo"] = False


def iniciar():
    if ESTADO["vivo"]:
        return
    _PARAR.clear()
    threading.Thread(target=_bucle, name="titan-noticias", daemon=True).start()


def detener():
    _PARAR.set()
