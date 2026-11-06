import json
import os
from pathlib import Path

from twisted.internet import reactor
from ctrader_open_api import Client, TcpProtocol, Protobuf, EndPoints
from ctrader_open_api.messages import OpenApiMessages_pb2 as OA

BASE = Path(__file__).resolve().parent
CONFIG_FILE = BASE / "ctrader_app.json"
TOKEN_FILE = BASE / "oauth_tokens.json"
ACCOUNT_FILE = BASE / "ctrader_accounts.json"

TIMEOUT = 35

def stop(message=None):
    global finished

    if finished:
        return

    finished = True

    if message:
        print(message)

    if timeout_call.active():
        timeout_call.cancel()

    try:
        client.stopService()
    except Exception:
        pass

    if reactor.running:
        reactor.callLater(0, reactor.stop)


def mask(value):
    value = str(value)
    if len(value) <= 4:
        return "****"
    return "****" + value[-4:]


def on_error(failure):
    print("\nERROR DE COMUNICACIÓN O API")
    print("Tipo:", failure.type.__name__)
    print("Detalle:", failure.getErrorMessage())
    stop("CONEXIÓN NO COMPLETADA.")


def on_connected(c):
    print("\nCONEXIÓN TCP: ESTABLECIDA")
    print("Autenticando aplicación TITAN AI...")

    request = OA.ProtoOAApplicationAuthReq()
    request.clientId = cfg["client_id"]
    request.clientSecret = cfg["client_secret"]

    c.send(request, responseTimeoutInSeconds=15).addCallbacks(
        on_app_authenticated,
        on_error
    )


def on_app_authenticated(message):
    try:
        response = Protobuf.extract(message)
    except Exception as exc:
        print("ERROR interpretando autenticación:", type(exc).__name__)
        stop()
        return

    if response.DESCRIPTOR.name != "ProtoOAApplicationAuthRes":
        print("Respuesta inesperada:", response.DESCRIPTOR.name)
        stop("AUTENTICACIÓN DE APLICACIÓN NO CONFIRMADA.")
        return

    print("AUTENTICACIÓN DE APLICACIÓN: CORRECTA")
    print("Solicitando cuentas autorizadas...")

    request = OA.ProtoOAGetAccountListByAccessTokenReq()
    request.accessToken = tokens["accessToken"]

    client.send(request, responseTimeoutInSeconds=15).addCallbacks(
        on_accounts_received,
        on_error
    )


def on_accounts_received(message):
    try:
        response = Protobuf.extract(message)
    except Exception as exc:
        print("ERROR interpretando cuentas:", type(exc).__name__)
        stop()
        return

    if response.DESCRIPTOR.name != "ProtoOAGetAccountListByAccessTokenRes":
        print("Respuesta inesperada:", response.DESCRIPTOR.name)
        stop("NO SE PUDO CONFIRMAR LA LISTA DE CUENTAS.")
        return

    accounts = []

    for account in response.ctidTraderAccount:
        item = {
            "account_id": str(account.ctidTraderAccountId),
            "trader_login": str(account.traderLogin),
            "environment": "LIVE" if account.isLive else "DEMO",
            "is_live": bool(account.isLive)
        }
        accounts.append(item)

    temp = ACCOUNT_FILE.with_suffix(".tmp")

    try:
        temp.write_text(json.dumps(accounts, indent=2))
        os.chmod(temp, 0o600)
        temp.replace(ACCOUNT_FILE)
        os.chmod(ACCOUNT_FILE, 0o600)
    except OSError as exc:
        print("ERROR guardando cuentas:", type(exc).__name__)
        stop()
        return

    demo = sum(1 for a in accounts if not a["is_live"])
    live = sum(1 for a in accounts if a["is_live"])

    print("\n========== CUENTAS CTRADER ==========")
    print("Total de cuentas:", len(accounts))
    print("Cuentas DEMO:", demo)
    print("Cuentas LIVE:", live)

    for index, account in enumerate(accounts, 1):
        print(f"\nCuenta {index}")
        print("Entorno:", account["environment"])
        print("Account ID:", mask(account["account_id"]))
        print("Trader Login:", mask(account["trader_login"]))

    print("\nArchivo local:", ACCOUNT_FILE.name)
    print("Permisos:", oct(ACCOUNT_FILE.stat().st_mode & 0o777))
    print("Identificadores completos: NO MOSTRADOS")

    stop("\nRESULTADO: CONSULTA DE CUENTAS COMPLETADA.")


def on_timeout():
    stop("ERROR: tiempo de espera agotado.")


# Validación de archivos
if not CONFIG_FILE.exists() or not TOKEN_FILE.exists():
    raise SystemExit("ERROR: faltan archivos de configuración o tokens.")

cfg = json.loads(CONFIG_FILE.read_text())
tokens = json.loads(TOKEN_FILE.read_text())

if not all([
    cfg.get("client_id"),
    cfg.get("client_secret"),
    tokens.get("accessToken"),
    tokens.get("refreshToken")
]):
    raise SystemExit("ERROR: credenciales o tokens incompletos.")

if tokens.get("clientId") != cfg["client_id"]:
    raise SystemExit("ERROR: el token pertenece a otra aplicación.")

if tokens.get("scope") != "accounts":
    raise SystemExit("ERROR: permiso OAuth inesperado.")

finished = False

client = Client(
    EndPoints.PROTOBUF_DEMO_HOST,
    EndPoints.PROTOBUF_PORT,
    TcpProtocol
)

client.setConnectedCallback(on_connected)
client.setDisconnectedCallback(
    lambda c, reason: print("Conexión desconectada.")
)

timeout_call = reactor.callLater(TIMEOUT, on_timeout)

print("========== TITAN QUANT / CTRADER ==========")
print("Aplicación: TITAN AI")
print("Servidor: DEMO")
print("Puerto:", EndPoints.PROTOBUF_PORT)
print("Permiso: accounts (solo lectura)")
print("Órdenes habilitadas: NO")
print("\nIniciando conexión...")

client.startService()
reactor.run()
