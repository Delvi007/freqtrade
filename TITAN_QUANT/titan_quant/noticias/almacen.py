"""Base propia del centro de noticias: datos/noticias/noticias.db (separada de cuentas, backtests y titan_quant.db)."""
import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager

from .. import config
from . import catalogo

ESQUEMA = """
CREATE TABLE IF NOT EXISTS fuentes(id TEXT PRIMARY KEY, nombre TEXT NOT NULL, categoria TEXT NOT NULL, url TEXT NOT NULL,
    tipo TEXT NOT NULL DEFAULT 'rss', acceso TEXT NOT NULL, primaria INTEGER NOT NULL DEFAULT 0, idioma TEXT, frecuencia_min INTEGER NOT NULL,
    prioridad INTEGER NOT NULL DEFAULT 3, activo INTEGER NOT NULL DEFAULT 1, criterios TEXT NOT NULL, estrellas INTEGER NOT NULL,
    palabras_clave TEXT DEFAULT '', limite_hora INTEGER NOT NULL DEFAULT 12, nota TEXT DEFAULT '', api_clave_ref TEXT,
    personalizada INTEGER NOT NULL DEFAULT 0, creada_ts INTEGER, etag TEXT, last_modified TEXT,
    estado TEXT NOT NULL DEFAULT 'sin_probar', ultima_ok_ts INTEGER, ultimo_intento_ts INTEGER, ultimo_error TEXT,
    ultima_latencia_ms INTEGER, ultimo_item_ts INTEGER, items_ultima INTEGER, fallos_seguidos INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS pruebas(id INTEGER PRIMARY KEY AUTOINCREMENT, fuente_id TEXT NOT NULL, ts INTEGER NOT NULL, ok INTEGER NOT NULL,
    http INTEGER, items INTEGER, con_fecha INTEGER, edad_h REAL, latencia_ms INTEGER, duplicados INTEGER, detalle TEXT);
CREATE TABLE IF NOT EXISTS noticias(id TEXT PRIMARY KEY, fuente_id TEXT NOT NULL, titulo TEXT NOT NULL, resumen TEXT, enlace TEXT,
    autor TEXT, publicada_ts INTEGER, actualizada_ts INTEGER, recogida_ts INTEGER NOT NULL, fecha_estimada INTEGER NOT NULL DEFAULT 0,
    grupo_id TEXT NOT NULL, categoria TEXT, subcategoria TEXT, paises TEXT, activos TEXT, entidades TEXT, sentimiento REAL, tono_monetario REAL,
    rumor INTEGER NOT NULL DEFAULT 0, urgente INTEGER NOT NULL DEFAULT 0, sorpresa TEXT, impacto TEXT, puntuaciones TEXT, verificada INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS i_not_ts ON noticias(publicada_ts);
CREATE INDEX IF NOT EXISTS i_not_grupo ON noticias(grupo_id);
CREATE TABLE IF NOT EXISTS grupos(id TEXT PRIMARY KEY, titulo TEXT NOT NULL, tokens TEXT NOT NULL, primera_ts INTEGER NOT NULL, ultima_ts INTEGER NOT NULL,
    fuentes TEXT NOT NULL, n_fuentes INTEGER NOT NULL, contradiccion INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS i_grupo_ts ON grupos(ultima_ts);
CREATE TABLE IF NOT EXISTS calendario(id TEXT PRIMARY KEY, titulo TEXT NOT NULL, pais TEXT, moneda TEXT, ts INTEGER NOT NULL, impacto TEXT,
    prevision TEXT, anterior TEXT, publicado TEXT, tipo TEXT, fuente_id TEXT NOT NULL, actualizado_ts INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS i_cal_ts ON calendario(ts);
CREATE TABLE IF NOT EXISTS uso_motor(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, motor TEXT NOT NULL, activo TEXT, noticias TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ajustes(clave TEXT PRIMARY KEY, valor TEXT NOT NULL);
"""

_L = threading.local()
_INIT = {"ruta": None}
_LOCK = threading.Lock()


def ruta():
    return config.DATOS / "noticias" / "noticias.db"


def _con():
    r = str(ruta())
    c = getattr(_L, "c", None)
    if c is None or getattr(_L, "r", None) != r:
        ruta().parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(r, timeout=15, isolation_level=None, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA busy_timeout=15000")
        try:
            c.execute("PRAGMA journal_mode=WAL")
        except sqlite3.DatabaseError:
            pass
        try:
            os.chmod(r, 0o600)
        except OSError:
            pass
        _L.c, _L.r = c, r
    if _INIT["ruta"] != r:
        with _LOCK:
            if _INIT["ruta"] != r:
                c.executescript(ESQUEMA)
                _sembrar(c)
                _INIT["ruta"] = r
    return c


def cerrar():
    c = getattr(_L, "c", None)
    if c is not None:
        c.close()
        _L.c = None
    _INIT["ruta"] = None


@contextmanager
def tx():
    c = _con()
    c.execute("BEGIN IMMEDIATE")
    try:
        yield c
        c.execute("COMMIT")
    except BaseException:
        c.execute("ROLLBACK")
        raise


def q(sql, args=()):
    return [dict(r) for r in _con().execute(sql, args).fetchall()]


def q1(sql, args=()):
    r = _con().execute(sql, args).fetchone()
    return dict(r) if r else None


def _sembrar(c):
    """Inserta las fuentes del catálogo que aún no existen (nunca pisa la configuración del usuario)."""
    ahora = int(time.time())
    for s in catalogo.CATALOGO:
        if c.execute("SELECT 1 FROM fuentes WHERE id=?", (s["id"],)).fetchone():
            continue
        est = s["estrellas"] or catalogo.estrellas(s["criterios"], s["primaria"])
        estado = "no_disponible" if s["acceso"] in ("sin_rss_publico", "bloqueado") else "sin_probar"
        c.execute("""INSERT INTO fuentes(id,nombre,categoria,url,tipo,acceso,primaria,idioma,frecuencia_min,prioridad,activo,criterios,estrellas,
                     nota,personalizada,creada_ts,estado) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)""",
                  (s["id"], s["nombre"], s["categoria"], s["url"], s["tipo"], s["acceso"], int(s["primaria"]), s["idioma"], s["frecuencia_min"],
                   s["prioridad"], int(s["activo"]), json.dumps(s["criterios"]), est, s["nota"], ahora, estado))


def ajuste(clave, defecto=None):
    r = q1("SELECT valor FROM ajustes WHERE clave=?", (clave,))
    return json.loads(r["valor"]) if r else defecto


def guardar_ajuste(clave, valor):
    with tx() as c:
        c.execute("INSERT OR REPLACE INTO ajustes(clave,valor) VALUES(?,?)", (clave, json.dumps(valor)))
