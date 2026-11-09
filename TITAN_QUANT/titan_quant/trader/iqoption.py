"""Adaptador IQ Option (opciones binarias) — librería NO OFICIAL `iqoptionapi` (copia local en TITAN_QUANT/iqoptionapi).

Política de TITAN:
  * Solo cuenta PRACTICE. Se comprueba el modo de balance INMEDIATAMENTE antes de cada orden; si no es PRACTICE, no se opera.
  * El modo REAL no está implementado en este adaptador.
  * Todo lo que se registra procede del broker. Si IQ Option no confirma algo, el adaptador lo dice; nunca lo deduce.

Estados de una orden según la respuesta de `buy()` (código de la librería, stable_api.buy):
  (True, id)        → ACEPTADA: IQ Option creó la opción y devolvió su id (mensaje 'option' con id/created/exp).
  (False, mensaje)  → RECHAZADA por el broker (ErrorAdaptador: con certeza no se ejecutó).
  (False, None)     → SIN CONFIRMAR: agotó 5 s sin respuesta; la orden PUDO ejecutarse (OrdenNoConfirmada).
  (True, None)/exc. → SIN CONFIRMAR (OrdenNoConfirmada). Nunca se reintenta un envío.
Apertura confirmada: el mensaje de creación del broker (o el evento 'socket-option-opened') con el mismo id.
Resultado: get_options_v2(...,'binary,turbo') leído de api.get_options_v2_data con tiempo máximo; win/loose/equal,
win_amount y amount salen del registro de la operación cerrada en IQ Option. Sin ese registro no hay resultado.
"""
import threading
import time

from .base import Adaptador, ErrorAdaptador, OrdenNoConfirmada


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
        raise RuntimeError("La librería iqoptionapi no está disponible. Es no oficial.")
    api = _api(cred)
    modo = api.get_balance_mode() if hasattr(api, "get_balance_mode") else None
    if modo != "PRACTICE":
        raise RuntimeError("No se pudo confirmar la cuenta PRACTICE.")
    return f"Conectado a IQ Option en PRACTICE (saldo de práctica: {api.get_balance()})"


PAYOUT_TIMEOUT_S = 20      # tiempo máximo para get_all_profit(); el ciclo del bot dura 60 s
CERRADAS_TIMEOUT_S = 8.0   # tiempo máximo para la consulta de operaciones cerradas
CERRADAS_LIMITE = 50
_PAYOUT_HILO = None        # consulta de payout en curso (una a la vez)
_L_CERRADAS = threading.Lock()


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and v not in (float("inf"), float("-inf")) else None


def consultar_cerradas(api, timeout_s=CERRADAS_TIMEOUT_S, limite=CERRADAS_LIMITE):
    """Lista de operaciones binarias/turbo cerradas de la cuenta, tal como las da IQ Option, o None si no responde a tiempo.
    No usa get_optioninfo_v2 (su espera es un bucle sin límite)."""
    canal = api.api
    with _L_CERRADAS:
        try:
            canal.get_options_v2_data = None
            canal.get_options_v2(limite, "binary,turbo")
        except Exception:
            return None
        fin = time.monotonic() + timeout_s
        while time.monotonic() < fin:
            data = getattr(canal, "get_options_v2_data", None)
            if data is not None:
                try:
                    return list(data["msg"]["closed_options"])
                except (KeyError, TypeError):
                    return None
            time.sleep(0.2)
    return None


_L_HIST = threading.Lock()
TIPOS_HISTORIAL = ("turbo-option", "binary-option")


def consultar_historial(api, timeout_s=CERRADAS_TIMEOUT_S, limite=CERRADAS_LIMITE):
    """Posiciones cerradas de opciones turbo/binarias según el historial del broker (portfolio.get-history-positions).
    Vía verificada el 09/11/2026 (get_options_v2 dejó de responder). Devuelve la lista o None si IQ Option no responde."""
    canal = api.api
    todas, alguna = [], False
    with _L_HIST:
        for tipo in TIPOS_HISTORIAL:
            try:
                canal.position_history_v2 = None
                canal.get_position_history_v2(tipo, limite, 0, 0, 0)
            except Exception:
                continue
            fin = time.monotonic() + timeout_s
            while time.monotonic() < fin:
                r = getattr(canal, "position_history_v2", None)
                if r is not None:
                    try:
                        if r.get("status", 2000) == 2000 or "msg" in r:
                            todas.extend(r["msg"]["positions"])
                            alguna = True
                    except (KeyError, TypeError, AttributeError):
                        pass
                    break
                time.sleep(0.2)
    return todas if alguna else None


def resultado_de_historial(p):
    """(motivo, neto, entrada, salida) desde una posición del historial del broker, o None si no está cerrada con resultado."""
    if p.get("status") != "closed":
        return None
    razon = p.get("close_reason") or (p.get("raw_event") or {}).get("result")
    neto = _num(p.get("pnl_net", p.get("pnl")))
    motivo = {"win": "ganada", "loose": "perdida", "equal": "empate"}.get(razon)
    if motivo is None or neto is None:
        return None
    return motivo, neto, _num(p.get("open_quote")), _num(p.get("close_quote"))


def _payout_de_profit_income(v):
    """IQ Option envía profit_income como retorno TOTAL en % (183 = inversión + 83 % de ganancia). Devuelve 0.83."""
    if v is None:
        return None
    if v > 100:
        return round((v - 100) / 100.0, 4)
    return None                                  # forma desconocida: no se interpreta


def _id_de(entrada):
    v = entrada.get("id")
    if isinstance(v, (list, tuple)):
        v = v[0] if v else None
    return None if v is None else str(v)


def resultado_de_cerrada(entrada):
    """(motivo, neto) a partir del registro de IQ Option, o None si el registro no trae un estado conocido."""
    win = entrada.get("win")
    if win == "equal":
        return "empate", 0.0
    importe, ganado = _num(entrada.get("amount")), _num(entrada.get("win_amount"))
    if importe is None or ganado is None:
        return None
    if win == "win":
        return "ganada", ganado - importe
    if win == "loose":
        return "perdida", ganado - importe
    return None


class IQOption(Adaptador):
    id, nombre = "iqoption", "IQ Option (no oficial)"
    mercados = ("binarias",)
    tipos_orden = ("binaria",)
    modalidades = ("binaria", "binaria_real")
    CUENTA_POR_MODALIDAD = {"binaria": "PRACTICE", "binaria_real": "REAL"}
    autenticacion = "Correo y contraseña (no hay OAuth); guardados cifrados en la bóveda"
    comisiones = "Incluidas en el payout"
    spreads = "No expuestos por la librería"
    limites_api = "No documentados (API no oficial)"
    restricciones = "Opciones binarias prohibidas a minoristas en UE/Reino Unido y otros países; REAL solo con el interruptor LIVE del bot"
    compatibilidad = "Librería no oficial; verificado con la cuenta PRACTICE mediante titan_quant.cli verificar_brokers"

    def __init__(self, cred, api=None, cuenta="PRACTICE"):
        if cuenta not in ("PRACTICE", "REAL"):
            raise ErrorAdaptador("Cuenta de IQ Option no válida.")
        self.cred = cred
        self.cuenta = cuenta          # PRACTICE (bot 'binaria') o REAL (bot 'binaria_real', con el interruptor LIVE)
        self._api_fija = api          # para pruebas: una sesión ya construida

    def _sesion(self):
        return self._api_fija if self._api_fija is not None else _api(self.cred)

    def conectado(self):
        if self._api_fija is None and not disponible():
            return False
        try:
            return bool(self._sesion().check_connect())
        except Exception:
            return False

    def cotizacion(self, simbolo):
        import iqoption_data
        self._sesion()
        q = iqoption_data.latest_quote(simbolo)
        return {"precio": q["precio"], "bid": None, "ask": None, "spread": None, "ts": q["hora"],
                "edad_s": int(time.time() - q["hora"]), "proveedor": "iqoption", "instrumento": "binaria"}

    def saldo(self):
        """Saldo de la cuenta del bot, leído de IQ Option con la cuenta seleccionada y verificada."""
        import iqoption_data
        api = self._sesion()
        if self.cuenta == "PRACTICE":
            from ..binaria_bot.capital import leer_capital_practica
            with iqoption_data.cuenta(api, "PRACTICE"):
                return {"balance": leer_capital_practica(api), "moneda": "PRACTICE"}
        with iqoption_data.cuenta(api, "REAL"):
            bal = _num(api.get_balance())
            moneda = api.get_currency() if hasattr(api, "get_currency") else None
        if bal is None:
            raise ErrorAdaptador("IQ Option no devolvió el saldo de la cuenta REAL.")
        return {"balance": bal, "moneda": moneda or "REAL"}

    def velas_m1(self, simbolo, n=120):
        """Últimas n velas M1 CERRADAS (se descarta la vela en formación)."""
        import iqoption_data
        self._sesion()
        filas, _ = iqoption_data.history(simbolo, rango="1d", intervalo="1m")
        ahora = time.time()
        cerradas = [f for f in filas if f[0] + 60 <= ahora]
        return [{"ts": int(f[0]), "open": float(f[1]), "high": float(f[2]), "low": float(f[3]), "close": float(f[4])}
                for f in cerradas[-n:]]

    def velas(self, simbolo, intervalo="1m", n=120):
        """Últimas n velas CERRADAS de la temporalidad indicada (se descarta la vela en formación)."""
        import iqoption_data
        from ..historico import SEG
        self._sesion()
        paso = SEG[intervalo]
        rango = {60: "1d", 300: "5d", 900: "7d", 3600: "1mo"}.get(paso, "1mo")
        filas, _ = iqoption_data.history(simbolo, rango=rango, intervalo=intervalo)
        ahora = time.time()
        cerradas = [f for f in filas if f[0] + paso <= ahora]
        return [{"ts": int(f[0]), "open": float(f[1]), "high": float(f[2]), "low": float(f[3]), "close": float(f[4])}
                for f in cerradas[-n:]]

    def payout(self, simbolo):
        """Payout turbo (vencimiento 5 min) del par, solo lectura. None si no es fiable.
        La librería espera en bucle a get_all_init sin límite: la consulta va en un hilo con tiempo
        máximo, y no se lanza otra mientras la anterior siga atascada (así no se bloquea el ciclo del bot)."""
        global _PAYOUT_HILO
        if _PAYOUT_HILO is not None and _PAYOUT_HILO.is_alive():
            return None
        resultado = {}

        def _tarea():
            try:
                resultado["perfiles"] = self._sesion().get_all_profit()
            except Exception as exc:  # noqa: BLE001
                resultado["error"] = exc

        _PAYOUT_HILO = threading.Thread(target=_tarea, name="iq-payout", daemon=True)
        _PAYOUT_HILO.start()
        _PAYOUT_HILO.join(PAYOUT_TIMEOUT_S)
        if _PAYOUT_HILO.is_alive() or "error" in resultado:
            return None
        try:
            perfiles = resultado.get("perfiles")
            fila = perfiles.get(simbolo) if isinstance(perfiles, dict) else None
            valor = (fila or {}).get("turbo") if isinstance(fila, dict) else None
            if valor is None and isinstance(perfiles, dict):
                valor = (perfiles.get("turbo") or {}).get(simbolo)
        except Exception:
            return None
        if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not (0 < valor < 1.5):
            return None
        return float(valor)

    # ----------------------------------------------------------------- órdenes
    def abrir(self, sol):
        if self.CUENTA_POR_MODALIDAD.get(sol.get("modalidad")) != self.cuenta:
            raise ErrorAdaptador(f"La orden de la modalidad {sol.get('modalidad')} no corresponde a la cuenta {self.cuenta}: orden bloqueada.")
        if sol["tipo"] != "binaria":
            raise ErrorAdaptador("Este adaptador solo envía binarias.")
        api = self._sesion()
        import iqoption_data
        try:
            activo, _, abierto = iqoption_data.resolve(sol["instrumento"])
        except Exception as e:
            raise ErrorAdaptador(f"No se pudo resolver {sol['instrumento']} en IQ Option: {e}")
        if not abierto:                       # None = estado de mercado desconocido: tampoco se envía
            raise ErrorAdaptador(f"{activo} está cerrado/suspendido en IQ Option (o no se pudo confirmar que esté abierto): orden no enviada.")
        if iqoption_data.id_activo(activo) is None:
            raise ErrorAdaptador(f"{activo}: la librería no conoce su id de activo; orden no enviada.")
        minutos = max(1, int(round((sol["expira_ts"] - time.time()) / 60)))
        direccion = "call" if sol["direccion"] == "alcista" else "put"
        try:
            sel = iqoption_data.cuenta(api, self.cuenta).__enter__()
        except Exception as e:
            raise ErrorAdaptador(f"No se pudo seleccionar y verificar la cuenta {self.cuenta} antes de enviar ({e}): orden no enviada.")
        try:
            enviado_ts = time.time()
            try:
                ok, resp = sel.buy(float(sol["monto"]), activo, direccion, minutos)
            except Exception as e:
                raise OrdenNoConfirmada(f"excepción durante el envío ({type(e).__name__}); la orden pudo ejecutarse")
            msg = self._mensaje_creacion(api, str(resp)) if ok is True and resp is not None else {}
        finally:
            iqoption_data.cuenta(api, self.cuenta).__exit__(None, None, None)
        if ok is False and isinstance(resp, str):
            raise ErrorAdaptador(f"IQ Option rechazó la orden: {resp}")
        if ok is not True or resp is None:
            raise OrdenNoConfirmada("IQ Option no confirmó la orden en 5 s (respuesta ambigua de buy()); la orden pudo ejecutarse")
        oid = str(resp)
        precio = _num(msg.get("value")) if msg else None
        payout = _num(msg.get("profit_income")) if msg else None
        evidencia = {"broker": "iqoption", "cuenta": self.cuenta, "id": oid, "activo": activo, "direccion": direccion,
                     "minutos": minutos, "monto": float(sol["monto"]), "enviado_ts": int(enviado_ts),
                     "respuesta_creacion": {k: msg.get(k) for k in ("id", "created", "exp", "value", "price", "profit_income",
                                                                   "type", "act", "direction") if k in msg} if msg else None}
        return {"id_externo": oid, "precio_entrada": precio, "costo": 0.0, "fuente_precio": "iqoption (mensaje de creación)" if precio else None,
                "payout": _payout_de_profit_income(payout), "evidencia": evidencia}

    @staticmethod
    def _mensaje_creacion(api, oid):
        """Mensaje 'option' con el que IQ Option confirmó la creación (lo guarda la librería en buy_multi_option)."""
        try:
            for v in (api.api.buy_multi_option or {}).values():
                if isinstance(v, dict) and str(v.get("id")) == oid:
                    return dict(v)
        except Exception:
            pass
        return {}

    def verificar_apertura(self, op):
        """Confirmada si consta el mensaje de creación del broker con el mismo id, o el evento socket-option-opened."""
        import json
        oid = str(op.get("id_externo") or "")
        if not oid:
            return {"confirmada": False, "detalle": "sin id del broker"}
        try:
            ev = json.loads(op.get("evidencia") or "{}") if isinstance(op.get("evidencia"), str) else (op.get("evidencia") or {})
        except ValueError:
            ev = {}
        crea = (ev or {}).get("respuesta_creacion") or {}
        if str(crea.get("id")) == oid and crea.get("created"):
            return {"confirmada": True, "precio_entrada": _num(crea.get("value")),
                    "evidencia": {"fuente": "mensaje de creación de IQ Option", "id": oid, "created": crea.get("created"), "exp": crea.get("exp")}}
        try:
            api = self._sesion()
            abiertas = getattr(api.api, "socket_option_opened", {}) or {}
            m = abiertas.get(int(oid)) or abiertas.get(oid)
            if m:
                return {"confirmada": True, "precio_entrada": _num((m.get("msg") or {}).get("value")),
                        "evidencia": {"fuente": "socket-option-opened", "id": oid}}
        except Exception as ex:                  # sin respuesta: queda NO confirmada (lado seguro) y se dice por qué
            return {"confirmada": False, "detalle": f"IQ Option no respondió al verificar la apertura ({type(ex).__name__})"}
        return {"confirmada": False, "detalle": "IQ Option aún no confirma la apertura"}

    def actualizar(self, op, ahora=None):
        """Resultado SOLO desde los registros del broker (historial de posiciones; respaldo: closed_options).
        None si aún no consta o IQ Option no responde: la operación sigue PENDIENTE, nunca se inventa."""
        if time.time() < (op.get("expira_ts") or 0) + 5:
            return None
        import iqoption_data
        oid = str(op["id_externo"])
        api = self._sesion()
        with iqoption_data.cuenta(api, self.cuenta):           # el historial se pide para la cuenta del bot
            hist = consultar_historial(api)
        for p in hist or []:
            if str(p.get("external_id")) != oid and str((p.get("raw_event") or {}).get("option_id")) != oid:
                continue
            res = resultado_de_historial(p)
            if res is None:
                return None
            motivo, neto, entrada, salida = res
            ev = {k: p.get(k) for k in ("external_id", "instrument_type", "active_id", "status", "open_time", "open_quote", "invest",
                                         "close_time", "close_quote", "close_reason", "close_profit", "pnl", "pnl_net") if k in p}
            return {"precio_salida": salida, "resultado": float(neto), "motivo": f"vencimiento ({motivo})",
                    "r": float(neto) / op["monto"] if op.get("monto") else None,
                    "evidencia": {"fuente": "IQ Option portfolio.get-history-positions", **ev},
                    "evidencia_cierre": {"fuente": "IQ Option portfolio.get-history-positions", "id": oid,
                                         "status": p.get("status"), "close_time": p.get("close_time")}}
        with iqoption_data.cuenta(api, self.cuenta):
            cerradas = consultar_cerradas(api)
        if cerradas is None:
            return None                       # sin respuesta: se reintenta en el próximo ciclo (sigue PENDIENTE)
        for e in cerradas:
            if _id_de(e) != oid:
                continue
            res = resultado_de_cerrada(e)
            if res is None:
                return None
            motivo, neto = res
            ev = {k: e.get(k) for k in ("id", "win", "amount", "win_amount", "created", "expired", "close_time", "value",
                                         "exp_value", "close_quote", "active_id") if k in e}
            salida = _num(e.get("exp_value")) if "exp_value" in e else None
            return {"precio_salida": salida, "resultado": float(neto), "motivo": f"vencimiento ({motivo})",
                    "r": float(neto) / op["monto"] if op.get("monto") else None,
                    "evidencia": {"fuente": "IQ Option closed_options", **ev},
                    "evidencia_cierre": {"fuente": "IQ Option closed_options", "id": oid, "win": e.get("win")}}
        return None

    def cerrar(self, op, motivo):
        raise ErrorAdaptador("Las binarias de IQ Option no se pueden cerrar antes del vencimiento.")
