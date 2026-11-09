"""CONFIGURACIÓN E INTEGRACIONES: catálogo de proveedores, credenciales cifradas, estados y pruebas reales.

Estados: no_configurada · configurada · conectada · desconectada · error · deshabilitada · pendiente_autorizacion.
Nunca se marca "conectada" sin una comprobación real contra el servicio.
"""
import json
import time
import urllib.parse
import urllib.request

from . import db
from .seguridad import boveda

ESTADOS = ("no_configurada", "configurada", "conectada", "desconectada", "error", "deshabilitada", "pendiente_autorizacion")


def C(id_, etiqueta, secreto=False, requerido=True, tipo="text", opciones=None, ayuda=None):
    return {"id": id_, "etiqueta": etiqueta, "secreto": secreto, "requerido": requerido, "tipo": tipo, "opciones": opciones, "ayuda": ayuda}


CATALOGO = {
    "correo_smtp": {"nombre": "Correo (SMTP)", "grupo": "Correo electrónico", "ubicacion": "configuracion",
                    "descripcion": ("Envía la confirmación de cuenta, el aviso de solicitudes, la aceptación y la recuperación. "
                                    "Recomendado: Gmail con contraseña de aplicación, o Brevo. Hotmail/Outlook.com personal NO sirve: "
                                    "Microsoft desactivó el SMTP con contraseña."),
                    "campos": [C("proveedor_correo", "Proveedor", tipo="select", opciones=["gmail", "brevo", "outlook_365", "otro"],
                                 ayuda="gmail y brevo rellenan servidor, puerto y seguridad automáticamente"),
                               C("usuario", "Usuario SMTP (en Gmail: tu dirección @gmail.com)"),
                               C("clave", "Clave SMTP (en Gmail: contraseña de aplicación de 16 letras)", True),
                               C("remitente", "Remitente (normalmente el mismo correo)", requerido=False),
                               C("host", "Servidor SMTP", requerido=False), C("puerto", "Puerto", tipo="number", requerido=False),
                               C("seguridad", "Seguridad", tipo="select", opciones=["ssl", "starttls"], requerido=False)]},
    "telegram": {"nombre": "Telegram", "grupo": "Telegram", "ubicacion": "configuracion",
                 "descripcion": "Bot para alertas y para el menú interactivo existente.",
                 "campos": [C("token", "Token del bot (@BotFather)", True), C("chat_id", "ID del chat autorizado", True)]},
    "iqoption": {"nombre": "IQ Option", "grupo": "Brokers", "descripcion": "Adaptador NO OFICIAL (librería iqoptionapi). Solo lectura y cuenta PRACTICE.",
                 "campos": [C("correo", "Correo de la cuenta"), C("clave", "Contraseña", True)], "broker": True},
    "ctrader": {"nombre": "cTrader Open API", "grupo": "Brokers", "descripcion": "API oficial de Spotware con OAuth (permiso de trading). Opera cuentas DEMO y REAL por separado.",
                "campos": [C("client_id", "Client ID"), C("client_secret", "Client Secret", True),
                           C("redirect_uri", "Redirect URI", ayuda="Debe coincidir con la registrada en la app de cTrader"),
                           C("access_token", "Access token", True, requerido=False), C("refresh_token", "Refresh token", True, requerido=False)],
                "broker": True, "oauth": True},
}


def _http(url, cabeceras=None, datos=None, espera=15):
    req = urllib.request.Request(url, data=datos, headers={"User-Agent": "TITAN-QUANT/7", **(cabeceras or {})})
    with urllib.request.urlopen(req, timeout=espera) as r:
        return r.status, r.read()


def _fila(uid, prov):
    return db.q1("SELECT * FROM integraciones WHERE usuario_id=? AND proveedor=?", (uid, prov))


def estado_calculado(uid, prov, fila=None):
    fila = fila or _fila(uid, prov)
    cat = CATALOGO[prov]
    if fila and not fila["activa"]:
        return "deshabilitada"
    req = [c["id"] for c in cat["campos"] if c["requerido"]]
    if req:
        aj = json.loads(fila["ajustes"]) if fila else {}
        m = boveda.mascaras(uid, prov)
        tiene = all((k in m) or aj.get(k) not in (None, "") for k in req)
        if not tiene:
            return "no_configurada"
    if prov == "ctrader":
        if "access_token" not in boveda.mascaras(uid, prov):
            return "pendiente_autorizacion"
    if fila and fila["estado"] in ("conectada", "error", "desconectada"):
        return fila["estado"]
    return "configurada" if (req or fila) else "no_configurada"


def listar(uid):
    out = []
    for prov, cat in CATALOGO.items():
        fila = _fila(uid, prov)
        aj = json.loads(fila["ajustes"]) if fila else {}
        mas = boveda.mascaras(uid, prov)
        campos = []
        for c in cat["campos"]:
            v = {"id": c["id"], "etiqueta": c["etiqueta"], "secreto": c["secreto"], "requerido": c["requerido"],
                 "tipo": c["tipo"], "opciones": c["opciones"], "ayuda": c["ayuda"]}
            if c["secreto"]:
                v["mascara"] = (mas.get(c["id"]) or {}).get("mascara")      # nunca el valor
                v["guardado"] = c["id"] in mas
            else:
                v["valor"] = aj.get(c["id"])
            campos.append(v)
        out.append({"proveedor": prov, "nombre": cat["nombre"], "grupo": cat["grupo"], "descripcion": cat["descripcion"],
                    "campos": campos, "estado": estado_calculado(uid, prov, fila), "activa": bool(fila["activa"]) if fila else True,
                    "ultima_prueba_ts": fila["ultima_prueba_ts"] if fila else None, "resultado": fila["resultado"] if fila else None,
                    "error": fila["error"] if fila else None, "broker": bool(cat.get("broker")), "oauth": bool(cat.get("oauth")),
                    "ubicacion": cat.get("ubicacion", "integraciones")})
    return out


def guardar(uid, prov, valores):
    if prov not in CATALOGO:
        raise ValueError("Proveedor desconocido")
    cat = CATALOGO[prov]
    secretos, ajustes = {}, {}
    fila = _fila(uid, prov)
    previos = json.loads(fila["ajustes"]) if fila else {}
    for c in cat["campos"]:
        v = valores.get(c["id"])
        if v is None:
            continue
        v = str(v).strip()[:4000]
        if c["tipo"] == "number" and v and not v.isdigit():
            raise ValueError(f"{c['etiqueta']}: debe ser un número")
        if c["opciones"] and v and v not in c["opciones"]:
            raise ValueError(f"{c['etiqueta']}: opción no válida")
        (secretos if c["secreto"] else ajustes)[c["id"]] = v
    ajustes = {**previos, **{k: v for k, v in ajustes.items()}}
    if prov == "correo_smtp":
        from . import correo
        preset = correo.PRESETS.get(ajustes.get("proveedor_correo") or "otro", {})
        if ajustes.get("proveedor_correo") in ("gmail", "brevo"):
            ajustes.update(preset)                 # valores conocidos del proveedor
        else:
            for k, v in preset.items():
                ajustes.setdefault(k, v)
        if ajustes.get("usuario"):
            ajustes["usuario"] = ajustes["usuario"].strip()
        if not ajustes.get("host"):
            raise ValueError("Indica el servidor SMTP o elige gmail/brevo como proveedor.")
    boveda.guardar(uid, prov, secretos)
    with db.tx() as c:
        c.execute("INSERT INTO integraciones(usuario_id,proveedor,activa,estado,ajustes) VALUES(?,?,1,'configurada',?) "
                  "ON CONFLICT(usuario_id,proveedor) DO UPDATE SET ajustes=excluded.ajustes, estado='configurada', error=NULL",
                  (uid, prov, json.dumps(ajustes, ensure_ascii=False)))
    db.auditar(uid, "integracion_guardada", "integracion", prov, {"campos_publicos": sorted(ajustes), "campos_secretos": sorted(secretos)})
    return estado_calculado(uid, prov)


def activar(uid, prov, activa):
    if prov not in CATALOGO:
        raise ValueError("Proveedor desconocido")
    with db.tx() as c:
        c.execute("INSERT INTO integraciones(usuario_id,proveedor,activa,estado) VALUES(?,?,?,'configurada') "
                  "ON CONFLICT(usuario_id,proveedor) DO UPDATE SET activa=excluded.activa", (uid, prov, 1 if activa else 0))
    db.auditar(uid, "integracion_activada" if activa else "integracion_desactivada", "integracion", prov)


def eliminar(uid, prov):
    n = boveda.eliminar(uid, prov)
    with db.tx() as c:
        c.execute("DELETE FROM integraciones WHERE usuario_id=? AND proveedor=?", (uid, prov))
    db.auditar(uid, "integracion_eliminada", "integracion", prov, {"secretos_borrados": n})
    return n


def _config(uid, prov):
    fila = _fila(uid, prov)
    aj = json.loads(fila["ajustes"]) if fila else {}
    return {**aj, **boveda.leer(uid, prov)}


def _probar(uid, prov):
    cfg = _config(uid, prov)
    if prov == "telegram":
        st, b = _http(f"https://api.telegram.org/bot{cfg['token']}/getMe")
        d = json.loads(b)
        if not d.get("ok"):
            raise RuntimeError("Telegram rechazó el token")
        return "Bot @" + d["result"].get("username", "?")
    if prov == "correo_smtp":
        from . import correo
        return correo.probar_config(cfg)
    if prov == "iqoption":
        from .trader import iqoption
        return iqoption.probar(cfg)
    if prov == "ctrader":
        info = ctrader_cuentas(uid)
        cuentas = info["cuentas"]
        vivas = sum(1 for x in cuentas if x["real"])
        permiso = "con permiso de trading" if info.get("trading") else "SOLO LECTURA: vuelve a autorizar para operar"
        return f"{len(cuentas)} cuentas ({vivas} reales, {len(cuentas) - vivas} demo), {permiso}"
    raise ValueError("Sin prueba para " + prov)


def probar(uid, prov):
    if prov not in CATALOGO:
        raise ValueError("Proveedor desconocido")
    est = estado_calculado(uid, prov)
    if est in ("no_configurada", "deshabilitada"):
        return {"estado": est, "resultado": None, "error": "Configura y activa la integración antes de probarla."}
    try:
        res, estado, err = _probar(uid, prov), "conectada", None
    except Exception as e:
        res, estado = None, "error"
        err = f"{type(e).__name__}: {str(e)[:160]}"
        for k, v in _config(uid, prov).items():          # jamás devolver un secreto en un mensaje de error
            if v and len(str(v)) >= 6:
                err = err.replace(str(v), "••••")
    with db.tx() as c:
        c.execute("INSERT INTO integraciones(usuario_id,proveedor,activa,estado,ultima_prueba_ts,resultado,error) VALUES(?,?,1,?,?,?,?) "
                  "ON CONFLICT(usuario_id,proveedor) DO UPDATE SET estado=excluded.estado, ultima_prueba_ts=excluded.ultima_prueba_ts, "
                  "resultado=excluded.resultado, error=excluded.error", (uid, prov, estado, int(time.time()), res, err))
    if estado == "error":
        from . import alertas
        alertas.crear(uid, "integracion", f"Fallo de {CATALOGO[prov]['nombre']}", "media", justificacion=err, motores=["api"],
                      clave_dedupe=f"int|{prov}|{int(time.time() // 3600)}", notificar=False)
    return {"estado": estado, "resultado": res, "error": err}


# ----------------------------------------------------------------- cTrader: cuentas y símbolos por modalidad
def ctrader_cuentas(uid):
    """Cuentas vinculadas al token, marcadas DEMO o REAL. Se consulta por el host demo (la lista es la misma en ambos)."""
    from .trader.base import ErrorAdaptador
    from .trader.ctrader import CTrader
    try:
        info = CTrader(uid, "demo").cuentas()
    except ErrorAdaptador as e:
        raise RuntimeError(str(e)) from None
    permiso = str(info.get("permiso") or "")
    return {"cuentas": info["cuentas"], "permiso": permiso, "trading": (not permiso) or "TRADE" in permiso.upper() or permiso == "1"}


def ctrader_simbolos(uid, modalidad, ctid):
    from .trader.base import ErrorAdaptador
    from .trader.ctrader import CTrader
    try:
        return CTrader(uid, modalidad, ctid).simbolos()
    except ErrorAdaptador as e:
        raise RuntimeError(str(e)) from None


# ----------------------------------------------------------------- cTrader OAuth dentro de TITAN
AUTH_URL = "https://id.ctrader.com/my/settings/openapi/grantingaccess/"
TOKEN_URL = "https://openapi.ctrader.com/apps/token"


def ctrader_url_autorizacion(uid, state):
    cfg = _config(uid, "ctrader")
    if not cfg.get("client_id") or not cfg.get("redirect_uri"):
        raise ValueError("Guarda primero Client ID, Client Secret y Redirect URI.")
    db.set_cfg_usuario(uid, "ctrader_oauth_state", {"state": state, "ts": int(time.time())})
    return AUTH_URL + "?" + urllib.parse.urlencode({"client_id": cfg["client_id"], "redirect_uri": cfg["redirect_uri"],
                                                     "scope": "trading", "product": "web", "state": state})


def ctrader_intercambiar(uid, code, state):
    guardado = db.cfg_usuario(uid, "ctrader_oauth_state") or {}
    if not state or state != guardado.get("state") or time.time() - guardado.get("ts", 0) > 900:
        raise ValueError("Estado OAuth no válido o caducado (protección CSRF).")
    cfg = _config(uid, "ctrader")
    q = urllib.parse.urlencode({"grant_type": "authorization_code", "code": code, "redirect_uri": cfg["redirect_uri"],
                                "client_id": cfg["client_id"], "client_secret": cfg["client_secret"]})
    st, b = _http(TOKEN_URL + "?" + q, espera=25)
    d = json.loads(b)
    if not d.get("accessToken"):
        raise RuntimeError(d.get("description") or d.get("errorCode") or "cTrader no devolvió token")
    boveda.guardar(uid, "ctrader", {"access_token": d["accessToken"], "refresh_token": d.get("refreshToken")})
    db.set_cfg_usuario(uid, "ctrader_oauth_state", None)
    return probar(uid, "ctrader")
