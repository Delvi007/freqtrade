"""Carga de velas y agregación a M1 sin información futura.

Formato de entrada (sonda_iqoption/crudas/*.json):
  {"meta": {...}, "velas": [{"from": seg, "open", "close", "min", "max", "volume", ...}, ...]}
La marca de tiempo de inicio de cada vela es 'from' (segundos Unix).

Agregación M1: una vela M1 solo se considera CERRADA cuando existen sus 60 segundos.
Las velas parciales se descartan para no usar información incompleta.
"""
import json
from dataclasses import dataclass
from typing import List

SEGUNDOS_M1 = 60


@dataclass(frozen=True)
class Vela:
    ts: int          # inicio del minuto (Unix, segundos)
    open: float
    high: float
    low: float
    close: float


def cargar_crudas(ruta):
    """Lee el JSON de la sonda. No modifica el archivo."""
    with open(ruta, "r", encoding="utf-8") as f:
        data = json.load(f)
    velas = data.get("velas")
    if not isinstance(velas, list):
        raise ValueError("formato inesperado: falta la lista 'velas'")
    return velas


def agregar_m1(velas_5s, segundos_esperados=SEGUNDOS_M1):
    """Agrupa velas de n segundos en M1. Descarta minutos incompletos.

    Entrada: lista de dicts con 'from', 'open', 'max', 'min', 'close'.
    Salida: lista de Vela ordenadas por ts, sin duplicados.
    """
    grupos = {}
    for v in velas_5s:
        t = int(v["from"])
        m = t - (t % SEGUNDOS_M1)
        grupos.setdefault(m, []).append((t, v))
    salida: List[Vela] = []
    for m in sorted(grupos):
        filas = sorted(grupos[m], key=lambda x: x[0])
        # Cobertura exigida: el primer dato está en los 5 s iniciales del minuto y el último
        # en sus 5 s finales. Sin esto, un minuto incompleto produciría una vela sesgada.
        primera, ultima = filas[0][0], filas[-1][0]
        tolerancia = 5
        if primera - m > tolerancia or ultima < m + segundos_esperados - tolerancia:
            continue
        pasos = [filas[i + 1][0] - filas[i][0] for i in range(len(filas) - 1)]
        if pasos and max(pasos) > 10:
            continue
        salida.append(Vela(
            ts=m,
            open=float(filas[0][1]["open"]),
            high=max(float(v["max"]) for _, v in filas),
            low=min(float(v["min"]) for _, v in filas),
            close=float(filas[-1][1]["close"]),
        ))
    return salida


def tramos_continuos(velas_m1):
    """Parte la serie en tramos sin huecos de un minuto. Un hueco corta el tramo."""
    tramos, actual = [], []
    for v in velas_m1:
        if actual and v.ts - actual[-1].ts != SEGUNDOS_M1:
            tramos.append(actual)
            actual = []
        actual.append(v)
    if actual:
        tramos.append(actual)
    return tramos
