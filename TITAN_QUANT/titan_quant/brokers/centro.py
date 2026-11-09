"""Centro de brokers: interruptor ON/OFF, entorno (DEMO/REAL), credenciales en la bóveda, diagnóstico, actividad y
sincronización (C3/C4). El broker es la fuente de verdad: lo sincronizado se guarda con su identificador original.

Base propia: datos/brokers/brokers.db (separada de las cuentas de los bots y de los backtests).
"""
import json
import sqlite3
import threading
import time
from contextlib import contextmanager

from .. import config, db
from ..seguridad import boveda, interruptores
from . import catalogo
from .conectores import CONECTORES

ESQUEMA = """
CREATE TABLE IF NOT EXISTS ajustes(broker TEXT NOT NULL, usuario_id INTEGER NOT NULL, habilitado INTEGER NOT NULL DEFAULT 0,
    entorno TEXT NOT NULL DEFAULT 'demo', sync_min INTEGER NOT NULL DEFAULT 5, riesgo_max_pct REAL NOT NULL DEFAULT 1.0,
    actualizado_ts INTEGER, PRIMARY KEY(broker, usuario_id));
CREATE TABLE IF NOT EXISTS estado(broker TEXT NOT NULL, usuario_id INTEGER NOT NULL, conectado INTEGER NOT NULL DEFAULT 0,
    ultimo_ok_ts INTEGER, ultimo_intento_ts INTEGER, ultimo_error TEXT, latencia_ms INTEGER, capacidades TEXT, detalle TEXT,
    ultima_sync_ts INTEGER, PRIMARY KEY(broker, usuario_id));
CREATE TABLE IF NOT EXISTS actividad(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, broker TEXT NOT NULL, usuario_id INTEGER,
    entorno TEXT, accion TEXT NOT NULL, ok INTEGER NOT NULL, detalle TEXT, ms INTEGER);
CREATE INDEX IF NOT EXISTS i_act ON actividad(broker, ts);
CREATE TABLE IF NOT EXISTS cuenta(broker TEXT NOT NULL, usuario_id INTEGER NOT NULL, entorno TEXT NOT NULL, ts INTEGER NOT NULL, datos TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS posiciones(broker TEXT NOT NULL, usuario_id INTEGER NOT NULL, entorno TEXT NOT NULL, id_externo TEXT NOT NULL,
    simbolo TEXT, lado TEXT, cantidad REAL, precio_entrada REAL, pnl_no_realizado REAL, stop REAL, objetivo REAL, swap REAL, abierta_ts INTEGER,
    visto_ts INTEGER NOT NULL, abierta INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(broker, usuario_id, entorno, id_externo));
CREATE TABLE IF NOT EXISTS ordenes(broker TEXT NOT NULL, usuario_id INTEGER NOT NULL, entorno TEXT NOT NULL, id_externo TEXT NOT NULL,
    simbolo TEXT, lado TEXT, cantidad REAL, tipo TEXT, precio REAL, estado TEXT, creada_ts INTEGER, visto_ts INTEGER NOT NULL,
    PRIMARY KEY(broker, usuario_id, entorno, id_externo));
CREATE TABLE IF NOT EXISTS ejecuciones(broker TEXT NOT NULL, usuario_id INTEGER NOT NULL, entorno TEXT NOT NULL, id_externo TEXT NOT NULL,
    orden_id TEXT, simbolo TEXT, lado TEXT, cantidad REAL, precio REAL, comision REAL, swap REAL, pnl REAL, parcial INTEGER, ts INTEGER,
    recibida_ts INTEGER NOT NULL, PRIMARY KEY(broker, usuario_id, entorno, id_externo));
"""
_L = threading.local()


def ruta():
    return config.DATOS / "brokers" / "brokers.db"


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
        c.executescript(ESQUEMA)
        _L.c, _L.r = c, r
    return c


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


def q(sql, a=()):
    return [dict(r) for r in _con().execute(sql, a).fetchall()]


def q1(sql, a=()):
    r = _con().execute(sql, a).fetchone()
    return dict(r) if r else None


def cerrar():
    c = getattr(_L, "c", None)
    if c is not None:
        c.close()
        _L.c = None


PROVEEDOR = "broker_"     # prefijo en la bóveda


def ajustes(uid, broker):
    a = q1("SELECT * FROM ajustes WHERE broker=? AND usuario_id=?", (broker, uid))
    return a or {"broker": broker, "usuario_id": uid, "habilitado": 0, "entorno": "demo", "sync_min": 5, "riesgo_max_pct": 1.0}


def guardar(uid, broker, habilitado=None, entorno=None, credenciales=None, sync_min=None, riesgo_max_pct=None):
    if broker not in CONECTORES:
        raise ValueError("Este broker no tiene conector en TITAN (consulta la matriz).")
    a = ajustes(uid, broker)
    if entorno is not None:
        if entorno not in ("demo", "real"):
            raise ValueError("Entorno no válido.")
        a["entorno"] = entorno
    if habilitado is not None:
        a["habilitado"] = int(bool(habilitado))
    if sync_min is not None:
        a["sync_min"] = max(1, min(1440, int(sync_min)))
    if riesgo_max_pct is not None:
        a["riesgo_max_pct"] = max(0.05, min(5.0, float(riesgo_max_pct)))
    with tx() as c:
        c.execute("""INSERT INTO ajustes(broker,usuario_id,habilitado,entorno,sync_min,riesgo_max_pct,actualizado_ts) VALUES(?,?,?,?,?,?,?)
                     ON CONFLICT(broker,usuario_id) DO UPDATE SET habilitado=excluded.habilitado, entorno=excluded.entorno,
                     sync_min=excluded.sync_min, riesgo_max_pct=excluded.riesgo_max_pct, actualizado_ts=excluded.actualizado_ts""",
                  (broker, uid, a["habilitado"], a["entorno"], a["sync_min"], a["riesgo_max_pct"], int(time.time())))
    if credenciales:
        campos = {k: str(v).strip() for k, v in credenciales.items() if str(v or "").strip() and k in dict(CONECTORES[broker].CAMPOS)}
        if campos:
            previas = {}
            try:
                previas = boveda.leer(uid, PROVEEDOR + broker) or {}
            except Exception:
                pass
            boveda.guardar(uid, PROVEEDOR + broker, {**previas, **campos})
    db.auditar(uid, "broker_configurado", "broker", broker, {"habilitado": a["habilitado"], "entorno": a["entorno"],
                                                              "credenciales_actualizadas": sorted((credenciales or {}).keys())})
    return a


def conector(uid, broker, entorno=None):
    cls = CONECTORES[broker]
    try:
        cred = boveda.leer(uid, PROVEEDOR + broker) or {}
    except Exception:
        cred = {}
    a = ajustes(uid, broker)
    ent = entorno or a["entorno"]

    def registrar(accion, ok, detalle, ms):
        try:
            with tx() as c:
                c.execute("INSERT INTO actividad(ts,broker,usuario_id,entorno,accion,ok,detalle,ms) VALUES(?,?,?,?,?,?,?,?)",
                          (int(time.time()), broker, uid, ent, accion[:80], int(ok), str(detalle)[:300], ms))
        except Exception:
            pass
    return cls(cred, ent, registrar=registrar)


def diagnosticar(uid, broker):
    """Prueba real: autenticación + lectura (o datos públicos). Nunca marca 'conectado' sin respuesta del broker."""
    ahora = int(time.time())
    t0 = time.time()
    try:
        r = conector(uid, broker).probar()
        ok, det, cap, err = True, r["detalle"], r.get("capacidades", []), None
    except Exception as e:
        ok, det, cap, err = False, None, [], f"{type(e).__name__}: {str(e)[:250]}"
    ms = int((time.time() - t0) * 1000)
    with tx() as c:
        c.execute("""INSERT INTO estado(broker,usuario_id,conectado,ultimo_ok_ts,ultimo_intento_ts,ultimo_error,latencia_ms,capacidades,detalle)
                     VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(broker,usuario_id) DO UPDATE SET conectado=excluded.conectado,
                     ultimo_ok_ts=COALESCE(excluded.ultimo_ok_ts, estado.ultimo_ok_ts), ultimo_intento_ts=excluded.ultimo_intento_ts,
                     ultimo_error=excluded.ultimo_error, latencia_ms=excluded.latencia_ms,
                     capacidades=CASE WHEN excluded.conectado THEN excluded.capacidades ELSE estado.capacidades END, detalle=excluded.detalle""",
                  (broker, uid, int(ok), ahora if ok else None, ahora, err, ms, json.dumps(cap), det))
    return {"ok": ok, "detalle": det or err, "capacidades": cap, "latencia_ms": ms}


def sincronizar(uid, broker):
    """Trae del broker cuenta, posiciones, órdenes y ejecuciones (comisiones, swaps, parciales). Sin duplicados (id del broker)."""
    a = ajustes(uid, broker)
    if not a["habilitado"]:
        return {"ok": False, "detalle": "broker apagado (OFF)"}
    ad = conector(uid, broker)
    ahora = int(time.time())
    res = {"ok": True, "posiciones": 0, "ordenes": 0, "ejecuciones_nuevas": 0, "errores": []}
    ent = a["entorno"]
    try:
        cta = ad.cuenta()
        with tx() as c:
            c.execute("INSERT INTO cuenta(broker,usuario_id,entorno,ts,datos) VALUES(?,?,?,?,?)", (broker, uid, ent, ahora, json.dumps(cta)))
    except Exception as e:
        res["errores"].append(f"cuenta: {type(e).__name__}: {str(e)[:150]}")
    try:
        ps = ad.posiciones()
        with tx() as c:
            c.execute("UPDATE posiciones SET abierta=0 WHERE broker=? AND usuario_id=? AND entorno=?", (broker, uid, ent))
            for p in ps:
                c.execute("""INSERT INTO posiciones(broker,usuario_id,entorno,id_externo,simbolo,lado,cantidad,precio_entrada,pnl_no_realizado,stop,objetivo,
                             swap,abierta_ts,visto_ts,abierta) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,1) ON CONFLICT(broker,usuario_id,entorno,id_externo)
                             DO UPDATE SET cantidad=excluded.cantidad, pnl_no_realizado=excluded.pnl_no_realizado, stop=excluded.stop,
                             objetivo=excluded.objetivo, swap=excluded.swap, visto_ts=excluded.visto_ts, abierta=1""",
                          (broker, uid, ent, p["id_externo"], p["simbolo"], p["lado"], p["cantidad"], p["precio_entrada"], p["pnl_no_realizado"],
                           p["stop"], p["objetivo"], p["swap"], p["abierta_ts"], ahora))
        res["posiciones"] = len(ps)
    except Exception as e:
        res["errores"].append(f"posiciones: {type(e).__name__}: {str(e)[:150]}")
    try:
        os_ = ad.ordenes()
        with tx() as c:
            for o in os_:
                c.execute("""INSERT INTO ordenes(broker,usuario_id,entorno,id_externo,simbolo,lado,cantidad,tipo,precio,estado,creada_ts,visto_ts)
                             VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(broker,usuario_id,entorno,id_externo) DO UPDATE SET estado=excluded.estado,
                             cantidad=excluded.cantidad, visto_ts=excluded.visto_ts""",
                          (broker, uid, ent, o["id_externo"], o["simbolo"], o["lado"], o["cantidad"], o["tipo"], o["precio"], o["estado"], o["creada_ts"], ahora))
        res["ordenes"] = len(os_)
    except Exception as e:
        res["errores"].append(f"órdenes: {type(e).__name__}: {str(e)[:150]}")
    try:
        ult = (q1("SELECT MAX(ts) t FROM ejecuciones WHERE broker=? AND usuario_id=? AND entorno=?", (broker, uid, ent)) or {}).get("t")
        ej = ad.ejecuciones((ult - 86400) if ult else ahora - 30 * 86400)
        n = 0
        with tx() as c:
            for x in ej:
                cur = c.execute("""INSERT OR IGNORE INTO ejecuciones(broker,usuario_id,entorno,id_externo,orden_id,simbolo,lado,cantidad,precio,comision,swap,pnl,
                                   parcial,ts,recibida_ts) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                (broker, uid, ent, x["id_externo"], x.get("orden_id"), x["simbolo"], x["lado"], x["cantidad"], x["precio"],
                                 x.get("comision") or 0.0, x.get("swap") or 0.0, x.get("pnl"), int(bool(x.get("parcial"))), x.get("ts"), ahora))
                n += cur.rowcount
        res["ejecuciones_nuevas"] = n
    except Exception as e:
        res["errores"].append(f"ejecuciones: {type(e).__name__}: {str(e)[:150]}")
    res["ok"] = not res["errores"] or bool(res["posiciones"] or res["ordenes"] or res["ejecuciones_nuevas"])
    with tx() as c:
        c.execute("UPDATE estado SET ultima_sync_ts=? WHERE broker=? AND usuario_id=?", (ahora, broker, uid))
    return res


def orden_prueba_demo(uid, broker, simbolo, lado, cantidad, stop=None, objetivo=None):
    """Orden de PRUEBA en la cuenta DEMO (para verificar la ejecución). Respeta la PARADA TOTAL y el interruptor del broker."""
    a = ajustes(uid, broker)
    if not a["habilitado"]:
        raise PermissionError("Enciende primero el broker (interruptor ON).")
    if a["entorno"] != "demo":
        raise PermissionError("Las órdenes de prueba solo se envían a la cuenta DEMO.")
    ok, motivo = interruptores.permitido(broker)
    if not ok:
        raise PermissionError(motivo)
    r = conector(uid, broker).abrir(simbolo, lado, cantidad, stop, objetivo)
    db.auditar(uid, "orden_prueba_demo", "broker", broker, {"simbolo": simbolo, "lado": lado, "cantidad": cantidad, "id": r.get("id_externo")})
    return r


def panel(uid):
    """Matriz + estado + ajustes de cada broker para la interfaz (sin credenciales: solo máscaras)."""
    out = []
    for b in catalogo.lista():
        e = q1("SELECT * FROM estado WHERE broker=? AND usuario_id=?", (b["id"], uid)) or {}
        a = ajustes(uid, b["id"])
        tiene = b["id"] in CONECTORES
        mascaras = {}
        if tiene:
            try:
                mascaras = boveda.mascaras(uid, PROVEEDOR + b["id"]) or {}
            except Exception:
                mascaras = {}
        out.append({**b, "habilitado": bool(a["habilitado"]), "entorno": a["entorno"], "sync_min": a["sync_min"], "riesgo_max_pct": a["riesgo_max_pct"],
                    "tiene_conector": tiene, "campos": [{"id": k, "etiqueta": t} for k, t in (CONECTORES[b["id"]].CAMPOS if tiene else ())],
                    "credenciales": mascaras, "conectado": bool(e.get("conectado")), "ultimo_ok_ts": e.get("ultimo_ok_ts"), "ultimo_error": e.get("ultimo_error"),
                    "latencia_ms": e.get("latencia_ms"), "capacidades": json.loads(e.get("capacidades") or "[]"), "detalle_estado": e.get("detalle"),
                    "ultima_sync_ts": e.get("ultima_sync_ts"),
                    "posiciones": (q1("SELECT COUNT(*) n FROM posiciones WHERE broker=? AND usuario_id=? AND abierta=1", (b["id"], uid)) or {}).get("n", 0),
                    "ejecuciones": (q1("SELECT COUNT(*) n FROM ejecuciones WHERE broker=? AND usuario_id=?", (b["id"], uid)) or {}).get("n", 0),
                    "permitido": interruptores.permitido(b["id"])[0]})
    return out


def actividad(uid, broker, limite=50):
    return q("SELECT ts,entorno,accion,ok,detalle,ms FROM actividad WHERE broker=? AND usuario_id=? ORDER BY id DESC LIMIT ?", (broker, uid, int(limite)))


# ------------------------------------------------------------------------------------------------ bucle de sincronización
ESTADO = {"vivo": False, "rondas": 0, "ultima_ts": None, "error": None}
_PARAR = threading.Event()


def ronda():
    ahora = int(time.time())
    for a in q("SELECT * FROM ajustes WHERE habilitado=1"):
        e = q1("SELECT * FROM estado WHERE broker=? AND usuario_id=?", (a["broker"], a["usuario_id"])) or {}
        if e.get("ultima_sync_ts") and ahora - e["ultima_sync_ts"] < a["sync_min"] * 60:
            continue
        try:
            diagnosticar(a["usuario_id"], a["broker"])
            sincronizar(a["usuario_id"], a["broker"])
        except Exception as ex:
            ESTADO["error"] = f"{a['broker']}: {type(ex).__name__}"
    ESTADO.update(rondas=ESTADO["rondas"] + 1, ultima_ts=int(time.time()))


def _bucle():
    ESTADO["vivo"] = True
    while not _PARAR.is_set():
        try:
            ronda()
        except Exception as e:
            ESTADO["error"] = f"{type(e).__name__}: {e}"[:200]
        _PARAR.wait(60)
    ESTADO["vivo"] = False


def iniciar():
    if not ESTADO["vivo"]:
        _PARAR.clear()
        threading.Thread(target=_bucle, name="titan-brokers-sync", daemon=True).start()


def detener():
    _PARAR.set()
