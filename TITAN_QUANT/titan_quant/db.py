"""Base de datos principal de TITAN QUANT (titan_quant.db) con migraciones versionadas.

- Las bases heredadas (titan_activos.db, titan_planes.db, titan_lab.db) NO se modifican aquí:
  se siguen usando tal cual; esta base solo guarda lo nuevo y referencias a lo existente.
- WAL + busy_timeout: varios hilos escriben (servidor, bot operador, motores).
- Antes de migrar se hace una copia con la API de respaldo de SQLite.
"""
import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager

from . import config

_LOCAL = threading.local()
_MIGRAR_LOCK = threading.Lock()
_MIGRADO = set()

MIGRACIONES = [
    # 1 — usuarios, sesiones, seguridad, credenciales, integraciones, configuración
    """
    CREATE TABLE usuarios(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        correo TEXT NOT NULL UNIQUE COLLATE NOCASE,
        nombre TEXT NOT NULL,
        clave_hash TEXT NOT NULL,
        rol TEXT NOT NULL DEFAULT 'usuario' CHECK(rol IN ('propietario','usuario')),
        verificado INTEGER NOT NULL DEFAULT 0,
        fallos INTEGER NOT NULL DEFAULT 0,
        bloqueado_hasta INTEGER NOT NULL DEFAULT 0,
        acepta_terminos_ts INTEGER NOT NULL,
        creado_ts INTEGER NOT NULL,
        actualizado_ts INTEGER NOT NULL
    );
    CREATE TABLE sesiones(
        id TEXT PRIMARY KEY,                 -- SHA-256 del token, el token en claro solo vive en la cookie
        usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        csrf TEXT NOT NULL,
        creada_ts INTEGER NOT NULL, expira_ts INTEGER NOT NULL, ultimo_ts INTEGER NOT NULL,
        ip TEXT, agente TEXT, revocada INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX ix_sesiones_usuario ON sesiones(usuario_id);
    CREATE TABLE tokens(
        hash TEXT PRIMARY KEY,
        usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        tipo TEXT NOT NULL CHECK(tipo IN ('verificar','restablecer')),
        creado_ts INTEGER NOT NULL, expira_ts INTEGER NOT NULL, usado_ts INTEGER
    );
    CREATE TABLE eventos_seguridad(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, usuario_id INTEGER,
        tipo TEXT NOT NULL, ip TEXT, detalle TEXT
    );
    CREATE INDEX ix_evseg_usuario ON eventos_seguridad(usuario_id, ts);
    CREATE TABLE credenciales(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        proveedor TEXT NOT NULL, campo TEXT NOT NULL,
        cifrado BLOB NOT NULL, mascara TEXT NOT NULL, actualizado_ts INTEGER NOT NULL,
        UNIQUE(usuario_id, proveedor, campo)
    );
    CREATE TABLE integraciones(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        proveedor TEXT NOT NULL,
        activa INTEGER NOT NULL DEFAULT 1,
        estado TEXT NOT NULL DEFAULT 'no_configurada',
        ultima_prueba_ts INTEGER, resultado TEXT, error TEXT,
        ajustes TEXT NOT NULL DEFAULT '{}',
        UNIQUE(usuario_id, proveedor)
    );
    CREATE TABLE config_usuario(
        usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        clave TEXT NOT NULL, valor TEXT NOT NULL, ts INTEGER NOT NULL,
        PRIMARY KEY(usuario_id, clave)
    );
    CREATE TABLE config_sistema(clave TEXT PRIMARY KEY, valor TEXT NOT NULL, ts INTEGER NOT NULL);
    CREATE TABLE auditoria(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, usuario_id INTEGER,
        accion TEXT NOT NULL, objeto TEXT, objeto_id TEXT, detalle TEXT
    );
    CREATE INDEX ix_auditoria_usuario ON auditoria(usuario_id, ts);
    """,
    # 2 — análisis, alertas, visibilidad lógica, motores
    """
    CREATE TABLE analisis(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL,
        usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        simbolo TEXT NOT NULL, horizonte TEXT NOT NULL, nivel TEXT NOT NULL, politica TEXT NOT NULL,
        direccion TEXT, probabilidad REAL, hay_oportunidad INTEGER NOT NULL DEFAULT 0,
        fuente_datos TEXT, resultado TEXT NOT NULL
    );
    CREATE INDEX ix_analisis_usuario ON analisis(usuario_id, ts);
    CREATE TABLE alertas(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL,
        usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        categoria TEXT NOT NULL, tipo TEXT NOT NULL,
        importancia TEXT NOT NULL CHECK(importancia IN ('baja','media','alta','critica')),
        activo TEXT, mercado TEXT, direccion TEXT, precio_ref REAL, horizonte TEXT,
        justificacion TEXT, motores TEXT, modalidad TEXT,
        estado TEXT NOT NULL DEFAULT 'nueva' CHECK(estado IN ('nueva','leida')),
        clave_dedupe TEXT, datos TEXT,
        UNIQUE(usuario_id, clave_dedupe)
    );
    CREATE INDEX ix_alertas_usuario ON alertas(usuario_id, ts);
    CREATE TABLE alertas_silencio(
        usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        categoria TEXT NOT NULL, ts INTEGER NOT NULL, PRIMARY KEY(usuario_id, categoria)
    );
    -- Ocultar / archivar SIN borrar: el registro original nunca se toca.
    CREATE TABLE visibilidad(
        usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        tipo TEXT NOT NULL, objeto_id TEXT NOT NULL,
        estado TEXT NOT NULL CHECK(estado IN ('oculto','archivado')), ts INTEGER NOT NULL,
        PRIMARY KEY(usuario_id, tipo, objeto_id)
    );
    CREATE TABLE estado_motores(
        motor TEXT PRIMARY KEY, ts INTEGER NOT NULL, estado TEXT NOT NULL,
        duracion_ms INTEGER, ejecuciones INTEGER NOT NULL DEFAULT 0, errores INTEGER NOT NULL DEFAULT 0,
        detalle TEXT, error TEXT
    );
    """,
    # 3 — bot operador
    """
    CREATE TABLE bot_estado(
        usuario_id INTEGER PRIMARY KEY REFERENCES usuarios(id) ON DELETE CASCADE,
        estado TEXT NOT NULL DEFAULT 'detenido' CHECK(estado IN ('detenido','activo','pausado','emergencia')),
        ajustes TEXT NOT NULL DEFAULT '{}', real_habilitado INTEGER NOT NULL DEFAULT 0,
        actualizado_ts INTEGER NOT NULL
    );
    CREATE TABLE operaciones(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        modalidad TEXT NOT NULL CHECK(modalidad IN ('simulacion','demo','real')),
        broker TEXT NOT NULL, cuenta TEXT, instrumento TEXT NOT NULL, mercado TEXT NOT NULL,
        tipo TEXT NOT NULL CHECK(tipo IN ('binaria','margen')),
        direccion TEXT NOT NULL CHECK(direccion IN ('alcista','bajista')),
        monto REAL NOT NULL, precio_entrada REAL, stop REAL, objetivo REAL, payout REAL,
        expira_ts INTEGER, costo REAL NOT NULL DEFAULT 0,
        estado TEXT NOT NULL CHECK(estado IN ('abierta','cerrada','rechazada')),
        abierta_ts INTEGER NOT NULL, cerrada_ts INTEGER, precio_salida REAL,
        resultado REAL, r REAL, motivo_cierre TEXT, id_externo TEXT,
        fuente_precio TEXT, motores TEXT, controles TEXT, analisis_id INTEGER, clave_dedupe TEXT
    );
    CREATE INDEX ix_oper_usuario ON operaciones(usuario_id, abierta_ts);
    CREATE UNIQUE INDEX ux_oper_dedupe ON operaciones(usuario_id, clave_dedupe) WHERE clave_dedupe IS NOT NULL;
    CREATE TABLE decisiones_bot(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL,
        usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        modalidad TEXT NOT NULL, instrumento TEXT, accion TEXT NOT NULL, motivo TEXT,
        controles TEXT, motores TEXT, operacion_id INTEGER
    );
    CREATE INDEX ix_decisiones_usuario ON decisiones_bot(usuario_id, ts);
    """,
    # 4 — administración: aprobación de solicitudes, administradores y suspensión
    """
    ALTER TABLE usuarios ADD COLUMN aprobado INTEGER NOT NULL DEFAULT 1;
    ALTER TABLE usuarios ADD COLUMN admin INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE usuarios ADD COLUMN suspendido INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE usuarios ADD COLUMN ultimo_acceso_ts INTEGER;
    UPDATE usuarios SET admin=1, aprobado=1 WHERE rol='propietario'
    """,
]


def _abrir(ruta):
    c = sqlite3.connect(str(ruta), timeout=15, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA busy_timeout=15000")
    try:
        c.execute("PRAGMA journal_mode=WAL")
    except sqlite3.DatabaseError:
        pass
    return c


def con():
    """Conexión por hilo a la base principal (migra la primera vez)."""
    ruta = str(config.DB_PRINCIPAL)
    c = getattr(_LOCAL, "c", None)
    if c is None or getattr(_LOCAL, "ruta", None) != ruta:
        config.asegurar_directorios()
        migrar()
        c = _abrir(ruta)
        _LOCAL.c, _LOCAL.ruta = c, ruta
    return c


def cerrar_hilo():
    c = getattr(_LOCAL, "c", None)
    if c is not None:
        c.close()
        _LOCAL.c = None


@contextmanager
def tx():
    """Transacción explícita: todo o nada."""
    c = con()
    c.execute("BEGIN IMMEDIATE")
    try:
        yield c
        c.execute("COMMIT")
    except BaseException:
        c.execute("ROLLBACK")
        raise


def q(sql, args=()):
    return [dict(r) for r in con().execute(sql, args).fetchall()]


def q1(sql, args=()):
    r = con().execute(sql, args).fetchone()
    return dict(r) if r else None


def respaldar(destino=None, ruta=None):
    """Copia consistente con la API de respaldo de SQLite (sirve con la base abierta)."""
    ruta = ruta or config.DB_PRINCIPAL
    if not os.path.exists(ruta):
        return None
    config.asegurar_directorios()
    destino = destino or config.RESPALDOS / (os.path.basename(str(ruta)) + time.strftime(".%Y%m%d_%H%M%S.bak"))
    src = sqlite3.connect(str(ruta))
    dst = sqlite3.connect(str(destino))
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    os.chmod(destino, 0o600)
    return destino


def migrar():
    ruta = str(config.DB_PRINCIPAL)
    with _MIGRAR_LOCK:
        if ruta in _MIGRADO:
            return
        existe = os.path.exists(ruta)
        c = _abrir(ruta)
        try:
            c.execute("CREATE TABLE IF NOT EXISTS esquema_version(version INTEGER NOT NULL, ts INTEGER NOT NULL)")
            v = c.execute("SELECT COALESCE(MAX(version),0) FROM esquema_version").fetchone()[0]
            pendientes = list(enumerate(MIGRACIONES, start=1))[v:]
            if pendientes and existe and v > 0:
                c.close()
                respaldar(ruta=ruta)
                c = _abrir(ruta)
            for num, sql in pendientes:
                c.execute("BEGIN IMMEDIATE")
                try:
                    for st in [s for s in sql.split(";") if s.strip()]:
                        c.execute(st)
                    c.execute("INSERT INTO esquema_version(version, ts) VALUES(?,?)", (num, int(time.time())))
                    c.execute("COMMIT")
                except BaseException:
                    c.execute("ROLLBACK")
                    raise
        finally:
            c.close()
        try:
            os.chmod(ruta, 0o600)
        except OSError:
            pass
        _MIGRADO.add(ruta)


def reiniciar_para_pruebas():
    """Solo pruebas: olvida conexiones y migraciones en memoria (tras cambiar config.DATOS)."""
    cerrar_hilo()
    _MIGRADO.clear()


# ----------------------------------------------------------------- configuración y auditoría
def cfg_usuario(uid, clave, defecto=None):
    r = q1("SELECT valor FROM config_usuario WHERE usuario_id=? AND clave=?", (uid, clave))
    return json.loads(r["valor"]) if r else defecto


def set_cfg_usuario(uid, clave, valor):
    antes = cfg_usuario(uid, clave)
    with tx() as c:
        c.execute("INSERT INTO config_usuario(usuario_id,clave,valor,ts) VALUES(?,?,?,?) "
                  "ON CONFLICT(usuario_id,clave) DO UPDATE SET valor=excluded.valor, ts=excluded.ts",
                  (uid, clave, json.dumps(valor), int(time.time())))
    if antes != valor:
        auditar(uid, "cambio_configuracion", "config", clave, {"antes": antes, "despues": valor})


def cfg_sistema(clave, defecto=None):
    r = q1("SELECT valor FROM config_sistema WHERE clave=?", (clave,))
    return json.loads(r["valor"]) if r else defecto


def set_cfg_sistema(clave, valor):
    with tx() as c:
        c.execute("INSERT INTO config_sistema(clave,valor,ts) VALUES(?,?,?) ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor, ts=excluded.ts",
                  (clave, json.dumps(valor), int(time.time())))


def auditar(uid, accion, objeto=None, objeto_id=None, detalle=None):
    with tx() as c:
        c.execute("INSERT INTO auditoria(ts,usuario_id,accion,objeto,objeto_id,detalle) VALUES(?,?,?,?,?,?)",
                  (int(time.time()), uid, accion, objeto, None if objeto_id is None else str(objeto_id),
                   json.dumps(detalle, ensure_ascii=False, default=str)[:4000] if detalle is not None else None))
