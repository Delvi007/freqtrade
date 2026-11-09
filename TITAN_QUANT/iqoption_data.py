# -*- coding: utf-8 -*-
"""Conector comunitario IQ Option para TITAN QUANT. SOLO LECTURA.
No contiene ni expone funciones para enviar órdenes. Las velas no incluyen Bid/Ask/spread.
"""
from __future__ import annotations
import os, time, threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / '.iqoption.env'
_LOCK = threading.RLock()
_API = None
_STREAMS = set()
_PREV_CACHE = {}
MAX_CANDLES = 20000

# Catálogo por grupo: éxitos y fallos se guardan en caché para no reintentar en cada ciclo.
_CAT = {}      # grupo -> (ts, {nombre: {'open': bool}})
_FALLOS = {}   # grupo -> (ts, mensaje)
TTL_OK_S = 300
TTL_FALLO_S = 300
TIMEOUT_CATALOGO_S = 15
# Pares OTC (p. ej. EURGBP-OTC) no están en cfd/forex/crypto. Grupos de binarias/turbo: nombres por verificar en PRACTICE.
GRUPOS_OTC = ('turbo', 'binary')

# Símbolos internos de TITAN -> nombres candidatos de IQ Option y mercado esperado.
MAP = {
 'GC=F': (['XAUUSD','GOLD'], ['cfd']), 'SI=F': (['XAGUSD','SILVER'], ['cfd']),
 'CL=F': (['OIL','WTI','USOIL'], ['cfd']), 'NG=F': (['NATGAS','NATURALGAS'], ['cfd']),
 'ES=F': (['US500','SPX500','S&P500'], ['cfd']), 'NQ=F': (['US100','NAS100','NASDAQ'], ['cfd']),
 'EURUSD=X': (['EURUSD'], ['forex']), 'GBPUSD=X': (['GBPUSD'], ['forex']),
 'JPY=X': (['USDJPY'], ['forex']), 'DOP=X': (['USDDOP','DOPUSD'], ['forex']), 'DXY': (['USDX','DXY','USDINDEX'], ['cfd']),
 'BTC-USD': (['BTCUSD','BTCUSD-L'], ['crypto']), 'ETH-USD': (['ETHUSD','ETHUSD-L'], ['crypto']),
 'SOL-USD': (['SOLUSD','SOLUSD-L'], ['crypto']), 'XRP-USD': (['XRPUSD','XRPUSD-L'], ['crypto']),
 'QQQ': (['QQQ','NASDAQ100ETF'], ['cfd']), 'SPY': (['SPY','SP500ETF'], ['cfd']),
 'AMD': (['AMD','ADVANCEDMICRODEVICES'], ['cfd']), 'AAPL': (['AAPL','APPLE'], ['cfd']),
 'NVDA': (['NVDA','NVIDIA'], ['cfd']), 'BA': (['BA','BOEING'], ['cfd']),
 'BABA': (['BABA','ALIBABA'], ['cfd']), 'MSFT': (['MSFT','MICROSOFT'], ['cfd']),
 'GOOGL': (['GOOGL','GOOGLE','ALPHABET'], ['cfd']), 'META': (['META','FACEBOOK'], ['cfd']),
 'VST': (['VST','VISTRA'], ['cfd']), 'TSLA': (['TSLA','TESLA'], ['cfd']),
 'AMZN': (['AMZN','AMAZON'], ['cfd']),
}
INTERVALS = {'1m':60,'5m':300,'15m':900,'30m':1800,'60m':3600,'1h':3600,
             '4h':14400,'1d':86400,'1wk':604800,'1w':604800,'1mo':2592000}
RANGES = {'1d':86400,'5d':5*86400,'7d':7*86400,'1mo':30*86400,'3mo':90*86400,
          '6mo':180*86400,'1y':365*86400,'2y':730*86400,'60d':60*86400,
          '730d':730*86400,'max':3650*86400}

# TITAN v7: las credenciales pueden venir de la bóveda cifrada (trader/iqoption.py las asigna aquí en memoria).
CREDENCIALES = None


def _credentials():
    if CREDENCIALES and CREDENCIALES.get('correo') and CREDENCIALES.get('clave'):
        return CREDENCIALES['correo'], CREDENCIALES['clave']
    vals = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding='utf-8').splitlines():
            line=line.strip()
            if not line or line.startswith('#') or '=' not in line: continue
            k,v=line.split('=',1); vals[k.strip()]=v.strip().strip('"').strip("'")
    email = os.getenv('IQOPTION_EMAIL') or vals.get('IQOPTION_EMAIL')
    password = os.getenv('IQOPTION_PASSWORD') or vals.get('IQOPTION_PASSWORD')
    if not email or not password:
        raise RuntimeError('Faltan IQOPTION_EMAIL e IQOPTION_PASSWORD en .iqoption.env')
    return email,password

def _api():
    global _API
    with _LOCK:
        if _API is not None:
            try:
                if _API.check_connect(): return _API
            except Exception: pass
            _API=None
        from iqoptionapi.stable_api import IQ_Option
        email,password=_credentials()
        obj=IQ_Option(email,password)
        ok,reason=obj.connect()
        if not ok:
            raise RuntimeError('IQ Option no autorizó la conexión: '+str(reason))
        # Forzar el contexto de práctica y verificarlo; no se permite seleccionar REAL.
        obj.change_balance('PRACTICE')
        modo = obj.get_balance_mode() if hasattr(obj,'get_balance_mode') else None
        if modo != 'PRACTICE':
            raise RuntimeError('No se pudo confirmar la cuenta PRACTICE; conexión bloqueada.')
        # No inicializar el catálogo DIGITAL: puede devolver None y bloquear
        # la conexión. TITAN consulta su catálogo por categoría bajo demanda.
        _API=obj
        return _API

def _get_instruments_bounded(api, market, timeout=15):
    """Consulta WebSocket con espera limitada; evita el while infinito."""
    channel = api.api
    channel.instruments = None
    channel.get_instruments(market)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = channel.instruments
        if result is not None:
            if not isinstance(result, dict):
                raise RuntimeError("respuesta WebSocket no válida")
            return result
        time.sleep(0.1)

    raise TimeoutError(
        "IQ Option no respondió a get-instruments para " + market
        + " en " + str(timeout) + " segundos"
    )


def _abierto_ahora(item, ahora):
    schedule = item.get("schedule") or []
    if not isinstance(schedule, list):
        return False
    for period in schedule:
        if not isinstance(period, dict):
            continue
        try:
            if float(period["open"]) <= ahora <= float(period["close"]):
                return True
        except (KeyError, TypeError, ValueError):
            continue
    return False


def _catalogo_grupo(api, group):
    """Catálogo de UN grupo. Éxitos y fallos quedan en caché: un grupo caído no se reintenta en cada ciclo."""
    ahora = time.time()
    with _LOCK:
        ok = _CAT.get(group)
        if ok and ahora - ok[0] < TTL_OK_S:
            return ok[1]
        fa = _FALLOS.get(group)
        if fa and ahora - fa[0] < TTL_FALLO_S:
            raise RuntimeError(fa[1])
        try:
            response = _get_instruments_bounded(api, group, timeout=TIMEOUT_CATALOGO_S)
            instruments = response.get("instruments")
            if not isinstance(instruments, list):
                raise RuntimeError("lista de instrumentos ausente")
            assets = {}
            for item in instruments:
                if not isinstance(item, dict) or not item.get("name"):
                    continue
                assets[str(item["name"])] = {"open": _abierto_ahora(item, time.time())}
            if not assets:
                raise RuntimeError("IQ Option devolvió cero instrumentos")
        except Exception as exc:
            msg = "{}: {}".format(group, exc)
            _FALLOS[group] = (ahora, msg)
            raise RuntimeError(msg)
        _FALLOS.pop(group, None)
        _CAT[group] = (ahora, assets)
        print("[IQ OPTION] {}: {} instrumentos".format(group, len(assets)))
        return assets

def _norm(s):
    return ''.join(ch for ch in str(s).upper() if ch.isalnum())

def _activos_estaticos():
    """Tabla de activos que trae la librería (nombre -> id). No requiere red."""
    try:
        from iqoptionapi.constants import ACTIVES
        return ACTIVES
    except Exception:
        return {}

_BIN = {"ts": 0.0, "estado": None, "hilo": None, "res": None}
_L_BIN = threading.Lock()
TTL_BIN_S = 60
VIGENCIA_MAX_BIN_S = 300      # si IQ Option tarda, se usa el último estado real durante como mucho 5 min
TIMEOUT_BIN_S = 20


def estado_binarias(api, timeout=TIMEOUT_BIN_S):
    """Estado real de los activos de opciones binarias/turbo según IQ Option (get_all_init_v2):
    {nombre: {'turbo': abierto, 'binary': abierto}} con abierto = enabled y no is_suspended.
    get-instruments NO responde para los grupos turbo/binary (verificado el 09/11/2026), por eso se usa esta fuente.
    Consulta en un hilo con tiempo máximo; None si IQ Option no responde (estado desconocido: no se opera)."""
    ahora = time.time()
    if _BIN["estado"] is not None and ahora - _BIN["ts"] < TTL_BIN_S:
        return _BIN["estado"]
    with _L_BIN:
        hilo = _BIN["hilo"]
        if hilo is None or not hilo.is_alive():
            # Una sola consulta a la vez; quien llegue mientras está en curso ESPERA su resultado (antes recibía None
            # y el escáner caía a get-instruments, que no responde para binarias, y abortaba el ciclo entero).
            res = {}

            def _tarea():
                try:
                    res["v2"] = api.get_all_init_v2()
                except Exception as exc:  # noqa: BLE001
                    res["error"] = exc

            hilo = threading.Thread(target=_tarea, name="iq-init-v2", daemon=True)
            _BIN.update(hilo=hilo, res=res)
            hilo.start()
        res = _BIN["res"]
    hilo.join(timeout)
    v2 = res.get("v2")
    if hilo.is_alive() or not isinstance(v2, dict):
        return _ultimo_estado_vigente(ahora)
    estado = {}
    for opcion in ("turbo", "binary"):
        for clave, act in ((v2.get(opcion) or {}).get("actives") or {}).items():
            try:
                nombre = str(act["name"]).split(".", 1)[-1]
                abierto = bool(act.get("enabled")) and not bool(act.get("is_suspended"))
            except (KeyError, TypeError):
                continue
            estado.setdefault(nombre, {})[opcion] = abierto
            if str(clave).isdigit():
                estado[nombre]["id"] = int(clave)          # id del activo que exige buy()
    if not estado:
        return _ultimo_estado_vigente(ahora)
    _BIN.update(ts=ahora, estado=estado)
    return estado


def _ultimo_estado_vigente(ahora):
    """Último estado REAL recibido de IQ Option si no tiene más de VIGENCIA_MAX_BIN_S; si no, None (desconocido: no se opera)."""
    if _BIN["estado"] is not None and ahora - _BIN["ts"] <= VIGENCIA_MAX_BIN_S:
        return _BIN["estado"]
    return None


_L_CUENTA = threading.RLock()


class _Cuenta:
    """Selecciona la cuenta de IQ Option (PRACTICE o REAL) para UNA operación sensible y la deja en PRACTICE al salir.
    La librería guarda la cuenta activa en una variable GLOBAL del proceso (global_value.balance_id) que usan buy() y el
    historial: por eso todo lo que depende de la cuenta se hace dentro de este cerrojo y con la cuenta verificada."""
    def __init__(self, api, tipo):
        if tipo not in ("PRACTICE", "REAL"):
            raise ValueError("Cuenta de IQ Option no válida: " + str(tipo))
        self.api, self.tipo = api, tipo

    def __enter__(self):
        _L_CUENTA.acquire()
        try:
            if hasattr(self.api, "change_balance") and self.api.get_balance_mode() != self.tipo:
                self.api.change_balance(self.tipo)
            modo = self.api.get_balance_mode()
            if modo != self.tipo:
                raise RuntimeError(f"No se pudo seleccionar la cuenta {self.tipo} de IQ Option (activa: {modo}).")
        except BaseException:
            _L_CUENTA.release()
            raise
        return self.api

    def __exit__(self, *exc):
        try:
            if self.tipo != "PRACTICE" and hasattr(self.api, "change_balance"):
                self.api.change_balance("PRACTICE")
        finally:
            _L_CUENTA.release()
        return False


def cuenta(api, tipo):
    return _Cuenta(api, tipo)


def id_activo(nombre):
    """Id numérico del activo para buy(): la tabla estática de la librería o, si falta, el que publica IQ Option."""
    from iqoptionapi import constants as OP
    if nombre in OP.ACTIVES:
        return OP.ACTIVES[nombre]
    est = _BIN.get("estado") or {}
    i = (est.get(nombre) or {}).get("id")
    if i is not None:
        OP.ACTIVES[nombre] = i                         # la librería lo busca en esta tabla
    return i


def resolve(symbol):
    s=str(symbol).upper().strip()
    if s.endswith('-OTC'):
        candidates, groups = [s], list(GRUPOS_OTC)
    else:
        candidates, groups = MAP.get(s, ([s], ['forex','cfd','crypto']))
    api=_api()
    if s.endswith('-OTC'):
        # Opciones binarias: el estado abierto/suspendido sale de get_all_init_v2 (fuente fiable para turbo/binary).
        est = estado_binarias(api)
        if est is not None:
            for nombre, porop in est.items():
                if _norm(nombre) == _norm(s):
                    id_activo(nombre)                  # registra el id para velas, cotización y buy()
                    return nombre, 'turbo', bool(porop.get('turbo', porop.get('binary')))
            raise LookupError(f'{s}: IQ Option no publica este par en binarias/turbo (get_all_init_v2)')
    errores=[]
    for group in groups:
        try:
            assets=_catalogo_grupo(api, group)
        except Exception as exc:
            errores.append(str(exc))
            continue
        keys={_norm(k):k for k in assets}
        for candidate in candidates:
            key=keys.get(_norm(candidate))
            if key is not None:
                return key,group,bool((assets.get(key) or {}).get('open'))
    if errores:
        # Respaldo sin red: si el catálogo no responde, un par OTC conocido por la librería se
        # resuelve por su tabla estática. abierto=None = estado desconocido; abrir() lo bloquea.
        if s.endswith('-OTC') and s in _activos_estaticos():
            return s, 'estatico', None
        raise RuntimeError(f'{s}: no se pudo consultar el catálogo IQ Option ({" | ".join(errores)})')
    # No sustituir silenciosamente un instrumento por otro.
    raise LookupError(f'{s}: instrumento no localizado en el catálogo IQ Option para {groups}; revisar símbolo/cobertura de la cuenta')

def _interval(v):
    if isinstance(v,int): return v
    if v not in INTERVALS: raise ValueError('Temporalidad no soportada por IQ Option: '+str(v))
    return INTERVALS[v]

def _count(rango, seconds):
    dur=RANGES.get(str(rango), 30*86400)
    return max(2,min(MAX_CANDLES,int(dur//seconds)+3))

def history(symbol, rango='1mo', intervalo='60m'):
    api=_api(); active,group,is_open=resolve(symbol); seconds=_interval(intervalo)
    count=_count(rango,seconds); end=int(api.get_server_timestamp() or time.time())
    rows=[]; remaining=count
    # IQ Option limita habitualmente la consulta a lotes de 1000 velas.
    while remaining>0:
        n=min(1000,remaining)
        with _LOCK: batch=api.get_candles(active,seconds,n,end)
        if not batch: break
        clean=[]
        for x in batch:
            try:
                ts=int(x.get('from',x.get('at')))
                o=float(x['open']); h=float(x.get('max',x.get('high'))); l=float(x.get('min',x.get('low'))); c=float(x['close'])
                vol=float(x.get('volume') or 0)
                clean.append([ts,o,h,l,c,vol])
            except Exception: continue
        if not clean: break
        rows.extend(clean)
        oldest=min(x[0] for x in clean)
        if oldest>=end: break
        end=oldest-1; remaining-=len(clean)
        if len(clean)<n: break
    unique={int(x[0]):x for x in rows}
    out=[unique[k] for k in sorted(unique)]
    if not out: raise RuntimeError(f'IQ Option no devolvió velas para {symbol} ({active})')
    return out, {'symbol':active,'market':group,'open':is_open,'provider':'IQ Option',
                 'regularMarketPrice':out[-1][4], 'chartPreviousClose':out[-2][4] if len(out)>1 else None,
                 'timestamp':out[-1][0], 'bid':None,'ask':None,'spread':None,
                 'spread_available':False,'volume_available':any(x[5] for x in out)}

def bars(symbol, rango='1mo', intervalo='60m'):
    rows,meta=history(symbol,rango,intervalo)
    out=[{'t':x[0],'o':x[1],'h':x[2],'l':x[3],'c':x[4],'v':x[5]} for x in rows]
    if len(out)<2: raise RuntimeError('IQ Option devolvió muy pocas velas')
    return out

def latest_quote(symbol):
    api=_api(); active,group,is_open=resolve(symbol); stream_key=(active,60)
    with _LOCK:
        if stream_key not in _STREAMS:
            api.start_candles_stream(active,60,30); _STREAMS.add(stream_key)
    data=api.get_realtime_candles(active,60) or {}
    vals=[]
    for k,v in data.items():
        try:
            vals.append((int(v.get('from',k)),float(v['open']),float(v.get('max',v.get('high'))),
                         float(v.get('min',v.get('low'))),float(v['close']),float(v.get('volume') or 0)))
        except Exception: pass
    if vals:
        vals.sort(key=lambda x:x[0]); last=vals[-1]
    else:
        rows,_=history(symbol,'1d','1m'); last=rows[-1]
    # Cambio diario: usa cierre de vela diaria anterior cuando está disponible.
    prev=None; cached=_PREV_CACHE.get(symbol)
    if cached and time.time()-cached[0] < 600: prev=cached[1]
    else:
        try:
            daily,_=history(symbol,'5d','1d'); prev=daily[-2][4] if len(daily)>1 else None
            _PREV_CACHE[symbol]=(time.time(),prev)
        except Exception: prev=None
    return {'precio':last[4], 'previo':prev,
            'cambio_pct':((last[4]/prev)-1)*100 if prev else None,
            'vela':'alcista' if last[4]>=last[1] else 'bajista', 'hora':last[0],
            'fuente':'IQ Option','simbolo_proveedor':active,'mercado_iq':group,'abierto_iq':is_open,
            'bid':None,'ask':None,'spread':None,'spread_disponible':False,
            'volumen':last[5],'timestamp_proveedor':last[0]}
