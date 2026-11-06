import json
from pathlib import Path

from twisted.internet import reactor
from ctrader_open_api import Client, TcpProtocol, Protobuf, EndPoints
from ctrader_open_api.messages import OpenApiMessages_pb2 as OA

BASE = Path(__file__).resolve().parent
CONFIG_FILE = BASE / "ctrader_app.json"
TOKEN_FILE = BASE / "oauth_tokens.json"
ACCOUNT_FILE = BASE / "ctrader_accounts.json"

TIMEOUT = 35

finished = False
timeout_call = None
client = None
demo_account = None
cfg = {}
tokens = {}


def stop(message=None):
    global finished

    if finished:
        return

    finished = True

    if message:
        print(message)

    if timeout_call and timeout_call.active():
        timeout_call.cancel()

    try:
        if client:
            client.stopService()
    except Exception:
        pass

    if reactor.running:
        reactor.callLater(0, reactor.stop)


def on_error(failure):
    print("\nERROR DE COMUNICACIÓN O API")
    print("Tipo:", failure.type.__name__)
    print("Detalle:", failure.getErrorMessage())
    stop("AUTENTICACIÓN DEMO NO COMPLETADA.")


def on_connected(connection):
    print("\nCONEXIÓN TCP: ESTABLECIDA")
    print("Autenticando aplicación TITAN AI...")

    request = OA.ProtoOAApplicationAuthReq()
    request.clientId = cfg["client_id"]
    request.clientSecret = cfg["client_secret"]

    connection.send(
        request,
        responseTimeoutInSeconds=15
    ).addCallbacks(on_app_authenticated, on_error)


def on_app_authenticated(message):
    try:
        response = Protobuf.extract(message)
    except Exception as exc:
        print("ERROR interpretando respuesta:", type(exc).__name__)
        stop()
        return

    if response.DESCRIPTOR.name != "ProtoOAApplicationAuthRes":
        print("Respuesta inesperada:", response.DESCRIPTOR.name)
        stop("AUTENTICACIÓN DE APLICACIÓN NO CONFIRMADA.")
        return

    print("AUTENTICACIÓN DE APLICACIÓN: CORRECTA")
    print("Preparando autenticación de cuenta DEMO...")

    request = OA.ProtoOAAccountAuthReq()
    request.ctidTraderAccountId = int(demo_account["account_id"])
    request.accessToken = tokens["accessToken"]

    client.send(
        request,
        responseTimeoutInSeconds=15
    ).addCallbacks(on_demo_authenticated, on_error)


def on_demo_authenticated(message):
    try:
        response = Protobuf.extract(message)
    except Exception as exc:
        print("ERROR interpretando respuesta:", type(exc).__name__)
        stop()
        return

    response_name = response.DESCRIPTOR.name

    if response_name != "ProtoOAAccountAuthRes":
        print("Respuesta recibida:", response_name)
        stop("AUTENTICACIÓN DE CUENTA DEMO NO CONFIRMADA.")
        return

    print("\n========== AUTENTICACIÓN DE CUENTA ==========")
    print("Cuenta seleccionada: DEMO")
    print("Account ID:", "****" + str(demo_account["account_id"])[-4:])
    print("Trader Login:", "****" + str(demo_account["trader_login"])[-4:])
    print("RESPUESTA API: ProtoOAAccountAuthRes")
    print("AUTENTICACIÓN DE CUENTA DEMO: CORRECTA")
    print("\nÓrdenes enviadas: 0")
    print("Cuenta LIVE utilizada: NO")
    print("Permiso OAuth: accounts")
    print("\nRESULTADO: CUENTA DEMO AUTENTICADA.")
    stop()


def on_disconnected(*args):
    if not finished:
        print("\nCONEXIÓN DESCONECTADA.")
        stop("PROCESO INTERRUMPIDO.")


def load_and_validate():
    for path in (CONFIG_FILE, TOKEN_FILE, ACCOUNT_FILE):
        if not path.is_file():
            raise RuntimeError(f"Archivo necesario no encontrado: {path.name}")

    config = json.loads(CONFIG_FILE.read_text())
    token_data = json.loads(TOKEN_FILE.read_text())
    account_data = json.loads(ACCOUNT_FILE.read_text())

    if not isinstance(account_data, list):
        raise RuntimeError("Formato inesperado en ctrader_accounts.json")

    if token_data.get("scope") != "accounts":
        raise RuntimeError("El permiso OAuth no coincide con accounts.")

    if not token_data.get("accessToken"):
        raise RuntimeError("No existe access token.")

    if not config.get("client_id") or not config.get("client_secret"):
        raise RuntimeError("Faltan credenciales de aplicación.")

    if token_data.get("clientId") != config.get("client_id"):
        raise RuntimeError("El Client ID del token no coincide con la aplicación.")

    demo_accounts = [
        account for account in account_data
        if account.get("is_live") is False
        and str(account.get("environment", "")).upper() == "DEMO"
        and str(account.get("account_id", "")).isdigit()
    ]

    if len(demo_accounts) != 1:
        raise RuntimeError(
            f"Se esperaba exactamente una cuenta DEMO válida; encontradas: {len(demo_accounts)}"
        )

    selected = demo_accounts[0]

    # Protección adicional: nunca aceptar una cuenta marcada como LIVE.
    if selected.get("is_live") is not False:
        raise RuntimeError("Protección activada: cuenta no DEMO.")

    return config, token_data, selected


def main():
    global cfg, tokens, demo_account, client, timeout_call

    print("========== TITAN QUANT / CTRADER ==========")
    print("Proceso: AUTENTICACIÓN DEMO")
    print("Servidor: DEMO")
    print("Puerto: 5035")
    print("Permiso OAuth: accounts")
    print("Órdenes habilitadas: NO")
    print("Cuenta LIVE: BLOQUEADA")

    try:
        cfg, tokens, demo_account = load_and_validate()
    except Exception as exc:
        print("\nVALIDACIÓN FALLIDA:", str(exc))
        return

    print("\nValidación de archivos: CORRECTA")
    print("Cuenta DEMO identificada:", "****" + str(demo_account["account_id"])[-4:])
    print("\nIniciando conexión...")

    client = Client(
        EndPoints.PROTOBUF_DEMO_HOST,
        EndPoints.PROTOBUF_PORT,
        TcpProtocol
    )

    client.setConnectedCallback(on_connected)
    client.setDisconnectedCallback(on_disconnected)

    timeout_call = reactor.callLater(
        TIMEOUT,
        lambda: stop("TIEMPO DE ESPERA AGOTADO.")
    )

    client.startService()
    reactor.run()


if __name__ == "__main__":
    main()
