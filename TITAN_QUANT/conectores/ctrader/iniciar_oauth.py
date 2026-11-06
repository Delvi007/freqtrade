import json
import os
import secrets
import requests

from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler

BASE = Path(__file__).resolve().parent
CONFIG = BASE / "ctrader_app.json"
TOKEN_FILE = BASE / "oauth_tokens.json"

AUTH_URL = "https://id.ctrader.com/my/settings/openapi/grantingaccess/"
TOKEN_URL = "https://openapi.ctrader.com/apps/token"

if not CONFIG.exists():
    raise SystemExit("ERROR: falta ctrader_app.json")

cfg = json.loads(CONFIG.read_text())

client_id = cfg.get("client_id", "").strip()
client_secret = cfg.get("client_secret", "").strip()
redirect_uri = cfg.get("redirect_uri", "").strip()

if not all((client_id, client_secret, redirect_uri)):
    raise SystemExit("ERROR: configuración incompleta.")

uri = urlparse(redirect_uri)

if uri.scheme != "http" or uri.hostname != "localhost":
    raise SystemExit("ERROR: Redirect URI debe utilizar localhost.")

if uri.path != "/callback" or not uri.port:
    raise SystemExit("ERROR: Redirect URI incorrecta.")

state = secrets.token_urlsafe(32)


def intercambiar_codigo(code):
    params = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret
    }

    print("\nIntercambiando código por tokens...")

    try:
        response = requests.get(
            TOKEN_URL,
            params=params,
            timeout=25
        )
    except requests.RequestException as exc:
        print("ERROR de comunicación:", type(exc).__name__)
        return False

    try:
        result = response.json()
    except ValueError:
        print("ERROR: cTrader devolvió una respuesta no JSON.")
        print("HTTP:", response.status_code)
        return False

    if not isinstance(result, dict):
        print("ERROR: respuesta OAuth no válida.")
        return False

    access = result.get("accessToken")
    refresh = result.get("refreshToken")

    if not response.ok or not access or not refresh:
        error = result.get("errorCode") or result.get("error") or "ERROR_DESCONOCIDO"
        description = (
            result.get("description")
            or result.get("errorDescription")
            or ""
        )

        print("ERROR OAuth:", error, description)
        print("HTTP:", response.status_code)
        return False

    secure_data = {
        "accessToken": access,
        "refreshToken": refresh,
        "expiresIn": result.get("expiresIn"),
        "tokenType": result.get("tokenType"),
        "clientId": client_id,
        "redirectUri": redirect_uri,
        "scope": "accounts"
    }

    temp = TOKEN_FILE.with_suffix(".tmp")

    try:
        temp.write_text(json.dumps(secure_data))
        os.chmod(temp, 0o600)
        temp.replace(TOKEN_FILE)
        os.chmod(TOKEN_FILE, 0o600)
    except OSError as exc:
        print("ERROR guardando tokens:", type(exc).__name__)
        return False

    print("\n========== AUTENTICACIÓN ==========")
    print("Access Token: GUARDADO")
    print("Refresh Token: GUARDADO")
    print("Permiso: accounts")
    print("Archivo: oauth_tokens.json")
    print("Permisos:", oct(TOKEN_FILE.stat().st_mode & 0o777))
    print("Valores secretos: NO MOSTRADOS")

    return True


class CallbackHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path != "/callback":
            self.reply(404, "Ruta no válida.")
            return

        params = parse_qs(parsed.query)

        if params.get("state", [""])[0] != state:
            self.reply(400, "Estado OAuth incorrecto.")
            return

        error = params.get("error", [None])[0]

        if error:
            self.reply(400, "cTrader rechazó la autorización.")
            print("ERROR de autorización:", error)
            self.server.done = True
            return

        code = params.get("code", [None])[0]

        if not code:
            self.reply(400, "No se recibió código OAuth.")
            self.server.done = True
            return

        self.reply(200, "Autorización recibida. TITAN está procesándola.")

        print("\nAUTORIZACIÓN RECIBIDA.")
        print("Código recibido: NO MOSTRADO")

        success = intercambiar_codigo(code)

        self.server.success = success
        self.server.done = True

    def reply(self, status, message):
        body = (
            "<!doctype html><html><meta charset='utf-8'>"
            f"<body><h2>{message}</h2></body></html>"
        ).encode()

        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


server = HTTPServer(("127.0.0.1", uri.port), CallbackHandler)
server.timeout = 1
server.done = False
server.success = False

auth_params = {
    "client_id": client_id,
    "redirect_uri": redirect_uri,
    "scope": "accounts",
    "product": "web",
    "state": state
}

auth_link = AUTH_URL + "?" + urlencode(auth_params)

print("\n========== TITAN AI / cTRADER ==========")
print("Aplicación:", cfg.get("app_name", "TITAN AI"))
print("App ID:", cfg.get("app_id", "No registrado"))
print("Permiso: accounts (solo lectura)")
print("Redirect URI:", redirect_uri)
print("Receptor local: ACTIVO")
print("\nABRE ESTE ENLACE EN CHROME:\n")
print(auth_link)
print("\nAutoriza la aplicación.")
print("No cierres esta terminal.")

try:
    while not server.done:
        server.handle_request()
except KeyboardInterrupt:
    print("\nProceso interrumpido.")
finally:
    server.server_close()

if server.success:
    print("\nRESULTADO: AUTENTICACIÓN COMPLETADA.")
else:
    print("\nRESULTADO: AUTENTICACIÓN NO COMPLETADA.")
