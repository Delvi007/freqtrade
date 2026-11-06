"""Contrato común de los 23 motores.

Cada motor declara: número, id, nombre, objetivo, métodos (y por qué), entradas, salidas, dependencias,
consumo esperado y comportamiento por nivel. `ejecutar(ctx)` devuelve SIEMPRE un ResultadoMotor:

    {"motor": id, "numero": n, "estado": ESTADO, "duracion_ms": int, "salida": {...},
     "notas": [...], "faltantes": [...], "error": str|None}

ESTADOS:
    completado   — hizo todo lo previsto para el nivel.
    simplificado — se redujo la carga (recursos) y se dice qué se recortó.
    sin_datos    — no había datos suficientes; NO se inventa nada.
    aplazado     — no se ejecutó por recursos/tiempo; se puede reintentar.
    error        — fallo inesperado; queda registrado en estado_motores.

ctx (contrato de entrada compartido):
    ctx["activo"]     dict del catálogo (simbolo, nombre, clase, ...)
    ctx["horizonte"]  id de niveles.HORIZONTES
    ctx["p"]          parámetros efectivos del nivel (tras el plan adaptativo)
    ctx["res"]        {motor_id: ResultadoMotor} de los motores ya ejecutados
    ctx["usuario_id"] dueño de la ejecución
"""
import json
import time
import traceback

from .. import db

ESTADOS = ("completado", "simplificado", "sin_datos", "aplazado", "error")
REGISTRO = {}


class SinDatos(Exception):
    """El motor no tiene datos suficientes: se informa, no se inventa."""


class Motor:
    numero = 0
    id = ""
    nombre = ""
    objetivo = ""
    metodos = ""           # algoritmos y justificación
    entradas = ()
    salidas = ()
    dependencias = ()      # ids de motores que deben ejecutarse antes
    consumo = "bajo"       # bajo | medio | alto
    niveles = ""           # qué cambia entre niveles
    en_analisis = True     # participa en el análisis de un activo

    def calcular(self, ctx):  # pragma: no cover - abstracto
        raise NotImplementedError

    def ficha(self):
        return {"numero": self.numero, "id": self.id, "nombre": self.nombre, "objetivo": self.objetivo,
                "metodos": self.metodos, "entradas": list(self.entradas), "salidas": list(self.salidas),
                "dependencias": list(self.dependencias), "consumo": self.consumo, "niveles": self.niveles}

    def ejecutar(self, ctx):
        t0 = time.monotonic()
        notas, faltantes, estado, salida, err = [], [], "completado", {}, None
        try:
            r = self.calcular(ctx) or {}
            salida = r.get("salida", r)
            notas = r.get("notas", [])
            faltantes = r.get("faltantes", [])
            estado = r.get("estado", "completado")
        except SinDatos as e:
            estado, faltantes = "sin_datos", [str(e)]
        except Exception as e:  # registrar sin tumbar al resto
            estado, err = "error", f"{type(e).__name__}: {e}"[:300]
            notas = [traceback.format_exc(limit=2)[-400:]]
        dur = int((time.monotonic() - t0) * 1000)
        res = {"motor": self.id, "numero": self.numero, "nombre": self.nombre, "estado": estado,
               "duracion_ms": dur, "salida": salida, "notas": notas, "faltantes": faltantes, "error": err}
        registrar_estado(self.id, estado, dur, notas[:1] if estado != "error" else None, err)
        return res


def registrar(cls):
    m = cls()
    assert m.id and m.numero and m.id not in REGISTRO, cls
    REGISTRO[m.id] = m
    return cls


def registrar_estado(motor, estado, dur, detalle=None, error=None):
    try:
        with db.tx() as c:
            c.execute("""INSERT INTO estado_motores(motor,ts,estado,duracion_ms,ejecuciones,errores,detalle,error) VALUES(?,?,?,?,1,?,?,?)
                         ON CONFLICT(motor) DO UPDATE SET ts=excluded.ts, estado=excluded.estado, duracion_ms=excluded.duracion_ms,
                         ejecuciones=ejecuciones+1, errores=errores+excluded.errores, detalle=excluded.detalle,
                         error=COALESCE(excluded.error, error)""",
                      (motor, int(time.time()), estado, dur, 1 if estado == "error" else 0,
                       json.dumps(detalle, ensure_ascii=False, default=str)[:500] if detalle else None, error))
    except Exception:
        pass


def resultado(ctx, motor_id):
    r = ctx["res"].get(motor_id)
    if not r or r["estado"] in ("error", "sin_datos", "aplazado"):
        return None
    return r["salida"]


def ordenados():
    return sorted(REGISTRO.values(), key=lambda m: m.numero)
