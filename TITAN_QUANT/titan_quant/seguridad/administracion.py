"""Panel de administración: solicitudes de cuenta, aprobación con correo de aceptación, suspensión y administradores.

Privilegios:
  * PROPIETARIO (primera cuenta): todo, incluido nombrar o retirar administradores. No se puede suspender ni degradar.
  * ADMINISTRADOR: aprobar/rechazar solicitudes, suspender/reactivar usuarios normales, reenviar verificaciones,
    cerrar sesiones, ver el diagnóstico y los datos heredados (planes, laboratorio, historial del bot).
Todas las acciones quedan en auditoría.
"""
import time

from .. import correo, db
from . import cuentas


class ErrorAdmin(ValueError):
    pass


def es_admin(u):
    return bool(u and (u.get("rol") == "propietario" or u.get("admin")))


def _objetivo(uid):
    u = db.q1("SELECT * FROM usuarios WHERE id=?", (int(uid),))
    if not u:
        raise ErrorAdmin("Usuario no encontrado.")
    return u


def _proteger(actor, u):
    if u["rol"] == "propietario":
        raise ErrorAdmin("La cuenta propietaria no se puede modificar desde aquí.")
    if u["id"] == actor["id"]:
        raise ErrorAdmin("No puedes aplicarte esta acción a ti mismo.")
    if u["admin"] and actor["rol"] != "propietario":
        raise ErrorAdmin("Solo la cuenta propietaria puede modificar a otro administrador.")


def listar():
    filas = db.q("""SELECT id, correo, nombre, rol, admin, verificado, aprobado, suspendido, creado_ts, ultimo_acceso_ts,
                    bloqueado_hasta, fallos,
                    (SELECT COUNT(*) FROM sesiones s WHERE s.usuario_id=u.id AND s.revocada=0 AND s.expira_ts>?) sesiones
                    FROM usuarios u ORDER BY (aprobado=0 AND suspendido=0) DESC, id""", (int(time.time()),))
    for f in filas:
        f["admin"] = bool(f["rol"] == "propietario" or f["admin"])
        f["estado"] = ("suspendido" if f["suspendido"] else "pendiente_aprobacion" if not f["aprobado"]
                       else "sin_confirmar" if not f["verificado"] else "activo")
        f["bloqueo_temporal"] = f["bloqueado_hasta"] > time.time()
    return filas


def resumen():
    filas = listar()
    return {"total": len(filas), "pendientes": sum(f["estado"] == "pendiente_aprobacion" for f in filas),
            "requiere_aprobacion": cuentas.requiere_aprobacion(), "correo_configurado": correo.configurado()}


def _correo_seguro(fn, *a):
    """Envía y devuelve (canal, aviso). Un fallo de correo nunca deshace la acción del administrador."""
    try:
        return fn(*a), None
    except Exception as e:
        return "error", str(e)


def aprobar(actor, uid, ip=None):
    u = _objetivo(uid)
    if u["rol"] == "propietario":
        raise ErrorAdmin("La cuenta propietaria ya está aprobada.")
    with db.tx() as c:
        c.execute("UPDATE usuarios SET aprobado=1, verificado=1, suspendido=0, fallos=0, bloqueado_hasta=0, actualizado_ts=? WHERE id=?",
                  (int(time.time()), u["id"]))
    db.auditar(actor["id"], "usuario_aprobado", "usuario", u["id"], {"correo": u["correo"]})
    cuentas.evento(u["id"], "cuenta_aprobada", ip, f"por {actor['correo']}")
    canal, aviso = _correo_seguro(correo.aceptacion, cuentas.usuario(u["id"]))
    return {"correo": canal, "aviso_correo": aviso}


def rechazar(actor, uid, ip=None):
    u = _objetivo(uid)
    _proteger(actor, u)
    with db.tx() as c:
        c.execute("UPDATE usuarios SET aprobado=0, suspendido=1, actualizado_ts=? WHERE id=?", (int(time.time()), u["id"]))
        c.execute("UPDATE sesiones SET revocada=1 WHERE usuario_id=?", (u["id"],))
    db.auditar(actor["id"], "solicitud_rechazada", "usuario", u["id"], {"correo": u["correo"]})
    cuentas.evento(u["id"], "solicitud_rechazada", ip)
    return {}


def suspender(actor, uid, si=True, ip=None):
    u = _objetivo(uid)
    _proteger(actor, u)
    with db.tx() as c:
        c.execute("UPDATE usuarios SET suspendido=?, actualizado_ts=? WHERE id=?", (1 if si else 0, int(time.time()), u["id"]))
        if si:
            c.execute("UPDATE sesiones SET revocada=1 WHERE usuario_id=?", (u["id"],))
    db.auditar(actor["id"], "usuario_suspendido" if si else "usuario_reactivado", "usuario", u["id"])
    cuentas.evento(u["id"], "cuenta_suspendida" if si else "cuenta_reactivada", ip)
    return {}


def hacer_admin(actor, uid, si=True):
    if actor["rol"] != "propietario":
        raise ErrorAdmin("Solo la cuenta propietaria puede nombrar o retirar administradores.")
    u = _objetivo(uid)
    if u["rol"] == "propietario":
        raise ErrorAdmin("La cuenta propietaria ya tiene todos los privilegios.")
    if si and (not u["aprobado"] or u["suspendido"]):
        raise ErrorAdmin("Aprueba o reactiva la cuenta antes de hacerla administradora.")
    with db.tx() as c:
        c.execute("UPDATE usuarios SET admin=?, actualizado_ts=? WHERE id=?", (1 if si else 0, int(time.time()), u["id"]))
    db.auditar(actor["id"], "admin_concedido" if si else "admin_retirado", "usuario", u["id"])
    cuentas.evento(u["id"], "admin_concedido" if si else "admin_retirado", None, f"por {actor['correo']}")
    return {}


def cerrar_sesiones(actor, uid):
    u = _objetivo(uid)
    if u["id"] != actor["id"]:
        _proteger(actor, u)
    with db.tx() as c:
        n = c.execute("UPDATE sesiones SET revocada=1 WHERE usuario_id=? AND revocada=0", (u["id"],)).rowcount
    db.auditar(actor["id"], "sesiones_cerradas_admin", "usuario", u["id"], {"n": n})
    return {"sesiones_cerradas": n}


def desbloquear(actor, uid):
    u = _objetivo(uid)
    with db.tx() as c:
        c.execute("UPDATE usuarios SET fallos=0, bloqueado_hasta=0 WHERE id=?", (u["id"],))
    db.auditar(actor["id"], "bloqueo_temporal_retirado", "usuario", u["id"])
    return {}


def reenviar_verificacion(actor, uid):
    u = _objetivo(uid)
    if u["verificado"]:
        raise ErrorAdmin("Ese correo ya está confirmado.")
    tok = cuentas.emitir_token(u["id"], "verificar")
    canal, aviso = _correo_seguro(correo.verificacion, cuentas.usuario(u["id"]), tok)
    db.auditar(actor["id"], "verificacion_reenviada", "usuario", u["id"])
    return {"correo": canal, "aviso_correo": aviso}


def configurar(actor, requiere_aprobacion):
    db.set_cfg_sistema("registro_requiere_aprobacion", bool(requiere_aprobacion))
    db.auditar(actor["id"], "cambio_configuracion", "sistema", "registro_requiere_aprobacion", {"despues": bool(requiere_aprobacion)})
    return resumen()


def notificar_solicitud(nuevo):
    """Avisa a todos los administradores de una solicitud nueva: alerta en el panel (+Telegram) y correo."""
    from .. import alertas
    for a in db.q("SELECT id, correo, nombre FROM usuarios WHERE (rol='propietario' OR admin=1) AND suspendido=0"):
        alertas.crear(a["id"], "sistema", f"Nueva solicitud de cuenta: {nuevo['nombre']}", "alta",
                      justificacion=f"{nuevo['correo']} pidió acceso. Apruébala o recházala en Administración.",
                      clave_dedupe=f"solicitud|{nuevo['id']}")
        _correo_seguro(correo.aviso_solicitud, a, nuevo)
