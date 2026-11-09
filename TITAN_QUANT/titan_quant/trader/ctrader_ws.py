"""Cliente de cTrader Open API (Spotware) por WebSocket + JSON — solo biblioteca estándar.

Documentación oficial usada:
  * JSON por WebSocket: wss://demo.ctraderapi.com:5036 y wss://live.ctraderapi.com:5036
    Mensaje: {"clientMsgId": str, "payloadType": int, "payload": {...}}  (help.ctrader.com/open-api/sending-receiving-json)
  * Números de mensaje (ProtoOAPayloadType) y unidades (help.ctrader.com/open-api/messages y model-messages):
      precios de spot/trendbar y relativeStopLoss/TakeProfit en 1/100000 de unidad de precio;
      volume en 0,01 unidades (1000 = 10,00 unidades); dinero en enteros con exponente moneyDigits.
Las cuentas DEMO solo existen en el host demo y las REALES en el host live: una sesión nunca mezcla ambas.
"""
import base64
import hashlib
import json
import os
import socket
import ssl
import struct
import time
import uuid
from urllib.parse import urlparse

HOSTS = {"demo": "wss://demo.ctraderapi.com:5036", "live": "wss://live.ctraderapi.com:5036"}

PT = {  # ProtoOAPayloadType / ProtoPayloadType
    "HEARTBEAT": 51, "ERROR_COMUN": 50,
    "APP_AUTH_REQ": 2100, "APP_AUTH_RES": 2101, "ACCOUNT_AUTH_REQ": 2102, "ACCOUNT_AUTH_RES": 2103,
    "NEW_ORDER_REQ": 2106, "AMEND_POSITION_SLTP_REQ": 2110, "CLOSE_POSITION_REQ": 2111, "ASSET_LIST_REQ": 2112, "ASSET_LIST_RES": 2113,
    "SYMBOLS_LIST_REQ": 2114, "SYMBOLS_LIST_RES": 2115, "SYMBOL_BY_ID_REQ": 2116, "SYMBOL_BY_ID_RES": 2117,
    "TRADER_REQ": 2121, "TRADER_RES": 2122, "RECONCILE_REQ": 2124, "RECONCILE_RES": 2125, "EXECUTION_EVENT": 2126,
    "SUBSCRIBE_SPOTS_REQ": 2127, "SUBSCRIBE_SPOTS_RES": 2128, "UNSUBSCRIBE_SPOTS_REQ": 2129, "UNSUBSCRIBE_SPOTS_RES": 2130,
    "SPOT_EVENT": 2131, "ORDER_ERROR_EVENT": 2132, "DEAL_LIST_REQ": 2133, "DEAL_LIST_RES": 2134,
    "GET_TRENDBARS_REQ": 2137, "GET_TRENDBARS_RES": 2138, "ERROR_RES": 2142,
    "ACCOUNTS_TOKEN_INVALIDATED": 2147, "CLIENT_DISCONNECT": 2148,
    "ACCOUNTS_BY_TOKEN_REQ": 2149, "ACCOUNTS_BY_TOKEN_RES": 2150, "REFRESH_TOKEN_REQ": 2173, "REFRESH_TOKEN_RES": 2174,
}
TIPO_ORDEN = {"MARKET": 1}
LADO = {"BUY": 1, "SELL": 2}
EJECUCION = {2: "ORDER_ACCEPTED", 3: "ORDER_FILLED", 4: "ORDER_REPLACED", 5: "ORDER_CANCELLED", 6: "ORDER_EXPIRED",
             7: "ORDER_REJECTED", 8: "ORDER_CANCEL_REJECTED", 9: "SWAP", 10: "DEPOSIT_WITHDRAW", 11: "ORDER_PARTIAL_FILL"}
PERIODO = {"1m": 1, "5m": 5, "15m": 7, "30m": 8, "60m": 9, "1h": 9, "4h": 10, "1d": 12, "1wk": 13}
ESCALA = 100000
ERRORES_TOKEN = ("CH_ACCESS_TOKEN_INVALID", "OA_AUTH_TOKEN_EXPIRED", "INVALID_ACCESS_TOKEN", "ACCESS_TOKEN_INVALID", "CH_CTID_TRADER_ACCOUNT_NOT_FOUND_BY_TOKEN")


_L_HIST = __import__("threading").Lock()
_ULTIMA_HIST = [0.0]
INTERVALO_HIST_S = 0.35            # ≈ 3 peticiones de históricos por segundo en todo el proceso (límite de cTrader: 5/s)


def _regular_historicos():
    if SesionCTrader.URL_PRUEBAS:                   # servidor de pruebas local: sin límite
        return
    with _L_HIST:
        espera = _ULTIMA_HIST[0] + INTERVALO_HIST_S - time.monotonic()
        if espera > 0:
            time.sleep(espera)
        _ULTIMA_HIST[0] = time.monotonic()


class ErrorCTrader(Exception):
    def __init__(self, codigo, descripcion=""):
        super().__init__(f"{codigo}: {descripcion}".strip(": "))
        self.codigo, self.descripcion = codigo, descripcion

    @property
    def es_token(self):
        return any(x in (self.codigo or "") for x in ERRORES_TOKEN)


def n(x, defecto=None):
    """Los int64 llegan como número o como texto en JSON de protobuf: siempre entero."""
    if x is None or x == "":
        return defecto
    try:
        return int(x)
    except (TypeError, ValueError):
        return int(float(x))


def enum(x, mapa):
    if isinstance(x, str) and not x.lstrip("-").isdigit():
        return x
    return mapa.get(n(x), str(x))


# ============================================================================ WebSocket mínimo (RFC 6455)
class WebSocket:
    GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    def __init__(self, url, espera=20, ctx_ssl=None):
        u = urlparse(url)
        self.host, self.puerto = u.hostname, u.port or (443 if u.scheme == "wss" else 80)
        s = socket.create_connection((self.host, self.puerto), timeout=espera)
        if u.scheme == "wss":
            s = (ctx_ssl or ssl.create_default_context()).wrap_socket(s, server_hostname=self.host)
        self.s, self.buf = s, b""
        clave = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f"GET {u.path or '/'} HTTP/1.1\r\nHost: {self.host}:{self.puerto}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                        f"Sec-WebSocket-Key: {clave}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        cab = b""
        while b"\r\n\r\n" not in cab:
            trozo = self.s.recv(4096)
            if not trozo:
                raise ConnectionError("El servidor cerró la conexión durante el saludo WebSocket")
            cab += trozo
        cab, self.buf = cab.split(b"\r\n\r\n", 1)
        lineas = cab.decode("latin-1").split("\r\n")
        if " 101 " not in lineas[0] + " ":
            raise ConnectionError("Saludo WebSocket rechazado: " + lineas[0][:80])
        acc = {k.strip().lower(): v.strip() for k, v in (ln.split(":", 1) for ln in lineas[1:] if ":" in ln)}.get("sec-websocket-accept")
        esperado = base64.b64encode(hashlib.sha1((clave + self.GUID).encode()).digest()).decode()
        if acc != esperado:
            raise ConnectionError("Saludo WebSocket con clave de aceptación incorrecta")

    def _leer(self, k):
        while len(self.buf) < k:
            t = self.s.recv(65536)
            if not t:
                raise ConnectionError("Conexión cerrada por cTrader")
            self.buf += t
        out, self.buf = self.buf[:k], self.buf[k:]
        return out

    def _trama(self, opcode, datos):
        cab = bytes([0x80 | opcode])
        L = len(datos)
        if L < 126:
            cab += bytes([0x80 | L])
        elif L < 65536:
            cab += bytes([0x80 | 126]) + struct.pack(">H", L)
        else:
            cab += bytes([0x80 | 127]) + struct.pack(">Q", L)
        m = os.urandom(4)
        self.s.sendall(cab + m + bytes(b ^ m[i % 4] for i, b in enumerate(datos)))

    def enviar(self, texto):
        self._trama(0x1, texto.encode("utf-8"))

    def recibir(self, espera):
        self.s.settimeout(espera)
        partes = []
        while True:
            b1, b2 = self._leer(2)
            fin, op = b1 & 0x80, b1 & 0x0F
            L = b2 & 0x7F
            if L == 126:
                L = struct.unpack(">H", self._leer(2))[0]
            elif L == 127:
                L = struct.unpack(">Q", self._leer(8))[0]
            mascara = self._leer(4) if b2 & 0x80 else None
            datos = self._leer(L)
            if mascara:
                datos = bytes(b ^ mascara[i % 4] for i, b in enumerate(datos))
            if op == 0x9:
                self._trama(0xA, datos)
                continue
            if op == 0xA:
                continue
            if op == 0x8:
                raise ConnectionError("cTrader cerró la conexión")
            partes.append(datos)
            if fin:
                return b"".join(partes).decode("utf-8")

    def cerrar(self):
        try:
            self._trama(0x8, b"")
        except OSError:
            pass
        try:
            self.s.close()
        except OSError:
            pass


# ============================================================================ sesión de protocolo
class SesionCTrader:
    """Una conexión a UN entorno (demo o live). Uso:  with SesionCTrader("demo", cid, secreto, token) as s: ..."""

    URL_PRUEBAS = None          # las pruebas automáticas apuntan aquí a un servidor cTrader simulado

    def __init__(self, entorno, client_id, client_secret, access_token=None, espera=20, ctx_ssl=None):
        if entorno not in HOSTS:
            raise ValueError("Entorno cTrader no válido (demo | live)")
        self.entorno, self.cid, self.secreto, self.token = entorno, client_id, client_secret, access_token
        self.espera, self.ctx_ssl, self.ws, self.ctid = espera, ctx_ssl, None, None
        self.eventos = []

    def __enter__(self):
        self.abrir()
        return self

    def __exit__(self, *a):
        self.cerrar()

    def abrir(self):
        url = (self.URL_PRUEBAS or {}).get(self.entorno) if isinstance(self.URL_PRUEBAS, dict) else None
        self.ws = WebSocket(url or HOSTS[self.entorno], self.espera, self.ctx_ssl)
        try:
            self.pedir(PT["APP_AUTH_REQ"], {"clientId": self.cid, "clientSecret": self.secreto}, (PT["APP_AUTH_RES"],))
        except BaseException:
            self.cerrar()
            raise
        return self

    def cerrar(self):
        if self.ws:
            self.ws.cerrar()
            self.ws = None

    def _enviar(self, pt, payload, msgid=None):
        self.ws.enviar(json.dumps({"clientMsgId": msgid or uuid.uuid4().hex[:24], "payloadType": pt, "payload": payload}))

    def recibir(self, espera):
        while True:
            m = json.loads(self.ws.recibir(espera))
            pt = n(m.get("payloadType"))
            if pt == PT["HEARTBEAT"]:
                self.ws.enviar(json.dumps({"payloadType": PT["HEARTBEAT"]}))
                continue
            return pt, m.get("payload") or {}, m.get("clientMsgId")

    def pedir(self, pt, payload, respuestas, espera=None, filtro=None):
        """Envía y espera una de las `respuestas`. Los errores (2142/50/2132) se convierten en ErrorCTrader.
        Los eventos que lleguen mientras tanto se guardan en self.eventos."""
        msgid = uuid.uuid4().hex[:24]
        self._enviar(pt, payload, msgid)
        limite = time.monotonic() + (espera or self.espera)
        while True:
            resto = limite - time.monotonic()
            if resto <= 0:
                raise ErrorCTrader("TIEMPO_AGOTADO", f"cTrader no respondió al mensaje {pt}")
            try:
                rpt, p, mid = self.recibir(resto)
            except socket.timeout:
                raise ErrorCTrader("TIEMPO_AGOTADO", f"cTrader no respondió al mensaje {pt}") from None
            if rpt in (PT["ERROR_RES"], PT["ERROR_COMUN"]) and (mid in (None, msgid)):
                raise ErrorCTrader(p.get("errorCode", "ERROR"), p.get("description", ""))
            if rpt == PT["ORDER_ERROR_EVENT"]:
                raise ErrorCTrader(p.get("errorCode", "ORDER_ERROR"), p.get("description", ""))
            if rpt in (PT["ACCOUNTS_TOKEN_INVALIDATED"], PT["CLIENT_DISCONNECT"]):
                raise ErrorCTrader("CH_ACCESS_TOKEN_INVALID", p.get("reason", "token invalidado o cliente desconectado"))
            if rpt in respuestas and (filtro is None or filtro(rpt, p, mid == msgid)):
                return p
            self.eventos.append((rpt, p))

    # ----------------------------------------------------------------- operaciones de alto nivel
    def cuentas(self):
        p = self.pedir(PT["ACCOUNTS_BY_TOKEN_REQ"], {"accessToken": self.token}, (PT["ACCOUNTS_BY_TOKEN_RES"],))
        out = []
        for c in p.get("ctidTraderAccount", []):
            out.append({"ctid": n(c.get("ctidTraderAccountId")), "real": bool(c.get("isLive")), "login": n(c.get("traderLogin")),
                        "broker": c.get("brokerTitleShort") or c.get("brokerName")})
        return {"cuentas": out, "permiso": p.get("permissionScope")}

    def autorizar_cuenta(self, ctid):
        self.pedir(PT["ACCOUNT_AUTH_REQ"], {"ctidTraderAccountId": int(ctid), "accessToken": self.token}, (PT["ACCOUNT_AUTH_RES"],))
        self.ctid = int(ctid)

    def refrescar_token(self, refresh_token):
        p = self.pedir(PT["REFRESH_TOKEN_REQ"], {"refreshToken": refresh_token}, (PT["REFRESH_TOKEN_RES"],))
        return {"access_token": p["accessToken"], "refresh_token": p.get("refreshToken"), "expira_s": n(p.get("expiresIn"))}

    def trader(self):
        t = self.pedir(PT["TRADER_REQ"], {"ctidTraderAccountId": self.ctid}, (PT["TRADER_RES"],))["trader"]
        md = n(t.get("moneyDigits"), 2)
        return {"balance": n(t.get("balance"), 0) / 10 ** md, "moneyDigits": md, "depositAssetId": n(t.get("depositAssetId")),
                "apalancamiento": n(t.get("leverageInCents"), 0) / 100 if t.get("leverageInCents") else None}

    def activos(self):
        p = self.pedir(PT["ASSET_LIST_REQ"], {"ctidTraderAccountId": self.ctid}, (PT["ASSET_LIST_RES"],))
        return {n(a.get("assetId")): a.get("name") for a in p.get("asset", [])}

    def simbolos(self):
        p = self.pedir(PT["SYMBOLS_LIST_REQ"], {"ctidTraderAccountId": self.ctid}, (PT["SYMBOLS_LIST_RES"],))
        return [{"id": n(s.get("symbolId")), "nombre": s.get("symbolName"), "base": n(s.get("baseAssetId")),
                 "cotizada": n(s.get("quoteAssetId")), "activo": s.get("enabled", True),
                 "descripcion": s.get("description"), "categoria": n(s.get("symbolCategoryId"))} for s in p.get("symbol", [])]

    def simbolo(self, sid):
        p = self.pedir(PT["SYMBOL_BY_ID_REQ"], {"ctidTraderAccountId": self.ctid, "symbolId": [int(sid)]}, (PT["SYMBOL_BY_ID_RES"],))
        if not p.get("symbol"):
            raise ErrorCTrader("SIMBOLO_NO_ENCONTRADO", str(sid))
        s = p["symbol"][0]
        return {"id": n(s.get("symbolId")), "digitos": n(s.get("digits"), 5), "pip": n(s.get("pipPosition"), 4),
                "lote": n(s.get("lotSize")), "vol_min": n(s.get("minVolume"), 1), "vol_max": n(s.get("maxVolume")),
                "vol_paso": n(s.get("stepVolume"), 1)}

    def cotizacion(self, sid, espera=15):
        sid = int(sid)
        self.pedir(PT["SUBSCRIBE_SPOTS_REQ"], {"ctidTraderAccountId": self.ctid, "symbolId": [sid], "subscribeToSpotTimestamp": True},
                   (PT["SUBSCRIBE_SPOTS_RES"],))
        bid = ask = ts = None
        limite = time.monotonic() + espera
        while bid is None or ask is None:
            if time.monotonic() > limite:
                break
            ev = next(((pt, p) for pt, p in self.eventos if pt == PT["SPOT_EVENT"] and n(p.get("symbolId")) == sid), None)
            if ev:
                self.eventos.remove(ev)
                p = ev[1]
            else:
                try:
                    pt, p, _ = self.recibir(max(0.1, limite - time.monotonic()))
                except socket.timeout:
                    break
                if pt != PT["SPOT_EVENT"] or n(p.get("symbolId")) != sid:
                    self.eventos.append((pt, p))
                    continue
            bid = n(p.get("bid"), None) if p.get("bid") is not None else bid
            ask = n(p.get("ask"), None) if p.get("ask") is not None else ask
            ts = n(p.get("timestamp"), None) or ts
        try:
            self.pedir(PT["UNSUBSCRIBE_SPOTS_REQ"], {"ctidTraderAccountId": self.ctid, "symbolId": [sid]}, (PT["UNSUBSCRIBE_SPOTS_RES"],), espera=5)
        except ErrorCTrader:
            pass
        if bid is None or ask is None:
            raise ErrorCTrader("SIN_COTIZACION", "cTrader no envió bid y ask a tiempo (¿mercado cerrado?)")
        ahora = time.time()
        ts_s = ts / 1000 if ts and ts > 1e11 else (ts or ahora)
        return {"bid": bid / ESCALA, "ask": ask / ESCALA, "precio": (bid + ask) / 2 / ESCALA, "spread": (ask - bid) / ESCALA,
                "ts": int(ts_s), "edad_s": max(0, int(ahora - ts_s))}

    def velas(self, sid, intervalo, desde_ms, hasta_ms, cuenta=None):
        """Trendbars con regulador de frecuencia para todo el proceso (cTrader limita las peticiones de históricos) y un
        reintento con espera si el broker responde que se superó el límite."""
        for intento in range(3):
            _regular_historicos()
            try:
                return self._velas(sid, intervalo, desde_ms, hasta_ms, cuenta)
            except ErrorCTrader as e:
                if "BLOCKED_PAYLOAD_TYPE" not in (e.codigo or "") or intento == 2:
                    raise
                time.sleep(2.0 * (intento + 1))

    def _velas(self, sid, intervalo, desde_ms, hasta_ms, cuenta=None):
        per = PERIODO.get(intervalo)
        if not per:
            raise ValueError("Intervalo no disponible en cTrader: " + str(intervalo))
        pl = {"ctidTraderAccountId": self.ctid, "symbolId": int(sid), "period": per, "fromTimestamp": int(desde_ms), "toTimestamp": int(hasta_ms)}
        if cuenta:
            pl["count"] = int(cuenta)
        p = self.pedir(PT["GET_TRENDBARS_REQ"], pl, (PT["GET_TRENDBARS_RES"],), espera=40)
        out = []
        for b in p.get("trendbar", []):
            lo = n(b.get("low"), 0)
            out.append([n(b.get("utcTimestampInMinutes"), 0) * 60, (lo + n(b.get("deltaOpen"), 0)) / ESCALA,
                        (lo + n(b.get("deltaHigh"), 0)) / ESCALA, lo / ESCALA, (lo + n(b.get("deltaClose"), 0)) / ESCALA, n(b.get("volume"), 0)])
        return sorted(out)

    def posiciones(self):
        p = self.pedir(PT["RECONCILE_REQ"], {"ctidTraderAccountId": self.ctid}, (PT["RECONCILE_RES"],))
        out = []
        for x in p.get("position", []):
            td = x.get("tradeData", {})
            out.append({"id": n(x.get("positionId")), "simbolo": n(td.get("symbolId")), "volumen": n(td.get("volume")),
                        "lado": enum(td.get("tradeSide"), {1: "BUY", 2: "SELL"}), "precio": x.get("price"),
                        "etiqueta": td.get("label"), "stop": x.get("stopLoss"), "objetivo": x.get("takeProfit")})
        return out

    def _esperar_ejecucion(self, filtro, espera=25):
        """Espera ORDER_FILLED (o rechazo) del evento de ejecución que cumpla `filtro`."""
        limite = time.monotonic() + espera
        while time.monotonic() < limite:
            ev = next(((pt, p) for pt, p in self.eventos if pt == PT["EXECUTION_EVENT"] and filtro(p)), None)
            if ev:
                self.eventos.remove(ev)
                p = ev[1]
            else:
                try:
                    pt, p, _ = self.recibir(max(0.1, limite - time.monotonic()))
                except socket.timeout:
                    break
                if pt == PT["ORDER_ERROR_EVENT"]:
                    raise ErrorCTrader(p.get("errorCode", "ORDER_ERROR"), p.get("description", ""))
                if pt == PT["ERROR_RES"]:
                    raise ErrorCTrader(p.get("errorCode", "ERROR"), p.get("description", ""))
                if pt != PT["EXECUTION_EVENT"] or not filtro(p):
                    self.eventos.append((pt, p))
                    continue
            tipo = enum(p.get("executionType"), EJECUCION)
            if tipo == "ORDER_FILLED":
                return p
            if tipo in ("ORDER_REJECTED", "ORDER_CANCELLED", "ORDER_EXPIRED"):
                raise ErrorCTrader(p.get("errorCode") or tipo, "orden no ejecutada")
        raise ErrorCTrader("TIEMPO_AGOTADO", "no llegó la confirmación de ejecución")

    def orden_mercado(self, sid, lado, volumen, rel_stop, rel_obj, etiqueta, ref_cliente, comentario=""):
        pl = {"ctidTraderAccountId": self.ctid, "symbolId": int(sid), "orderType": TIPO_ORDEN["MARKET"], "tradeSide": LADO[lado],
              "volume": int(volumen), "label": etiqueta[:100], "clientOrderId": ref_cliente[:50], "comment": comentario[:512]}
        if rel_stop:
            pl["relativeStopLoss"] = int(rel_stop)
        if rel_obj:
            pl["relativeTakeProfit"] = int(rel_obj)
        self._enviar(PT["NEW_ORDER_REQ"], pl)
        p = self._esperar_ejecucion(lambda e: (e.get("order") or {}).get("clientOrderId") == ref_cliente)
        pos, deal = p.get("position") or {}, p.get("deal") or {}
        return {"posicion": n(pos.get("positionId") or deal.get("positionId")), "precio": deal.get("executionPrice") or pos.get("price"),
                "volumen": n(deal.get("filledVolume") or deal.get("volume") or volumen), "comision": n(deal.get("commission"), 0),
                "moneyDigits": n(deal.get("moneyDigits") or pos.get("moneyDigits"), 2)}

    def modificar_sltp(self, pos_id, stop=None, objetivo=None, espera=15):
        """ProtoOAAmendPositionSLTPReq: fija stop y objetivo ABSOLUTOS de una posición abierta. Devuelve el evento de ejecución
        del broker para esa posición; lanza ErrorCTrader si el broker lo rechaza o no responde."""
        pl = {"ctidTraderAccountId": self.ctid, "positionId": int(pos_id)}
        if stop is not None:
            pl["stopLoss"] = float(stop)
        if objetivo is not None:
            pl["takeProfit"] = float(objetivo)
        self._enviar(PT["AMEND_POSITION_SLTP_REQ"], pl)
        es_suyo = lambda p: n((p.get("position") or {}).get("positionId")) == int(pos_id)   # noqa: E731
        limite = time.monotonic() + espera
        while time.monotonic() < limite:
            ev = next(((pt, p) for pt, p in self.eventos if pt == PT["EXECUTION_EVENT"] and es_suyo(p)), None)
            if ev:
                self.eventos.remove(ev)
                return ev[1]
            try:
                pt, p, _ = self.recibir(max(0.1, limite - time.monotonic()))
            except socket.timeout:
                break
            if pt in (PT["ORDER_ERROR_EVENT"], PT["ERROR_RES"]):
                raise ErrorCTrader(p.get("errorCode", "ERROR"), p.get("description", ""))
            if pt == PT["EXECUTION_EVENT"] and es_suyo(p):
                return p
            self.eventos.append((pt, p))
        raise ErrorCTrader("TIEMPO_AGOTADO", "cTrader no confirmó la modificación del stop/objetivo")

    def cerrar_posicion(self, pos_id, volumen):
        self._enviar(PT["CLOSE_POSITION_REQ"], {"ctidTraderAccountId": self.ctid, "positionId": int(pos_id), "volume": int(volumen)})
        p = self._esperar_ejecucion(lambda e: n((e.get("position") or {}).get("positionId")) == int(pos_id)
                                    or n((e.get("deal") or {}).get("positionId")) == int(pos_id))
        return p

    def cierres(self, desde_ms, hasta_ms):
        """Deals de cierre (con closePositionDetail) en la ventana: resultado neto por posición."""
        p = self.pedir(PT["DEAL_LIST_REQ"], {"ctidTraderAccountId": self.ctid, "fromTimestamp": int(desde_ms), "toTimestamp": int(hasta_ms),
                                             "maxRows": 1000}, (PT["DEAL_LIST_RES"],), espera=40)
        out = {}
        for d in p.get("deal", []):
            cd = d.get("closePositionDetail")
            if not cd:
                continue
            md = n(cd.get("moneyDigits") or d.get("moneyDigits"), 2)
            pid = n(d.get("positionId"))
            neto = (n(cd.get("grossProfit"), 0) + n(cd.get("swap"), 0) + n(cd.get("commission"), 0)) / 10 ** md
            prev = out.get(pid)
            out[pid] = {"posicion": pid, "precio_salida": d.get("executionPrice"), "resultado": neto + (prev["resultado"] if prev else 0),
                        "ts": n(d.get("executionTimestamp"), 0) // 1000, "volumen_cerrado": n(cd.get("closedVolume"))}
        return out
