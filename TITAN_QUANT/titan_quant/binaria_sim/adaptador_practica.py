"""Adaptador de órdenes de binarias en la cuenta PRACTICE de IQ Option.

Garantías (cubiertas por titan_quant/pruebas/test_binaria_sim_adaptador.py):
  * Antes de CADA orden verifica que la cuenta activa sea PRACTICE.
  * Interruptor de emergencia: bloquea órdenes nuevas hasta reactivarlo.
  * Valida monto, dirección y activo antes de enviar.
  * Respuestas de buy() según el código del commit 8a903cc:
      (True, id)        -> enviada
      (False, mensaje)  -> rechazada
      (False, None)     -> desconocida (agotó 5 s; la orden PUDO enviarse)
      (True, None)      -> desconocida
  * Nunca reintenta un envío.
  * Liquidación con tiempo máximo: pide get_options_v2 y lee api.get_options_v2_data con un
    límite. Si no responde a tiempo, devuelve None y la orden debe conciliarse.
  * Verificado en la librería 7.1.1 (zip de SISTEMA_INVERSION): buy() con 5 min envía
    option_type_id=3, que en la plataforma aparece como Binaria.

Firmas verificadas en la librería 7.1.1:
  buy(self, price, ACTIVES, ACTION, expirations) -> (ok, respuesta)
  get_balance_mode(self)
  get_options_v2(limit, "binary,turbo") -> deja el mensaje en api.get_options_v2_data
  Forma de cada entrada de closed_options (según check_win_v3): 'id' es lista y el id está en
  ['id'][0]; 'win' en {'win','loose','equal'}; 'win_amount' y 'amount' para el monto neto.
"""
import logging
import time
from dataclasses import dataclass
from typing import Optional, Tuple

CUENTA_PERMITIDA = "PRACTICE"
DURACION_MIN = 5          # expirations de buy(): se asume minutos; no confirmado en el código del commit
MONTO_MAX_DEFAULT = 1.0
DIRECCIONES = {"CALL": "call", "PUT": "put"}
TIMEOUT_CONSULTA_S = 5.0
LIMITE_CERRADAS = 50

log = logging.getLogger("binaria_sim.practica")


class OrdenRechazada(RuntimeError):
    """La orden no se envió. Motivo claro y seguro para registrar."""


@dataclass(frozen=True)
class Resultado:
    estado: str                  # 'enviada' | 'rechazada' | 'desconocida'
    orden_id: Optional[str] = None
    motivo: str = ""


class AdaptadorPractica:
    def __init__(self, iq, monto_max=MONTO_MAX_DEFAULT, timeout_consulta_s=TIMEOUT_CONSULTA_S):
        if iq is None:
            raise ValueError("Se requiere una sesión de IQ Option ya conectada")
        if not (0 < monto_max <= MONTO_MAX_DEFAULT * 10):
            raise ValueError("monto_max fuera de rango seguro")
        if timeout_consulta_s <= 0:
            raise ValueError("timeout_consulta_s debe ser positivo")
        self.iq = iq
        self.monto_max = monto_max
        self.timeout_consulta_s = timeout_consulta_s
        self.interruptor = False

    def apagar_nuevas(self):
        self.interruptor = True
        log.warning("interruptor de emergencia activado: no se envían órdenes nuevas")

    def reactivar(self):
        self.interruptor = False
        log.warning("interruptor de emergencia desactivado")

    def _verificar_practica(self):
        try:
            modo = self.iq.get_balance_mode()
        except Exception as e:
            raise OrdenRechazada(f"no se pudo verificar la cuenta ({type(e).__name__})")
        if modo != CUENTA_PERMITIDA:
            raise OrdenRechazada(f"cuenta activa '{modo}' no permitida; solo se admite {CUENTA_PERMITIDA}")

    def _validar(self, activo, direccion, monto):
        if self.interruptor:
            raise OrdenRechazada("interruptor de emergencia activo")
        if not activo or not isinstance(activo, str):
            raise OrdenRechazada("activo inválido")
        if direccion not in DIRECCIONES:
            raise OrdenRechazada(f"dirección inválida: {direccion!r}")
        if not isinstance(monto, (int, float)) or isinstance(monto, bool) or not (0 < monto <= self.monto_max):
            raise OrdenRechazada(f"monto {monto!r} fuera de límite (máx. {self.monto_max})")

    def enviar(self, activo, direccion, monto):
        """Envía una orden a PRACTICE. Nunca lanza excepciones: devuelve un Resultado."""
        try:
            self._validar(activo, direccion, monto)
            self._verificar_practica()
        except OrdenRechazada as e:
            log.warning("orden rechazada antes de enviar: %s", e)
            return Resultado("rechazada", motivo=str(e))

        try:
            ok, respuesta = self.iq.buy(monto, activo, DIRECCIONES[direccion], DURACION_MIN)
        except Exception as e:
            log.error("resultado desconocido tras enviar %s %s: %s", activo, direccion, type(e).__name__)
            return Resultado("desconocida", motivo=f"excepción durante el envío ({type(e).__name__})")

        if ok is True and respuesta is not None:
            log.info("orden enviada a PRACTICE: %s %s monto=%s id=%s", activo, direccion, monto, respuesta)
            return Resultado("enviada", orden_id=str(respuesta))

        if ok is False and isinstance(respuesta, str):
            log.warning("broker rechazó la orden %s %s", activo, direccion)
            return Resultado("rechazada", motivo=f"el broker rechazó la orden: {respuesta}")

        log.error("estado de la orden %s %s no confirmado; requiere conciliación", activo, direccion)
        return Resultado("desconocida", motivo="no confirmada: requiere conciliación antes de reintentar")

    def _consultar_cerradas(self):
        """Pide las operaciones cerradas y lee el dato que el websocket deja en api.get_options_v2_data.

        No usa get_optioninfo_v2 porque su espera es un bucle sin límite que, en la prueba real del
        08/11/2026, no devolvió el dato aunque el mensaje llegó. Aquí la espera tiene tiempo máximo y
        no deja hilos bloqueados. Devuelve None si no hay respuesta a tiempo."""
        api = self.iq.api
        try:
            api.get_options_v2_data = None
            api.get_options_v2(LIMITE_CERRADAS, "binary,turbo")
        except Exception as e:
            log.error("error al pedir operaciones cerradas (%s)", type(e).__name__)
            return None
        limite = time.monotonic() + self.timeout_consulta_s
        while time.monotonic() < limite:
            data = getattr(api, "get_options_v2_data", None)
            if data is not None:
                return data
            time.sleep(0.2)
        log.error("consulta de operaciones cerradas sin respuesta en %s s", self.timeout_consulta_s)
        return None

    def liquidar(self, orden_id) -> Optional[Tuple[str, float]]:
        """Devuelve (estado, monto_neto) con estado 'ganada'|'perdida'|'empate', o None si no hay
        resultado todavía o la consulta no respondió. Nunca bloquea más que el tiempo máximo."""
        data = self._consultar_cerradas()
        if not data:
            return None
        try:
            cerradas = data["msg"]["closed_options"]
        except (KeyError, TypeError):
            log.error("forma inesperada de la respuesta de operaciones cerradas")
            return None
        for op in cerradas:
            try:
                id_op = op["id"][0]
            except (KeyError, IndexError, TypeError):
                continue
            if str(id_op) != str(orden_id):
                continue
            win = op.get("win")
            if win == "equal":
                return ("empate", 0.0)
            if win == "win":
                return ("ganada", float(op["win_amount"]) - float(op["amount"]))
            if win == "loose":
                return ("perdida", float(op["win_amount"]) - float(op["amount"]))
            log.error("estado de resultado desconocido para la orden %s", orden_id)
            return None
        return None
