"""Backtest y métricas de la señal binaria. Sin red, sin credenciales, sin órdenes.

Cada señal se evalúa con datos posteriores a su confirmación, así que no hay anticipación.
Las señales cuya ventana de vencimiento no está completa en los datos se descartan y se cuentan.

Métricas (por operación, con monto unitario):
  * Tasa de aciertos sobre operaciones decididas (sin empates) con IC 95 % de Wilson.
  * Punto de equilibrio: 1 / (1 + pago), donde pago es la fracción de ganancia (p. ej. 0.80).
  * Retorno esperado por unidad: tasa * pago - (1 - tasa) * 1.
  * Drawdown máximo y racha máxima de pérdidas sobre la curva acumulada.
"""
import math

from .senal import VENCIMIENTO_VELAS, generar, resultado, segmentos_continuos


def validar_pago(pago):
    if pago is None or not isinstance(pago, (int, float)) or not (0 < pago < 10):
        raise ValueError("Se requiere el pago real del activo como fracción (p. ej. 0.80). No se usa un valor por defecto.")


def simular(velas, pago, vencimiento=VENCIMIENTO_VELAS):
    """Devuelve (operaciones, descartadas). velas: serie (ts, o, h, l, c) ya cargada y ordenada."""
    validar_pago(pago)
    operaciones, descartadas = [], 0
    for tramo in segmentos_continuos(velas):
        for s in generar(tramo):
            j = s["indice"]
            ent, fin = j + 1, j + vencimiento
            if fin > len(tramo) - 1:
                descartadas += 1
                continue
            p_ent = tramo[ent][1]
            p_fin = tramo[fin][4]
            estado, retorno = resultado(s["direccion"], p_ent, p_fin, pago)
            operaciones.append({
                "ts_senal": s["ts_senal"], "ts_entrada": tramo[ent][0],
                "vencimiento_ts": tramo[fin][0] + 60, "direccion": s["direccion"],
                "precio_entrada": p_ent, "precio_vencimiento": p_fin,
                "resultado": estado, "retorno": retorno,
            })
    return operaciones, descartadas


def wilson(aciertos, n, z=1.96):
    """Intervalo de confianza de Wilson para una proporción. Devuelve (bajo, alto) o None si n = 0."""
    if n == 0:
        return None
    p = aciertos / n
    z2 = z * z
    centro = (p + z2 / (2 * n)) / (1 + z2 / n)
    margen = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / (1 + z2 / n)
    return (max(0.0, centro - margen), min(1.0, centro + margen))


def metricas(operaciones, pago):
    validar_pago(pago)
    decididas = [o for o in operaciones if o["resultado"] in ("ganada", "perdida")]
    n = len(decididas)
    ganadas = sum(1 for o in decididas if o["resultado"] == "ganada")
    perdidas = n - ganadas
    empates = sum(1 for o in operaciones if o["resultado"] == "empate")
    tasa = ganadas / n if n else None
    equilibrio = 1.0 / (1.0 + pago)
    esperado = (ganadas * pago - perdidas) / n if n else None

    curva, pico, dd, racha, racha_max = 0.0, 0.0, 0.0, 0, 0
    for o in operaciones:
        curva += o["retorno"]
        pico = max(pico, curva)
        dd = max(dd, pico - curva)
        if o["resultado"] == "perdida":
            racha += 1
            racha_max = max(racha_max, racha)
        elif o["resultado"] == "ganada":
            racha = 0
    return {
        "operaciones": len(operaciones), "decididas": n, "ganadas": ganadas,
        "perdidas": perdidas, "empates": empates,
        "tasa_aciertos": tasa, "ic95_aciertos": wilson(ganadas, n),
        "punto_equilibrio": equilibrio, "retorno_esperado_por_unidad": esperado,
        "retorno_acumulado": curva, "drawdown_maximo": dd, "racha_perdidas_max": racha_max,
    }
