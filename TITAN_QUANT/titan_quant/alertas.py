"""Centro de alertas: registro permanente, leída/no leída, filtros, búsqueda, silenciar categorías y ocultar sin borrar."""
import json
import time

from . import db, historial

CATEGORIAS = {
    "oportunidad": "Oportunidades", "entrada": "Entradas nuevas", "escenario": "Cambios de escenario",
    "ruptura": "Rupturas de soportes y resistencias", "rechazo": "Rechazos de zonas", "tendencia": "Cambios de tendencia",
    "macro": "Eventos macroeconómicos", "noticia": "Noticias importantes", "conexion": "Errores de conexión",
    "integracion": "Fallos de integraciones", "riesgo": "Alertas de riesgo", "operacion": "Operaciones abiertas, cerradas o rechazadas",
    "sistema": "Sistema",
}
IMPORTANCIAS = ("baja", "media", "alta", "critica")
SONIDO_POR_DEFECTO = {"activado": False, "volumen": 0.6, "oportunidad": True, "entrada": True, "operacion": True, "critica": True}


def crear(uid, categoria, tipo, importancia="media", activo=None, mercado=None, direccion=None, precio_ref=None,
          horizonte=None, justificacion=None, motores=None, modalidad=None, datos=None, clave_dedupe=None, notificar=True):
    """Devuelve el id o None si ya existía la misma alerta (clave_dedupe): nunca se duplica ni suena dos veces."""
    if categoria not in CATEGORIAS:
        raise ValueError("Categoría de alerta desconocida")
    if importancia not in IMPORTANCIAS:
        raise ValueError("Importancia no válida")
    with db.tx() as c:
        cur = c.execute("""INSERT OR IGNORE INTO alertas(ts,usuario_id,categoria,tipo,importancia,activo,mercado,direccion,precio_ref,horizonte,
                           justificacion,motores,modalidad,clave_dedupe,datos) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (int(time.time()), uid, categoria, tipo[:120], importancia, activo, mercado, direccion, precio_ref, horizonte,
                         (justificacion or "")[:2000], json.dumps(motores or [], ensure_ascii=False), modalidad, clave_dedupe,
                         json.dumps(datos, ensure_ascii=False, default=str) if datos is not None else None))
        aid = cur.lastrowid if cur.rowcount else None
    if aid and notificar and importancia in ("alta", "critica") and not silenciada(uid, categoria):
        pref = db.cfg_usuario(uid, "notificaciones", {"telegram": True})
        if pref.get("telegram", True):
            from .motores import sistema
            sistema.enviar_telegram_fondo(f"TITAN · {CATEGORIAS[categoria]} · {tipo}\n{activo or ''} {direccion or ''}\n{(justificacion or '')[:500]}")
    return aid


def silenciada(uid, categoria):
    return db.q1("SELECT 1 x FROM alertas_silencio WHERE usuario_id=? AND categoria=?", (uid, categoria)) is not None


def silenciar(uid, categoria, si=True):
    if categoria not in CATEGORIAS:
        raise ValueError("Categoría desconocida")
    with db.tx() as c:
        if si:
            c.execute("INSERT OR IGNORE INTO alertas_silencio(usuario_id,categoria,ts) VALUES(?,?,?)", (uid, categoria, int(time.time())))
        else:
            c.execute("DELETE FROM alertas_silencio WHERE usuario_id=? AND categoria=?", (uid, categoria))
    db.auditar(uid, "silenciar_categoria" if si else "reactivar_categoria", "alerta_categoria", categoria)


def listar(uid, categoria=None, estado=None, importancia=None, buscar=None, ver="normal", limite=100, desde_id=None):
    """ver: normal (sin ocultas/archivadas) | ocultos | archivados | todo."""
    sql = ["SELECT a.*, v.estado AS visibilidad FROM alertas a LEFT JOIN visibilidad v ON v.usuario_id=a.usuario_id AND v.tipo='alerta' AND v.objeto_id=CAST(a.id AS TEXT) WHERE a.usuario_id=?"]
    args = [uid]
    if categoria:
        sql.append("AND a.categoria=?"); args.append(categoria)
    if estado:
        sql.append("AND a.estado=?"); args.append(estado)
    if importancia:
        sql.append("AND a.importancia=?"); args.append(importancia)
    if buscar:
        sql.append("AND (a.tipo LIKE ? OR a.justificacion LIKE ? OR a.activo LIKE ?)"); args += ["%" + buscar[:60] + "%"] * 3
    if desde_id:
        sql.append("AND a.id>?"); args.append(int(desde_id))
    sql.append({"normal": "AND v.estado IS NULL", "ocultos": "AND v.estado='oculto'", "archivados": "AND v.estado='archivado'"}.get(ver, ""))
    sql.append("ORDER BY a.id DESC LIMIT ?"); args.append(max(1, min(int(limite), 500)))
    filas = db.q(" ".join(sql), args)
    sil = {r["categoria"] for r in db.q("SELECT categoria FROM alertas_silencio WHERE usuario_id=?", (uid,))}
    for f in filas:
        f["motores"] = json.loads(f["motores"] or "[]")
        f["datos"] = json.loads(f["datos"]) if f["datos"] else None
        f["silenciada"] = f["categoria"] in sil
        f["categoria_nombre"] = CATEGORIAS.get(f["categoria"], f["categoria"])
    return filas


def marcar(uid, ids, leida=True):
    ids = [int(i) for i in ids][:500]
    if not ids:
        return 0
    with db.tx() as c:
        n = c.execute(f"UPDATE alertas SET estado=? WHERE usuario_id=? AND id IN ({','.join('?' * len(ids))})",
                      ["leida" if leida else "nueva", uid] + ids).rowcount
    return n


def contadores(uid):
    r = db.q1("""SELECT COUNT(*) total, COALESCE(SUM(a.estado='nueva'),0) nuevas,
                 COALESCE(SUM(a.estado='nueva' AND a.importancia='critica'),0) criticas
                 FROM alertas a LEFT JOIN visibilidad v ON v.usuario_id=a.usuario_id AND v.tipo='alerta' AND v.objeto_id=CAST(a.id AS TEXT)
                 WHERE a.usuario_id=? AND v.estado IS NULL""", (uid,))
    r["ultima_id"] = (db.q1("SELECT MAX(id) m FROM alertas WHERE usuario_id=?", (uid,)) or {}).get("m")
    return r


def ocultar(uid, ids):
    return historial.cambiar_visibilidad(uid, "alerta", ids, "oculto")


def desde_analisis(uid, res, analisis_id):
    """Crea las alertas que corresponden a un análisis (oportunidad o vigilancia), sin duplicar."""
    a = res["activo"]["simbolo"]
    fu = res.get("fusion") or {}
    motores = [m["motor"] for m in res["motores"] if m["estado"] in ("completado", "simplificado")]
    if res["hay_oportunidad"]:
        e = res["escenario"]
        crear(uid, "oportunidad", f"Oportunidad {e['direccion']} en {a}", "alta", a, res["fuente_datos"]["tipo"] if res.get("fuente_datos") else None,
              e["direccion"], e["precio_referencia"], res["horizonte"], " ".join(fu.get("justificacion", [])[:4]), motores,
              "analisis", {"analisis_id": analisis_id, "escenario": e},
              clave_dedupe=f"op|{a}|{res['horizonte']}|{e['direccion']}|{int(res['ts'] // 3600)}")
    for f in (res.get("motores") or []):
        if f["motor"] == "data" and f["estado"] == "sin_datos":
            crear(uid, "conexion", f"Sin datos de {a}", "media", a, justificacion="; ".join(f["faltantes"]), motores=["data"],
                  clave_dedupe=f"sd|{a}|{int(res['ts'] // 1800)}")
    mac = next((m for m in res["motores"] if m["motor"] == "macro" and m["estado"] == "completado"), None)
    if mac and mac["salida"].get("eventos_alto_impacto_6h"):
        ev = mac["salida"]["eventos"][0]
        crear(uid, "macro", ev.get("nombre") or "Evento macro", "alta", a, justificacion=ev.get("titulo"), motores=["macro"],
              clave_dedupe=f"mac|{ev.get('enlace')}")
