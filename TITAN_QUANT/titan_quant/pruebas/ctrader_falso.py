"""Servidor cTrader Open API SIMULADO (WebSocket + JSON) para las pruebas automáticas.

Reproduce lo que TITAN usa del protocolo oficial: autenticación de aplicación y de cuenta, lista de cuentas por token
(con isLive y permissionScope), renovación de token, activos, símbolos, detalle de símbolo, trader, suscripción a spots,
velas (trendbars con deltas), órdenes a mercado con stop/objetivo RELATIVOS, ejecución, reconcile, cierre, deals,
heartbeat y ping. Dos instancias independientes: DEMO y LIVE, cada una con SOLO sus cuentas (como los hosts reales).
No es un sustituto de probar con tu cuenta demo real: sirve para comprobar la lógica de TITAN sin red.
"""
import base64
import hashlib
import itertools
import json
import math
import random
import socketserver
import struct
import threading
import time

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
ESC = 100000
PERIODO_S = {1: 60, 5: 300, 7: 900, 8: 1800, 9: 3600, 10: 14400, 12: 86400, 13: 604800}
ACTIVOS = {1: "USD", 2: "EUR", 5: "XAU", 6: "XAG"}
SIMBOLOS = {
    41: {"symbolName": "XAUUSD", "baseAssetId": 5, "quoteAssetId": 1, "digits": 2, "pipPosition": 1, "lotSize": 10000,
         "minVolume": 100, "maxVolume": 10000000, "stepVolume": 100},
    1: {"symbolName": "EURUSD", "baseAssetId": 2, "quoteAssetId": 1, "digits": 5, "pipPosition": 4, "lotSize": 10000000,
        "minVolume": 100000, "maxVolume": 10000000000, "stepVolume": 100000},
    42: {"symbolName": "XAGUSD", "baseAssetId": 6, "quoteAssetId": 1, "digits": 3, "pipPosition": 2, "lotSize": 500000,
         "minVolume": 100, "maxVolume": 10000000, "stepVolume": 100, "enabled": False},
}


class Mundo:
    """Estado compartido por los dos servidores: tokens y cuentas. Cada cuenta pertenece a UN entorno."""

    def __init__(self):
        self.client_id, self.client_secret = "app-prueba", "secreto-app"
        self.tokens = {"tok-trading": "SCOPE_TRADE", "tok-lectura": "SCOPE_VIEW"}
        self.refresh = {"ref-1": "tok-trading"}
        self.precios = {41: [2000.00, 2000.40], 1: [1.08000, 1.08010], 42: [25.000, 25.030]}
        self.cuentas = {
            9001: {"live": False, "login": 5001, "deposito": 1, "balance": 1000000, "env": "demo"},     # 10 000,00 USD
            9002: {"live": False, "login": 5002, "deposito": 2, "balance": 500000, "env": "demo"},      # 5 000,00 EUR
            7001: {"live": True, "login": 6001, "deposito": 1, "balance": 200000, "env": "live"},       # 2 000,00 USD
        }
        for c in self.cuentas.values():
            c.update(posiciones={}, deals=[])
        self.ids = itertools.count(100)
        self.L = threading.RLock()
        self.ordenes = []                 # registro de todas las órdenes recibidas (para las aserciones)
        self.modificaciones = []          # modificaciones de SL/TP recibidas (2110)
        self.enum_como_texto = False      # alterna la forma de los enums en las respuestas
        self.velas_n = 400

    # ----------------------------------------------------------------- utilidades de prueba
    def mover(self, sid, bid, ask):
        """Cambia el precio y ejecuta stops/objetivos alcanzados (como el broker)."""
        with self.L:
            self.precios[sid] = [bid, ask]
            for ctid, c in self.cuentas.items():
                for pid, p in list(c["posiciones"].items()):
                    if p["symbolId"] != sid:
                        continue
                    compra = p["side"] == 1
                    if p["sl"] is not None and ((compra and bid <= p["sl"]) or (not compra and ask >= p["sl"])):
                        self._cerrar(ctid, pid, p["volume"], p["sl"])
                    elif p["tp"] is not None and ((compra and bid >= p["tp"]) or (not compra and ask <= p["tp"])):
                        self._cerrar(ctid, pid, p["volume"], p["tp"])

    def _conv(self, c, sid, importe_cotizada):
        s = SIMBOLOS[sid]
        if s["quoteAssetId"] == c["deposito"]:
            return importe_cotizada
        if c["deposito"] == 2 and s["quoteAssetId"] == 1:      # USD → EUR
            return importe_cotizada / ((self.precios[1][0] + self.precios[1][1]) / 2)
        raise RuntimeError("conversión no simulada")

    def _cerrar(self, ctid, pid, volumen, precio):
        c = self.cuentas[ctid]
        p = c["posiciones"].pop(pid)
        unidades = volumen / 100
        bruto = (precio - p["price"]) * unidades * (1 if p["side"] == 1 else -1)
        bruto_dep = self._conv(c, p["symbolId"], bruto)
        comision = -int(round(unidades * p["price"] * 0.00002 * 100))        # 0,002 % del nominal, en centavos
        g = int(round(bruto_dep * 100))
        c["balance"] += g + comision
        d = {"dealId": next(self.ids), "positionId": pid, "symbolId": p["symbolId"], "volume": volumen, "filledVolume": volumen,
             "executionPrice": precio, "executionTimestamp": int(time.time() * 1000), "tradeSide": 2 if p["side"] == 1 else 1,
             "commission": comision, "moneyDigits": 2,
             "closePositionDetail": {"entryPrice": p["price"], "grossProfit": g, "swap": 0, "commission": comision,
                                     "balance": c["balance"], "closedVolume": volumen, "moneyDigits": 2}}
        c["deals"].append(d)
        return d, p


class _Manejador(socketserver.BaseRequestHandler):
    def setup(self):
        self.buf = b""
        self.app = False
        self.cuentas_auth = set()
        self.suscritos = set()

    # ----------------------------------------------------------------- WebSocket servidor
    def _leer(self, k):
        while len(self.buf) < k:
            t = self.request.recv(65536)
            if not t:
                raise ConnectionError
            self.buf += t
        out, self.buf = self.buf[:k], self.buf[k:]
        return out

    def _trama(self, op, datos):
        L = len(datos)
        cab = bytes([0x80 | op]) + (bytes([L]) if L < 126 else bytes([126]) + struct.pack(">H", L) if L < 65536 else bytes([127]) + struct.pack(">Q", L))
        self.request.sendall(cab + datos)

    def enviar(self, pt, payload=None, mid=None):
        m = {"payloadType": pt}
        if payload is not None:
            m["payload"] = payload
        if mid:
            m["clientMsgId"] = mid
        self._trama(0x1, json.dumps(m).encode())

    def recibir(self):
        while True:
            b1, b2 = self._leer(2)
            op, L = b1 & 0x0F, b2 & 0x7F
            if L == 126:
                L = struct.unpack(">H", self._leer(2))[0]
            elif L == 127:
                L = struct.unpack(">Q", self._leer(8))[0]
            if not b2 & 0x80:
                raise ConnectionError("trama de cliente sin máscara (RFC 6455 lo prohíbe)")
            m = self._leer(4)
            datos = bytes(b ^ m[i % 4] for i, b in enumerate(self._leer(L)))
            if op == 0x8:
                raise ConnectionError
            if op in (0x9, 0xA):
                continue
            return json.loads(datos.decode())

    def handle(self):
        cab = b""
        while b"\r\n\r\n" not in cab:
            t = self.request.recv(4096)
            if not t:
                return
            cab += t
        clave = next(ln.split(":", 1)[1].strip() for ln in cab.decode().split("\r\n") if ln.lower().startswith("sec-websocket-key"))
        acc = base64.b64encode(hashlib.sha1((clave + GUID).encode()).digest()).decode()
        self.request.sendall(f"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {acc}\r\n\r\n".encode())
        try:
            while True:
                m = self.recibir()
                if m.get("payloadType") == 51:
                    continue
                self.server.mundo.L.acquire()
                try:
                    self.procesar(int(m["payloadType"]), m.get("payload") or {}, m.get("clientMsgId"))
                finally:
                    self.server.mundo.L.release()
        except (ConnectionError, OSError, StopIteration, ValueError):
            pass

    # ----------------------------------------------------------------- protocolo
    def error(self, codigo, desc, mid, ctid=None):
        p = {"errorCode": codigo, "description": desc}
        if ctid:
            p["ctidTraderAccountId"] = ctid
        self.enviar(2142, p, mid)

    def _enum(self, num, texto):
        return texto if self.server.mundo.enum_como_texto else num

    def procesar(self, pt, p, mid):
        W = self.server.mundo
        env = self.server.entorno
        if pt == 2100:
            if p.get("clientId") != W.client_id or p.get("clientSecret") != W.client_secret:
                return self.error("CH_CLIENT_AUTH_FAILURE", "Client authentication failure", mid)
            self.app = True
            self.enviar(2101, {}, mid)
            self.enviar(51)                                    # heartbeat del servidor: el cliente debe ignorarlo/contestar
            self._trama(0x9, b"ping")                          # ping WebSocket: el cliente debe contestar pong
            return
        if not self.app:
            return self.error("CH_CLIENT_NOT_AUTHENTICATED", "App not authorized", mid)
        if pt == 2149:
            tok = p.get("accessToken")
            if tok not in W.tokens:
                return self.error("CH_ACCESS_TOKEN_INVALID", "Invalid access token", mid)
            self.enviar(2150, {"accessToken": tok, "permissionScope": W.tokens[tok],
                               "ctidTraderAccount": [{"ctidTraderAccountId": str(k), "isLive": c["live"], "traderLogin": str(c["login"]),
                                                      "brokerTitleShort": "BrokerPrueba"} for k, c in W.cuentas.items()]}, mid)
            return
        if pt == 2173:
            ref = p.get("refreshToken")
            if ref not in W.refresh:
                return self.error("ACCESS_DENIED", "Invalid refresh token", mid)
            viejo = W.refresh.pop(ref)
            nuevo, nref = f"tok-{next(W.ids)}", f"ref-{next(W.ids)}"
            W.tokens[nuevo] = W.tokens.pop(viejo, "SCOPE_TRADE")
            W.refresh[nref] = nuevo
            self.enviar(2174, {"accessToken": nuevo, "tokenType": "bearer", "expiresIn": 2628000, "refreshToken": nref}, mid)
            return
        ctid = int(p.get("ctidTraderAccountId") or 0)
        if pt == 2102:
            if p.get("accessToken") not in W.tokens:
                return self.error("CH_ACCESS_TOKEN_INVALID", "Invalid access token", mid, ctid)
            c = W.cuentas.get(ctid)
            if not c or c["env"] != env:                        # una cuenta real no existe en el host demo y viceversa
                return self.error("CANT_ROUTE_REQUEST", f"Account {ctid} is not on the {env} server", mid, ctid)
            self.cuentas_auth.add(ctid)
            self.token = p["accessToken"]
            self.enviar(2103, {"ctidTraderAccountId": ctid}, mid)
            return
        if ctid not in self.cuentas_auth:
            return self.error("ACCOUNT_NOT_AUTHORIZED", "Trading account is not authorized", mid, ctid)
        c = W.cuentas[ctid]
        if pt == 2121:
            self.enviar(2122, {"ctidTraderAccountId": ctid, "trader": {"ctidTraderAccountId": ctid, "balance": str(c["balance"]),
                                                                        "depositAssetId": str(c["deposito"]), "moneyDigits": 2,
                                                                        "leverageInCents": 10000}}, mid)
        elif pt == 2112:
            self.enviar(2113, {"ctidTraderAccountId": ctid, "asset": [{"assetId": k, "name": v} for k, v in ACTIVOS.items()]}, mid)
        elif pt == 2114:
            self.enviar(2115, {"ctidTraderAccountId": ctid, "symbol": [
                {"symbolId": k, "symbolName": v["symbolName"], "enabled": v.get("enabled", True), "baseAssetId": v["baseAssetId"],
                 "quoteAssetId": v["quoteAssetId"]} for k, v in SIMBOLOS.items()]}, mid)
        elif pt == 2116:
            out = [{"symbolId": k, **{x: y for x, y in SIMBOLOS[k].items() if x not in ("symbolName", "baseAssetId", "quoteAssetId", "enabled")}}
                   for k in p.get("symbolId", []) if k in SIMBOLOS]
            self.enviar(2117, {"ctidTraderAccountId": ctid, "symbol": out}, mid)
        elif pt == 2127:
            self.enviar(2128, {"ctidTraderAccountId": ctid}, mid)
            for sid in p.get("symbolId", []):
                bid, ask = W.precios[sid]
                self.enviar(2131, {"ctidTraderAccountId": ctid, "symbolId": sid, "bid": int(round(bid * ESC)), "ask": int(round(ask * ESC)),
                                   "timestamp": int(time.time() * 1000)})
        elif pt == 2129:
            self.enviar(2130, {"ctidTraderAccountId": ctid}, mid)
        elif pt == 2137:
            self._velas(ctid, p, mid)
        elif pt == 2106:
            self._orden(ctid, c, p, mid)
        elif pt == 2111:
            pid = int(p["positionId"])
            if pid not in c["posiciones"]:
                return self.error("POSITION_NOT_FOUND", "Position not found", mid, ctid)
            pos = c["posiciones"][pid]
            bid, ask = W.precios[pos["symbolId"]]
            d, pos = W._cerrar(ctid, pid, int(p["volume"]), bid if pos["side"] == 1 else ask)
            self.enviar(2126, {"ctidTraderAccountId": ctid, "executionType": self._enum(3, "ORDER_FILLED"),
                               "position": {"positionId": pid, "positionStatus": 2, "tradeData": {"symbolId": pos["symbolId"], "volume": 0}},
                               "deal": d}, mid)
        elif pt == 2110:
            pid = int(p["positionId"])
            if pid not in c["posiciones"]:
                return self.error("POSITION_NOT_FOUND", "Position not found", mid, ctid)
            pos = c["posiciones"][pid]
            bid, ask = W.precios[pos["symbolId"]]
            compra = pos["side"] == 1
            sl = p.get("stopLoss", pos["sl"])
            if sl is not None and ((compra and sl >= bid) or (not compra and sl <= ask)):
                return self.enviar(2132, {"ctidTraderAccountId": ctid, "errorCode": "TRADING_BAD_STOPS", "description": "SL al otro lado del precio"}, mid)
            pos["sl"], pos["tp"] = sl, p.get("takeProfit", pos["tp"])
            W.modificaciones.append({"ctid": ctid, "positionId": pid, "sl": pos["sl"], "tp": pos["tp"]})
            self.enviar(2126, {"ctidTraderAccountId": ctid, "executionType": self._enum(4, "ORDER_REPLACED"),
                               "position": {"positionId": pid, "price": pos["price"], "stopLoss": pos["sl"], "takeProfit": pos["tp"],
                                            "tradeData": {"symbolId": pos["symbolId"], "volume": pos["volume"], "tradeSide": pos["side"]}}}, mid)
        elif pt == 2124:
            self.enviar(2125, {"ctidTraderAccountId": ctid, "position": [
                {"positionId": str(k), "price": v["price"], "stopLoss": v["sl"], "takeProfit": v["tp"], "moneyDigits": 2,
                 "tradeData": {"symbolId": v["symbolId"], "volume": str(v["volume"]), "tradeSide": self._enum(v["side"], "BUY" if v["side"] == 1 else "SELL"),
                               "label": v["label"]}} for k, v in c["posiciones"].items()], "order": []}, mid)
        elif pt == 2133:
            d0, d1 = int(p["fromTimestamp"]), int(p["toTimestamp"])
            self.enviar(2134, {"ctidTraderAccountId": ctid, "deal": [d for d in c["deals"] if d0 <= d["executionTimestamp"] <= d1], "hasMore": False}, mid)
        else:
            self.error("UNSUPPORTED_MESSAGE", f"payloadType {pt} no simulado", mid, ctid)

    def _velas(self, ctid, p, mid):
        W = self.server.mundo
        sid, per = int(p["symbolId"]), int(p["period"])
        paso = PERIODO_S[per]
        hasta = int(p["toTimestamp"]) // 1000 // paso * paso
        n = min(int(p.get("count") or W.velas_n), W.velas_n)
        rnd = random.Random(sid * 1000 + per)
        precio = (W.precios[sid][0] + W.precios[sid][1]) / 2
        dig = SIMBOLOS[sid]["digits"]
        barras, c = [], precio
        for i in range(n):                                       # hacia atrás desde el precio actual
            t = hasta - i * paso
            o = c * (1 + rnd.gauss(0, 0.0015)) + (0.0004 * c * math.sin(i / 15))
            h = max(o, c) * (1 + abs(rnd.gauss(0, 0.0006)))
            lo = min(o, c) * (1 - abs(rnd.gauss(0, 0.0006)))
            q = lambda x: int(round(round(x, dig) * ESC))       # noqa: E731
            barras.append({"utcTimestampInMinutes": t // 60, "low": str(q(lo)), "deltaOpen": q(o) - q(lo), "deltaHigh": q(h) - q(lo),
                           "deltaClose": q(c) - q(lo), "volume": str(rnd.randint(50, 900)), "period": per})
            c = o
        desde = int(p["fromTimestamp"]) // 1000
        barras = [b for b in reversed(barras) if b["utcTimestampInMinutes"] * 60 >= desde]
        self.enviar(2138, {"ctidTraderAccountId": ctid, "period": per, "trendbar": barras, "symbolId": sid}, mid)

    def _orden(self, ctid, c, p, mid):
        W = self.server.mundo
        W.ordenes.append({"entorno": self.server.entorno, "ctid": ctid, **p})
        if W.tokens.get(self.token) != "SCOPE_TRADE":
            return self.error("NOT_ENOUGH_PERMISSION", "Access token has no trading permission", mid, ctid)
        sid = int(p["symbolId"])
        s = SIMBOLOS.get(sid)
        if not s:
            return self.error("SYMBOL_NOT_FOUND", "Symbol not found", mid, ctid)
        vol = int(p["volume"])
        if vol < s["minVolume"] or vol > s["maxVolume"] or vol % s["stepVolume"]:
            return self.enviar(2132, {"ctidTraderAccountId": ctid, "errorCode": "TRADING_BAD_VOLUME", "description": f"volumen {vol} no válido"}, mid)
        if int(p.get("orderType", 0)) != 1:
            return self.error("UNSUPPORTED", "solo mercado en el simulador", mid, ctid)
        if "stopLoss" in p or "takeProfit" in p:
            return self.error("TRADING_BAD_STOPS", "Market orders must use relative SL/TP", mid, ctid)
        paso = 10 ** (5 - s["digits"])
        for k in ("relativeStopLoss", "relativeTakeProfit"):
            if k in p and int(p[k]) % paso:
                return self.error("TRADING_BAD_STOPS", f"{k} no es múltiplo de {paso}", mid, ctid)
        lado = int(p["tradeSide"])
        bid, ask = W.precios[sid]
        precio = ask if lado == 1 else bid
        sg = 1 if lado == 1 else -1
        sl = round(precio - sg * int(p["relativeStopLoss"]) / ESC, s["digits"]) if p.get("relativeStopLoss") else None
        tp = round(precio + sg * int(p["relativeTakeProfit"]) / ESC, s["digits"]) if p.get("relativeTakeProfit") else None
        pid, oid = next(W.ids), next(W.ids)
        c["posiciones"][pid] = {"symbolId": sid, "volume": vol, "side": lado, "price": precio, "sl": sl, "tp": tp, "label": p.get("label")}
        comision = -int(round(vol / 100 * precio * 0.00002 * 100))
        c["balance"] += comision
        orden = {"orderId": oid, "clientOrderId": p.get("clientOrderId"), "orderType": self._enum(1, "MARKET"),
                 "tradeData": {"symbolId": sid, "volume": vol, "tradeSide": self._enum(lado, "BUY" if lado == 1 else "SELL")}}
        pos = {"positionId": pid, "price": precio, "stopLoss": sl, "takeProfit": tp, "moneyDigits": 2,
               "tradeData": {"symbolId": sid, "volume": vol, "tradeSide": lado, "label": p.get("label")}}
        self.enviar(2126, {"ctidTraderAccountId": ctid, "executionType": self._enum(2, "ORDER_ACCEPTED"), "order": orden, "position": pos})
        self.enviar(2131, {"ctidTraderAccountId": ctid, "symbolId": sid, "bid": int(bid * ESC), "ask": int(ask * ESC)})   # evento intercalado
        deal = {"dealId": next(W.ids), "orderId": oid, "positionId": pid, "symbolId": sid, "volume": vol, "filledVolume": vol,
                "executionPrice": precio, "executionTimestamp": int(time.time() * 1000), "commission": comision, "moneyDigits": 2,
                "tradeSide": lado}
        c["deals"].append(deal)
        self.enviar(2126, {"ctidTraderAccountId": ctid, "executionType": self._enum(3, "ORDER_FILLED"), "order": orden, "position": pos,
                           "deal": deal})


class _Servidor(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


class CTraderFalso:
    """Arranca DEMO y LIVE en puertos locales y apunta SesionCTrader.URL_PRUEBAS a ellos."""

    def __init__(self):
        self.mundo = Mundo()
        self.servidores = {}

    def __enter__(self):
        return self.iniciar()

    def __exit__(self, *a):
        self.detener()

    def iniciar(self):
        from titan_quant.trader.ctrader_ws import SesionCTrader
        urls = {}
        for env in ("demo", "live"):
            s = _Servidor(("127.0.0.1", 0), _Manejador)
            s.mundo, s.entorno = self.mundo, env
            threading.Thread(target=s.serve_forever, daemon=True).start()
            self.servidores[env] = s
            urls[env] = f"ws://127.0.0.1:{s.server_address[1]}/"
        self._anterior = SesionCTrader.URL_PRUEBAS
        SesionCTrader.URL_PRUEBAS = urls
        return self

    def detener(self):
        from titan_quant.trader import ctrader
        from titan_quant.trader.ctrader_ws import SesionCTrader
        SesionCTrader.URL_PRUEBAS = self._anterior
        ctrader._CACHE.clear()
        for s in self.servidores.values():
            s.shutdown()
            s.server_close()

