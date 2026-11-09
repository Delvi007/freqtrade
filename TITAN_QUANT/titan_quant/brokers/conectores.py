"""Conectores reales escritos según la documentación oficial de cada API.

OANDA v20 (developer.oanda.com/rest-live-v20) · Alpaca Trading/Market Data v2 (docs.alpaca.markets) · Tradier Brokerage
(documentation.tradier.com) · Kraken REST (docs.kraken.com/api) · Coinbase Advanced Trade (docs.cdp.coinbase.com).
"""
import base64
import hashlib
import hmac
import time
import urllib.parse

from .base import Conector, ErrorBroker, f, ts_iso
from ..trader.base import ErrorAdaptador

TF_OANDA = {"1m": "M1", "5m": "M5", "15m": "M15", "30m": "M30", "1h": "H1", "4h": "H4", "1d": "D"}
TF_ALPACA = {"1m": "1Min", "5m": "5Min", "15m": "15Min", "30m": "30Min", "1h": "1Hour", "4h": "4Hour", "1d": "1Day"}
TF_KRAKEN = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}
TF_COINBASE = {"1m": "ONE_MINUTE", "5m": "FIVE_MINUTE", "15m": "FIFTEEN_MINUTE", "30m": "THIRTY_MINUTE", "1h": "ONE_HOUR", "1d": "ONE_DAY"}
SEG = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}


# ================================================================================================ OANDA v20
class OANDA(Conector):
    id, nombre = "oanda", "OANDA"
    ENTORNOS = {"demo": "https://api-fxpractice.oanda.com", "real": "https://api-fxtrade.oanda.com"}
    CAMPOS = (("token", "Token personal de API"), ("cuenta", "Id de cuenta (opcional: se toma la primera)"))

    def cabeceras(self, metodo, ruta, cuerpo):
        if not self.cred.get("token"):
            raise ErrorBroker("OANDA: falta el token de API.")
        return {"Authorization": "Bearer " + self.cred["token"], "Accept-Datetime-Format": "UNIX"}

    def _cuenta_id(self):
        if not self.cred.get("cuenta"):
            cs = self.http("GET", "/v3/accounts").get("accounts") or []
            if not cs:
                raise ErrorBroker("OANDA: el token no tiene cuentas.")
            self.cred["cuenta"] = cs[0]["id"]
        return self.cred["cuenta"]

    @staticmethod
    def sym(s):
        s = str(s).upper().replace("/", "_")
        return s if "_" in s else (s[:3] + "_" + s[3:] if len(s) == 6 else s)

    def probar(self):
        a = self.cuenta()
        return {"ok": True, "detalle": f"cuenta {self._cuenta_id()} · saldo {a['balance']} {a['moneda']}",
                "capacidades": ["autenticacion", "cuenta", "posiciones", "ordenes", "ejecuciones", "cotizacion", "velas", "operar_demo"]}

    def cuenta(self):
        a = self.http("GET", f"/v3/accounts/{self._cuenta_id()}/summary")["account"]
        return {"balance": f(a.get("balance")), "equity": f(a.get("NAV")), "moneda": a.get("currency"), "margen_usado": f(a.get("marginUsed")),
                "pnl_no_realizado": f(a.get("unrealizedPL"))}

    def posiciones(self):
        out = []
        for t in self.http("GET", f"/v3/accounts/{self._cuenta_id()}/openTrades").get("trades") or []:
            u = f(t.get("currentUnits")) or 0
            out.append({"id_externo": str(t["id"]), "simbolo": t.get("instrument"), "lado": "compra" if u > 0 else "venta", "cantidad": abs(u),
                        "precio_entrada": f(t.get("price")), "pnl_no_realizado": f(t.get("unrealizedPL")),
                        "stop": f((t.get("stopLossOrder") or {}).get("price")), "objetivo": f((t.get("takeProfitOrder") or {}).get("price")),
                        "swap": f(t.get("financing")), "abierta_ts": ts_iso(t.get("openTime"))})
        return out

    def ordenes(self):
        return [{"id_externo": str(o["id"]), "simbolo": o.get("instrument"), "lado": "compra" if (f(o.get("units")) or 0) > 0 else "venta",
                 "cantidad": abs(f(o.get("units")) or 0), "tipo": o.get("type"), "precio": f(o.get("price")), "estado": o.get("state"),
                 "creada_ts": ts_iso(o.get("createTime"))}
                for o in self.http("GET", f"/v3/accounts/{self._cuenta_id()}/pendingOrders").get("orders") or []]

    def ejecuciones(self, desde_ts=None):
        r = self.http("GET", f"/v3/accounts/{self._cuenta_id()}/transactions/sinceid", {"id": self.cred.get("_desde_tx", 1)})
        out = []
        for t in r.get("transactions") or []:
            if t.get("type") != "ORDER_FILL":
                continue
            ts = ts_iso(t.get("time"))
            if desde_ts and ts and ts < desde_ts:
                continue
            u = f(t.get("units")) or 0
            out.append({"id_externo": str(t["id"]), "orden_id": str(t.get("orderID")), "simbolo": t.get("instrument"), "lado": "compra" if u > 0 else "venta",
                        "cantidad": abs(u), "precio": f(t.get("price")), "comision": f(t.get("commission")) or 0.0, "swap": f(t.get("financing")) or 0.0,
                        "pnl": f(t.get("pl")), "ts": ts, "parcial": bool(t.get("tradeReduced")),
                        "cerro": [x.get("tradeID") for x in (t.get("tradesClosed") or [])]})
        return out

    def cotizacion(self, simbolo):
        p = (self.http("GET", f"/v3/accounts/{self._cuenta_id()}/pricing", {"instruments": self.sym(simbolo)}).get("prices") or [None])[0]
        if not p:
            raise ErrorBroker("OANDA: sin precio.")
        bid, ask = f(p["bids"][0]["price"]), f(p["asks"][0]["price"])
        return {"bid": bid, "ask": ask, "precio": (bid + ask) / 2, "ts": ts_iso(p.get("time"))}

    def velas(self, simbolo, intervalo="1m", n=200):
        r = self.http("GET", f"/v3/instruments/{self.sym(simbolo)}/candles", {"granularity": TF_OANDA[intervalo], "count": min(5000, n + 1), "price": "M"})
        return [[ts_iso(c["time"]), f(c["mid"]["o"]), f(c["mid"]["h"]), f(c["mid"]["l"]), f(c["mid"]["c"]), c.get("volume", 0)]
                for c in r.get("candles") or [] if c.get("complete")][-n:]

    def abrir(self, simbolo, lado, cantidad, stop=None, objetivo=None):
        self._solo_demo("abrir operaciones")
        unidades = int(abs(cantidad)) * (1 if lado in ("compra", "alcista", "buy") else -1)
        orden = {"type": "MARKET", "instrument": self.sym(simbolo), "units": str(unidades), "timeInForce": "FOK", "positionFill": "DEFAULT"}
        if stop:
            orden["stopLossOnFill"] = {"price": f"{stop:.5f}"}
        if objetivo:
            orden["takeProfitOnFill"] = {"price": f"{objetivo:.5f}"}
        r = self.http("POST", f"/v3/accounts/{self._cuenta_id()}/orders", cuerpo={"order": orden}, accion="abrir orden")
        if r.get("orderCancelTransaction") or not r.get("orderFillTransaction"):
            raise ErrorAdaptador("OANDA rechazó la orden: " + str((r.get("orderCancelTransaction") or {}).get("reason") or r)[:200])
        fill = r["orderFillTransaction"]
        trade = fill.get("tradeOpened") or {}
        return {"id_externo": str(trade.get("tradeID") or fill["id"]), "precio_entrada": f(fill.get("price")), "comision": f(fill.get("commission")) or 0.0,
                "evidencia": {"orderFillTransaction": fill.get("id"), "tradeID": trade.get("tradeID")}}

    def cerrar(self, id_externo):
        self._solo_demo("cerrar operaciones")
        r = self.http("PUT", f"/v3/accounts/{self._cuenta_id()}/trades/{id_externo}/close", cuerpo={}, accion="cerrar")
        fill = r.get("orderFillTransaction") or {}
        return {"precio_salida": f(fill.get("price")), "resultado": f(fill.get("pl")), "comision": f(fill.get("commission")) or 0.0}

    def modificar_sltp(self, id_externo, stop=None, objetivo=None):
        self._solo_demo("modificar SL/TP")
        cuerpo = {}
        if stop:
            cuerpo["stopLoss"] = {"price": f"{stop:.5f}"}
        if objetivo:
            cuerpo["takeProfit"] = {"price": f"{objetivo:.5f}"}
        return self.http("PUT", f"/v3/accounts/{self._cuenta_id()}/trades/{id_externo}/orders", cuerpo=cuerpo, accion="modificar SL/TP")


# ================================================================================================ Alpaca
class Alpaca(Conector):
    id, nombre = "alpaca", "Alpaca"
    ENTORNOS = {"demo": "https://paper-api.alpaca.markets", "real": "https://api.alpaca.markets"}
    DATOS = "https://data.alpaca.markets"
    CAMPOS = (("clave", "API Key ID"), ("secreto", "API Secret Key"))

    def cabeceras(self, metodo, ruta, cuerpo):
        if not (self.cred.get("clave") and self.cred.get("secreto")):
            raise ErrorBroker("Alpaca: faltan la clave y el secreto de API.")
        return {"APCA-API-KEY-ID": self.cred["clave"], "APCA-API-SECRET-KEY": self.cred["secreto"]}

    def probar(self):
        a = self.cuenta()
        return {"ok": True, "detalle": f"cuenta {'paper' if self.entorno == 'demo' else 'real'} · equity {a['equity']} {a['moneda']}",
                "capacidades": ["autenticacion", "cuenta", "posiciones", "ordenes", "ejecuciones", "cotizacion", "velas", "operar_demo"]}

    def cuenta(self):
        a = self.http("GET", "/v2/account")
        return {"balance": f(a.get("cash")), "equity": f(a.get("equity")), "moneda": a.get("currency"), "margen_usado": f(a.get("initial_margin")),
                "pnl_no_realizado": None, "estado": a.get("status")}

    def posiciones(self):
        return [{"id_externo": p.get("asset_id") or p["symbol"], "simbolo": p["symbol"], "lado": "compra" if p.get("side") == "long" else "venta",
                 "cantidad": abs(f(p.get("qty")) or 0), "precio_entrada": f(p.get("avg_entry_price")), "pnl_no_realizado": f(p.get("unrealized_pl")),
                 "stop": None, "objetivo": None, "swap": 0.0, "abierta_ts": None} for p in self.http("GET", "/v2/positions") or []]

    def ordenes(self):
        return [{"id_externo": o["id"], "simbolo": o.get("symbol"), "lado": "compra" if o.get("side") == "buy" else "venta", "cantidad": f(o.get("qty")),
                 "tipo": o.get("type"), "precio": f(o.get("limit_price") or o.get("stop_price")), "estado": o.get("status"), "creada_ts": ts_iso(o.get("created_at"))}
                for o in self.http("GET", "/v2/orders", {"status": "open", "nested": "true"}) or []]

    def ejecuciones(self, desde_ts=None):
        params = {"direction": "desc", "page_size": 100}
        if desde_ts:
            params["after"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(desde_ts))
        return [{"id_externo": a["id"], "orden_id": a.get("order_id"), "simbolo": a.get("symbol"), "lado": "compra" if a.get("side") == "buy" else "venta",
                 "cantidad": f(a.get("qty")), "precio": f(a.get("price")), "comision": 0.0, "swap": 0.0, "pnl": None, "ts": ts_iso(a.get("transaction_time")),
                 "parcial": a.get("type") == "partial_fill"} for a in self.http("GET", "/v2/account/activities/FILL", params) or []]

    def cotizacion(self, simbolo):
        q = self.http("GET", f"/v2/stocks/{simbolo.upper()}/quotes/latest", base=self.DATOS).get("quote") or {}
        bid, ask = f(q.get("bp")), f(q.get("ap"))
        if not bid or not ask:
            raise ErrorBroker("Alpaca: sin cotización.")
        return {"bid": bid, "ask": ask, "precio": (bid + ask) / 2, "ts": ts_iso(q.get("t"))}

    def velas(self, simbolo, intervalo="1m", n=200):
        inicio = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - SEG[intervalo] * n * 3))
        r = self.http("GET", f"/v2/stocks/{simbolo.upper()}/bars", {"timeframe": TF_ALPACA[intervalo], "limit": min(10000, n), "start": inicio, "feed": "iex"},
                      base=self.DATOS)
        ahora = time.time()
        return [[ts_iso(b["t"]), f(b["o"]), f(b["h"]), f(b["l"]), f(b["c"]), b.get("v", 0)] for b in r.get("bars") or []
                if (ts_iso(b["t"]) or 0) + SEG[intervalo] <= ahora][-n:]

    def abrir(self, simbolo, lado, cantidad, stop=None, objetivo=None):
        self._solo_demo("abrir operaciones")
        cuerpo = {"symbol": simbolo.upper(), "qty": str(cantidad), "side": "buy" if lado in ("compra", "alcista", "buy") else "sell",
                  "type": "market", "time_in_force": "day"}
        if stop and objetivo:
            cuerpo.update(order_class="bracket", take_profit={"limit_price": round(objetivo, 2)}, stop_loss={"stop_price": round(stop, 2)})
        o = self.http("POST", "/v2/orders", cuerpo=cuerpo, accion="abrir orden")
        if not o.get("id"):
            raise ErrorAdaptador("Alpaca no devolvió id de orden.")
        return {"id_externo": o["id"], "precio_entrada": f(o.get("filled_avg_price")), "comision": 0.0, "evidencia": {"order_id": o["id"], "status": o.get("status")}}

    def cerrar(self, id_externo):
        self._solo_demo("cerrar operaciones")
        o = self.http("DELETE", f"/v2/positions/{urllib.parse.quote(str(id_externo))}", accion="cerrar")
        return {"precio_salida": f(o.get("filled_avg_price")), "resultado": None, "orden_cierre": o.get("id")}


# ================================================================================================ Tradier
class Tradier(Conector):
    id, nombre = "tradier", "Tradier"
    ENTORNOS = {"demo": "https://sandbox.tradier.com/v1", "real": "https://api.tradier.com/v1"}
    CAMPOS = (("token", "Token de acceso"), ("cuenta", "Número de cuenta (opcional)"))

    def cabeceras(self, metodo, ruta, cuerpo):
        if not self.cred.get("token"):
            raise ErrorBroker("Tradier: falta el token.")
        return {"Authorization": "Bearer " + self.cred["token"]}

    @staticmethod
    def _lista(x):
        return [] if not x or x == "null" else (x if isinstance(x, list) else [x])

    def _cuenta_id(self):
        if not self.cred.get("cuenta"):
            prof = self.http("GET", "/user/profile").get("profile") or {}
            cs = self._lista(prof.get("account"))
            if not cs:
                raise ErrorBroker("Tradier: el token no tiene cuentas.")
            self.cred["cuenta"] = cs[0]["account_number"]
        return self.cred["cuenta"]

    def reloj(self):
        return (self.http("GET", "/markets/clock", autenticar=False).get("clock") or {})

    def probar(self):
        a = self.cuenta()
        return {"ok": True, "detalle": f"cuenta {self._cuenta_id()} · equity {a['equity']}",
                "capacidades": ["autenticacion", "cuenta", "posiciones", "ordenes", "cotizacion", "velas", "operar_demo"]}

    def cuenta(self):
        b = self.http("GET", f"/accounts/{self._cuenta_id()}/balances").get("balances") or {}
        return {"balance": f(b.get("total_cash")), "equity": f(b.get("total_equity")), "moneda": "USD", "margen_usado": None,
                "pnl_no_realizado": f(b.get("open_pl"))}

    def posiciones(self):
        ps = self._lista((self.http("GET", f"/accounts/{self._cuenta_id()}/positions").get("positions") or {}).get("position"))
        return [{"id_externo": str(p.get("id") or p["symbol"]), "simbolo": p["symbol"], "lado": "compra" if (f(p.get("quantity")) or 0) > 0 else "venta",
                 "cantidad": abs(f(p.get("quantity")) or 0), "precio_entrada": (f(p.get("cost_basis")) or 0) / max(1e-9, abs(f(p.get("quantity")) or 1)),
                 "pnl_no_realizado": None, "stop": None, "objetivo": None, "swap": 0.0, "abierta_ts": ts_iso(p.get("date_acquired"))} for p in ps]

    def ordenes(self):
        os_ = self._lista((self.http("GET", f"/accounts/{self._cuenta_id()}/orders").get("orders") or {}).get("order"))
        return [{"id_externo": str(o["id"]), "simbolo": o.get("symbol"), "lado": "compra" if "buy" in str(o.get("side")) else "venta",
                 "cantidad": f(o.get("quantity")), "tipo": o.get("type"), "precio": f(o.get("price")), "estado": o.get("status"),
                 "creada_ts": ts_iso(o.get("create_date"))} for o in os_]

    def cotizacion(self, simbolo):
        q = (self.http("GET", "/markets/quotes", {"symbols": simbolo.upper()}).get("quotes") or {}).get("quote") or {}
        bid, ask = f(q.get("bid")), f(q.get("ask"))
        if not bid or not ask:
            raise ErrorBroker("Tradier: sin cotización.")
        return {"bid": bid, "ask": ask, "precio": (bid + ask) / 2, "ts": int((q.get("trade_date") or time.time() * 1000) / 1000)}

    def abrir(self, simbolo, lado, cantidad, stop=None, objetivo=None):
        self._solo_demo("abrir operaciones")
        o = self.http("POST", f"/accounts/{self._cuenta_id()}/orders", form=True, accion="abrir orden",
                      cuerpo={"class": "equity", "symbol": simbolo.upper(), "side": "buy" if lado in ("compra", "alcista", "buy") else "sell",
                              "quantity": str(int(cantidad)), "type": "market", "duration": "day"})
        oid = (o.get("order") or {}).get("id")
        if not oid:
            raise ErrorAdaptador("Tradier no devolvió id de orden: " + str(o)[:200])
        return {"id_externo": str(oid), "precio_entrada": None, "comision": 0.0, "evidencia": o.get("order")}


# ================================================================================================ Kraken
class Kraken(Conector):
    id, nombre = "kraken", "Kraken"
    ENTORNOS = {"demo": "https://api.kraken.com", "real": "https://api.kraken.com"}
    CAMPOS = (("clave", "API Key"), ("secreto", "Private Key (base64)"))
    publico = True
    MIN_INTERVALO_S = 1.0

    def firma(self, ruta, cuerpo):
        """API-Sign = HMAC-SHA512(ruta + SHA256(nonce + POST), base64decode(secreto)) — documentación oficial de Kraken."""
        datos = cuerpo.decode() if isinstance(cuerpo, bytes) else (cuerpo or "")
        nonce = urllib.parse.parse_qs(datos).get("nonce", [""])[0]
        msg = ruta.encode() + hashlib.sha256((nonce + datos).encode()).digest()
        return base64.b64encode(hmac.new(base64.b64decode(self.cred["secreto"]), msg, hashlib.sha512).digest()).decode()

    def cabeceras(self, metodo, ruta, cuerpo):
        if not ruta.startswith("/0/private/"):
            return {}
        if not (self.cred.get("clave") and self.cred.get("secreto")):
            raise ErrorBroker("Kraken: faltan la clave y la clave privada.")
        return {"API-Key": self.cred["clave"], "API-Sign": self.firma(ruta, cuerpo)}

    def _priv(self, metodo_api, extra=None):
        r = self.http("POST", "/0/private/" + metodo_api, cuerpo={"nonce": str(int(time.time() * 1000)), **(extra or {})}, form=True)
        if r.get("error"):
            raise ErrorBroker("Kraken: " + "; ".join(r["error"]))
        return r.get("result") or {}

    @staticmethod
    def par(s):
        s = str(s).upper().replace("/", "").replace("-", "")
        return "XBT" + s[3:] if s.startswith("BTC") else s

    def probar(self):
        t = self.cotizacion("BTCUSD")
        cap = ["datos_publicos", "cotizacion", "velas"]
        det = f"datos públicos OK · BTC/USD {t['precio']:.1f}"
        if self.cred.get("clave"):
            a = self.cuenta()
            cap += ["autenticacion", "cuenta", "ordenes", "ejecuciones", "validar_orden"]
            det += f" · cuenta autenticada ({len(a.get('activos') or {})} activos con saldo)"
        return {"ok": True, "detalle": det, "capacidades": cap}

    def cuenta(self):
        r = self._priv("Balance")
        return {"balance": None, "equity": None, "moneda": "multi", "activos": {k: f(v) for k, v in r.items() if (f(v) or 0) > 0},
                "margen_usado": None, "pnl_no_realizado": None}

    def ordenes(self):
        r = self._priv("OpenOrders").get("open") or {}
        return [{"id_externo": k, "simbolo": (o.get("descr") or {}).get("pair"), "lado": "compra" if (o.get("descr") or {}).get("type") == "buy" else "venta",
                 "cantidad": f(o.get("vol")), "tipo": (o.get("descr") or {}).get("ordertype"), "precio": f((o.get("descr") or {}).get("price")),
                 "estado": o.get("status"), "creada_ts": int(f(o.get("opentm")) or 0)} for k, o in r.items()]

    def ejecuciones(self, desde_ts=None):
        r = self._priv("TradesHistory", {"start": str(int(desde_ts))} if desde_ts else None).get("trades") or {}
        return [{"id_externo": k, "orden_id": t.get("ordertxid"), "simbolo": t.get("pair"), "lado": "compra" if t.get("type") == "buy" else "venta",
                 "cantidad": f(t.get("vol")), "precio": f(t.get("price")), "comision": f(t.get("fee")) or 0.0, "swap": 0.0, "pnl": None,
                 "ts": int(f(t.get("time")) or 0)} for k, t in r.items()]

    def cotizacion(self, simbolo):
        r = self.http("GET", "/0/public/Ticker", {"pair": self.par(simbolo)}, autenticar=False)
        if r.get("error"):
            raise ErrorBroker("Kraken: " + "; ".join(r["error"]))
        t = next(iter((r.get("result") or {}).values()))
        bid, ask = f(t["b"][0]), f(t["a"][0])
        return {"bid": bid, "ask": ask, "precio": (bid + ask) / 2, "ts": int(time.time())}

    def velas(self, simbolo, intervalo="1m", n=200):
        r = self.http("GET", "/0/public/OHLC", {"pair": self.par(simbolo), "interval": TF_KRAKEN[intervalo]}, autenticar=False)
        if r.get("error"):
            raise ErrorBroker("Kraken: " + "; ".join(r["error"]))
        filas = next(v for k, v in (r.get("result") or {}).items() if k != "last")
        ahora = time.time()
        return [[int(x[0]), f(x[1]), f(x[2]), f(x[3]), f(x[4]), f(x[6])] for x in filas if int(x[0]) + SEG[intervalo] <= ahora][-n:]

    def validar_orden(self, simbolo, lado, cantidad):
        """Kraken no tiene demo de spot: AddOrder con validate=true COMPRUEBA la orden sin ejecutarla."""
        return self._priv("AddOrder", {"pair": self.par(simbolo), "type": "buy" if lado in ("compra", "buy") else "sell", "ordertype": "market",
                                       "volume": str(cantidad), "validate": "true"})

    def abrir(self, simbolo, lado, cantidad, stop=None, objetivo=None):
        raise ErrorAdaptador("Kraken no ofrece cuenta demo de spot: TITAN solo valida órdenes (validate=true), nunca las ejecuta.")


# ================================================================================================ Coinbase Advanced
class Coinbase(Conector):
    id, nombre = "coinbase", "Coinbase Advanced"
    ENTORNOS = {"demo": "https://api.coinbase.com", "real": "https://api.coinbase.com"}
    CAMPOS = (("nombre_clave", "Nombre de la clave CDP (organizations/…/apiKeys/…)"), ("clave_privada", "Clave privada EC (PEM)"))
    publico = True

    def cabeceras(self, metodo, ruta, cuerpo):
        if "/market/" in ruta:
            return {}
        if not (self.cred.get("nombre_clave") and self.cred.get("clave_privada")):
            raise ErrorBroker("Coinbase: faltan el nombre y la clave privada CDP.")
        return {"Authorization": "Bearer " + self._jwt(metodo, ruta.split("?")[0])}

    def _jwt(self, metodo, ruta):
        """JWT ES256 según la documentación de Coinbase Developer Platform (válido 2 minutos)."""
        import json
        import secrets
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

        def b64(b):
            return base64.urlsafe_b64encode(b).rstrip(b"=").decode()
        ahora = int(time.time())
        cab = {"alg": "ES256", "kid": self.cred["nombre_clave"], "nonce": secrets.token_hex(16), "typ": "JWT"}
        carga = {"sub": self.cred["nombre_clave"], "iss": "cdp", "nbf": ahora, "exp": ahora + 120, "uri": f"{metodo} api.coinbase.com{ruta}"}
        firmado = b64(json.dumps(cab, separators=(",", ":")).encode()) + "." + b64(json.dumps(carga, separators=(",", ":")).encode())
        clave = serialization.load_pem_private_key(self.cred["clave_privada"].replace("\\n", "\n").encode(), password=None)
        r, s = decode_dss_signature(clave.sign(firmado.encode(), ec.ECDSA(hashes.SHA256())))
        return firmado + "." + b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))

    @staticmethod
    def prod(s):
        s = str(s).upper().replace("/", "-")
        return s if "-" in s else s[:-3] + "-" + s[-3:]

    def probar(self):
        t = self.cotizacion("BTC-USD")
        cap = ["datos_publicos", "cotizacion", "velas"]
        det = f"datos públicos OK · BTC-USD {t['precio']:.2f}"
        if self.cred.get("nombre_clave"):
            self.cuenta()
            cap += ["autenticacion", "cuenta", "ordenes", "ejecuciones"]
            det += " · cuenta autenticada"
        return {"ok": True, "detalle": det, "capacidades": cap}

    def cuenta(self):
        cs = self.http("GET", "/api/v3/brokerage/accounts").get("accounts") or []
        return {"balance": None, "equity": None, "moneda": "multi", "margen_usado": None, "pnl_no_realizado": None,
                "activos": {c.get("currency"): f((c.get("available_balance") or {}).get("value")) for c in cs if (f((c.get("available_balance") or {}).get("value")) or 0) > 0}}

    def ordenes(self):
        return [{"id_externo": o["order_id"], "simbolo": o.get("product_id"), "lado": "compra" if o.get("side") == "BUY" else "venta",
                 "cantidad": f(o.get("filled_size")), "tipo": o.get("order_type"), "precio": f(o.get("average_filled_price")), "estado": o.get("status"),
                 "creada_ts": ts_iso(o.get("created_time"))} for o in self.http("GET", "/api/v3/brokerage/orders/historical/batch", {"order_status": "OPEN"}).get("orders") or []]

    def ejecuciones(self, desde_ts=None):
        return [{"id_externo": x["entry_id"], "orden_id": x.get("order_id"), "simbolo": x.get("product_id"), "lado": "compra" if x.get("side") == "BUY" else "venta",
                 "cantidad": f(x.get("size")), "precio": f(x.get("price")), "comision": f(x.get("commission")) or 0.0, "swap": 0.0, "pnl": None,
                 "ts": ts_iso(x.get("trade_time"))} for x in self.http("GET", "/api/v3/brokerage/orders/historical/fills").get("fills") or []]

    def cotizacion(self, simbolo):
        p = self.http("GET", f"/api/v3/brokerage/market/products/{self.prod(simbolo)}", autenticar=False)
        precio = f(p.get("price"))
        if not precio:
            raise ErrorBroker("Coinbase: sin precio.")
        b = self.http("GET", "/api/v3/brokerage/market/product_book", {"product_id": self.prod(simbolo), "limit": 1}, autenticar=False).get("pricebook") or {}
        bid = f(((b.get("bids") or [{}])[0]).get("price")) or precio
        ask = f(((b.get("asks") or [{}])[0]).get("price")) or precio
        return {"bid": bid, "ask": ask, "precio": precio, "ts": int(time.time())}

    def velas(self, simbolo, intervalo="1m", n=200):
        if intervalo not in TF_COINBASE:
            raise ErrorAdaptador(f"Coinbase no ofrece velas de {intervalo}.")
        fin = int(time.time())
        ini = fin - SEG[intervalo] * min(n, 349)
        r = self.http("GET", f"/api/v3/brokerage/market/products/{self.prod(simbolo)}/candles",
                      {"start": ini, "end": fin, "granularity": TF_COINBASE[intervalo]}, autenticar=False)
        filas = sorted([[int(c["start"]), f(c["open"]), f(c["high"]), f(c["low"]), f(c["close"]), f(c["volume"])] for c in r.get("candles") or []])
        return [x for x in filas if x[0] + SEG[intervalo] <= fin][-n:]

    def abrir(self, simbolo, lado, cantidad, stop=None, objetivo=None):
        raise ErrorAdaptador("Coinbase Advanced no tiene entorno demo: TITAN no envía órdenes a esta cuenta (solo lectura).")


CONECTORES = {c.id: c for c in (OANDA, Alpaca, Tradier, Kraken, Coinbase)}
