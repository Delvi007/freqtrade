"""Cuentas de usuario: registro, verificación por correo, inicio de sesión, sesiones, recuperación y eventos.

Reglas que se cumplen aquí (orden maestra, sección 10 y 18):
  * Contraseñas con hash scrypt y sal; nunca en texto plano.
  * Mismo mensaje y tiempo parecido cuando un correo no existe (no se enumeran cuentas).
  * Bloqueo temporal tras INTENTOS_MAX fallos; límite de peticiones por IP (limites.py).
  * Tokens de verificación/restablecimiento aleatorios, guardados como hash, temporales y de un solo uso.
  * Sesiones con token aleatorio (cookie HttpOnly) guardado como hash, caducidad y cierre remoto.
  * El primer usuario registrado es el PROPIETARIO.
"""
import re
import time

from .. import config, db
from . import cripto

RX_CORREO = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,190}\.[A-Za-z]{2,24}$")


class ErrorCuenta(ValueError):
    pass


def _ahora():
    return int(time.time())


def evento(uid, tipo, ip=None, detalle=None):
    with db.tx() as c:
        c.execute("INSERT INTO eventos_seguridad(ts,usuario_id,tipo,ip,detalle) VALUES(?,?,?,?,?)",
                  (_ahora(), uid, tipo, (ip or "")[:64], (detalle or "")[:300]))


def validar_clave(clave, clave2=None, correo="", nombre=""):
    if clave2 is not None and clave != clave2:
        raise ErrorCuenta("Las contraseñas no coinciden.")
    if len(clave) < config.CLAVE_MIN:
        raise ErrorCuenta(f"La contraseña debe tener al menos {config.CLAVE_MIN} caracteres.")
    if len(clave) > 256:
        raise ErrorCuenta("La contraseña es demasiado larga.")
    clases = sum(bool(re.search(p, clave)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]"))
    if clases < 3:
        raise ErrorCuenta("Usa al menos tres de estos tipos: minúsculas, mayúsculas, números y símbolos.")
    bajo = clave.lower()
    if correo and correo.split("@")[0].lower() in bajo and len(correo.split("@")[0]) >= 4:
        raise ErrorCuenta("La contraseña no puede contener tu correo.")
    if bajo in ("contraseña123!", "password123!", "titanquant123"):
        raise ErrorCuenta("Esa contraseña es demasiado común.")


def _publico(u):
    return {"id": u["id"], "correo": u["correo"], "nombre": u["nombre"], "rol": u["rol"],
            "verificado": bool(u["verificado"]), "creado_ts": u["creado_ts"],
            "admin": bool(u["rol"] == "propietario" or u["admin"]), "aprobado": bool(u["aprobado"]),
            "suspendido": bool(u["suspendido"]), "ultimo_acceso_ts": u["ultimo_acceso_ts"]}


def es_local(ip):
    """Petición hecha desde el propio dispositivo (el servidor escucha en 127.0.0.1 por defecto)."""
    return (ip or "") in ("127.0.0.1", "::1", "::ffff:127.0.0.1")


def requiere_aprobacion():
    return bool(db.cfg_sistema("registro_requiere_aprobacion", True))


def usuario(uid):
    u = db.q1("SELECT * FROM usuarios WHERE id=?", (uid,))
    return _publico(u) if u else None


def registrar(nombre, correo, clave, clave2, acepta, ip=None):
    """Devuelve (usuario, token_verificacion). Si el correo ya existe devuelve (None, None): el servidor
    responde el MISMO mensaje genérico. La PRIMERA cuenta creada desde el propio dispositivo (127.0.0.1)
    es la del administrador propietario y queda activada sin correo (token None)."""
    nombre = (nombre or "").strip()
    correo = (correo or "").strip().lower()
    if not (2 <= len(nombre) <= 80):
        raise ErrorCuenta("Escribe tu nombre (2 a 80 caracteres).")
    if not RX_CORREO.match(correo):
        raise ErrorCuenta("Correo electrónico no válido.")
    if not acepta:
        raise ErrorCuenta("Debes aceptar los términos y la política de privacidad.")
    validar_clave(clave, clave2, correo, nombre)
    if db.q1("SELECT id FROM usuarios WHERE correo=?", (correo,)):
        evento(None, "registro_duplicado", ip, correo[:3] + "…")
        return None, None
    h = cripto.hash_clave(clave)
    ahora = _ahora()
    aprobacion = requiere_aprobacion()
    with db.tx() as c:
        primero = c.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 0
        activar = primero and es_local(ip)
        cur = c.execute("INSERT INTO usuarios(correo,nombre,clave_hash,rol,verificado,aprobado,admin,acepta_terminos_ts,creado_ts,actualizado_ts) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (correo, nombre, h, "propietario" if primero else "usuario", 1 if activar else 0,
                         1 if (primero or not aprobacion) else 0, 1 if primero else 0, ahora, ahora, ahora))
        uid = cur.lastrowid
    evento(uid, "registro", ip, ("propietario" if primero else "usuario") + (" activado en el dispositivo" if activar else ""))
    if activar:
        return usuario(uid), None
    return usuario(uid), emitir_token(uid, "verificar")


def emitir_token(uid, tipo):
    t = cripto.token()
    dur = config.TOKEN_VERIF_HORAS * 3600 if tipo == "verificar" else config.TOKEN_RESET_MIN * 60
    with db.tx() as c:
        # un solo token vivo por usuario y tipo
        c.execute("UPDATE tokens SET usado_ts=? WHERE usuario_id=? AND tipo=? AND usado_ts IS NULL", (_ahora(), uid, tipo))
        c.execute("INSERT INTO tokens(hash,usuario_id,tipo,creado_ts,expira_ts) VALUES(?,?,?,?,?)",
                  (cripto.h_token(t), uid, tipo, _ahora(), _ahora() + dur))
    return t


def _consumir(t, tipo):
    if not t or len(t) > 200:
        return None
    with db.tx() as c:
        r = c.execute("SELECT * FROM tokens WHERE hash=? AND tipo=?", (cripto.h_token(t), tipo)).fetchone()
        if not r or r["usado_ts"] is not None or r["expira_ts"] < _ahora():
            return None
        c.execute("UPDATE tokens SET usado_ts=? WHERE hash=?", (_ahora(), r["hash"]))
        return r["usuario_id"]


def verificar_correo(t, ip=None):
    uid = _consumir(t, "verificar")
    if not uid:
        raise ErrorCuenta("El enlace de verificación no es válido o caducó.")
    with db.tx() as c:
        c.execute("UPDATE usuarios SET verificado=1, actualizado_ts=? WHERE id=?", (_ahora(), uid))
    evento(uid, "correo_verificado", ip)
    return usuario(uid)


def reenviar_verificacion(correo):
    u = db.q1("SELECT * FROM usuarios WHERE correo=?", ((correo or "").strip().lower(),))
    if not u or u["verificado"]:
        return None, None
    return _publico(u), emitir_token(u["id"], "verificar")


MSG_LOGIN = "Correo o contraseña incorrectos, o la cuenta está bloqueada temporalmente."


def iniciar_sesion(correo, clave, ip=None, agente=None, recordar=False):
    """Devuelve (usuario, token_sesion, csrf)."""
    correo = (correo or "").strip().lower()
    u = db.q1("SELECT * FROM usuarios WHERE correo=?", (correo,))
    if not u:
        cripto.verificar_falso(clave or "")
        evento(None, "login_fallido", ip, "correo desconocido")
        raise ErrorCuenta(MSG_LOGIN)
    if u["bloqueado_hasta"] > _ahora():
        cripto.verificar_falso(clave or "")
        evento(u["id"], "login_bloqueado", ip)
        raise ErrorCuenta(MSG_LOGIN)
    if not cripto.verificar_clave(clave or "", u["clave_hash"]):
        fallos = u["fallos"] + 1
        bloqueo = _ahora() + config.BLOQUEO_MIN * 60 if fallos >= config.INTENTOS_MAX else 0
        with db.tx() as c:
            c.execute("UPDATE usuarios SET fallos=?, bloqueado_hasta=? WHERE id=?", (0 if bloqueo else fallos, bloqueo, u["id"]))
        evento(u["id"], "cuenta_bloqueada" if bloqueo else "login_fallido", ip, f"fallo {fallos}")
        raise ErrorCuenta(MSG_LOGIN)
    if u["suspendido"]:
        evento(u["id"], "login_suspendido", ip)
        raise ErrorCuenta("Tu cuenta está suspendida. Contacta con el administrador.")
    if not u["verificado"] and u["rol"] == "propietario" and es_local(ip):
        # El propietario, con su contraseña y desde el propio dispositivo, no necesita correo para activarse.
        with db.tx() as c:
            c.execute("UPDATE usuarios SET verificado=1 WHERE id=?", (u["id"],))
        evento(u["id"], "propietario_activado_en_dispositivo", ip)
        u = db.q1("SELECT * FROM usuarios WHERE id=?", (u["id"],))
    if not u["verificado"]:
        evento(u["id"], "login_sin_verificar", ip)
        raise ErrorCuenta("Debes confirmar tu correo antes de entrar. Revisa tu bandeja (y la carpeta de spam) o pide un enlace nuevo.")
    if not u["aprobado"]:
        evento(u["id"], "login_pendiente_aprobacion", ip)
        raise ErrorCuenta("Tu solicitud está pendiente de aprobación por el administrador. Recibirás un correo cuando la acepte.")
    t, csrf = cripto.token(), cripto.token()
    dur = config.SESION_RECORDAR_DIAS * 86400 if recordar else config.SESION_HORAS * 3600
    with db.tx() as c:
        c.execute("UPDATE usuarios SET fallos=0, bloqueado_hasta=0, ultimo_acceso_ts=? WHERE id=?", (_ahora(), u["id"]))
        c.execute("INSERT INTO sesiones(id,usuario_id,csrf,creada_ts,expira_ts,ultimo_ts,ip,agente) VALUES(?,?,?,?,?,?,?,?)",
                  (cripto.h_token(t), u["id"], csrf, _ahora(), _ahora() + dur, _ahora(), (ip or "")[:64], (agente or "")[:200]))
    evento(u["id"], "login", ip)
    return _publico(u), t, csrf


def sesion(t):
    """Devuelve dict con usuario y csrf si el token es válido, o None."""
    if not t or len(t) > 200:
        return None
    s = db.q1("SELECT * FROM sesiones WHERE id=?", (cripto.h_token(t),))
    if not s or s["revocada"] or s["expira_ts"] < _ahora():
        return None
    if _ahora() - s["ultimo_ts"] > 60:
        with db.tx() as c:
            c.execute("UPDATE sesiones SET ultimo_ts=? WHERE id=?", (_ahora(), s["id"]))
    u = usuario(s["usuario_id"])
    if not u or u["suspendido"] or not u["aprobado"]:
        return None
    return {"usuario": u, "csrf": s["csrf"], "sesion_id": s["id"]}


def cerrar_sesion(t, uid=None, ip=None):
    with db.tx() as c:
        c.execute("UPDATE sesiones SET revocada=1 WHERE id=?", (cripto.h_token(t),))
    evento(uid, "logout", ip)


def cerrar_todas(uid, excepto=None, ip=None):
    with db.tx() as c:
        c.execute("UPDATE sesiones SET revocada=1 WHERE usuario_id=? AND id<>?", (uid, excepto or ""))
    evento(uid, "logout_todas", ip)


def sesiones(uid, actual=None):
    filas = db.q("SELECT id, creada_ts, ultimo_ts, expira_ts, ip, agente FROM sesiones WHERE usuario_id=? AND revocada=0 AND expira_ts>? ORDER BY ultimo_ts DESC",
                 (uid, _ahora()))
    for f in filas:
        f["actual"] = f["id"] == actual
        f["id"] = f["id"][:16]          # identificador parcial: nunca el hash completo
    return filas


def cerrar_sesion_id(uid, id_parcial, ip=None):
    s = db.q1("SELECT id FROM sesiones WHERE usuario_id=? AND substr(id,1,16)=? AND revocada=0", (uid, (id_parcial or "")[:16]))
    if not s:
        raise ErrorCuenta("Sesión no encontrada.")
    with db.tx() as c:
        c.execute("UPDATE sesiones SET revocada=1 WHERE id=?", (s["id"],))
    evento(uid, "sesion_cerrada_remota", ip)


def solicitar_restablecimiento(correo, ip=None):
    """Siempre responde igual. Devuelve (usuario, token) solo para que el servidor envíe el correo."""
    u = db.q1("SELECT * FROM usuarios WHERE correo=?", ((correo or "").strip().lower(),))
    if not u:
        evento(None, "reset_correo_desconocido", ip)
        return None, None
    evento(u["id"], "reset_solicitado", ip)
    return _publico(u), emitir_token(u["id"], "restablecer")


def restablecer(t, clave, clave2, ip=None):
    u0 = db.q1("SELECT u.* FROM tokens k JOIN usuarios u ON u.id=k.usuario_id WHERE k.hash=? AND k.tipo='restablecer'", (cripto.h_token(t or ""),))
    validar_clave(clave, clave2, u0["correo"] if u0 else "")
    uid = _consumir(t, "restablecer")
    if not uid:
        raise ErrorCuenta("El enlace de recuperación no es válido o caducó.")
    with db.tx() as c:
        c.execute("UPDATE usuarios SET clave_hash=?, fallos=0, bloqueado_hasta=0, verificado=1, actualizado_ts=? WHERE id=?",
                  (cripto.hash_clave(clave), _ahora(), uid))
        c.execute("UPDATE sesiones SET revocada=1 WHERE usuario_id=?", (uid,))
    evento(uid, "clave_restablecida", ip)
    return usuario(uid)


def cambiar_clave(uid, actual, nueva, nueva2, sesion_actual=None, ip=None):
    u = db.q1("SELECT * FROM usuarios WHERE id=?", (uid,))
    if not u or not cripto.verificar_clave(actual or "", u["clave_hash"]):
        evento(uid, "cambio_clave_fallido", ip)
        raise ErrorCuenta("La contraseña actual no es correcta.")
    validar_clave(nueva, nueva2, u["correo"])
    with db.tx() as c:
        c.execute("UPDATE usuarios SET clave_hash=?, actualizado_ts=? WHERE id=?", (cripto.hash_clave(nueva), _ahora(), uid))
        c.execute("UPDATE sesiones SET revocada=1 WHERE usuario_id=? AND id<>?", (uid, sesion_actual or ""))
    evento(uid, "clave_cambiada", ip)


def actualizar_perfil(uid, nombre):
    nombre = (nombre or "").strip()
    if not (2 <= len(nombre) <= 80):
        raise ErrorCuenta("Nombre no válido.")
    with db.tx() as c:
        c.execute("UPDATE usuarios SET nombre=?, actualizado_ts=? WHERE id=?", (nombre, _ahora(), uid))
    db.auditar(uid, "perfil_actualizado", "usuario", uid)
    return usuario(uid)


def eventos(uid, limite=50):
    return db.q("SELECT ts, tipo, ip, detalle FROM eventos_seguridad WHERE usuario_id=? ORDER BY id DESC LIMIT ?", (uid, limite))


def hay_usuarios():
    return db.q1("SELECT COUNT(*) n FROM usuarios")["n"] > 0
