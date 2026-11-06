"""Adaptador cTrader Open API (Spotware) — API OFICIAL, OAuth 2.0, órdenes a mercado con stop y objetivo.

* DEMO → host demo.ctraderapi.com · REAL (LIVE) → host live.ctraderapi.com. El adaptador comprueba en cada sesión
  que la cuenta elegida es del tipo correcto: una cuenta real NUNCA se usa en modalidad demo ni al revés.
* Requiere un token con permiso de TRADING (OAuth con scope=trading). Con scope=accounts solo se puede leer.
* Tamaño: unidades = riesgo (en la divisa de la cuenta) / (distancia al stop × conversión de divisa),
  redondeado hacia ABAJO al paso de volumen del símbolo; si no llega al volumen mínimo, la orden se rechaza.
* Stop y objetivo se envían RELATIVOS (obligatorio en órdenes a mercado), con la misma distancia porcentual
  del escenario, redondeados a los decimales del símbolo.
* Precios, bid/ask, spread, comisiones, swap y resultado salen del propio broker.
"""
import math
import time

from .base import Adaptador, ErrorAdaptador
from .ctrader_ws import ESCALA, ErrorCTrader, SesionCTrader

_CACHE = {}          # (entorno, ctid) -> {"t": ts, "simbolos": [...], "activos": {...}}


class CTrader(Adaptador):
    id, nombre = "ctrader", "cTrader Open API"
    mercados = ("forex", "metales", "indices", "energia", "acciones_cfd", "cripto_cfd")
    tipos_orden = ("mercado",)
    modalidades = ("demo", "real")
    autenticacion = "OAuth 2.0 (Client ID/Secret + tokens con permiso de trading), desde Integraciones"
    comisiones = "Las del broker; se leen de cada ejecución y cierre"
    spreads = "Reales: bid/ask del broker en cada orden"
    limites_api = "Límites por aplicación de Spotware; sesiones cortas por operación"
    restricciones = "Requiere permiso 'trading'; demo y real usan hosts y bases de datos separados"
    compatibilidad = "Probado contra un servidor cTrader simulado; validar primero en DEMO con tu cuenta"

    def __init__(self, uid=None, modalidad="demo", cuenta_ctid=None, simbolo_broker=None, cred=None):
        if modalidad not in ("demo", "real"):
            raise ErrorAdaptador("cTrader se usa en modalidad demo o real.")
        self.uid, self.modalidad = uid, modalidad
        self.entorno = "demo" if modalidad == "demo" else "live"
        self.ctid = int(cuenta_ctid) if cuenta_ctid else None
        self.simbolo_broker = (simbolo_broker or "").upper()
        self.cred = cred if cred is not None else self._leer_cred()

    # ----------------------------------------------------------------- sesión con renovación de token
    def _leer_cred(self):
        if self.uid is None:
            return {}
        from .. import integraciones          # Client ID y Redirect URI son ajustes; secreto y tokens van cifrados en la bóveda
        return integraciones._config(self.uid, "ctrader")

    def _abrir(self, autorizar=True):
        if not self.cred.get("client_id") or not self.cred.get("client_secret") or not self.cred.get("access_token"):
            raise ErrorAdaptador("cTrader no está autorizado: completa Integraciones → cTrader → Autorizar.")
        s = SesionCTrader(self.entorno, self.cred["client_id"], self.cred["client_secret"], self.cred["access_token"])
        try:
            s.abrir()
            if autorizar:
                if not self.ctid:
                    raise ErrorAdaptador("Elige la cuenta cTrader en la configuración del bot.")
                self._comprobar_cuenta(s)
                s.autorizar_cuenta(self.ctid)
            return s
        except ErrorCTrader as e:
            s.cerrar()
            if e.es_token and self.cred.get("refresh_token") and not getattr(self, "_renovado", False):
                self._renovar()
                return self._abrir(autorizar)
            raise ErrorAdaptador(self._explicar(e)) from None
        except Exception:
            s.cerrar()
            raise

    def _renovar(self):
        self._renovado = True
        s = SesionCTrader(self.entorno, self.cred["client_id"], self.cred["client_secret"])
        try:
            s.abrir()
            nuevo = s.refrescar_token(self.cred["refresh_token"])
        except ErrorCTrader as e:
            raise ErrorAdaptador("El token de cTrader caducó y no se pudo renovar: vuelve a autorizar en Integraciones. " + e.codigo) from None
        finally:
            s.cerrar()
        self.cred.update(access_token=nuevo["access_token"], refresh_token=nuevo["refresh_token"] or self.cred.get("refresh_token"))
        if self.uid is not None:
            from ..seguridad import boveda
            boveda.guardar(self.uid, "ctrader", {"access_token": self.cred["access_token"], "refresh_token": self.cred["refresh_token"]})

    def _comprobar_cuenta(self, s):
        info = s.cuentas()
        c = next((x for x in info["cuentas"] if x["ctid"] == self.ctid), None)
        if not c:
            raise ErrorAdaptador(f"La cuenta {self.ctid} no está vinculada a este token de cTrader.")
        if c["real"] != (self.modalidad == "real"):
            raise ErrorAdaptador(f"La cuenta {self.ctid} es {'REAL' if c['real'] else 'DEMO'} y la modalidad elegida es "
                                 f"{self.modalidad.upper()}: no se mezclan cuentas.")
        permiso = str(info.get("permiso") or "")
        if permiso and "TRADE" not in permiso.upper() and permiso != "1":
            self.solo_lectura = True

    @staticmethod
    def _explicar(e):
        if e.es_token:
            return "Token de cTrader no válido o caducado: vuelve a autorizar en Integraciones → cTrader."
        if "PERMISSION" in e.codigo or "SCOPE" in e.codigo or "NOT_AUTHORIZED" in e.codigo:
            return "El token no tiene permiso de TRADING: vuelve a autorizar (TITAN pide scope=trading)."
        if "MARKET_CLOSED" in e.codigo or "SIN_COTIZACION" in e.codigo:
            return "Mercado cerrado o sin cotización en este momento."
        if "NOT_ENOUGH_MONEY" in e.codigo:
            return "Margen insuficiente en la cuenta."
        return f"cTrader: {e.codigo} {e.descripcion}".strip()

    def _catalogo(self, s):
        k = (self.entorno, self.ctid)
        c = _CACHE.get(k)
        if not c or time.time() - c["t"] > 3600:
            c = {"t": time.time(), "simbolos": s.simbolos(), "activos": s.activos()}
            _CACHE[k] = c
        return c

    def _simbolo(self, s, nombre=None):
        nombre = (nombre or self.simbolo_broker).upper()
        cat = self._catalogo(s)
        sim = next((x for x in cat["simbolos"] if (x["nombre"] or "").upper() == nombre), None)
        if not sim:
            raise ErrorAdaptador(f"El símbolo {nombre} no existe en esta cuenta cTrader.")
        return sim, cat

    # ----------------------------------------------------------------- consultas
    def cuentas(self):
        s = self._abrir(autorizar=False)
        try:
            return s.cuentas()
        finally:
            s.cerrar()

    def simbolos(self):
        s = self._abrir()
        try:
            return [x for x in self._catalogo(s)["simbolos"] if x.get("activo", True)]
        finally:
            s.cerrar()

    def conectado(self):
        try:
            s = self._abrir()
            s.cerrar()
            return True
        except Exception:
            return False

    def saldo(self):
        s = self._abrir()
        try:
            t = s.trader()
            t["moneda"] = self._catalogo(s)["activos"].get(t["depositAssetId"])
            return t
        finally:
            s.cerrar()

    def cotizacion(self, simbolo=None):
        s = self._abrir()
        try:
            sim, _ = self._simbolo(s, None)
            q = s.cotizacion(sim["id"])
            q.update(proveedor=f"ctrader-{self.entorno}", instrumento=f"{sim['nombre']} (cTrader)")
            return q
        except ErrorCTrader as e:
            raise ErrorAdaptador(self._explicar(e)) from None
        finally:
            s.cerrar()

    def serie(self, instrumento, intervalo, segundos):
        """Velas del propio broker para que el análisis use los mismos precios que la ejecución."""
        s = self._abrir()
        try:
            sim, _ = self._simbolo(s, None)
            hasta = int(time.time() * 1000)
            velas = s.velas(sim["id"], intervalo, hasta - int(segundos) * 1000, hasta, cuenta=5000)
        except ErrorCTrader as e:
            raise ErrorAdaptador(self._explicar(e)) from None
        finally:
            s.cerrar()
        if len(velas) < 60:
            raise ErrorAdaptador(f"cTrader devolvió solo {len(velas)} velas de {sim['nombre']}.")
        return {"simbolo": instrumento, "proveedor": f"ctrader-{self.entorno}", "simbolo_proveedor": sim["nombre"], "tipo": "cfd",
                "intervalo": intervalo, "rango": f"{int(segundos // 86400)}d", "t": [v[0] for v in velas], "o": [v[1] for v in velas],
                "h": [v[2] for v in velas], "l": [v[3] for v in velas], "c": [v[4] for v in velas], "v": [float(v[5]) for v in velas],
                "meta": {"precio": velas[-1][4], "bid": None, "ask": None, "zona": "UTC"}, "obtenido_ts": time.time()}

    # ----------------------------------------------------------------- órdenes
    def _conversion(self, s, sim, cat, deposito, precio):
        """Factor para pasar beneficios en la divisa COTIZADA a la divisa de la cuenta."""
        nombres = cat["activos"]
        cot, base, dep = nombres.get(sim["cotizada"]), nombres.get(sim["base"]), nombres.get(deposito)
        if not cot or not dep:
            raise ErrorAdaptador("No se conocen las divisas del símbolo o de la cuenta.")
        if cot == dep:
            return 1.0, dep
        if base == dep:
            return 1.0 / precio, dep
        for nombre, invertir in ((cot + dep, False), (dep + cot, True)):
            par = next((x for x in cat["simbolos"] if (x["nombre"] or "").upper() == nombre.upper()), None)
            if par:
                q = s.cotizacion(par["id"])
                return (1.0 / q["precio"] if invertir else q["precio"]), dep
        raise ErrorAdaptador(f"No hay par de conversión {cot}/{dep} en la cuenta: orden rechazada para no calcular mal el riesgo.")

    @staticmethod
    def _relativo(distancia, digitos):
        paso = 10 ** max(0, 5 - int(digitos))
        return max(paso, int(round(distancia * ESCALA / paso)) * paso)

    def abrir(self, sol):
        if sol.get("tipo") != "margen":
            raise ErrorAdaptador("cTrader en TITAN opera órdenes con stop y objetivo (tipo margen).")
        s = self._abrir()
        try:
            if getattr(self, "solo_lectura", False):
                raise ErrorAdaptador("El token solo tiene permiso de lectura: vuelve a autorizar con permiso de trading.")
            sim, cat = self._simbolo(s, None)
            det = s.simbolo(sim["id"])
            q = s.cotizacion(sim["id"])
            t = s.trader()
            lado = "BUY" if sol["direccion"] == "alcista" else "SELL"
            entrada = q["ask"] if lado == "BUY" else q["bid"]
            d_stop = entrada * sol["stop_dist_pct"]
            d_obj = entrada * sol["obj_dist_pct"] if sol.get("obj_dist_pct") else None
            conv, moneda = self._conversion(s, sim, cat, t["depositAssetId"], q["precio"])
            unidades = sol["riesgo_importe"] / (d_stop * conv)
            paso = max(1, det["vol_paso"] or 1)
            vol = int(math.floor(unidades * 100 / paso)) * paso
            if det.get("vol_max"):
                vol = min(vol, det["vol_max"])
            if vol < (det["vol_min"] or 1):
                raise ErrorAdaptador(f"El riesgo permitido ({sol['riesgo_importe']:.2f} {moneda}) no alcanza el volumen mínimo de "
                                     f"{sim['nombre']} ({det['vol_min'] / 100:g} unidades). Sube el riesgo o elige otro símbolo.")
            rel_s = self._relativo(d_stop, det["digitos"])
            rel_o = self._relativo(d_obj, det["digitos"]) if d_obj else None
            ref = f"TQ{int(time.time() * 1000)}"
            r = s.orden_mercado(sim["id"], lado, vol, rel_s, rel_o, "TITAN", ref, f"TITAN {self.modalidad} {sol.get('estrategia', 'fusion')}")
        except ErrorCTrader as e:
            raise ErrorAdaptador(self._explicar(e)) from None
        finally:
            s.cerrar()
        precio = float(r["precio"] or entrada)
        sg = 1 if lado == "BUY" else -1
        riesgo_ef = vol / 100 * (rel_s / ESCALA) * conv
        return {"id_externo": str(r["posicion"]), "precio_entrada": precio, "costo": -r["comision"] / 10 ** r["moneyDigits"] if r["comision"] else 0.0,
                "volumen": vol, "unidades": vol / 100, "monto": vol / 100 * precio, "riesgo_importe": riesgo_ef, "moneda": moneda,
                "stop": precio - sg * rel_s / ESCALA, "objetivo": (precio + sg * rel_o / ESCALA) if rel_o else None,
                "fuente_precio": f"ctrader-{self.entorno}:{sim['nombre']} bid {q['bid']} ask {q['ask']}", "edad_s": q["edad_s"],
                "simbolo_broker": sim["nombre"]}

    def actualizar(self, op, ahora=None):
        s = self._abrir()
        try:
            abiertas = {p["id"] for p in s.posiciones()}
            pid = int(op["id_externo"])
            if pid in abiertas:
                return None
            fin = int(time.time() * 1000) + 60000
            cierres = s.cierres(int(op["abierta_ts"]) * 1000 - 60000, fin)
        except ErrorCTrader as e:
            raise ErrorAdaptador(self._explicar(e)) from None
        finally:
            s.cerrar()
        c = cierres.get(pid)
        if not c:
            return None               # aún no aparece el deal de cierre: se reintenta en el próximo ciclo
        motivo = "cerrada en el broker"
        if op.get("stop") and c["precio_salida"] is not None:
            tol = abs(op["precio_entrada"] - op["stop"]) * 0.15
            if abs(c["precio_salida"] - op["stop"]) <= tol:
                motivo = "stop"
            elif op.get("objetivo") and abs(c["precio_salida"] - op["objetivo"]) <= tol:
                motivo = "objetivo"
        return {"precio_salida": c["precio_salida"], "resultado": c["resultado"], "motivo": motivo}

    def cerrar(self, op, motivo):
        s = self._abrir()
        try:
            pid = int(op["id_externo"])
            pos = next((p for p in s.posiciones() if p["id"] == pid), None)
            if pos:
                s.cerrar_posicion(pid, pos["volumen"])
            cierres = s.cierres(int(op["abierta_ts"]) * 1000 - 60000, int(time.time() * 1000) + 60000)
        except ErrorCTrader as e:
            raise ErrorAdaptador(self._explicar(e)) from None
        finally:
            s.cerrar()
        c = cierres.get(pid)
        if not c:
            raise ErrorAdaptador("Se pidió el cierre pero cTrader aún no confirma el resultado.")
        return {"precio_salida": c["precio_salida"], "resultado": c["resultado"], "motivo": motivo}

    def verificar(self, op):
        try:
            s = self._abrir()
        except Exception:
            return False
        try:
            return int(op["id_externo"]) in {p["id"] for p in s.posiciones()}
        except Exception:
            return False
        finally:
            s.cerrar()
