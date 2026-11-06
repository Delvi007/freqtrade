"""Adaptador IQ Option (opciones binarias/digitales y CFD) — librería NO OFICIAL `iqoptionapi`.

Capacidades documentadas (según la librería comunitaria; IQ Option no publica una API oficial):
  conexión con correo y contraseña · cambio de balance PRACTICE/REAL · catálogo por categoría (cfd, forex, crypto)
  · velas históricas (lotes de 1000) · velas en tiempo real · compra de binarias `buy(monto, activo, 'call'|'put', minutos)`
  · resultado `check_win_v3(id)` · payout `get_all_profit()`.
NO disponibles: bid/ask/spread en velas, límites de API documentados.

Política de TITAN:
  * Solo cuenta PRACTICE. Se comprueba el modo de balance INMEDIATAMENTE antes de cada orden; si no es PRACTICE, no se opera.
  * El modo REAL no está implementado en este adaptador.
  * La librería puede romperse con cambios de IQ Option y su uso automatizado puede infringir sus términos y causar
    el bloqueo de la cuenta. Estado de compatibilidad: NO VERIFICADO en este entorno (la librería no está instalada).
"""
import time

from .base import Adaptador, ErrorAdaptador


def disponible():
    try:
        import iqoptionapi  # noqa: F401
        return True
    except Exception:
        return False


def _api(cred):
    import iqoption_data
    if cred:
        iqoption_data.CREDENCIALES = {"correo": cred.get("correo"), "clave": cred.get("clave")}
    return iqoption_data._api()


def probar(cred):
    if not disponible():
        raise RuntimeError("La librería iqoptionapi no está instalada (pip install iqoptionapi). Es no oficial.")
    api = _api(cred)
    modo = api.get_balance_mode() if hasattr(api, "get_balance_mode") else None
    if modo != "PRACTICE":
        raise RuntimeError("No se pudo confirmar la cuenta PRACTICE.")
    return f"Conectado a IQ Option en PRACTICE (saldo de práctica: {api.get_balance()})"


class IQOption(Adaptador):
    id, nombre = "iqoption", "IQ Option (no oficial)"
    mercados = ("binarias", "forex", "cripto", "cfd")
    tipos_orden = ("binaria",)
    modalidades = ("demo",)
    autenticacion = "Correo y contraseña (no hay OAuth); guardados cifrados en la bóveda"
    comisiones = "Incluidas en el payout"
    spreads = "No expuestos por la librería"
    limites_api = "No documentados (API no oficial)"
    restricciones = "Opciones binarias prohibidas a minoristas en UE/Reino Unido y otros países; solo PRACTICE en TITAN"
    compatibilidad = "No verificado: requiere iqoptionapi y prueba con cuenta PRACTICE"

    def __init__(self, cred):
        self.cred = cred

    def conectado(self):
        if not disponible():
            return False
        try:
            return bool(_api(self.cred).check_connect())
        except Exception:
            return False

    def cotizacion(self, simbolo):
        import iqoption_data
        _api(self.cred)
        q = iqoption_data.latest_quote(simbolo)
        return {"precio": q["precio"], "bid": None, "ask": None, "spread": None, "ts": q["hora"],
                "edad_s": int(time.time() - q["hora"]), "proveedor": "iqoption", "instrumento": "cfd/binaria"}

    def abrir(self, sol):
        if sol.get("modalidad") != "demo":
            raise ErrorAdaptador("IQ Option en TITAN solo opera en PRACTICE (demo).")
        if sol["tipo"] != "binaria":
            raise ErrorAdaptador("Este adaptador solo envía binarias.")
        api = _api(self.cred)
        if (api.get_balance_mode() if hasattr(api, "get_balance_mode") else None) != "PRACTICE":
            raise ErrorAdaptador("La cuenta no está en PRACTICE: orden bloqueada.")
        import iqoption_data
        activo, _, abierto = iqoption_data.resolve(sol["instrumento"])
        if not abierto:
            raise ErrorAdaptador(f"{activo} está cerrado en IQ Option.")
        minutos = max(1, int(round((sol["expira_ts"] - time.time()) / 60)))
        ok, oid = api.buy(float(sol["monto"]), activo, "call" if sol["direccion"] == "alcista" else "put", minutos)
        if not ok:
            raise ErrorAdaptador(f"IQ Option rechazó la orden: {oid}")
        q = self.cotizacion(sol["instrumento"])
        return {"id_externo": str(oid), "precio_entrada": q["precio"], "costo": 0.0, "fuente_precio": "iqoption", "edad_s": q["edad_s"]}

    def actualizar(self, op, ahora=None):
        if time.time() < (op.get("expira_ts") or 0) + 5:
            return None
        api = _api(self.cred)
        try:
            res = api.check_win_v3(int(op["id_externo"]))
        except Exception as e:
            raise ErrorAdaptador(f"No se pudo verificar el resultado: {type(e).__name__}")
        return {"precio_salida": None, "resultado": float(res), "motivo": "vencimiento", "r": float(res) / op["monto"]}

    def cerrar(self, op, motivo):
        raise ErrorAdaptador("Las binarias de IQ Option no se pueden cerrar antes del vencimiento.")

    def verificar(self, op):
        return bool(op.get("id_externo"))
