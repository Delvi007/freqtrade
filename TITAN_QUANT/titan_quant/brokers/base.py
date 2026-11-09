"""Interfaz común de los conectores de broker y cliente HTTP con tiempo máximo, límite de frecuencia y registro de actividad.

Todas las respuestas se NORMALIZAN al mismo formato para que TITAN trate igual a cualquier broker:
    cuenta()       {'balance', 'equity', 'moneda', 'margen_usado', 'pnl_no_realizado'}
    posiciones()   [{'id_externo','simbolo','lado','cantidad','precio_entrada','pnl_no_realizado','stop','objetivo','swap','abierta_ts'}]
    ordenes()      [{'id_externo','simbolo','lado','cantidad','tipo','precio','estado','creada_ts'}]
    ejecuciones()  [{'id_externo','orden_id','simbolo','lado','cantidad','precio','comision','swap','pnl','ts'}]
    cotizacion(s)  {'bid','ask','precio','ts'}
    velas(s,tf,n)  [[ts, o, h, l, c, v], …]   (solo velas cerradas)

Regla de seguridad: en el entorno REAL los conectores solo LEEN. Abrir, cerrar o modificar en REAL lanza ErrorAdaptador:
la operativa con dinero real de estos brokers no está habilitada en TITAN.
"""
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from ..trader.base import ErrorAdaptador

TIMEOUT = 30
INTERVALOS = ("1m", "5m", "15m", "30m", "1h", "4h", "1d")


class ErrorBroker(ErrorAdaptador):
    def __init__(self, msg, http=None):
        super().__init__(msg)
        self.http = http


def _ctx():
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


class Conector:
    id = "base"
    nombre = "Broker"
    ENTORNOS = {}                  # {'demo': url, 'real': url}
    MIN_INTERVALO_S = 0.25         # separación mínima entre peticiones (respeta los límites de la API)
    publico = False                # True = tiene datos de mercado públicos sin credenciales

    def __init__(self, cred=None, entorno="demo", abrir_url=None, registrar=None):
        if entorno not in self.ENTORNOS:
            raise ValueError(f"{self.nombre}: entorno no disponible ({entorno}).")
        self.cred = dict(cred or {})
        self.entorno = entorno
        self.base = self.ENTORNOS[entorno]
        self._abrir_url = abrir_url            # inyectable en pruebas
        self._registrar = registrar            # callback(accion, ok, detalle, ms)
        self._ultimo = 0.0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ HTTP
    def cabeceras(self, metodo, ruta, cuerpo):
        return {}

    def http(self, metodo, ruta, params=None, cuerpo=None, base=None, form=False, autenticar=True, accion=None):
        with self._lock:
            espera = self._ultimo + self.MIN_INTERVALO_S - time.time()
            if espera > 0:
                time.sleep(espera)
            self._ultimo = time.time()
        url = (base or self.base) + ruta
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        datos = None
        cab = {"Accept": "application/json", "User-Agent": "TITAN-QUANT/7.2"}
        if cuerpo is not None:
            if form:
                datos = urllib.parse.urlencode(cuerpo).encode()
                cab["Content-Type"] = "application/x-www-form-urlencoded"
            else:
                datos = json.dumps(cuerpo).encode()
                cab["Content-Type"] = "application/json"
        if autenticar:
            cab.update(self.cabeceras(metodo, ruta, datos))
        req = urllib.request.Request(url, data=datos, method=metodo, headers=cab)
        t0 = time.time()
        etiqueta = accion or f"{metodo} {ruta.split('?')[0]}"
        try:
            r = (self._abrir_url or (lambda rq: urllib.request.urlopen(rq, timeout=TIMEOUT, context=_ctx())))(req)
            txt = r.read().decode("utf-8", "replace")
            ms = int((time.time() - t0) * 1000)
            self._log(etiqueta, True, f"HTTP {getattr(r, 'status', 200)}", ms)
            return json.loads(txt) if txt.strip() else {}
        except urllib.error.HTTPError as e:
            ms = int((time.time() - t0) * 1000)
            try:
                det = e.read().decode("utf-8", "replace")[:300]
            except Exception:
                det = ""
            self._log(etiqueta, False, f"HTTP {e.code}", ms)
            raise ErrorBroker(f"{self.nombre} respondió HTTP {e.code}: {self._limpio(det)}", e.code)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            ms = int((time.time() - t0) * 1000)
            self._log(etiqueta, False, type(e).__name__, ms)
            raise ErrorBroker(f"{self.nombre} no responde ({type(e).__name__}).")

    def _limpio(self, txt):
        """Nunca devolver credenciales en mensajes de error."""
        for v in self.cred.values():
            if isinstance(v, str) and len(v) >= 6:
                txt = txt.replace(v, "•••")
        return txt

    def _log(self, accion, ok, detalle, ms):
        if self._registrar:
            try:
                self._registrar(accion, ok, detalle, ms)
            except Exception:
                pass

    # ------------------------------------------------------------------ seguridad
    def _solo_demo(self, que):
        if self.entorno != "demo":
            raise ErrorAdaptador(f"{self.nombre}: {que} en la cuenta REAL no está habilitado en TITAN (solo lectura).")

    # ------------------------------------------------------------------ interfaz (cada conector implementa lo que su API permite)
    def probar(self):
        """Diagnóstico: autenticación + lectura. Devuelve {'ok', 'detalle', 'capacidades'}."""
        raise NotImplementedError

    def cuenta(self):
        raise ErrorAdaptador(f"{self.nombre}: lectura de cuenta no disponible.")

    def posiciones(self):
        return []

    def ordenes(self):
        return []

    def ejecuciones(self, desde_ts=None):
        return []

    def cotizacion(self, simbolo):
        raise ErrorAdaptador(f"{self.nombre}: cotización no disponible.")

    def velas(self, simbolo, intervalo="1m", n=200):
        raise ErrorAdaptador(f"{self.nombre}: velas no disponibles.")

    def abrir(self, simbolo, lado, cantidad, stop=None, objetivo=None):
        raise ErrorAdaptador(f"{self.nombre}: envío de órdenes no implementado.")

    def cerrar(self, id_externo):
        raise ErrorAdaptador(f"{self.nombre}: cierre no implementado.")

    def modificar_sltp(self, id_externo, stop=None, objetivo=None):
        raise ErrorAdaptador(f"{self.nombre}: modificación de SL/TP no implementada.")


def ts_iso(t):
    """ISO-8601 / RFC3339 (con fracciones y Z) → epoch segundos."""
    if t is None:
        return None
    if isinstance(t, (int, float)):
        return int(t)
    from datetime import datetime
    s = str(t).replace("Z", "+00:00")
    if "." in s:
        cab, resto = s.split(".", 1)
        zona = ""
        for sep in ("+", "-"):
            if sep in resto:
                frac, z = resto.split(sep, 1)
                zona = sep + z
                break
        else:
            frac = resto
        s = cab + "." + frac[:6] + zona
    try:
        return int(datetime.fromisoformat(s).timestamp())
    except ValueError:
        try:
            return int(float(t))
        except (TypeError, ValueError):
            return None


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None
