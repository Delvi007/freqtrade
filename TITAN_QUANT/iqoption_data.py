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
_OPEN = None
_OPEN_TS = 0
_STREAMS = set()
_PREV_CACHE = {}
MAX_CANDLES = 20000

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


def _open_times():
    global _OPEN, _OPEN_TS
    with _LOCK:
        if _OPEN is not None and time.time() - _OPEN_TS < 300:
            return _OPEN

        api = _api()
        data = {}
        errors = []

        # Consultar exclusivamente los mercados utilizados por TITAN.
        # No llamar get_all_open_time(): esa función consulta DIGITAL
        # y puede fallar cuando IQ Option no devuelve su catálogo.
        for group in ("cfd", "forex", "crypto"):
            try:
                response = _get_instruments_bounded(api, group, timeout=15)
                if not isinstance(response, dict):
                    raise RuntimeError("respuesta no válida")
                instruments = response.get("instruments")
                if not isinstance(instruments, list):
                    raise RuntimeError("lista de instrumentos ausente")

                assets = {}
                for item in instruments:
                    if not isinstance(item, dict) or not item.get("name"):
                        continue

                    name = str(item["name"])
                    schedule = item.get("schedule") or []
                    is_open = False

                    if isinstance(schedule, list):
                        for period in schedule:
                            if not isinstance(period, dict):
                                continue
                            try:
                                opening = float(period["open"])
                                closing = float(period["close"])
                                if opening <= time.time() <= closing:
                                    is_open = True
                                    break
                            except (KeyError, TypeError, ValueError):
                                continue

                    assets[name] = {"open": is_open}

                if not assets:
                    raise RuntimeError("IQ Option devolvió cero instrumentos")

                data[group] = assets
                print("[IQ OPTION] {}: {} instrumentos".format(group, len(assets)))

            except Exception as exc:
                errors.append("{}: {}".format(group, exc))

        if errors:
            raise RuntimeError(
                "No se pudo completar el catálogo IQ Option: " + " | ".join(errors)
            )

        _OPEN = data
        _OPEN_TS = time.time()
        return data

def _norm(s):
    return ''.join(ch for ch in str(s).upper() if ch.isalnum())

def resolve(symbol):
    s=str(symbol).upper().strip()
    candidates, groups = MAP.get(s, ([s], ['forex','cfd','crypto']))
    data=_open_times()
    for group in groups:
        assets=data.get(group) or {}
        keys={_norm(k):k for k in assets}
        for candidate in candidates:
            key=keys.get(_norm(candidate))
            if key is not None:
                return key,group,bool((assets.get(key) or {}).get('open'))
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
