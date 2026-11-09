"""Bases de datos SEPARADAS por cuenta de broker, y base de CONOCIMIENTO (R) separada por origen.

    datos/cuentas/demo.db         bot cTrader en la cuenta DEMO: operaciones, decisiones, eventos del broker
    datos/cuentas/binaria.db      bot de binarias en la cuenta PRACTICE de IQ Option
    datos/cuentas/real.db         bot cTrader en la cuenta REAL (LIVE): solo opera con el interruptor LIVE encendido
    datos/cuentas/binaria_real.db bot IQ Option en la cuenta REAL: solo opera con el interruptor LIVE encendido
    datos/conocimiento.db         R de operaciones CERRADAS Y CONFIRMADAS por el broker, siempre con su origen
                                  (demo = cTrader DEMO, binaria = IQ Option PRACTICE); las consultas filtran por origen

La simulación interna de operaciones se retiró (v7.2.1-sin-simulacion). El archivo histórico
datos/cuentas/simulacion.db, si existe, no se abre ni se lee desde la operativa: queda en disco como archivo.

Ciclo de vida verificable de cada operación (columna `fase`; cada transición queda en `operacion_eventos`):
    oportunidad_detectada → orden_enviada → orden_aceptada → abierta_confirmada → cerrada_confirmada → resultado_recibido
                                        ↘ error_broker (rechazo, tiempo agotado o estado no confirmado)
Una oportunidad detectada NO es una operación; una orden enviada NO es una orden aceptada; una orden aceptada NO es
un resultado. Solo las filas con fase 'resultado_recibido' y fuente_resultado='broker' cuentan en informes y saldos.
"""
import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager

from .. import config, db

MODALIDADES = ("demo", "real", "binaria", "binaria_real")
RETIRADAS = ("simulacion",)          # simulación interna retirada: su base no se abre
FASES = ("oportunidad_detectada", "orden_enviada", "orden_aceptada", "abierta_confirmada", "cerrada_confirmada",
         "resultado_recibido", "error_broker", "ajuste_stop")      # ajuste_stop: solo como EVENTO (trailing confirmado por el broker)
ESTADOS = ("enviada", "aceptada", "abierta", "cerrada", "rechazada", "error")
VIVOS = ("enviada", "aceptada", "abierta", "error")     # siguen en el broker o pendientes de confirmar/conciliar
_LOCAL = threading.local()
_MIGRADAS = set()
_L = threading.RLock()

_TABLA_OPERACIONES = """operaciones(
    id INTEGER PRIMARY KEY AUTOINCREMENT, usuario_id INTEGER NOT NULL,
    modalidad TEXT NOT NULL, broker TEXT NOT NULL, cuenta TEXT, instrumento TEXT NOT NULL, simbolo_broker TEXT, mercado TEXT NOT NULL,
    tipo TEXT NOT NULL CHECK(tipo IN ('binaria','margen')), direccion TEXT NOT NULL CHECK(direccion IN ('alcista','bajista')),
    monto REAL NOT NULL, riesgo_importe REAL, volumen INTEGER, moneda TEXT,
    precio_entrada REAL, stop REAL, objetivo REAL, payout REAL, expira_ts INTEGER, costo REAL NOT NULL DEFAULT 0,
    estado TEXT NOT NULL CHECK(estado IN ('enviada','aceptada','abierta','cerrada','rechazada','error')),
    abierta_ts INTEGER NOT NULL, cerrada_ts INTEGER,
    precio_salida REAL, resultado REAL, r REAL, motivo_cierre TEXT, id_externo TEXT, fuente_precio TEXT,
    estrategia TEXT, horizonte TEXT, motores TEXT, controles TEXT, clave_dedupe TEXT,
    fase TEXT NOT NULL DEFAULT 'oportunidad_detectada' CHECK(fase IN ('oportunidad_detectada','orden_enviada','orden_aceptada',
        'abierta_confirmada','cerrada_confirmada','resultado_recibido','error_broker')),
    fuente_resultado TEXT, evidencia TEXT, actualizado_ts INTEGER
)"""

ESQUEMA_CUENTA = """
CREATE TABLE IF NOT EXISTS bot_estado(
    usuario_id INTEGER PRIMARY KEY,
    estado TEXT NOT NULL DEFAULT 'detenido' CHECK(estado IN ('detenido','activo','pausado','emergencia')),
    ajustes TEXT NOT NULL DEFAULT '{}', real_habilitado INTEGER NOT NULL DEFAULT 0, actualizado_ts INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS """ + _TABLA_OPERACIONES + """;
CREATE INDEX IF NOT EXISTS ix_oper_usuario ON operaciones(usuario_id, abierta_ts);
CREATE UNIQUE INDEX IF NOT EXISTS ux_oper_dedupe ON operaciones(usuario_id, clave_dedupe) WHERE clave_dedupe IS NOT NULL;
CREATE TABLE IF NOT EXISTS operacion_eventos(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, operacion_id INTEGER NOT NULL, fase TEXT NOT NULL,
    id_broker TEXT, detalle TEXT
);
CREATE INDEX IF NOT EXISTS ix_opev ON operacion_eventos(operacion_id, ts);
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
        raise ValueError("Modalidad no válida (demo | real | binaria | binaria_real; la simulación se retiró)")
    return config.DATOS / "cuentas" / f"{modalidad}.db"


def ruta_conocimiento():
    return config.DATOS / "conocimiento.db"


def _migrar_operaciones(c):
    """Bases anteriores: `operaciones` solo admitía abierta/cerrada/rechazada y no tenía `fase`.
    Se reconstruye en UNA transacción conservando TODAS las filas. La fase se deduce de forma conservadora:
      rechazada                → oportunidad_detectada
      cerrada con id de broker → resultado_recibido (fuente_resultado='broker')
      abierta con id de broker → abierta_confirmada
      cerrada/abierta sin id   → estado 'error', fase error_broker (no hay prueba de que el broker la ejecutara)"""
    fila = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='operaciones'").fetchone()
    if not fila or "fase TEXT" in fila[0]:
        return
    cols = [r[1] for r in c.execute("PRAGMA table_info(operaciones)")]
    lista = ",".join(cols)
    c.execute("BEGIN IMMEDIATE")
    try:
        c.execute("ALTER TABLE operaciones RENAME TO operaciones_v721")
        c.execute("DROP INDEX IF EXISTS ix_oper_usuario")
        c.execute("DROP INDEX IF EXISTS ux_oper_dedupe")
        c.execute("CREATE TABLE " + _TABLA_OPERACIONES)
        c.execute(f"INSERT INTO operaciones({lista}) SELECT {lista} FROM operaciones_v721")
        c.execute("""UPDATE operaciones SET
                         fase = CASE WHEN estado='rechazada' THEN 'oportunidad_detectada'
                                     WHEN estado='cerrada' AND id_externo IS NOT NULL THEN 'resultado_recibido'
                                     WHEN estado='abierta' AND id_externo IS NOT NULL THEN 'abierta_confirmada'
                                     ELSE 'error_broker' END,
                         fuente_resultado = CASE WHEN estado='cerrada' AND id_externo IS NOT NULL THEN 'broker' END,
                         estado = CASE WHEN estado IN ('cerrada','abierta') AND id_externo IS NULL THEN 'error' ELSE estado END""")
        c.execute("DROP TABLE operaciones_v721")
        c.execute("COMMIT")
    except BaseException:
        c.execute("ROLLBACK")
        raise


def _abrir(p, esquema, ident=None):
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p.parent, 0o700)
    except OSError:
        pass
    c = sqlite3.connect(str(p), timeout=15, check_same_thread=False, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=15000")
    try:
        c.execute("PRAGMA journal_mode=WAL")
    except sqlite3.DatabaseError:
        pass
    k = str(p)
    if k not in _MIGRADAS:
        with _L:
            if esquema is ESQUEMA_CUENTA:
                _migrar_operaciones(c)
            c.executescript(esquema)
            if esquema is ESQUEMA_CUENTA and "stop_inicial" not in {r[1] for r in c.execute("PRAGMA table_info(operaciones)")}:
                c.execute("ALTER TABLE operaciones ADD COLUMN stop_inicial REAL")      # stop con el que se abrió (base de 1 R)
            if ident:
                fila = c.execute("SELECT valor FROM identidad WHERE clave='modalidad'").fetchone()
                if fila and fila[0] != ident:
                    raise RuntimeError(f"La base {p.name} pertenece a '{fila[0]}', no a '{ident}'. No se mezclan cuentas.")
                c.execute("INSERT OR IGNORE INTO identidad(clave,valor) VALUES('modalidad',?)", (ident,))
            try:
                os.chmod(p, 0o600)
            except OSError:
                pass
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


# ----------------------------------------------------------------- ciclo de vida verificable
def evento(c, operacion_id, fase, detalle=None, id_broker=None, ts=None):
    """Registra una transición del ciclo de vida, dentro de la transacción `c`."""
    if fase not in FASES:
        raise ValueError("Fase desconocida: " + str(fase))
    if detalle is not None and not isinstance(detalle, str):
        detalle = json.dumps(detalle, ensure_ascii=False, default=str)
    c.execute("INSERT INTO operacion_eventos(ts,operacion_id,fase,id_broker,detalle) VALUES(?,?,?,?,?)",
              (int(ts or time.time()), operacion_id, fase, None if id_broker is None else str(id_broker),
               (detalle or "")[:4000] or None))


def eventos(modalidad, operacion_id):
    return q(modalidad, "SELECT * FROM operacion_eventos WHERE operacion_id=? ORDER BY id", (operacion_id,))


# ----------------------------------------------------------------- conocimiento (R), separado por origen
def aprender(origen, estrategia, instrumento, horizonte, direccion, r, motivo=None):
    """Solo R de operaciones CERRADAS Y CONFIRMADAS por el broker: ni importes, ni saldos, ni IDs de cuenta/posición."""
    if r is None or origen not in MODALIDADES:
        return
    c = con_conocimiento()
    c.execute("INSERT INTO resultados(ts,origen,estrategia,instrumento,horizonte,direccion,r,motivo) VALUES(?,?,?,?,?,?,?,?)",
              (int(time.time()), origen, estrategia or "fusion", instrumento, horizonte, direccion, float(r), motivo))


def conocimiento(estrategia=None, instrumento=None, origen=None):
    """Estadística de R. Excluye siempre la simulación retirada. Con `origen` (demo = cTrader DEMO,
    binaria = IQ Option PRACTICE) lee un solo broker: los mercados no se mezclan."""
    from ..motores import mat
    sql, a = "SELECT origen, r FROM resultados WHERE origen NOT IN ('simulacion')", []
    if origen:
        sql += " AND origen=?"
        a.append(origen)
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
    No borra nada de titan_quant.db. Las filas de la simulación retirada NO se copian a ninguna cuenta de broker."""
    if db.cfg_sistema("cuentas_separadas_v72"):
        return
    with _L:
        if db.cfg_sistema("cuentas_separadas_v72"):
            return
        tablas = {r["name"] for r in db.q("SELECT name FROM sqlite_master WHERE type='table'")}
        movidas = {m: 0 for m in MODALIDADES}
        if "operaciones" in tablas:
            cons = {m: _abrir(ruta(m), ESQUEMA_CUENTA, m) for m in MODALIDADES}
            for c in cons.values():
                c.execute("BEGIN IMMEDIATE")
            for o in db.q("SELECT * FROM operaciones ORDER BY id"):
                m = o["modalidad"]
                if m not in MODALIDADES:
                    continue
                cols = [k for k in o if k != "analisis_id"]
                cons[m].execute(f"INSERT OR IGNORE INTO operaciones({','.join(cols)}) VALUES({','.join('?' * len(cols))})", [o[k] for k in cols])
                movidas[m] += 1
            for d in db.q("SELECT * FROM decisiones_bot ORDER BY id"):
                m = d["modalidad"]
                if m not in MODALIDADES:
                    continue
                cols = list(d)
                cons[m].execute(f"INSERT OR IGNORE INTO decisiones_bot({','.join(cols)}) VALUES({','.join('?' * len(cols))})", [d[k] for k in cols])
            for b in db.q("SELECT * FROM bot_estado"):
                aj = json.loads(b["ajustes"] or "{}")
                m = aj.get("modalidad")
                if m not in MODALIDADES:
                    continue
                cons[m].execute("INSERT OR IGNORE INTO bot_estado(usuario_id,estado,ajustes,real_habilitado,actualizado_ts) VALUES(?,?,?,?,?)",
                                (b["usuario_id"], "detenido", b["ajustes"], 0, b["actualizado_ts"]))
            for c in cons.values():
                c.execute("COMMIT")
                c.close()
            # Las filas antiguas copiadas sin fase se normalizan con la regla conservadora de _migrar_operaciones.
            for m in MODALIDADES:
                cc = _abrir(ruta(m), ESQUEMA_CUENTA, m)
                cc.execute("""UPDATE operaciones SET fase='resultado_recibido', fuente_resultado='broker'
                              WHERE fase='oportunidad_detectada' AND estado='cerrada' AND id_externo IS NOT NULL""")
                cc.execute("""UPDATE operaciones SET estado='error', fase='error_broker'
                              WHERE fase='oportunidad_detectada' AND estado IN ('cerrada','abierta') AND id_externo IS NULL""")
                cc.execute("""UPDATE operaciones SET fase='abierta_confirmada'
                              WHERE fase='oportunidad_detectada' AND estado='abierta' AND id_externo IS NOT NULL""")
                cc.close()
        db.set_cfg_sistema("cuentas_separadas_v72", {"ts": int(time.time()), "operaciones_copiadas": movidas})
