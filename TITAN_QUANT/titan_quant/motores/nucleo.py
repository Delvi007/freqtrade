"""Motor 1 — TITAN CORE: coordina los 23 motores (análisis inmediato y vigilancia prospectiva).

Orden por dependencias (capas). Dentro de cada capa los motores se ejecutan en paralelo hasta la
concurrencia efectiva del plan adaptativo. Si se agota el presupuesto de tiempo, los motores que
faltan quedan APLAZADOS (y se informa), nunca se rellenan con datos inventados.
"""
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

from .. import config, db, niveles, recursos
from . import base
from .base import Motor, registrar

# importar registra los motores
from . import mercado, cuant, info, sistema  # noqa: F401

PRESUPUESTO_S = {"basico": 60, "intermedio": 90, "avanzado": 150, "super": 240}


@registrar
class MotorNucleo(Motor):
    numero, id, nombre = 1, "core", "TITAN CORE"
    objetivo = "Orquestar los motores, ordenar sus dependencias, repartir la carga y entregar un único resultado trazable."
    metodos = "Ordenación topológica por dependencias declaradas, ejecución por capas con hilos y presupuesto de tiempo por nivel."
    en_analisis = False

    def calcular(self, ctx):
        return {"salida": ctx.get("plan_core", {})}


def capas(ids):
    pend = {i: set(d for d in base.REGISTRO[i].dependencias if d in ids) for i in ids}
    out = []
    while pend:
        listos = sorted([i for i, d in pend.items() if not d], key=lambda x: base.REGISTRO[x].numero)
        if not listos:
            raise RuntimeError("Dependencias circulares entre motores: " + ", ".join(pend))
        out.append(listos)
        for i in listos:
            pend.pop(i)
        for d in pend.values():
            d.difference_update(listos)
    return out


def _ejecutar_en_hilo(mid, ctx):
    try:
        return base.REGISTRO[mid].ejecutar(ctx)
    finally:
        db.cerrar_hilo()          # cada hilo del pool cierra su conexión SQLite


def _estado_bot():
    try:
        return json.loads((config.RAIZ / ".estado_bot.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def resolver_activo(simbolo):
    import activos
    s = str(simbolo or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9.^=\-]{1,20}", s):
        raise ValueError("Símbolo no válido.")
    a = activos.buscar(s, _estado_bot().get("personalizados", []))
    return a or activos.personalizado(s)


def analizar(simbolo, horizonte="corto", nivel="intermedio", politica="automatico", usuario_id=None,
             cartera=None, riesgo=None, diag=None, presupuesto_s=None, serie=None):
    """serie: velas ya obtenidas (p. ej. del broker cTrader) para analizar con los mismos precios con los que se ejecuta."""
    niveles.validar_horizonte(horizonte)
    activo = resolver_activo(simbolo)
    t0 = time.monotonic()
    diag = diag or recursos.diagnostico(red=False)
    p, ajustes = recursos.plan_ejecucion(nivel, politica, diag)
    ctx = {"activo": activo, "horizonte": horizonte, "p": p, "politica": politica, "res": {}, "usuario_id": usuario_id,
           "diagnostico": diag, "ajustes_adaptativos": ajustes,
           "cartera": cartera if cartera is not None else _estado_bot().get("seleccion", []),
           "riesgo_usuario": riesgo, "serie_externa": serie}
    ids = [m.id for m in base.REGISTRO.values() if m.en_analisis]
    orden = capas(ids)
    limite = presupuesto_s or PRESUPUESTO_S[nivel]
    with ThreadPoolExecutor(max_workers=p["concurrencia"]) as ex:
        for capa in orden:
            if time.monotonic() - t0 > limite:
                for mid in capa:
                    ctx["res"][mid] = {"motor": mid, "numero": base.REGISTRO[mid].numero, "nombre": base.REGISTRO[mid].nombre,
                                       "estado": "aplazado", "duracion_ms": 0, "salida": {}, "notas": ["presupuesto de tiempo agotado"],
                                       "faltantes": [], "error": None}
                    base.registrar_estado(mid, "aplazado", 0)
                continue
            for r in ex.map(lambda mid: _ejecutar_en_hilo(mid, ctx), capa):
                ctx["res"][r["motor"]] = r
    resumen = {}
    for r in ctx["res"].values():
        resumen[r["estado"]] = resumen.get(r["estado"], 0) + 1
    ctx["plan_core"] = {"capas": orden, "concurrencia": p["concurrencia"], "presupuesto_s": limite,
                        "duracion_total_ms": int((time.monotonic() - t0) * 1000), "estados": resumen,
                        "motores_en_analisis": len(ids)}
    ctx["res"]["core"] = base.REGISTRO["core"].ejecutar(ctx)
    for mid in ("monitoring", "api", "web", "telegram"):
        ctx["res"][mid] = base.REGISTRO[mid].ejecutar(ctx)
    fu = base.resultado(ctx, "fusion") or {}
    dat = base.resultado(ctx, "data") or {}
    return {
        "ts": int(time.time()), "activo": {k: activo.get(k) for k in ("simbolo", "nombre", "clase", "categoria")},
        "horizonte": horizonte, "nivel": nivel, "politica": politica, "parametros": {k: p[k] for k in ("concurrencia", "montecarlo_sim", "backtest_barras", "ml_epocas")},
        "ajustes_adaptativos": ajustes, "fuente_datos": {k: dat.get(k) for k in ("proveedor", "simbolo_proveedor", "tipo", "intervalo", "rango", "calidad")} if dat else None,
        "hay_oportunidad": bool(fu.get("hay_oportunidad")), "direccion": fu.get("direccion"),
        "escenario": fu.get("escenario"), "fusion": fu,
        "informe_md": (base.resultado(ctx, "research") or {}).get("informe_md"),
        "motores": sorted(ctx["res"].values(), key=lambda r: r["numero"]),
    }


def guardar(uid, res):
    esc = res.get("escenario") or {}
    with db.tx() as c:
        cur = c.execute("INSERT INTO analisis(ts,usuario_id,simbolo,horizonte,nivel,politica,direccion,probabilidad,hay_oportunidad,fuente_datos,resultado) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (res["ts"], uid, res["activo"]["simbolo"], res["horizonte"], res["nivel"], res["politica"], res.get("direccion"),
                         esc.get("probabilidad"), int(res["hay_oportunidad"]), json.dumps(res.get("fuente_datos"), default=str),
                         json.dumps(res, ensure_ascii=False, default=str)))
        return cur.lastrowid
