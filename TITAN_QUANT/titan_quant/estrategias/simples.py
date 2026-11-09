"""Estrategias BÁSICAS y configurables, comunes a los dos bots (cTrader e IQ Option).

Cada estrategia es una función pura: recibe listas OHLC (velas CERRADAS, en orden) y sus parámetros, y devuelve eventos
{"indice": j, "direccion": "compra"|"venta"} calculados SOLO con datos hasta la vela j (sin mirar al futuro).
No ejecutan órdenes. La ejecución (y el backtest) decide la entrada en la apertura de j+1.

Exigencia básica a propósito: reglas clásicas y conocidas, con pocos parámetros y valores habituales.
"""
from ..indicadores.keltner import keltner
from ..indicadores.rci import rci
from ..indicadores.suavizado import ema, rma, sma


def _rsi(close, n):
    out = [None] * len(close)
    if len(close) <= n:
        return out
    sub = [max(0.0, b - a) for a, b in zip(close, close[1:])]
    baj = [max(0.0, a - b) for a, b in zip(close, close[1:])]
    mg, mp = rma(sub, n), rma(baj, n)
    for i in range(1, len(close)):
        g, p = mg[i - 1], mp[i - 1]
        if g is None or p is None:
            continue
        out[i] = 100.0 if p == 0 else 100.0 - 100.0 / (1.0 + g / p)
    return out


def cruce_ema(o, h, l, c, rapida=9, lenta=21):
    """COMPRA cuando la EMA rápida cruza por encima de la lenta; VENTA al revés."""
    if rapida >= lenta:
        raise ValueError("La EMA rápida debe ser menor que la lenta")
    er, el = ema(c, int(rapida)), ema(c, int(lenta))
    out = []
    for j in range(1, len(c)):
        if None in (er[j], el[j], er[j - 1], el[j - 1]):
            continue
        if er[j - 1] <= el[j - 1] and er[j] > el[j]:
            out.append({"indice": j, "direccion": "compra"})
        elif er[j - 1] >= el[j - 1] and er[j] < el[j]:
            out.append({"indice": j, "direccion": "venta"})
    return out


def rsi_reversion(o, h, l, c, periodo=14, sobreventa=30.0, sobrecompra=70.0):
    """COMPRA cuando el RSI sale de sobreventa (cruza hacia arriba el nivel); VENTA cuando sale de sobrecompra."""
    r = _rsi(c, int(periodo))
    out = []
    for j in range(1, len(c)):
        if r[j] is None or r[j - 1] is None:
            continue
        if r[j - 1] < sobreventa <= r[j]:
            out.append({"indice": j, "direccion": "compra"})
        elif r[j - 1] > sobrecompra >= r[j]:
            out.append({"indice": j, "direccion": "venta"})
    return out


def bollinger_reversion(o, h, l, c, periodo=20, desviaciones=2.0):
    """COMPRA cuando el cierre vuelve dentro de la banda inferior; VENTA cuando vuelve dentro de la superior."""
    n = int(periodo)
    out, media = [], sma(c, n)
    bandas = [None] * len(c)
    for j in range(n - 1, len(c)):
        v = c[j - n + 1:j + 1]
        m = media[j]
        d = (sum((x - m) ** 2 for x in v) / n) ** 0.5
        bandas[j] = (m - desviaciones * d, m + desviaciones * d)
    for j in range(1, len(c)):
        if bandas[j] is None or bandas[j - 1] is None:
            continue
        (bi_p, bs_p), (bi, bs) = bandas[j - 1], bandas[j]
        if c[j - 1] < bi_p and c[j] >= bi:
            out.append({"indice": j, "direccion": "compra"})
        elif c[j - 1] > bs_p and c[j] <= bs:
            out.append({"indice": j, "direccion": "venta"})
    return out


def ruptura_donchian(o, h, l, c, periodo=20):
    """COMPRA cuando el cierre supera el máximo de las `periodo` velas anteriores; VENTA cuando perfora el mínimo."""
    n = int(periodo)
    out = []
    for j in range(n + 1, len(c)):
        maximo, minimo = max(h[j - n:j]), min(l[j - n:j])
        if c[j] > maximo and c[j - 1] <= max(h[j - n - 1:j - 1]):          # primera vela que rompe
            out.append({"indice": j, "direccion": "compra"})
        elif c[j] < minimo and c[j - 1] >= min(l[j - n - 1:j - 1]):
            out.append({"indice": j, "direccion": "venta"})
    return out


def keltner_rci(o, h, l, c, periodo_keltner=20, multiplicador=1.5, periodo_rci=9, umbral=70.0, ventana=4):
    from .keltner_rci import senales
    return [{"indice": e["indice"], "direccion": e["direccion"]}
            for e in senales(h, l, c, int(periodo_keltner), float(multiplicador), int(periodo_rci), float(umbral), int(ventana))]


# id → (nombre, función, parámetros por defecto, rangos permitidos)
CATALOGO = {
    "cruce_ema": ("Cruce de medias EMA", cruce_ema, {"rapida": 9, "lenta": 21}, {"rapida": (2, 100), "lenta": (3, 300)}),
    "rsi_reversion": ("RSI: salida de sobreventa / sobrecompra", rsi_reversion,
                      {"periodo": 14, "sobreventa": 30.0, "sobrecompra": 70.0}, {"periodo": (2, 100), "sobreventa": (5, 50), "sobrecompra": (50, 95)}),
    "bollinger_reversion": ("Bollinger: regreso a la banda", bollinger_reversion, {"periodo": 20, "desviaciones": 2.0},
                            {"periodo": (5, 200), "desviaciones": (0.5, 4.0)}),
    "ruptura_donchian": ("Ruptura de canal Donchian", ruptura_donchian, {"periodo": 20}, {"periodo": (5, 200)}),
    "keltner_rci": ("Keltner + RCI", keltner_rci, {"periodo_keltner": 20, "multiplicador": 1.5, "periodo_rci": 9, "umbral": 70.0, "ventana": 4},
                    {"periodo_keltner": (5, 100), "multiplicador": (0.5, 4.0), "periodo_rci": (3, 50), "umbral": (30, 95), "ventana": (1, 20)}),
}


def tendencia(c, rapida=50, lenta=200):
    """Tendencia por vela, calculada SOLO con datos hasta esa vela:
    +1 alcista  = EMA rápida > EMA lenta y cierre > EMA lenta
    -1 bajista  = EMA rápida < EMA lenta y cierre < EMA lenta
     0 sin tendencia clara (o EMAs aún sin calentar): no se opera."""
    er, el = ema(c, int(rapida)), ema(c, int(lenta))
    out = []
    for x, a, b in zip(c, er, el):
        if a is None or b is None:
            out.append(0)
        elif a > b and x > b:
            out.append(1)
        elif a < b and x < b:
            out.append(-1)
        else:
            out.append(0)
    return out


def a_favor_de_tendencia(eventos, c, rapida=50, lenta=200):
    """Conserva solo las señales a favor de la tendencia: compra con tendencia alcista y venta con tendencia bajista."""
    t = tendencia(c, rapida, lenta)
    return [e for e in eventos if t[e["indice"]] == (1 if e["direccion"] == "compra" else -1)]


def validar_parametros(estrategia, params):
    """Devuelve los parámetros completos y validados (por defecto + los indicados dentro de rango)."""
    if estrategia not in CATALOGO:
        raise ValueError("Estrategia desconocida: " + str(estrategia))
    _, _, defecto, rangos = CATALOGO[estrategia]
    out = dict(defecto)
    for k, v in (params or {}).items():
        if k not in defecto:
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"{estrategia}.{k}: debe ser numérico")
        lo, hi = rangos[k]
        if not lo <= v <= hi:
            raise ValueError(f"{estrategia}.{k}: fuera de rango [{lo}, {hi}]")
        out[k] = int(v) if isinstance(defecto[k], int) else v
    if estrategia == "cruce_ema" and out["rapida"] >= out["lenta"]:
        raise ValueError("cruce_ema: la EMA rápida debe ser menor que la lenta")
    if estrategia == "rsi_reversion" and out["sobreventa"] >= out["sobrecompra"]:
        raise ValueError("rsi_reversion: sobreventa debe ser menor que sobrecompra")
    return out


def senales(estrategia, o, h, l, c, params=None, tendencia_emas=None):
    """Señales de la estrategia. Con `tendencia_emas=(rápida, lenta)` solo devuelve las que van a favor de la tendencia."""
    fn = CATALOGO[estrategia][1]
    ev = fn(o, h, l, c, **validar_parametros(estrategia, params))
    if tendencia_emas:
        ev = a_favor_de_tendencia(ev, c, *tendencia_emas)
    return ev


def catalogo_publico():
    return {k: {"nombre": v[0], "parametros": v[2], "rangos": v[3]} for k, v in CATALOGO.items()}
