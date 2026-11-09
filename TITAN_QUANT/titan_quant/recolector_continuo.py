"""Recolector CONTINUO de velas de los dos brokers, en TODAS las temporalidades (solo lectura: nunca envía órdenes).

Dos hilos de fondo independientes, que arrancan con el servidor y no se detienen:
  cTrader   → todos los símbolos activos de la cuenta DEMO del bot (sus nombres de cTrader), temporalidades 1m 5m 15m 1h 4h 1d,
              guardadas en datos/backtest_ctrader/historico.db (proveedor 'ctrader-demo').
  IQ Option → todos los pares abiertos (estado real de IQ Option), temporalidades 1m 5m 15m 1h,
              guardadas en datos/backtest_binaria/historico.db (proveedor 'iqoption').
La descarga es incremental (desde la última vela guardada), solo de velas CERRADAS, y recorre los activos en ronda.
Con esa base siempre al día, los escáneres de los bots evalúan las estrategias en todas las temporalidades.
"""
import threading
import time
import traceback

TF_CTRADER = {"1m": 7, "5m": 30, "15m": 60, "1h": 180, "4h": 500, "1d": 2000}    # días de historia por temporalidad
TF_IQ = {"1m": 3000, "5m": 2000, "15m": 1500, "1h": 1000}                         # velas por temporalidad
PAUSA_S = 0.4                    # entre peticiones (respeta los límites de las APIs)
REINTENTO_S = 120                # si el broker no está disponible o falta configuración

ESTADO = {"ctrader": {"vivo": False, "ronda": 0, "actual": None, "descargadas": 0, "error": None, "ts": None, "activos": 0},
          "iqoption": {"vivo": False, "ronda": 0, "actual": None, "descargadas": 0, "error": None, "ts": None, "activos": 0}}
_HILOS = {}
_PARAR = threading.Event()


def _uid():
    from . import db
    fila = db.q1("SELECT id FROM usuarios ORDER BY id LIMIT 1")
    return fila["id"] if fila else None


def _bucle_ctrader():
    from .backtest_ctrader import almacen
    from .backtest_ctrader.escaner import proveedor
    from .historico import SEG
    from .trader import autotrader
    from .trader.ctrader import CTrader
    est = ESTADO["ctrader"]
    while not _PARAR.is_set():
        ses = None
        try:
            uid = _uid()
            ctid = autotrader.estado(uid, "demo")["ajustes"].get("cuenta_ctid") if uid else None
            if not ctid:
                est["error"] = "falta la cuenta cTrader DEMO en el bot cTrader"
                _PARAR.wait(REINTENTO_S)
                continue
            ad = CTrader(uid, "demo", ctid, None)
            ses = ad._abrir()
            cat = sorted((x for x in ad._catalogo(ses)["simbolos"] if x.get("activo", True) and x.get("nombre")), key=lambda x: x["nombre"])
            est.update(activos=len(cat), error=None)
            alm, prov = almacen(), proveedor("demo")
            peticiones = 0
            for sim in cat:
                for tf, dias in TF_CTRADER.items():
                    if _PARAR.is_set():
                        return
                    ahora = int(time.time())
                    fin = ahora - ahora % SEG[tf]
                    est["actual"] = f"{sim['nombre']} {tf}"
                    r = alm.descargar_incremental(ses, prov, sim["nombre"], sim["id"], tf, fin - dias * 86400, fin, lote=1000)
                    est["descargadas"] += r["guardadas"]
                    peticiones += r["peticiones"]
                    est["ts"] = int(time.time())
                    time.sleep(PAUSA_S)
                    if peticiones > 400:                 # sesiones cortas: se renueva la conexión periódicamente
                        ses.cerrar()
                        ses, peticiones = ad._abrir(), 0
            est["ronda"] += 1
        except Exception as e:
            est["error"] = f"{type(e).__name__}: {e}"[:300]
            _PARAR.wait(REINTENTO_S)
        finally:
            if ses is not None:
                try:
                    ses.cerrar()
                except Exception:
                    pass


def _bucle_iq():
    from . import integraciones
    from .backtest_binaria.escaner import pares_abiertos
    from .backtest_binaria.recolector import recopilar_iqoption
    from .trader.iqoption import IQOption
    est = ESTADO["iqoption"]
    while not _PARAR.is_set():
        try:
            uid = _uid()
            cred = integraciones._config(uid, "iqoption") if uid else {}
            if not cred.get("correo") or not cred.get("clave"):
                est["error"] = "IQ Option no está configurado"
                _PARAR.wait(REINTENTO_S)
                continue
            api = IQOption(cred)._sesion()
            pares = pares_abiertos(api)
            est.update(activos=len(pares), error=None)
            for par in pares:
                for tf, n in TF_IQ.items():
                    if _PARAR.is_set():
                        return
                    est["actual"] = f"{par} {tf}"
                    r = recopilar_iqoption(par, n, sesion=api, intervalo=tf)
                    est["descargadas"] += r.get("guardadas", 0)
                    est["ts"] = int(time.time())
                    time.sleep(PAUSA_S)
            est["ronda"] += 1
            _PARAR.wait(30)
        except Exception as e:
            est["error"] = f"{type(e).__name__}: {e}"[:300]
            _PARAR.wait(REINTENTO_S)


def _envolver(nombre, fn):
    def run():
        ESTADO[nombre]["vivo"] = True
        try:
            fn()
        except Exception:
            ESTADO[nombre]["error"] = traceback.format_exc(limit=2)[-300:]
        finally:
            ESTADO[nombre]["vivo"] = False
    return run


def iniciar():
    _PARAR.clear()
    for nombre, fn in (("ctrader", _bucle_ctrader), ("iqoption", _bucle_iq)):
        h = _HILOS.get(nombre)
        if h and h.is_alive():
            continue
        h = threading.Thread(target=_envolver(nombre, fn), name="titan-recolector-" + nombre, daemon=True)
        h.start()
        _HILOS[nombre] = h


def detener():
    _PARAR.set()


def estado():
    return {k: dict(v, vivo=bool(_HILOS.get(k) and _HILOS[k].is_alive())) for k, v in ESTADO.items()}
