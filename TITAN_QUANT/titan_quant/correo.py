"""Envío de correo: verificación de cuenta, aviso de solicitud al administrador, aceptación y recuperación.

Se usa el SMTP configurado por la cuenta propietaria en Integraciones → Correo (SMTP).
Proveedores probados por su documentación pública:
  * Gmail: smtp.gmail.com:465 (SSL) con una CONTRASEÑA DE APLICACIÓN (requiere verificación en 2 pasos).
  * Brevo: smtp-relay.brevo.com:587 (STARTTLS) con el usuario y la clave SMTP de la cuenta Brevo (plan gratuito).
  * Hotmail/Outlook.com PERSONAL: Microsoft desactivó el acceso SMTP con contraseña (exige OAuth2): NO funciona.
Si no hay SMTP, el mensaje se guarda en datos/correo_saliente/ (permiso 600) y se muestra en la consola.
"""
import json
import os
import smtplib
import socket
import ssl
import time
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from . import config, db

PRESETS = {
    "gmail": {"host": "smtp.gmail.com", "puerto": "465", "seguridad": "ssl"},
    "brevo": {"host": "smtp-relay.brevo.com", "puerto": "587", "seguridad": "starttls"},
    "outlook_365": {"host": "smtp.office365.com", "puerto": "587", "seguridad": "starttls"},
    "otro": {},
}


def _smtp():
    dueno = db.q1("SELECT id FROM usuarios WHERE rol='propietario' ORDER BY id LIMIT 1")
    if not dueno:
        return None
    integ = db.q1("SELECT * FROM integraciones WHERE usuario_id=? AND proveedor='correo_smtp' AND activa=1", (dueno["id"],))
    if not integ:
        return None
    from .seguridad import boveda
    aj = json.loads(integ["ajustes"] or "{}")
    sec = boveda.leer(dueno["id"], "correo_smtp")
    if not aj.get("host") or not aj.get("usuario") or not sec.get("clave"):
        return None
    return {**aj, **sec}


def configurado():
    try:
        return _smtp() is not None
    except Exception:
        return False


def explicar_error(e, cfg=None):
    """Traduce los fallos SMTP a instrucciones concretas (sin incluir nunca la contraseña)."""
    host = (cfg or {}).get("host", "")
    if isinstance(e, smtplib.SMTPAuthenticationError):
        txt = (e.smtp_error or b"").decode("utf-8", "replace") if isinstance(e.smtp_error, bytes) else str(e.smtp_error)
        if "outlook" in host or "office365" in host or "basic authentication is disabled" in txt:
            return ("Microsoft rechazó el acceso: las cuentas personales de Hotmail/Outlook.com ya no permiten enviar por SMTP "
                    "con contraseña (exigen OAuth2). Usa Gmail con contraseña de aplicación o Brevo.")
        if "gmail" in host:
            return ("Gmail rechazó el usuario o la clave. Necesitas una CONTRASEÑA DE APLICACIÓN de 16 letras "
                    "(Cuenta de Google → Seguridad → Verificación en 2 pasos → Contraseñas de aplicaciones), no tu contraseña normal.")
        return f"El servidor rechazó el usuario o la clave ({e.smtp_code})."
    if isinstance(e, (socket.gaierror,)):
        return f"No se encuentra el servidor '{host}'. Revisa el nombre o la conexión a internet."
    if isinstance(e, (TimeoutError, socket.timeout, ConnectionRefusedError, OSError)) and not isinstance(e, smtplib.SMTPException):
        return f"No se pudo conectar con {host}: revisa puerto y seguridad (Gmail: 465 + ssl; Brevo: 587 + starttls)."
    if isinstance(e, smtplib.SMTPSenderRefused):
        return "El servidor no acepta ese remitente: usa como remitente el mismo correo con el que inicias sesión en el SMTP."
    if isinstance(e, smtplib.SMTPRecipientsRefused):
        return "El servidor rechazó la dirección de destino."
    return f"{type(e).__name__}: el envío falló."


def _guardar_local(destino, asunto, texto):
    config.asegurar_directorios()
    ruta = str(config.SALIDA_CORREO / (time.strftime("%Y%m%d_%H%M%S_") + destino.replace("@", "_at_").replace("/", "_")[:60] + ".txt"))
    fd = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(f"Para: {destino}\nAsunto: {asunto}\n\n{texto}\n")
    print(f"\n[CORREO NO CONFIGURADO] Mensaje para {destino} guardado en {ruta}\n{texto}\n", flush=True)
    return ruta


def _enviar_smtp(cfg, destino, asunto, texto):
    m = EmailMessage()
    remitente = cfg.get("remitente") or cfg.get("usuario")
    m["From"] = formataddr(("TITAN QUANT", remitente))
    m["To"] = destino
    m["Subject"] = asunto
    m["Message-ID"] = make_msgid(domain=remitente.split("@")[-1] if "@" in remitente else None)
    m.set_content(texto)
    puerto = int(cfg.get("puerto") or 587)
    ctx = ssl.create_default_context()
    if str(cfg.get("seguridad", "starttls")) == "ssl" or puerto == 465:
        with smtplib.SMTP_SSL(cfg["host"], puerto, context=ctx, timeout=25) as s:
            s.login(cfg["usuario"], cfg["clave"])
            s.send_message(m)
    else:
        with smtplib.SMTP(cfg["host"], puerto, timeout=25) as s:
            s.ehlo()
            s.starttls(context=ctx)
            s.ehlo()
            s.login(cfg["usuario"], cfg["clave"])
            s.send_message(m)


def enviar(destino, asunto, texto):
    """Devuelve 'smtp' o 'archivo'. Lanza RuntimeError con explicación si el SMTP configurado falla
    (el mensaje se guarda igualmente en datos/correo_saliente para no perderlo)."""
    cfg = _smtp()
    if not cfg:
        _guardar_local(destino, asunto, texto)
        return "archivo"
    try:
        _enviar_smtp(cfg, destino, asunto, texto)
        return "smtp"
    except Exception as e:
        _guardar_local(destino, asunto, texto)
        raise RuntimeError(explicar_error(e, cfg)) from None


def probar_config(cfg):
    """Solo inicia sesión (sin enviar). Lanza RuntimeError explicado si falla."""
    try:
        puerto = int(cfg.get("puerto") or 587)
        if str(cfg.get("seguridad")) == "ssl" or puerto == 465:
            s = smtplib.SMTP_SSL(cfg["host"], puerto, context=ssl.create_default_context(), timeout=20)
        else:
            s = smtplib.SMTP(cfg["host"], puerto, timeout=20)
            s.starttls(context=ssl.create_default_context())
        s.login(cfg["usuario"], cfg["clave"])
        s.quit()
    except Exception as e:
        raise RuntimeError(explicar_error(e, cfg)) from None
    return "Inicio de sesión SMTP correcto"


def base_url():
    """Nunca se usa la cabecera Host de la petición (evita enlaces de recuperación envenenados)."""
    pub = os.environ.get("TITAN_URL_PUBLICA", "").rstrip("/")
    if pub:
        return pub
    host = "127.0.0.1" if config.HOST in ("0.0.0.0", "::") else config.HOST
    return f"{'https' if config.HTTPS else 'http'}://{host}:{config.PUERTO}"


# ----------------------------------------------------------------- plantillas
NOTA_ENLACE = ("\n\nNota: el enlace abre TITAN en el dispositivo donde está instalado. Ábrelo desde el navegador "
               "de ese teléfono (o del equipo configurado en TITAN_URL_PUBLICA).")


def verificacion(u, tok):
    return enviar(u["correo"], "TITAN QUANT · confirma tu correo",
                  f"Hola {u['nombre']}:\n\nRecibimos tu solicitud de cuenta en TITAN QUANT.\n"
                  f"Confirma tu correo abriendo este enlace (válido {config.TOKEN_VERIF_HORAS} h):\n"
                  f"{base_url()}/api/auth/verificar?token={tok}\n\n"
                  "Si el administrador debe aprobar las cuentas nuevas, recibirás otro correo cuando la acepte.\n"
                  "Si no pediste esta cuenta, ignora este mensaje." + NOTA_ENLACE)


def aviso_solicitud(admin, nuevo):
    return enviar(admin["correo"], "TITAN QUANT · nueva solicitud de cuenta",
                  f"Hola {admin['nombre']}:\n\n{nuevo['nombre']} <{nuevo['correo']}> solicitó una cuenta en TITAN QUANT.\n"
                  f"Revísala en Administración: {base_url()}/#admin")


def aceptacion(u):
    return enviar(u["correo"], "TITAN QUANT · tu cuenta fue aceptada",
                  f"Hola {u['nombre']}:\n\nEl administrador aprobó tu cuenta. Ya puedes entrar en:\n{base_url()}\n" + NOTA_ENLACE)


def recuperacion(u, tok):
    return enviar(u["correo"], "TITAN QUANT · recuperar contraseña",
                  f"Para crear una contraseña nueva abre este enlace (válido {config.TOKEN_RESET_MIN} min, un solo uso):\n"
                  f"{base_url()}/#restablecer={tok}\n\nSi no lo pediste, ignora este mensaje: tu contraseña no cambia." + NOTA_ENLACE)


def prueba(destino):
    return enviar(destino, "TITAN QUANT · correo de prueba",
                  "Este es un correo de prueba de TITAN QUANT. Si lo recibes, el envío de verificaciones y aceptaciones funciona.")
