"""Laboratorio de backtesting walk-forward para binarias M1, sin información futura.

Reglas de ejecución (por señal en la vela j, cerrada):
  * La señal usa solo velas <= j (verificado por prueba de causalidad).
  * Entrada: precio de APERTURA de la vela j+1 (la primera disponible tras la señal).
  * Vencimiento: 5 minutos después de la entrada = CIERRE de la vela j+5.
  * Solo se toma una operación a la vez: no se abre otra hasta que venza la anterior.
  * CALL gana si salida > entrada; PUT gana si salida < entrada; empate = devolución (0).

Walk-forward: la serie se parte en K tramos temporales consecutivos. Los parámetros son FIJOS
(no se optimizan dentro del laboratorio), así que cada tramo es una evaluación fuera de muestra
independiente. Este módulo NO busca parámetros óptimos: hacerlo sin separar entrenamiento y
validación produce sobreajuste.
"""
from dataclasses import dataclass, field
from typing import List

from titan_quant.estrategias.keltner_rci import senales
from titan_quant.binaria_bot.datos import Vela, tramos_continuos
from titan_quant.binaria_bot.estadistica import (
    punto_equilibrio, intervalo_wilson, ventaja_significativa, valor_esperado_unitario,
)

VENCIMIENTO_VELAS = 5


@dataclass
class Operacion:
    ts_senal: int
    direccion: str        # CALL | PUT
    entrada: float
    salida: float
    resultado: str        # ganada | perdida | empate
    neto: float           # en unidades de monto


@dataclass
class ResumenTramo:
    indice: int
    n: int
    ganadas: int
    perdidas: int
    empates: int
    tasa_acierto: float   # ganadas / (ganadas + perdidas); None si no hay operaciones decisivas
    wilson_bajo: float
    wilson_alto: float
    equilibrio: float
    ev_unitario: float
    ventaja_significativa: bool
    operaciones: List[Operacion] = field(default_factory=list, repr=False)


def _operaciones_de_tramo(tramo, payout, params):
    high = [v.high for v in tramo]
    low = [v.low for v in tramo]
    close = [v.close for v in tramo]
    open_ = [v.open for v in tramo]
    eventos = senales(high, low, close, **params)
    ops = []
    libre_desde = 0
    for e in eventos:
        j = e["indice"]
        if j < libre_desde:
            continue                        # hay operación abierta: no se solapa
        if j + 1 + VENCIMIENTO_VELAS - 1 >= len(tramo):
            break                           # no hay datos para liquidar: se descarta
        entrada = open_[j + 1]
        salida = close[j + VENCIMIENTO_VELAS]
        direccion = "CALL" if e["direccion"] == "compra" else "PUT"
        if salida == entrada:
            res, neto = "empate", 0.0
        elif (direccion == "CALL") == (salida > entrada):
            res, neto = "ganada", payout
        else:
            res, neto = "perdida", -1.0
        ops.append(Operacion(tramo[j].ts, direccion, entrada, salida, res, neto))
        libre_desde = j + 1 + VENCIMIENTO_VELAS
    return ops


def evaluar_walk_forward(velas_m1: List[Vela], payout=0.86, k=4, params=None, min_ops_tramo=30):
    """Evalúa la estrategia en K tramos temporales consecutivos con parámetros fijos.

    Devuelve lista de ResumenTramo. Un tramo con menos de min_ops_tramo operaciones decisivas
    no declara ventaja (la muestra es insuficiente).
    """
    if k < 1:
        raise ValueError("k debe ser >= 1")
    if not (0 < payout < 5):
        raise ValueError("payout fuera de rango razonable")
    params = params or {}
    tramos = tramos_continuos(velas_m1)
    # Concatenamos tramos en orden temporal y los cortamos en K bloques por número de velas.
    # Cada bloque mantiene su continuidad: los cortes respetan los huecos originales.
    todas = [v for t in tramos for v in t]
    if not todas:
        return []
    tamano = max(1, len(todas) // k)
    resumenes = []
    for i in range(k):
        bloque = todas[i * tamano:(i + 1) * tamano] if i < k - 1 else todas[i * tamano:]
        ops = []
        for seg in tramos_continuos(bloque):
            ops.extend(_operaciones_de_tramo(seg, payout, params))
        g = sum(1 for o in ops if o.resultado == "ganada")
        p = sum(1 for o in ops if o.resultado == "perdida")
        e = sum(1 for o in ops if o.resultado == "empate")
        decisivas = g + p
        eq = punto_equilibrio(payout)
        ev = valor_esperado_unitario(g / decisivas, payout) if decisivas else 0.0
        bajo, alto = intervalo_wilson(g, decisivas) if decisivas else (0.0, 1.0)
        signif = decisivas >= min_ops_tramo and ventaja_significativa(g, decisivas, payout)
        resumenes.append(ResumenTramo(
            indice=i, n=len(ops), ganadas=g, perdidas=p, empates=e,
            tasa_acierto=(g / decisivas) if decisivas else None,
            wilson_bajo=bajo, wilson_alto=alto, equilibrio=eq, ev_unitario=ev,
            ventaja_significativa=signif, operaciones=ops,
        ))
    return resumenes
