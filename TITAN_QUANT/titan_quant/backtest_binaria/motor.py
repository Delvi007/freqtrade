"""Motor de backtesting del bot de binarias. RESULTADOS HISTÓRICOS CALCULADOS, nunca operaciones de IQ Option.

Reglas de ejecución (idénticas a las del bot en vivo; ver binaria_bot/backtest.py):
  * Señal Keltner + RCI con datos hasta la vela j CERRADA. Entrada: apertura de j+1. Vencimiento 5 velas M1:
    cierre de j+5. CALL gana si salida > entrada; PUT gana si salida < entrada; empate = devolución.
  * Una operación a la vez. Las velas con huecos cortan el tramo (no se liquida con datos inexistentes).
  * Payout: el observado en IQ Option (mediana de los registrados) o el que indique el usuario. Nunca uno por defecto.

Validación:
  1. Walk-forward con parámetros FIJOS en K tramos temporales: cada tramo es fuera de muestra.
  2. Ventaja estadística: límite inferior de Wilson (95 %) de la tasa de acierto frente al punto de equilibrio 1/(1+payout).
  3. Sobreoptimización: se optimizan los parámetros en el 70 % inicial (dentro de muestra) sobre una rejilla pequeña y se
     evalúan TODAS las combinaciones en el 30 % final. Si la mejor de dentro de muestra cae por debajo de la mediana
     fuera de muestra, o gana dentro y pierde fuera, se marca «sobreoptimización probable».
"""
import json
import statistics
import time
from itertools import product

from . import ETIQUETA, INTERVALO, almacen
from ..binaria_bot.autonomia import evidencia_suficiente
from ..binaria_bot.backtest import _operaciones_de_tramo, evaluar_walk_forward
from ..binaria_bot.datos import Vela, tramos_continuos
from ..binaria_bot.estadistica import intervalo_wilson, punto_equilibrio, valor_esperado_unitario, ventaja_significativa

PARAMS_BOT = {"periodo_keltner": 20, "multiplicador": 1.5, "periodo_rci": 9, "umbral": 70.0, "ventana": 4}
REJILLA = {"periodo_keltner": (14, 20, 30), "multiplicador": (1.5, 2.0), "periodo_rci": (9, 14), "umbral": (70.0, 80.0)}
FRACCION_DENTRO = 0.7
MIN_OPS = 30


class SinDatosBacktest(ValueError):
    pass


def _velas(activo, proveedor, desde=None, hasta=None, intervalo=INTERVALO):
    filas = almacen().leer(proveedor, activo, intervalo, desde, hasta)
    return [Vela(ts=int(f[0]), open=f[1], high=f[2], low=f[3], close=f[4]) for f in filas]


def _ops(velas, payout, params):
    ops = []
    for seg in tramos_continuos(velas):
        ops.extend(_operaciones_de_tramo(seg, payout, params))
    return ops


def tramos(velas, paso=60):
    """Tramos sin huecos para cualquier temporalidad (paso en segundos)."""
    out, actual = [], []
    for v in velas:
        if actual and v.ts - actual[-1].ts != paso:
            out.append(actual)
            actual = []
        actual.append(v)
    if actual:
        out.append(actual)
    return out


def ops_simple(velas, payout, estrategia, params=None, vencimiento=5, paso=60, tendencia_emas=None):
    """Operaciones binarias calculadas para una estrategia básica (estrategias/simples.py), por tramo continuo:
    entrada en la apertura de j+1, vencimiento al cierre de j+vencimiento, una operación a la vez."""
    from ..binaria_bot.backtest import Operacion
    from ..estrategias import simples
    ops = []
    for tramo in tramos(velas, paso):
        o, h, l, c = [v.open for v in tramo], [v.high for v in tramo], [v.low for v in tramo], [v.close for v in tramo]
        libre = 0
        for e in simples.senales(estrategia, o, h, l, c, params, tendencia_emas):
            j = e["indice"]
            if j < libre:
                continue
            if j + vencimiento >= len(tramo):
                break
            entrada, salida = o[j + 1], c[j + vencimiento]
            direccion = "CALL" if e["direccion"] == "compra" else "PUT"
            if salida == entrada:
                res, neto = "empate", 0.0
            elif (direccion == "CALL") == (salida > entrada):
                res, neto = "ganada", payout
            else:
                res, neto = "perdida", -1.0
            ops.append(Operacion(tramo[j].ts, direccion, entrada, salida, res, neto))
            libre = j + 1 + vencimiento
    return ops


def metricas(ops, payout):
    g = sum(1 for o in ops if o.resultado == "ganada")
    p = sum(1 for o in ops if o.resultado == "perdida")
    e = sum(1 for o in ops if o.resultado == "empate")
    n = g + p
    curva = pico = dd = 0.0
    racha = racha_max = 0
    for o in ops:
        curva += o.neto
        pico = max(pico, curva)
        dd = max(dd, pico - curva)
        if o.resultado == "perdida":
            racha += 1
            racha_max = max(racha_max, racha)
        elif o.resultado == "ganada":
            racha = 0
    bajo, alto = intervalo_wilson(g, n) if n else (None, None)
    return {"operaciones": len(ops), "decisivas": n, "ganadas": g, "perdidas": p, "empates": e,
            "tasa_acierto": (g / n) if n else None, "ic95_wilson": [bajo, alto] if n else None,
            "punto_equilibrio": punto_equilibrio(payout), "ev_por_unidad": valor_esperado_unitario(g / n, payout) if n else None,
            "retorno_acumulado_unidades": curva, "drawdown_max_unidades": dd, "racha_perdidas_max": racha_max,
            "ventaja_significativa": bool(n >= MIN_OPS and ventaja_significativa(g, n, payout))}


def _combos():
    claves = list(REJILLA)
    for valores in product(*(REJILLA[k] for k in claves)):
        yield {**PARAMS_BOT, **dict(zip(claves, valores))}


def sobreoptimizacion(velas, payout):
    corte = int(len(velas) * FRACCION_DENTRO)
    dentro, fuera = velas[:corte], velas[corte:]
    filas = []
    for prm in _combos():
        mi, mo = metricas(_ops(dentro, payout, prm), payout), metricas(_ops(fuera, payout, prm), payout)
        filas.append({"params": prm, "dentro": mi, "fuera": mo})
    validas = [f for f in filas if f["dentro"]["decisivas"] >= 10]
    if not validas:
        return {"evaluable": False, "motivo": "menos de 10 operaciones decisivas dentro de muestra en todas las combinaciones",
                "combinaciones": len(filas)}
    mejor = max(validas, key=lambda f: f["dentro"]["ev_por_unidad"])
    ev_fuera = sorted((f["fuera"]["ev_por_unidad"] for f in filas if f["fuera"]["ev_por_unidad"] is not None))
    mediana_fuera = statistics.median(ev_fuera) if ev_fuera else None
    ev_mejor_fuera = mejor["fuera"]["ev_por_unidad"]
    rango = (sum(1 for x in ev_fuera if ev_mejor_fuera is not None and x <= ev_mejor_fuera) / len(ev_fuera)) if ev_fuera and ev_mejor_fuera is not None else None
    motivos = []
    if ev_mejor_fuera is None:
        motivos.append("la mejor combinación no opera fuera de muestra")
    else:
        if mejor["dentro"]["ev_por_unidad"] > 0 >= ev_mejor_fuera:
            motivos.append("gana dentro de muestra y pierde fuera")
        if mediana_fuera is not None and ev_mejor_fuera < mediana_fuera:
            motivos.append("la mejor combinación dentro de muestra queda por debajo de la mediana fuera de muestra")
    actual = next(f for f in filas if f["params"] == PARAMS_BOT) if any(f["params"] == PARAMS_BOT for f in filas) else None
    return {"evaluable": True, "combinaciones": len(filas), "corte_ts": velas[corte].ts if corte < len(velas) else None,
            "mejor_dentro": {"params": mejor["params"], "ev_dentro": mejor["dentro"]["ev_por_unidad"], "ev_fuera": ev_mejor_fuera,
                             "decisivas_dentro": mejor["dentro"]["decisivas"], "decisivas_fuera": mejor["fuera"]["decisivas"]},
            "percentil_fuera_de_la_mejor": rango, "mediana_ev_fuera": mediana_fuera,
            "parametros_del_bot": {"ev_dentro": actual["dentro"]["ev_por_unidad"], "ev_fuera": actual["fuera"]["ev_por_unidad"],
                                   "decisivas_fuera": actual["fuera"]["decisivas"]} if actual else None,
            "sobreoptimizacion_probable": bool(motivos), "motivos": motivos}


def ejecutar(activo, proveedor="iqoption", payout=None, k=4, desde=None, hasta=None, params=None, guardar=True):
    """Ejecuta el backtest completo y (por defecto) guarda el informe en datos/backtest_binaria/historico.db."""
    activo = str(activo).upper()
    params = {**PARAMS_BOT, **(params or {})}
    velas = _velas(activo, proveedor, desde, hasta)
    if len(velas) < 200:
        raise SinDatosBacktest(f"Solo {len(velas)} velas M1 de {activo} ({proveedor}) en el histórico binario: recopila más datos.")
    if payout is None:
        from .recolector import payout_observado
        payout, n_obs = payout_observado(activo)
        if payout is None:
            raise SinDatosBacktest(f"No hay payout observado de {activo} en IQ Option: recopílalo o indícalo (no se usa uno por defecto).")
        fuente_payout = f"mediana de {n_obs} payout(s) observados en IQ Option"
    else:
        fuente_payout = "indicado por el usuario"
    payout = float(payout)
    if not (0 < payout < 1.5):
        raise ValueError("payout fuera de rango (fracción, p. ej. 0.86)")
    ops = _ops(velas, payout, params)
    wf = evaluar_walk_forward(velas, payout=payout, k=k, params=params, min_ops_tramo=MIN_OPS)
    ok, motivo = evidencia_suficiente(wf, min_tramos=k)
    res = {"etiqueta": ETIQUETA, "activo": activo, "proveedor_datos": proveedor, "velas": len(velas),
           "desde": velas[0].ts, "hasta": velas[-1].ts, "huecos": len(tramos_continuos(velas)) - 1,
           "payout": payout, "payout_fuente": fuente_payout, "parametros": params, "vencimiento_velas_m1": 5,
           "global": metricas(ops, payout),
           "walk_forward": [{"tramo": r.indice, "operaciones": r.n, "ganadas": r.ganadas, "perdidas": r.perdidas, "empates": r.empates,
                             "tasa_acierto": r.tasa_acierto, "ic95_wilson": [r.wilson_bajo, r.wilson_alto], "ev_por_unidad": r.ev_unitario,
                             "ventaja_significativa": r.ventaja_significativa} for r in wf],
           "evidencia_fuera_de_muestra": {"suficiente": ok, "motivo": motivo},
           "sobreoptimizacion": sobreoptimizacion(velas, payout),
           "ultimas_operaciones_calculadas": [{"ts_senal": o.ts_senal, "direccion": o.direccion, "entrada": o.entrada, "salida": o.salida,
                                               "resultado": o.resultado, "neto_unidades": o.neto} for o in ops[-20:]],
           "nota": "Resultados calculados sobre velas pasadas. El rendimiento histórico no garantiza resultados futuros."}
    if guardar:
        alm = almacen()
        with alm.tx() as c:
            cur = c.execute("""INSERT INTO informes(ts,etiqueta,activo,proveedor,desde,hasta,velas,payout,payout_fuente,parametros,resultado)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                            (int(time.time()), ETIQUETA, activo, proveedor, res["desde"], res["hasta"], len(velas), payout, fuente_payout,
                             json.dumps(params), json.dumps(res, ensure_ascii=False, default=str)))
            res["informe_id"] = cur.lastrowid
    return res


def informes(limite=20):
    filas = almacen().q("SELECT id, ts, etiqueta, activo, proveedor, desde, hasta, velas, payout, payout_fuente, resultado FROM informes ORDER BY id DESC LIMIT ?",
                        (int(limite),))
    for f in filas:
        r = json.loads(f.pop("resultado"))
        f["global"] = r.get("global")
        f["evidencia_fuera_de_muestra"] = r.get("evidencia_fuera_de_muestra")
        f["sobreoptimizacion_probable"] = (r.get("sobreoptimizacion") or {}).get("sobreoptimizacion_probable")
    return filas
