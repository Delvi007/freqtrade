"""Base de datos independiente del bot de binarias (SQLite).

No usa binaria.db del módulo existente ni guarda credenciales.
Cada orden pasa por los estados: senal -> enviada | rechazada | desconocida -> cerrada.
"""
import sqlite3

NOMBRE_POR_DEFECTO = "binaria_bot.db"

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS senales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    activo TEXT NOT NULL,
    direccion TEXT NOT NULL,
    accion TEXT NOT NULL,
    motivo TEXT
);
CREATE TABLE IF NOT EXISTS ordenes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    senal_id INTEGER,
    ts INTEGER NOT NULL,
    activo TEXT NOT NULL,
    direccion TEXT NOT NULL,
    monto REAL NOT NULL,
    estado TEXT NOT NULL,
    orden_broker TEXT,
    resultado TEXT,
    neto REAL,
    motivo TEXT
);
"""


class Almacen:
    def __init__(self, ruta=NOMBRE_POR_DEFECTO):
        if not str(ruta).lower().endswith(".db"):
            raise ValueError("la ruta debe terminar en .db")
        self.ruta = ruta
        self.con = sqlite3.connect(ruta)
        self.con.executescript(_ESQUEMA)
        self.con.commit()

    def registrar_senal(self, ts, activo, direccion, accion, motivo=""):
        cur = self.con.execute(
            "INSERT INTO senales (ts, activo, direccion, accion, motivo) VALUES (?,?,?,?,?)",
            (int(ts), activo, direccion, accion, motivo))
        self.con.commit()
        return cur.lastrowid

    def registrar_orden(self, senal_id, ts, activo, direccion, monto, estado, orden_broker=None, motivo=""):
        cur = self.con.execute(
            "INSERT INTO ordenes (senal_id, ts, activo, direccion, monto, estado, orden_broker, motivo)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (senal_id, int(ts), activo, direccion, float(monto), estado, orden_broker, motivo))
        self.con.commit()
        return cur.lastrowid

    def cerrar_orden(self, orden_id, resultado, neto):
        self.con.execute("UPDATE ordenes SET estado='cerrada', resultado=?, neto=? WHERE id=?",
                         (resultado, float(neto), orden_id))
        self.con.commit()

    def pendientes(self):
        return [dict(zip(("id", "orden_broker", "monto"), r)) for r in self.con.execute(
            "SELECT id, orden_broker, monto FROM ordenes WHERE estado IN ('enviada','desconocida')")]

    def cerrar(self):
        self.con.close()
