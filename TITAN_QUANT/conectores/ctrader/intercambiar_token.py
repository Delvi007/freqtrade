import json
import os
from pathlib import Path
import requests

BASE = Path(__file__).resolve().parent
CONFIG = BASE / "ctrader_app.json"
CODE_FILE = BASE / "oauth_code.json"
TOKEN_FILE = BASE / "oauth_tokens.json"

TOKEN_URL = "https://openapi.ctrader.com/apps/token"

if not CONFIG.exists() or not CODE_FILE.exists():
    raise SystemExit("ERROR: falta la configuracion o el codigo OAuth.")

cfg = json.loads(CONFIG.read_text())
data = json.loads(CODE_FILE.read_text())

client_id = cfg.get("client_id", "").strip()
client_secret = cfg.get("client_secret", "").strip()
redirect_uri = cfg.get("redirect_uri", "").strip()

code = data.get("code")

if not all((client_id, client_secret, redirect_uri, code)):
    raise SystemExit("ERROR: datos OAuth incompletos.")

if data.get("client_id") != client_id:
    raise SystemExit("ERROR: el codigo pertenece a otra aplicacion.")

if data.get("redirect_uri") != redirect_uri:
    raise SystemExit("ERROR: la URI del codigo no coincide con la configuracion.")

params = {
    "grant_type": "authorization_code",
    "code": code,
    "redirect_uri": redirect_uri,
    "client_id": client_id,
    "client_secret": client_secret
}

print("\nSolicitando tokens a cTrader...")

try:
    response = requests.get(TOKEN_URL, params=params, timeout=25)
    response.raise_for_status()
    result = response.json()
except requests.RequestException as exc:
    raise SystemExit(
        f"ERROR de comunicacion: {type(exc).__name__}: {exc}"
    )

if not isinstance(result, dict):
    raise SystemExit("ERROR: respuesta OAuth no valida.")

access = result.get("accessToken")
refresh = result.get("refreshToken")

if not access or not refresh:
    error = result.get("errorCode") or result.get("error") or "Sin tokens"
    description = (
        result.get("description")
        or result.get("errorDescription")
        or ""
    )
    raise SystemExit(f"ERROR OAuth: {error} {description}")

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
temp.write_text(json.dumps(secure_data))
os.chmod(temp, 0o600)
temp.replace(TOKEN_FILE)
os.chmod(TOKEN_FILE, 0o600)

CODE_FILE.unlink()

print("\n========== RESULTADO ==========")
print("Access Token: GUARDADO")
print("Refresh Token: GUARDADO")
print("Permiso solicitado: accounts")
print("Archivo protegido: oauth_tokens.json")
print("Permisos:", oct(TOKEN_FILE.stat().st_mode & 0o777))
print("Valores secretos: NO MOSTRADOS")
