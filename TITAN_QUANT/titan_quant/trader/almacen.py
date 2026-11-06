"""Bases de datos SEPARADAS por modalidad de operación, y base de CONOCIMIENTO compartida.

    datos/cuentas/simulacion.db   operaciones, decisiones, estado del bot y eventos del broker de SIMULACIÓN
    datos/cuentas/demo.db         … de la cuenta DEMO
    datos/cuentas/real.db         … de la cuenta REAL (LIVE)
    datos/conocimiento.db         lo único compartido: resultados normalizados (R) por estrategia e instrumento

Las bases de cuenta no se consultan entre sí: una consulta de la demo nunca puede leer filas de la real.
El conocimiento solo guarda R (resultado / riesgo), sin importes, saldos, IDs de cuenta ni de posición.
El Laboratorio de Aprendizaje (titan_lab.db) y los modelos de los motores también son comunes a todas las cuentas.
"""
import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager

from .. import config, db

MODALIDADES = ("simulacion", "demo", "real")
_LOCAL = threading.local()
_MIGRADAS = set()
_L = threading.RLock()

ESQUEMA_CUENTA = """
CREATE TABLE IF NOT EXISTS bot_estado(
    usuario_id INTEGER PRIMARY KEY,
    estado TEXT NOT NULL DEFAULT 'detenido' CHECK(estado IN ('detenido','activo','pausado','emergencia')),
    ajustes TEXT NOT NULL DEFAULT '{}', real_habilitado INTEGER NOT NULL DEFAULT 0, actualizado_ts INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS operaciones(
    id INTEGER PRIMARY KEY AUTOINCREMENT, usuario_id INTEGER NOT NULL,
    modalidad TEXT NOT NULL, broker TEXT NOT NULL, cuenta TEXT, instrumento TEXT NOT NULL, simbolo_broker TEXT, mercado TEXT NOT NULL,
    tipo TEXT NOT NULL CHECK(tipo IN ('binaria','margen')), direccion TEXT NOT NULL CHECK(direccion IN ('alcista','bajista')),
    monto REAL NOT NULL, riesgo_importe REAL, volumen INTEGER, moneda TEXT,
    precio_entrada REAL, stop REAL, objetivo REAL, payout REAL, expira_ts INTEGER, costo REAL NOT NULL DEFAULT 0,
    estado TEXT NOT NULL CHECK(estado IN ('abierta','cerrada','rechazada')), abierta_ts INTEGER NOT NULL, cerrada_ts INTEGER,
    precio_salida REAL, resultado REAL, r REAL, motivo_cierre TEXT, id_externo TEXT, fuente_precio TEXT,
    estrategia TEXT, horizonte TEXT, motores TEXT, controles TEXT, clave_dedupe TEXT
);
CREATE INDEX IF NOT EXISTS ix_oper_usuario ON operaciones(usuario_id, abierta_ts);
CREATE UNIQUE INDEX IF NOT EXISTS ux_oper_dedupe ON operaciones(usuario_id, clave_dedupe) WHERE clave_dedupe IS NOT NULL;
CREATE TABLE IF NOT EXISTS decisiones_bot(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, usuario_id INTEGER NOT NULL, modalidad TEXT NOT NULL,
    instrumento TEXT, accion TEXT NOT NULL, motivo TEXT, controles TEXT, motores TEXT, operacion_id INTEGER
);
CREATE INDEX IF NOT EXISTS ix_dec_usuario ON decisiones_bot(usuario_id, ts);
CREATE TABLE IF NOT EXISTS eventos_broker(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, usuario_id INTEGER NOT NULL, tipo TEXT NOT NULL, datos TEXT
);
CREATE TABLE IF NOT EXISTS saldos(
    ts INTEGER NOT NULL, usuario_id INTEGER NOT NULL, cuenta TEXT, balance REAL, moneda TEXT
);
CREATE TABLE IF NOT EXISTS identidad(clave TEXT PRIMARY KEY, valor TEXT NOT NULL);
"""

ESQUEMA_CONOCIMIENTO = """
CREATE TABLE IF NOT EXISTS resultados(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, origen TEXT NOT NULL,
    estrategia TEXT NOT NULL, instrumento TEXT NOT NULL, horizonte TEXT, direccion TEXT, r REAL NOT NULL, motivo TEXT
);
CREATE INDEX IF NOT EXISTS ix_res ON resultados(estrategia, instrumento, ts);
"""


def ruta(modalidad):
    if modalidad not in MODALIDADES:
        raise ValueError("Modalidad no válida")
    return config.DATOS / "cuentas" / f"{modalidad}.db"


def ruta_conocimiento():
    return config.DATOS / "conocimiento.db"


def _abrir(p, esquema, ident=None):
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p.parent, 0o700)
    except OSError:
        pass
    c = sqlite3.connect(str(p), timeout=15, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=15000")
    try:
        c.execute("PRAGMA journal_mode=WAL")
    except sqlite3.DatabaseError:
        pass
    k = str(p)
    if k not in _MIGRADAS:
        with _L:
            c.executescript(esquema)
            if ident:
                fila = c.execute("SELECT valor FROM identidad WHERE clave='modalidad'").fetchone()
                if fila and fila[0] != ident:
                    raise RuntimeError(f"La base {p.name} pertenece a '{fila[0]}', no a '{ident}'. No se mezclan cuentas.")
                c.execute("INSERT OR IGNORE INTO identidad(clave,valor) VALUES('modalidad',?)", (ident,))
            c.commit()
            os.chmod(p, 0o600)
            _MIGRADAS.add(k)
    return c


def con(modalidad):
    p = ruta(modalidad)
    cache = getattr(_LOCAL, "c", None)
    if cache is None or getattr(_LOCAL, "datos", None) != str(config.DATOS):
        cerrar_hilo()
        _LOCAL.c, _LOCAL.datos = {}, str(config.DATOS)
        cache = _LOCAL.c
    if modalidad not in cache:
        migrar_desde_principal()
        cache[modalidad] = _abrir(p, ESQUEMA_CUENTA, modalidad)
    return cache[modalidad]


def con_conocimiento():
    cache = getattr(_LOCAL, "k", None)
    if cache is None or getattr(_LOCAL, "kdatos", None) != str(config.DATOS):
        if cache is not None:
            cache.close()
        _LOCAL.k, _LOCAL.kdatos = _abrir(ruta_conocimiento(), ESQUEMA_CONOCIMIENTO), str(config.DATOS)
    return _LOCAL.k


def cerrar_hilo():
    for c in (getattr(_LOCAL, "c", None) or {}).values():
        try:
            c.close()
        except Exception:
            pass
    _LOCAL.c = None
    k = getattr(_LOCAL, "k", None)
    if k is not None:
        try:
            k.close()
        except Exception:
            pass
        _LOCAL.k = None


def reiniciar_para_pruebas():
    cerrar_hilo()
    _MIGRADAS.clear()


@contextmanager
def tx(modalidad):
    c = con(modalidad)
    c.execute("BEGIN IMMEDIATE")
    try:
        yield c
        c.execute("COMMIT")
    except BaseException:
        c.execute("ROLLBACK")
        raise


def q(modalidad, sql, args=()):
    return [dict(r) for r in con(modalidad).execute(sql, args).fetchall()]


def q1(modalidad, sql, args=()):
    r = con(modalidad).execute(sql, args).fetchone()
    return dict(r) if r else None


# ----------------------------------------------------------------- conocimiento compartido
def aprender(origen, estrategia, instrumento, horizonte, direccion, r, motivo=None):
    """Solo R normalizado: ni importes, ni saldos, ni identificadores de cuenta/posición."""
    if r is None:
        return
    c = con_conocimiento()
    c.execute("INSERT INTO resultados(ts,origen,estrategia,instrumento,horizonte,direccion,r,motivo) VALUES(?,?,?,?,?,?,?,?)",
              (int(time.time()), origen, estrategia or "fusion", instrumento, horizonte, direccion, float(r), motivo))
    c.commit()


def conocimiento(estrategia=None, instrumento=None):
    from ..motores import mat
    sql, a = "SELECT origen, r FROM resultados WHERE 1=1", []
    if estrategia:
        sql += " AND estrategia=?"
        a.append(estrategia)
    if instrumento:
        sql += " AND instrumento=?"
        a.append(instrumento)
    filas = [dict(x) for x in con_conocimiento().execute(sql, a).fetchall()]
    rs = [f["r"] for f in filas]
    g = sum(1 for x in rs if x > 0)
    lo, hi = mat.wilson(g, len(rs))
    por = {}
    for f in filas:
        por.setdefault(f["origen"], []).append(f["r"])
    return {"n": len(rs), "expectativa_r": (sum(rs) / len(rs)) if rs else None, "tasa_acierto": (g / len(rs)) if rs else None,
            "tasa_ic95": [lo, hi], "por_origen": {k: {"n": len(v), "expectativa_r": sum(v) / len(v)} for k, v in por.items()}}


# ----------------------------------------------------------------- migración desde v7.0/v7.1
def migrar_desde_principal():
    """Copia (una sola vez) las operaciones/decisiones/estado que estaban en titan_quant.db a la base de su modalidad.
    No borra nada de titan_quant.db: quedan como copia histórica sin uso."""
    if db.cfg_sistema("cuentas_separadas_v72"):
        return
    with _L:
        if db.cfg_sistema("cuentas_separadas_v72"):
            return
        tablas = {r["name"] for r in db.q("SELECT name FROM sqlite_master WHERE type='table'")}
        movidas = {m: 0 for m in MODALIDADES}
        if "operaciones" in tablas:
            cons = {m: _abrir(ruta(m), ESQUEMA_CUENTA, m) for m in MODALIDADES}
            for o in db.q("SELECT * FROM operaciones ORDER BY id"):
                m = o["modalidad"]
                cols = [k for k in o if k != "analisis_id"]
                cons[m].execute(f"INSERT OR IGNORE INTO operaciones({','.join(cols)}) VALUES({','.join('?' * len(cols))})", [o[k] for k in cols])
                movidas[m] += 1
            for d in db.q("SELECT * FROM decisiones_bot ORDER BY id"):
                m = d["modalidad"] if d["modalidad"] in MODALIDADES else "simulacion"
                cols = list(d)
                cons[m].execute(f"INSERT OR IGNORE INTO decisiones_bot({','.join(cols)}) VALUES({','.join('?' * len(cols))})", [d[k] for k in cols])
            for b in db.q("SELECT * FROM bot_estado"):
                aj = json.loads(b["ajustes"] or "{}")
                m = aj.get("modalidad") if aj.get("modalidad") in MODALIDADES else "simulacion"
                cons[m].execute("INSERT OR IGNORE INTO bot_estado(usuario_id,estado,ajustes,real_habilitado,actualizado_ts) VALUES(?,?,?,?,?)",
                                (b["usuario_id"], "detenido", b["ajustes"], 0, b["actualizado_ts"]))
            for c in cons.values():
                c.commit()
                c.close()
        db.set_cfg_sistema("cuentas_separadas_v72", {"ts": int(time.time()), "operaciones_copiadas": movidas})
