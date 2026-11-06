"""Servidor web de TITAN QUANT: cuentas, sesiones, CSRF, límites, los 23 motores, bot operador, alertas e historial.

Extiende el servidor heredado (api_web.Handler): sus rutas siguen funcionando, pero ahora EXIGEN sesión.
Por defecto escucha solo en 127.0.0.1. Para la red local: TITAN_HOST=0.0.0.0 (sigue exigiendo sesión;
sin HTTPS las contraseñas viajan sin cifrar por la Wi-Fi, por eso se avisa al arrancar).
"""
import json
import secrets
import sys
import time
import traceback
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import api_web  # noqa: E402  (módulo heredado)

from . import VERSION, alertas, config, correo, db, historial, integraciones, niveles, recursos  # noqa: E402
from .motores import base as mbase  # noqa: E402
from .motores import nucleo, sistema  # noqa: E402
from .registro import limpiar, log  # noqa: E402
from .seguridad import administracion, boveda, cuentas, limites  # noqa: E402
from .seguridad.cuentas import ErrorCuenta  # noqa: E402
from .trader import autotrader  # noqa: E402

COOKIE = "tq_sesion"
MAX_CUERPO = 64 * 1024

RUTAS_PUBLICAS = {"/api/health", "/api/auth/estado", "/api/auth/verificar"}
POST_PUBLICOS = {"/api/auth/registro", "/api/auth/login", "/api/auth/olvide", "/api/auth/restablecer", "/api/auth/reenviar"}
LEGADO_GET_USUARIO = {"/api/assets", "/api/quotes", "/api/chart", "/api/mtf"}
LEGADO_GET_PROPIETARIO = {"/api/history", "/api/stats", "/api/alerts", "/api/plans"}
LEGADO_POST_USUARIO = {"/api/analyze", "/api/report"}
LEGADO_POST_PROPIETARIO = {"/api/plan", "/api/plan/cancel", "/api/plan/limpiar"}

CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "connect-src 'self'; font-src 'self' data:; media-src 'self' data: blob:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")


class Respuesta(Exception):
    def __init__(self, codigo, datos):
        super().__init__(codigo)
        self.codigo, self.datos = codigo, datos


def _rq(cond, msg="Petición no válida."):
    if not cond:
        raise ValueError(msg)


def _ints(v):
    if not isinstance(v, list):
        v = [v]
    return [int(x) for x in v if str(x).lstrip("-").isdigit()]


# ============================================================================ manejadores GET
def g_estado(h, q):
    return {"ok": True, "hay_usuarios": cuentas.hay_usuarios(), "correo_configurado": correo.configurado(), "version": VERSION,
            "local": cuentas.es_local(h.ip()), "requiere_aprobacion": cuentas.requiere_aprobacion()}


def g_yo(h, q):
    s = h.requerir()
    u = s["usuario"]
    return {"ok": True, "usuario": u, "csrf": s["csrf"], "preferencias": preferencias(u["id"])}


def g_sesiones(h, q):
    s = h.requerir()
    return {"ok": True, "sesiones": cuentas.sesiones(s["usuario"]["id"], s["sesion_id"])}


def g_eventos(h, q):
    return {"ok": True, "eventos": cuentas.eventos(h.requerir()["usuario"]["id"])}


def g_preferencias(h, q):
    return {"ok": True, "preferencias": preferencias(h.requerir()["usuario"]["id"])}


def g_motores(h, q):
    h.requerir()
    est = sistema.estado_sistema(rapido=True)
    fichas = {m.id: m.ficha() for m in mbase.REGISTRO.values()}
    for m in est["motores"]:
        m["ficha"] = fichas[m["id"]]
    return {"ok": True, "motores": est["motores"], "total": len(est["motores"])}


def g_sistema(h, q):
    h.requerir(propietario=True)
    est = sistema.estado_sistema(rapido=False)
    est["autotrader_vivo"] = autotrader.hilo_vivo()
    est["autotrader_error"] = autotrader._HILO["error"]
    return {"ok": True, **est}


def g_hardware(h, q):
    h.requerir()
    d = recursos.diagnostico(red=q.get("red") == "1")
    return {"ok": True, "diagnostico": d, "recomendacion": recursos.recomendar_nivel(d)}


def g_niveles(h, q):
    u = h.requerir()["usuario"]
    return {"ok": True, "niveles": niveles.NIVELES, "orden": niveles.ORDEN, "politicas": niveles.POLITICAS, "horizontes": niveles.HORIZONTES,
            "seleccion": {"nivel": db.cfg_usuario(u["id"], "nivel", "intermedio"), "politica": db.cfg_usuario(u["id"], "politica", "automatico")},
            "recomendacion": recursos.recomendar_nivel()}


def g_analisis(h, q):
    u = h.requerir()["usuario"]
    r = db.q1("SELECT * FROM analisis WHERE id=? AND usuario_id=?", (int(q.get("id") or 0), u["id"]))
    if not r:
        raise Respuesta(404, {"ok": False, "error": "Análisis no encontrado."})
    return {"ok": True, "id": r["id"], "resultado": json.loads(r["resultado"])}


def g_integraciones(h, q):
    u = h.requerir()["usuario"]
    return {"ok": True, "integraciones": integraciones.listar(u["id"]), "estados": integraciones.ESTADOS}


def g_ctrader_callback(h, q):
    u = h.requerir()["usuario"]
    try:
        integraciones.ctrader_intercambiar(u["id"], q.get("code", ""), q.get("state", ""))
        destino = "/#integraciones-ok"
    except Exception as e:
        log().warning("cTrader OAuth: %s", type(e).__name__)
        destino = "/#integraciones-error"
    raise Respuesta(302, destino)


def g_alertas(h, q):
    u = h.requerir()["usuario"]
    return {"ok": True, "alertas": alertas.listar(u["id"], q.get("categoria") or None, q.get("estado") or None, q.get("importancia") or None,
                                                  q.get("buscar") or None, q.get("ver") or "normal", int(q.get("limite") or 100), q.get("desde_id") or None),
            "contadores": alertas.contadores(u["id"])}


def g_alertas_contadores(h, q):
    return {"ok": True, **alertas.contadores(h.requerir()["usuario"]["id"])}


def g_alertas_categorias(h, q):
    u = h.requerir()["usuario"]
    sil = {r["categoria"] for r in db.q("SELECT categoria FROM alertas_silencio WHERE usuario_id=?", (u["id"],))}
    return {"ok": True, "categorias": [{"id": k, "nombre": v, "silenciada": k in sil} for k, v in alertas.CATEGORIAS.items()]}


def g_historial(h, q):
    s = h.requerir()
    u = s["usuario"]
    tipo = q.get("tipo") or "analisis"
    return {"ok": True, "tipo": tipo, "tipos": historial.TIPOS,
            "filas": historial.listar(u["id"], tipo, q.get("ver") or "normal", int(q.get("limite") or 100), administracion.es_admin(u))}


def _modalidad(x):
    m = x.get("modalidad") or "simulacion"
    _rq(m in autotrader.MODALIDADES)
    return m


def g_operador(h, q):
    """Estado de los TRES bots (simulación, demo y real); cada uno lee solo su propia base."""
    u = h.requerir()["usuario"]
    from .trader import almacen
    from .trader.ctrader import CTrader
    from .trader.iqoption import IQOption, disponible
    from .trader.simulador import Simulador
    bots = {m: {**autotrader.estado(u["id"], m), "abiertas": autotrader.abiertas(u["id"], m)} for m in autotrader.MODALIDADES}
    k = almacen.conocimiento()
    return {"ok": True, "bots": bots, "modalidad": _modalidad(q), "hilo_vivo": autotrader.hilo_vivo(), "resumen": autotrader.resumen(u["id"]),
            "requisitos_real": autotrader.requisitos_real(u["id"]), "conocimiento": k,
            "conocimiento_fusion": almacen.conocimiento("fusion"),
            "estrategias": autotrader.ESTRATEGIAS, "limites": autotrader.LIMITES, "frase_real": autotrader.FRASE_REAL,
            "brokers_por_modalidad": autotrader.BROKERS_POR_MODALIDAD, "simbolos_sugeridos": autotrader.SIMBOLOS_SUGERIDOS,
            "brokers": [Simulador().ficha(), {**IQOption({}).ficha(), "libreria_instalada": disponible()}, CTrader(cred={}).ficha()],
            "ctrader_autorizado": "access_token" in boveda.mascaras(u["id"], "ctrader"),  # solo se mira si existe, nunca el valor
            "nivel": db.cfg_usuario(u["id"], "nivel", "intermedio")}


def _filas_json(filas):
    for f in filas:
        f["controles"] = json.loads(f.get("controles") or "[]")
        f["motores"] = json.loads(f.get("motores") or "[]")
    return filas


def g_operaciones(h, q):
    u = h.requerir()["usuario"]
    from .trader import almacen
    m = _modalidad(q)
    sql, a = "SELECT * FROM operaciones WHERE usuario_id=?", [u["id"]]
    if q.get("estado"):
        sql += " AND estado=?"
        a.append(q["estado"])
    return {"ok": True, "modalidad": m, "operaciones": _filas_json(almacen.q(m, sql + " ORDER BY id DESC LIMIT 200", a))}


def g_decisiones(h, q):
    u = h.requerir()["usuario"]
    from .trader import almacen
    m = _modalidad(q)
    return {"ok": True, "modalidad": m,
            "decisiones": _filas_json(almacen.q(m, "SELECT * FROM decisiones_bot WHERE usuario_id=? ORDER BY id DESC LIMIT 200", (u["id"],)))}


def g_ctrader_cuentas(h, q):
    u = h.requerir()["usuario"]
    h.limite("integracion")
    try:
        info = integraciones.ctrader_cuentas(u["id"])
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    m = q.get("modalidad")
    if m in ("demo", "real"):
        info["cuentas"] = [c for c in info["cuentas"] if c["real"] == (m == "real")]
    return {"ok": True, **info}


def g_ctrader_simbolos(h, q):
    u = h.requerir()["usuario"]
    h.limite("integracion")
    m = q.get("modalidad")
    _rq(m in ("demo", "real") and str(q.get("cuenta") or "").isdigit())
    try:
        sims = integraciones.ctrader_simbolos(u["id"], m, int(q["cuenta"]))
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "simbolos": sorted((x["nombre"] for x in sims if x.get("nombre")), key=str)}


def g_diagnostico(h, q):
    h.requerir(propietario=True)
    from .seguridad import cripto
    return {"ok": True, "version": VERSION, "cifrado": cripto.algoritmo(), "host": config.HOST, "puerto": config.PUERTO,
            "https": config.HTTPS, "correo_configurado": correo.configurado(), "sistema": sistema.estado_sistema(rapido=False),
            "pruebas": db.cfg_sistema("ultima_bateria_pruebas"), "autotrader": {"vivo": autotrader.hilo_vivo(), "error": autotrader._HILO["error"]},
            "errores_motores": db.q("SELECT motor, error, ts FROM estado_motores WHERE error IS NOT NULL ORDER BY ts DESC LIMIT 20")}


RUTAS_GET = {
    "/api/auth/estado": g_estado, "/api/auth/yo": g_yo, "/api/auth/sesiones": g_sesiones,
    "/api/cuenta/eventos": g_eventos, "/api/cuenta/preferencias": g_preferencias,
    "/api/tq/motores": g_motores, "/api/tq/sistema": g_sistema, "/api/tq/hardware": g_hardware, "/api/tq/niveles": g_niveles,
    "/api/tq/analisis": g_analisis, "/api/tq/integraciones": g_integraciones,
    "/api/tq/integraciones/ctrader/callback": g_ctrader_callback,
    "/api/tq/alertas": g_alertas, "/api/tq/alertas/contadores": g_alertas_contadores, "/api/tq/alertas/categorias": g_alertas_categorias,
    "/api/tq/historial": g_historial, "/api/tq/operador": g_operador, "/api/tq/operador/operaciones": g_operaciones,
    "/api/tq/operador/decisiones": g_decisiones,
    "/api/tq/ctrader/cuentas": g_ctrader_cuentas, "/api/tq/ctrader/simbolos": g_ctrader_simbolos, "/api/tq/diagnostico": g_diagnostico,
}


# ============================================================================ preferencias
PREF_DEF = {"zona": "America/Santo_Domingo", "nivel": "intermedio", "politica": "automatico", "horizonte": "corto",
            "sonidos": alertas.SONIDO_POR_DEFECTO, "notificaciones": {"telegram": True}, "riesgo": {"capital": 1000.0, "riesgo_pct": 1.0}}


def preferencias(uid):
    return {k: db.cfg_usuario(uid, k, v) for k, v in PREF_DEF.items()}


def _validar_pref(k, v):
    if k == "zona":
        from zoneinfo import ZoneInfo
        ZoneInfo(str(v))
        return str(v)
    if k == "nivel":
        niveles.parametros(v)
        return v
    if k == "politica":
        return niveles.validar_politica(v)
    if k == "horizonte":
        return niveles.validar_horizonte(v)
    if k == "sonidos":
        _rq(isinstance(v, dict))
        out = dict(alertas.SONIDO_POR_DEFECTO)
        for kk in out:
            if kk in v:
                out[kk] = max(0.0, min(1.0, float(v[kk]))) if kk == "volumen" else bool(v[kk])
        return out
    if k == "notificaciones":
        _rq(isinstance(v, dict))
        return {"telegram": bool(v.get("telegram", True))}
    if k == "riesgo":
        cap, pct = float(v.get("capital")), float(v.get("riesgo_pct"))
        _rq(10 <= cap <= 1e9, "Capital fuera de rango.")
        _rq(0.05 <= pct <= 5, "El riesgo por operación debe estar entre 0,05 % y 5 %.")
        return {"capital": cap, "riesgo_pct": pct}
    raise ValueError("Preferencia desconocida")


# ============================================================================ manejadores POST
def _enviar_seguro(fn, *a):
    try:
        return fn(*a)
    except Exception as e:
        log().error("correo: %s", limpiar(str(e)))
        return "error"


def p_registro(h, d):
    h.limite("registro")
    generico = "Solicitud recibida. Si los datos son válidos, recibirás un correo para confirmar tu dirección."
    if d.get("web"):                         # campo trampa: los humanos no lo ven
        return {"ok": True, "mensaje": generico}
    if time.time() - float(d.get("t") or 0) / 1000 < 2:
        raise ValueError("Formulario enviado demasiado rápido. Inténtalo de nuevo.")
    u, tok = cuentas.registrar(d.get("nombre"), d.get("correo"), d.get("clave", ""), d.get("clave2", ""), bool(d.get("acepta")), h.ip())
    if u and tok is None:                    # primera cuenta creada en el propio dispositivo
        return {"ok": True, "activado": True,
                "mensaje": "Cuenta de ADMINISTRADOR creada y activada en este dispositivo. Ya puedes iniciar sesión."}
    if u:
        _enviar_seguro(correo.verificacion, u, tok)
        if not u["aprobado"]:
            try:
                administracion.notificar_solicitud(u)
            except Exception as e:
                log().error("aviso de solicitud: %s", type(e).__name__)
    extra = ""
    if cuentas.requiere_aprobacion():
        extra = " Después, el administrador debe aprobar la solicitud; te avisaremos por correo."
    if not correo.configurado():
        extra += " (El envío de correo aún no está configurado: el administrador puede aprobar tu cuenta directamente.)"
    return {"ok": True, "mensaje": generico + extra}


def p_reenviar(h, d):
    h.limite("olvide")
    u, tok = cuentas.reenviar_verificacion(d.get("correo"))
    if u and tok:
        _enviar_seguro(correo.verificacion, u, tok)
    return {"ok": True, "mensaje": "Si la cuenta existe y no está confirmada, te enviamos un enlace nuevo."}


def p_login(h, d):
    h.limite("login")
    u, tok, csrf = cuentas.iniciar_sesion(d.get("correo"), d.get("clave"), h.ip(), h.headers.get("User-Agent"), bool(d.get("recordar")))
    dur = config.SESION_RECORDAR_DIAS * 86400 if d.get("recordar") else None
    h.cookie_nueva = (tok, dur)
    return {"ok": True, "usuario": u, "csrf": csrf}


def p_logout(h, d):
    s = h.requerir()
    cuentas.cerrar_sesion(h.token_cookie(), s["usuario"]["id"], h.ip())
    h.cookie_nueva = ("", 0)
    return {"ok": True}


def p_logout_todas(h, d):
    s = h.requerir()
    cuentas.cerrar_todas(s["usuario"]["id"], s["sesion_id"], h.ip())
    return {"ok": True}


def p_cerrar_sesion(h, d):
    s = h.requerir()
    cuentas.cerrar_sesion_id(s["usuario"]["id"], d.get("id"), h.ip())
    return {"ok": True}


def p_olvide(h, d):
    h.limite("olvide")
    u, tok = cuentas.solicitar_restablecimiento(d.get("correo"), h.ip())
    if u and tok:
        _enviar_seguro(correo.recuperacion, u, tok)
    return {"ok": True, "mensaje": "Si el correo está registrado, recibirás un enlace para restablecer la contraseña."}


def p_restablecer(h, d):
    h.limite("restablecer")
    cuentas.restablecer(d.get("token"), d.get("clave", ""), d.get("clave2", ""), h.ip())
    return {"ok": True, "mensaje": "Contraseña actualizada. Ya puedes iniciar sesión."}


def p_cambiar_clave(h, d):
    s = h.requerir()
    h.limite("login")
    cuentas.cambiar_clave(s["usuario"]["id"], d.get("actual"), d.get("nueva", ""), d.get("nueva2", ""), s["sesion_id"], h.ip())
    return {"ok": True, "mensaje": "Contraseña cambiada. Se cerraron tus otras sesiones."}


def p_perfil(h, d):
    s = h.requerir()
    return {"ok": True, "usuario": cuentas.actualizar_perfil(s["usuario"]["id"], d.get("nombre"))}


def p_preferencias(h, d):
    uid = h.requerir()["usuario"]["id"]
    _rq(isinstance(d, dict) and d, "Sin cambios.")
    for k, v in d.items():
        db.set_cfg_usuario(uid, k, _validar_pref(k, v))
    return {"ok": True, "preferencias": preferencias(uid)}


def p_nivel(h, d):
    uid = h.requerir()["usuario"]["id"]
    if "nivel" in d:
        db.set_cfg_usuario(uid, "nivel", _validar_pref("nivel", d["nivel"]))
    if "politica" in d:
        db.set_cfg_usuario(uid, "politica", _validar_pref("politica", d["politica"]))
    return {"ok": True, "nivel": db.cfg_usuario(uid, "nivel", "intermedio"), "politica": db.cfg_usuario(uid, "politica", "automatico")}


def p_analizar(h, d):
    uid = h.requerir()["usuario"]["id"]
    h.limite("analizar")
    hz = niveles.validar_horizonte(d.get("horizonte") or db.cfg_usuario(uid, "horizonte", "corto"))
    res = nucleo.analizar(d.get("simbolo"), hz, db.cfg_usuario(uid, "nivel", "intermedio"), db.cfg_usuario(uid, "politica", "automatico"),
                          usuario_id=uid, riesgo=db.cfg_usuario(uid, "riesgo", PREF_DEF["riesgo"]))
    aid = nucleo.guardar(uid, res)
    alertas.desde_analisis(uid, res, aid)
    return {"ok": True, "id": aid, "resultado": res}


def p_integ_guardar(h, d):
    uid = h.requerir()["usuario"]["id"]
    h.limite("integracion")
    _rq(isinstance(d.get("valores"), dict))
    return {"ok": True, "estado": integraciones.guardar(uid, d.get("proveedor"), d["valores"])}


def p_integ_probar(h, d):
    uid = h.requerir()["usuario"]["id"]
    h.limite("integracion")
    return {"ok": True, **integraciones.probar(uid, d.get("proveedor"))}


def p_integ_activar(h, d):
    uid = h.requerir()["usuario"]["id"]
    integraciones.activar(uid, d.get("proveedor"), bool(d.get("activa")))
    return {"ok": True}


def p_integ_eliminar(h, d):
    uid = h.requerir()["usuario"]["id"]
    return {"ok": True, "secretos_borrados": integraciones.eliminar(uid, d.get("proveedor"))}


def p_ctrader_autorizar(h, d):
    uid = h.requerir()["usuario"]["id"]
    return {"ok": True, "url": integraciones.ctrader_url_autorizacion(uid, secrets.token_urlsafe(24))}


def p_alertas_marcar(h, d, leida):
    uid = h.requerir()["usuario"]["id"]
    return {"ok": True, "n": alertas.marcar(uid, _ints(d.get("ids", [])), leida)}


def p_alertas_vis(h, d, estado):
    uid = h.requerir()["usuario"]["id"]
    return {"ok": True, "n": historial.cambiar_visibilidad(uid, "alerta", _ints(d.get("ids", [])), estado)}


def p_alertas_silenciar(h, d):
    uid = h.requerir()["usuario"]["id"]
    alertas.silenciar(uid, d.get("categoria"), bool(d.get("silenciar", True)))
    return {"ok": True}


def p_historial(h, d, estado):
    uid = h.requerir()["usuario"]["id"]
    return {"ok": True, "n": historial.cambiar_visibilidad(uid, d.get("tipo"), _ints(d.get("ids", [])), estado)}


def p_historial_eliminar(h, d):
    s = h.requerir()
    u = s["usuario"]
    return {"ok": True, "n": historial.eliminar_permanente(u["id"], _ints(d.get("ids", [])), d.get("frase"), administracion.es_admin(u))}


def _clave_ok(uid, clave):
    from .seguridad import cripto
    fila = db.q1("SELECT clave_hash FROM usuarios WHERE id=?", (uid,))
    return cripto.verificar_clave(clave or "", fila["clave_hash"])


def p_op_ajustes(h, d):
    uid = h.requerir()["usuario"]["id"]
    _rq(isinstance(d.get("ajustes"), dict))
    return {"ok": True, "ajustes": autotrader.guardar_ajustes(uid, _modalidad(d), d["ajustes"])}


def p_op_estado(h, d):
    uid = h.requerir()["usuario"]["id"]
    m = _modalidad(d)
    confirmado = False
    if m == "real" and d.get("estado") == "activo":
        h.limite("login")
        confirmado = _clave_ok(uid, d.get("clave"))
        if not confirmado:
            raise PermissionError("Contraseña incorrecta: el bot REAL no se ha iniciado.")
        if not api_web_local(h):
            raise PermissionError("El bot REAL solo se inicia desde el propio dispositivo donde corre TITAN.")
    e = autotrader.cambiar_estado(uid, m, d.get("estado"), confirmado_real=confirmado)
    if e["estado"] == "activo":
        autotrader.iniciar_hilo()
    return {"ok": True, **e}


def p_op_ciclo(h, d):
    uid = h.requerir()["usuario"]["id"]
    h.limite("analizar")
    return {"ok": True, "ciclo": autotrader.ciclo(uid, _modalidad(d))}


def p_op_real(h, d):
    u = h.requerir()["usuario"]
    if d.get("deshabilitar"):
        autotrader.deshabilitar_real(u["id"])
        return {"ok": True}
    h.limite("login")
    autotrader.habilitar_real(u["id"], d.get("frase"), _clave_ok(u["id"], d.get("clave")), api_web_local(h))
    return {"ok": True}


def api_web_local(h):
    from .seguridad import cuentas as _c
    return _c.es_local(h.ip())


# ============================================================================ administración
def _admin(h):
    return h.requerir(propietario=True)["usuario"]


def g_admin_usuarios(h, q):
    _admin(h)
    return {"ok": True, "usuarios": administracion.listar(), **administracion.resumen()}


def p_admin(h, d, accion):
    actor = _admin(h)
    uid = int(d.get("id") or 0)
    if accion == "aprobar":
        r = administracion.aprobar(actor, uid, h.ip())
    elif accion == "rechazar":
        r = administracion.rechazar(actor, uid, h.ip())
    elif accion == "suspender":
        r = administracion.suspender(actor, uid, True, h.ip())
    elif accion == "reactivar":
        r = administracion.suspender(actor, uid, False, h.ip())
    elif accion == "hacer_admin":
        r = administracion.hacer_admin(actor, uid, True)
    elif accion == "quitar_admin":
        r = administracion.hacer_admin(actor, uid, False)
    elif accion == "cerrar_sesiones":
        r = administracion.cerrar_sesiones(actor, uid)
    elif accion == "desbloquear":
        r = administracion.desbloquear(actor, uid)
    elif accion == "reenviar":
        r = administracion.reenviar_verificacion(actor, uid)
    else:
        raise ValueError("Acción desconocida")
    return {"ok": True, **r}


def p_admin_config(h, d):
    return {"ok": True, **administracion.configurar(_admin(h), bool(d.get("requiere_aprobacion")))}


def p_admin_correo_prueba(h, d):
    actor = _admin(h)
    h.limite("integracion")
    if not correo.configurado():
        raise ValueError("El correo no está configurado. Ve a Configuración e integraciones → Correo (SMTP).")
    try:
        correo.prueba(actor["correo"])
    except RuntimeError as e:
        raise ValueError(str(e))
    return {"ok": True, "mensaje": f"Correo de prueba enviado a {actor['correo']}. Revisa también la carpeta de spam."}


RUTAS_GET["/api/admin/usuarios"] = g_admin_usuarios


RUTAS_POST = {
    "/api/auth/registro": p_registro, "/api/auth/reenviar": p_reenviar, "/api/auth/login": p_login, "/api/auth/logout": p_logout,
    "/api/auth/logout_todas": p_logout_todas, "/api/auth/sesiones/cerrar": p_cerrar_sesion, "/api/auth/olvide": p_olvide,
    "/api/auth/restablecer": p_restablecer, "/api/auth/cambiar_clave": p_cambiar_clave,
    "/api/cuenta/perfil": p_perfil, "/api/cuenta/preferencias": p_preferencias,
    "/api/tq/nivel": p_nivel, "/api/tq/analizar": p_analizar,
    "/api/tq/integraciones/guardar": p_integ_guardar, "/api/tq/integraciones/probar": p_integ_probar,
    "/api/tq/integraciones/activar": p_integ_activar, "/api/tq/integraciones/eliminar": p_integ_eliminar,
    "/api/tq/integraciones/ctrader/autorizar": p_ctrader_autorizar,
    "/api/tq/alertas/leer": lambda h, d: p_alertas_marcar(h, d, True), "/api/tq/alertas/noleer": lambda h, d: p_alertas_marcar(h, d, False),
    "/api/tq/alertas/ocultar": lambda h, d: p_alertas_vis(h, d, "oculto"), "/api/tq/alertas/restaurar": lambda h, d: p_alertas_vis(h, d, "visible"),
    "/api/tq/alertas/silenciar": p_alertas_silenciar,
    "/api/tq/historial/ocultar": lambda h, d: p_historial(h, d, "oculto"), "/api/tq/historial/archivar": lambda h, d: p_historial(h, d, "archivado"),
    "/api/tq/historial/restaurar": lambda h, d: p_historial(h, d, "visible"), "/api/tq/historial/eliminar_permanente": p_historial_eliminar,
    "/api/tq/operador/ajustes": p_op_ajustes, "/api/tq/operador/estado": p_op_estado, "/api/tq/operador/ciclo": p_op_ciclo,
    "/api/tq/operador/real": p_op_real,
    "/api/admin/config": p_admin_config, "/api/admin/correo_prueba": p_admin_correo_prueba,
    **{f"/api/admin/{a}": (lambda h, d, a=a: p_admin(h, d, a)) for a in
       ("aprobar", "rechazar", "suspender", "reactivar", "hacer_admin", "quitar_admin", "cerrar_sesiones", "desbloquear", "reenviar")},
}


# ============================================================================ handler
class Handler(api_web.Handler):
    server_version = "TITAN"
    sys_version = ""

    def __init__(self, *a, **k):
        self._sesion = None
        self.cookie_nueva = None
        super(api_web.Handler, self).__init__(*a, directory=str(config.WEB), **k)

    def finish(self):
        try:
            super().finish()
        finally:
            db.cerrar_hilo()          # cada petición corre en su hilo: cerrar su conexión SQLite
            from .trader import almacen
            almacen.cerrar_hilo()

    # ---------------------------------------------------------------- utilidades
    def ip(self):
        return self.client_address[0] if self.client_address else "?"

    def limite(self, accion):
        if not limites.permitir(accion, self.ip()):
            cuentas.evento(None, "limite_superado", self.ip(), accion)
            raise Respuesta(429, {"ok": False, "error": "Demasiadas solicitudes. Espera unos minutos."})

    def token_cookie(self):
        c = SimpleCookie()
        try:
            c.load(self.headers.get("Cookie", ""))
        except Exception:
            return None
        return c[COOKIE].value if COOKIE in c else None

    def sesion(self):
        if self._sesion is None:
            self._sesion = cuentas.sesion(self.token_cookie()) or False
        return self._sesion or None

    def requerir(self, propietario=False):
        s = self.sesion()
        if not s:
            raise Respuesta(401, {"ok": False, "error": "Inicia sesión.", "auth": True})
        if propietario and not administracion.es_admin(s["usuario"]):
            raise Respuesta(403, {"ok": False, "error": "Solo administradores."})
        return s

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Content-Security-Policy", CSP)
        if config.HTTPS:
            self.send_header("Strict-Transport-Security", "max-age=31536000")
        if self.cookie_nueva is not None:
            tok, dur = self.cookie_nueva
            partes = [f"{COOKIE}={tok}", "Path=/", "HttpOnly", "SameSite=Lax"]
            if config.HTTPS:
                partes.append("Secure")
            if dur is not None:
                partes.append(f"Max-Age={dur}")
            self.send_header("Set-Cookie", "; ".join(partes))
            self.cookie_nueva = None
        super().end_headers()

    def log_message(self, fmt, *args):
        try:
            log().info("%s %s", self.ip(), limpiar(fmt % args).split("?")[0])
        except Exception:
            pass

    def enviar_json(self, codigo, datos):
        if codigo >= 500 and isinstance(datos, dict) and "error" in datos:
            ref = secrets.token_hex(4)
            log().error("500 [%s] %s", ref, limpiar(datos.get("error")))
            datos = {"ok": False, "error": f"Error interno (referencia {ref}). Consulta el registro del servidor."}
        super().enviar_json(codigo, datos)

    def redirigir(self, destino):
        self.send_response(302)
        self.send_header("Location", destino)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _origen_ok(self):
        o = self.headers.get("Origin") or self.headers.get("Referer")
        if not o:
            return True
        host = self.headers.get("Host", "")
        return urlparse(o).netloc == host

    def _leer_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n < 0 or n > MAX_CUERPO:
            raise Respuesta(413, {"ok": False, "error": "Solicitud demasiado grande."})
        if not n:
            return {}
        try:
            d = json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise Respuesta(400, {"ok": False, "error": "JSON no válido."})
        if not isinstance(d, dict):
            raise Respuesta(400, {"ok": False, "error": "Se esperaba un objeto JSON."})
        return d

    def _ejecutar(self, fn, *args):
        try:
            res = fn(self, *args)
            self.enviar_json(200, res)
        except Respuesta as r:
            if r.codigo == 302:
                self.redirigir(r.datos)
            else:
                self.enviar_json(r.codigo, r.datos)
        except (ErrorCuenta, ValueError, KeyError, TypeError) as e:
            msg = str(e) if isinstance(e, (ErrorCuenta, ValueError)) else "Petición no válida."
            self.enviar_json(400, {"ok": False, "error": msg[:300]})
        except PermissionError as e:
            self.enviar_json(403, {"ok": False, "error": str(e)[:300]})
        except Exception as e:
            ref = secrets.token_hex(4)
            log().error("500 [%s] %s %s", ref, type(e).__name__, limpiar(traceback.format_exc(limit=4)))
            self.enviar_json(500, {"ok": False, "error": f"Error interno (referencia {ref})."})

    # ---------------------------------------------------------------- GET
    def do_GET(self):
        u = urlparse(self.path)
        ruta = u.path
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if ruta.startswith("/api/") and not limites.permitir("api", self.ip()):
            return self.enviar_json(429, {"ok": False, "error": "Demasiadas solicitudes."})
        if ruta == "/api/auth/verificar":
            try:
                cuentas.verificar_correo(q.get("token"), self.ip())
                return self.redirigir("/#verificado")
            except ErrorCuenta:
                return self.redirigir("/#verificacion-fallida")
        if ruta in RUTAS_GET:
            return self._ejecutar(lambda h: RUTAS_GET[ruta](h, q))
        if ruta == "/api/health":
            return self.enviar_json(200, {"ok": True, "servicio": "TITAN_QUANT_API", "version": VERSION})
        if ruta.startswith("/api/"):
            try:
                if ruta.startswith("/api/lab/") or ruta in LEGADO_GET_PROPIETARIO:
                    self.requerir(propietario=True)
                elif ruta in LEGADO_GET_USUARIO:
                    self.requerir()
                else:
                    return self.enviar_json(404, {"ok": False, "error": "Endpoint desconocido."})
            except Respuesta as r:
                return self.enviar_json(r.codigo, r.datos)
            return super().do_GET()
        if ruta.endswith(".db") or "/." in ruta:
            return self.enviar_json(404, {"ok": False, "error": "No encontrado."})
        return super().do_GET()

    # ---------------------------------------------------------------- POST
    def do_POST(self):
        ruta = urlparse(self.path).path
        if not limites.permitir("api", self.ip()):
            return self.enviar_json(429, {"ok": False, "error": "Demasiadas solicitudes."})
        if not self._origen_ok():
            cuentas.evento(None, "origen_rechazado", self.ip(), ruta)
            return self.enviar_json(403, {"ok": False, "error": "Origen no permitido."})
        if ruta not in POST_PUBLICOS:
            s = self.sesion()
            if not s:
                return self.enviar_json(401, {"ok": False, "error": "Inicia sesión.", "auth": True})
            if not secrets.compare_digest(self.headers.get("X-CSRF-Token", ""), s["csrf"]):
                cuentas.evento(s["usuario"]["id"], "csrf_rechazado", self.ip(), ruta)
                return self.enviar_json(403, {"ok": False, "error": "Token CSRF no válido. Recarga la página."})
        if ruta in RUTAS_POST:
            try:
                d = self._leer_json()
            except Respuesta as r:
                return self.enviar_json(r.codigo, r.datos)
            return self._ejecutar(lambda h: RUTAS_POST[ruta](h, d))
        try:
            if ruta.startswith("/api/lab/") or ruta in LEGADO_POST_PROPIETARIO:
                self.requerir(propietario=True)
            elif ruta not in LEGADO_POST_USUARIO:
                return self.enviar_json(404, {"ok": False, "error": "Endpoint desconocido."})
        except Respuesta as r:
            return self.enviar_json(r.codigo, r.datos)
        return super().do_POST()


class Servidor(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def inicializar_bases_heredadas():
    """Crea (si faltan) las tablas de las bases heredadas para que una instalación nueva funcione desde cero."""
    hechas = []
    for nombre, fn in (("titan_activos.db", lambda: __import__("escenarios").conectar().close()),
                       ("titan_planes.db", lambda: __import__("plan_web")._con().close()),
                       ("titan_lab.db", lambda: __import__("lab_engine").init_db())):
        try:
            fn()
            hechas.append(nombre)
        except Exception as e:
            log().error("inicializar %s: %s", nombre, type(e).__name__)
    return hechas


def crear(host=None, puerto=None):
    config.asegurar_directorios()
    db.migrar()
    inicializar_bases_heredadas()
    api_web.HTML_DIR = config.WEB
    return Servidor((host or config.HOST, config.PUERTO if puerto is None else puerto), Handler)


def iniciar_fondo():
    try:
        import plan_web
        plan_web.iniciar_vigilante()
        print("  · Vigilante de planes: activo")
    except Exception as e:
        print("  · Vigilante de planes no iniciado:", type(e).__name__)
    try:
        import lab_engine
        lab_engine.iniciar()
        print("  · Laboratorio de Aprendizaje: activo")
    except Exception as e:
        print("  · Laboratorio no iniciado:", type(e).__name__)
    autotrader.iniciar_hilo()
    print("  · Bot operador (hilo): activo — solo opera si lo inicias desde la web")


def main():
    srv = crear()
    print(f"TITAN QUANT {VERSION}")
    print(f"  Abre en el navegador:  http://{'127.0.0.1' if config.HOST in ('0.0.0.0', '::') else config.HOST}:{config.PUERTO}")
    print(f"  Datos: {config.DATOS}")
    if config.HOST not in ("127.0.0.1", "localhost", "::1"):
        print("  AVISO: escuchando en la red local. Se exige sesión, pero sin HTTPS las contraseñas viajan sin cifrar por la Wi-Fi.")
    if not correo.configurado():
        print("  Correo SMTP no configurado: los enlaces de verificación y recuperación se mostrarán AQUÍ.")
    iniciar_fondo()
    print("  Ctrl+C para detener.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nDetenido.")


if __name__ == "__main__":
    main()
