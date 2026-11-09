"""Historial unificado con OCULTAR / ARCHIVAR (lógico) y ELIMINACIÓN PERMANENTE separada.

- Ocultar: deja de verse en la vista normal; el registro original no se toca.
- Archivar: se guarda aparte; se puede consultar en "archivados" y restaurar.
- Eliminar permanentemente: procedimiento distinto, solo para análisis ya archivados, con frase de confirmación,
  y queda registrado en auditoría. Operaciones, alertas, decisiones del bot y auditoría NUNCA se eliminan:
  forman parte de los resultados contables y de auditoría.
Limpiar la vista no altera métricas, informes ni registros: todas las estadísticas leen las tablas originales.
"""
import json
import sqlite3
import time

from . import config, db

TIPOS = {"analisis": "Análisis", "alerta": "Alertas",
         "operacion_demo": "Operaciones · cTrader (DEMO)", "operacion_binaria": "Operaciones · Binarias (IQ Option PRACTICE)",
         "operacion_real": "Operaciones · REAL (bloqueada)",
         "decision_demo": "Bot · cTrader (DEMO)", "decision_binaria": "Bot · Binarias (IQ Option PRACTICE)", "decision_real": "Bot · REAL (bloqueada)",
         "config": "Cambios de configuración", "evento": "Eventos relevantes", "plan": "Planes (web)",
         "lab": "Laboratorio · ARCHIVO de la simulación retirada"}
FRASE_ELIMINAR = "ELIMINAR PERMANENTEMENTE"


def cambiar_visibilidad(uid, tipo, ids, estado):
    if tipo not in TIPOS:
        raise ValueError("Tipo desconocido")
    if estado not in ("oculto", "archivado", "visible"):
        raise ValueError("Estado no válido")
    ids = [str(int(i)) for i in ids][:500]
    with db.tx() as c:
        for i in ids:
            if estado == "visible":
                c.execute("DELETE FROM visibilidad WHERE usuario_id=? AND tipo=? AND objeto_id=?", (uid, tipo, i))
            else:
                c.execute("INSERT INTO visibilidad(usuario_id,tipo,objeto_id,estado,ts) VALUES(?,?,?,?,?) "
                          "ON CONFLICT(usuario_id,tipo,objeto_id) DO UPDATE SET estado=excluded.estado, ts=excluded.ts",
                          (uid, tipo, i, estado, int(time.time())))
    db.auditar(uid, {"oculto": "ocultar_vista", "archivado": "archivar", "visible": "restaurar_vista"}[estado], tipo, ",".join(ids)[:500])
    return len(ids)


def _vis(uid, tipo):
    return {r["objeto_id"]: r["estado"] for r in db.q("SELECT objeto_id, estado FROM visibilidad WHERE usuario_id=? AND tipo=?", (uid, tipo))}


def _filtrar(filas, vis, ver):
    out = []
    for f in filas:
        e = vis.get(str(f["id"]))
        f["visibilidad"] = e or "visible"
        if (ver == "normal" and e is None) or (ver == "ocultos" and e == "oculto") or (ver == "archivados" and e == "archivado") or ver == "todo":
            out.append(f)
    return out


def _legado(nombre, sql, args=()):
    ruta = config.RAIZ / nombre
    if not ruta.exists():
        return []
    try:
        c = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True, timeout=5)
        c.row_factory = sqlite3.Row
        filas = [dict(r) for r in c.execute(sql, args).fetchall()]
        c.close()
        return filas
    except sqlite3.Error:
        return []


def listar(uid, tipo, ver="normal", limite=100, es_propietario=False):
    limite = max(1, min(int(limite), 500))
    if tipo == "analisis":
        filas = db.q("SELECT id, ts, simbolo, horizonte, nivel, direccion, probabilidad, hay_oportunidad, fuente_datos FROM analisis WHERE usuario_id=? ORDER BY id DESC LIMIT ?", (uid, limite * 3))
        for f in filas:
            f["modalidad"] = "analisis"
            f["fuente_datos"] = json.loads(f["fuente_datos"] or "null")
    elif tipo == "alerta":
        from . import alertas
        filas = alertas.listar(uid, ver="todo", limite=limite * 3)
    elif tipo.startswith(("operacion_", "decision_")):          # cada cuenta en SU base: nunca se mezclan
        from .trader import almacen
        clase, mod = tipo.split("_", 1)
        tabla = "operaciones" if clase == "operacion" else "decisiones_bot"
        filas = almacen.q(mod, f"SELECT * FROM {tabla} WHERE usuario_id=? ORDER BY id DESC LIMIT ?", (uid, limite * 3))
    elif tipo == "config":
        filas = db.q("SELECT * FROM auditoria WHERE usuario_id=? AND accion='cambio_configuracion' ORDER BY id DESC LIMIT ?", (uid, limite * 3))
    elif tipo == "evento":
        filas = db.q("SELECT * FROM auditoria WHERE usuario_id=? AND accion<>'cambio_configuracion' ORDER BY id DESC LIMIT ?", (uid, limite * 3))
    elif tipo == "plan":
        filas = _legado("titan_planes.db", "SELECT id, creado_ts ts, simbolo, mostrar, modo, direccion, tipo, entrada, stop, tp1, tp2, estado, resultado, r_final FROM planes ORDER BY id DESC LIMIT ?", (limite * 3,)) if es_propietario else []
        for f in filas:
            f["modalidad"] = "archivo_simulacion"
    elif tipo == "lab":
        filas = _legado("titan_lab.db", "SELECT id, motor, creado_ts ts, simbolo, estrategia, direccion, estado, resultado, r_neto FROM lab_trades ORDER BY id DESC LIMIT ?", (limite * 3,)) if es_propietario else []
        for f in filas:
            f["modalidad"] = "archivo_simulacion"
    else:
        raise ValueError("Tipo desconocido")
    return _filtrar(filas, _vis(uid, tipo), ver)[:limite]


def eliminar_permanente(uid, ids, frase, es_propietario):
    if not es_propietario:
        raise PermissionError("Solo la cuenta propietaria puede eliminar permanentemente.")
    if frase != FRASE_ELIMINAR:
        raise ValueError(f"Escribe exactamente: {FRASE_ELIMINAR}")
    ids = [int(i) for i in ids][:200]
    arch = {int(k) for k, v in _vis(uid, "analisis").items() if v == "archivado"}
    no = [i for i in ids if i not in arch]
    if no:
        raise ValueError("Solo se pueden eliminar análisis ARCHIVADOS. No archivados: " + ", ".join(map(str, no[:10])))
    with db.tx() as c:
        n = c.execute(f"DELETE FROM analisis WHERE usuario_id=? AND id IN ({','.join('?' * len(ids))})", [uid] + ids).rowcount
        c.execute(f"DELETE FROM visibilidad WHERE usuario_id=? AND tipo='analisis' AND objeto_id IN ({','.join('?' * len(ids))})", [uid] + [str(i) for i in ids])
    db.auditar(uid, "eliminacion_permanente", "analisis", ",".join(map(str, ids)), {"n": n})
    return n
