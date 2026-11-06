# -*- coding: utf-8 -*-
"""Vigilancia continua de TITAN QUANT: crea escenarios, evalúa su estado y envía alertas sin duplicados.
Las alertas son informativas: TITAN no ejecuta órdenes."""
from __future__ import annotations
from datetime import datetime, timezone

import activos as act
import agente
import escenarios as E
import macro

PARADA_MIN = 20
MAX_ACTIVOS = 8
N = agente._num

def _ya(c, clave):
    return E.kv_get(c, "al|" + clave) is not None

def _marca(c, clave):
    E.kv_set(c, "al|" + clave, "1")

def _latido(c, enviar, ahora, zona):
    prev = E.kv_get(c, "latido")
    if prev:
        ant = datetime.fromisoformat(prev)
        mins = (ahora - ant).total_seconds() / 60
        if mins > PARADA_MIN:
            enviar("TITAN QUANT — MONITOR REANUDADO\n\n"
                   f"El monitor estuvo detenido o sin conexión de {ant.astimezone(zona):%d/%m %H:%M} a {ahora.astimezone(zona):%d/%m %H:%M} ({mins / 60:.1f} h).\n"
                   "Los escenarios se recalcularon con las velas disponibles, pero ese periodo no se vigiló en tiempo real: pudo haber cambios de estado sin aviso.")
    E.kv_set(c, "latido", ahora.isoformat())

def _linea_macro(a, eventos):
    for x in eventos:
        if x["alto"] and x["edad_h"] <= 12 and a["clase"] in x["afecta"]:
            return f"{x['nombre']}: {x['titulo'][:90]}"
    return ""

def _activo(c, a, enviar, zona, ahora, cap, pct, ultimas, stats, eventos):
    sim = a["simbolo"]
    try:
        b = agente.barras(sim, "1mo", "60m")
    except Exception as ex:
        n = int(E.kv_get(c, "err|" + sim, "0")) + 1
        E.kv_set(c, "err|" + sim, n)
        if n >= 3 and E.kv_get(c, "erraviso|" + sim) != "1":
            E.kv_set(c, "erraviso|" + sim, "1")
            enviar(f"TITAN QUANT — ERROR DE DATOS\n\nNo se pudieron obtener datos de {a['nombre']} ({sim}) en {n} intentos seguidos ({type(ex).__name__}).\n"
                   "Los escenarios de este activo NO se están evaluando hasta que vuelvan los datos.")
        return
    E.kv_set(c, "err|" + sim, 0)
    if E.kv_get(c, "erraviso|" + sim) == "1":
        E.kv_set(c, "erraviso|" + sim, "0")
        enviar(f"TITAN QUANT — DATOS RECUPERADOS\n\nVolvieron los datos de {a['nombre']} ({sim}). Se reanuda la vigilancia.")
    edad_h = (ahora.timestamp() - b[-1]["t"]) / 3600
    obsoleta = edad_h > (2 if a["clase"] == "cripto" else 5) and (a["clase"] == "cripto" or ahora.weekday() < 5)
    if obsoleta:
        if E.kv_get(c, "obs|" + sim) != "1":
            E.kv_set(c, "obs|" + sim, "1")
            enviar(f"TITAN QUANT — DATOS OBSOLETOS\n\n{a['nombre']} ({sim}): la última vela tiene {edad_h:.1f} h de antigüedad (puede ser que el mercado esté cerrado).\n"
                   "No se evalúan condiciones con datos atrasados.")
        return
    E.kv_set(c, "obs|" + sim, "0")
    ultimas[sim] = b
    if not E.activos(c, sim):
        try:
            E.guardar(c, E.generar(a, b, ahora, cap, pct))
        except Exception:
            return
    macro_l = _linea_macro(a, eventos)
    for esc in E.activos(c, sim):
        res = E.evaluar(esc, b, ahora, a, cap, pct)
        for ev in E.aplicar(c, esc, res, ahora):
            if ev["estado"] == "expirado" and esc["estado"] != "confirmado":
                continue
            fila = c.execute("SELECT * FROM escenarios WHERE id=?", (esc["id"],)).fetchone()
            enviar(E.alerta(a, fila, ev["estado"], ev["motivo"], ev["precio"], res["plan"], ahora, zona, res["ultimo_t"], stats, macro_l))
    cer = E.cerradas(b, ahora)
    if len(cer) < 60:
        return
    rg = [x["h"] - x["l"] for x in cer]
    ratio = (sum(rg[-3:]) / 3) / (sum(rg[-17:-3]) / 14) if sum(rg[-17:-3]) else 1.0
    if ratio >= 2.0 and not _ya(c, f"vol|{sim}|{cer[-1]['t']}"):
        _marca(c, f"vol|{sim}|{cer[-1]['t']}")
        enviar(f"TITAN QUANT — AUMENTO EXCEPCIONAL DE VOLATILIDAD\n\n{a['nombre']} ({sim}): las últimas 3 velas se mueven {ratio:.1f} veces más que lo habitual.\n"
               "Precio observado: " + N(b[-1]["c"]) + "\nRevisa los escenarios activos: los stops pueden necesitar más margen y el deslizamiento será mayor.")
    cl = [x["c"] for x in cer]
    e20, e50 = agente.ema(cl, 20), agente.ema(cl, 50)
    ahora_s, antes_s = agente.sgn(e20[-1] - e50[-1]), agente.sgn(e20[-4] - e50[-4])
    if ahora_s and antes_s and ahora_s != antes_s and not _ya(c, f"tend|{sim}|{cer[-1]['t']}"):
        _marca(c, f"tend|{sim}|{cer[-1]['t']}")
        enviar(f"TITAN QUANT — CAMBIO RELEVANTE DE TENDENCIA\n\n{a['nombre']} ({sim}): la media de 20 velas cruzó {'sobre' if ahora_s > 0 else 'bajo'} la de 50 (velas de 1 h).\n"
               f"Precio observado: {N(b[-1]['c'])}\nEs una señal de tendencia, no una confirmación de operación: espera los escenarios.")

def _macro(c, e, enviar, zona, ahora, ultimas, eventos):
    avisados = 0
    for x in eventos:
        if not x["alto"] or x["edad_h"] > 3 or avisados >= 3:
            continue
        afect = []
        for s, b in ultimas.items():
            a = act.buscar(s, e["personalizados"])
            if a and a["clase"] in x["afecta"] and len(b) > 1:
                afect.append((a["nombre"], (b[-1]["c"] / b[-2]["c"] - 1) * 100))
        k = "mac|" + macro.clave(x)
        if afect and not _ya(c, k):
            _marca(c, k)
            avisados += 1
            enviar(macro.texto_alerta(x, afect, zona))

def _tasas(c, enviar, ahora, tasas):
    for t in tasas:
        if abs(t["cambio_pb"]) >= 5:
            k = f"tasa|{t['nombre']}|{ahora:%Y%m%d}|{1 if t['cambio_pb'] > 0 else -1}"
            if not _ya(c, k):
                _marca(c, k)
                enviar("TITAN QUANT — CAMBIO DE EXPECTATIVAS DE TIPOS DE INTERÉS\n\n"
                       f"{t['nombre']}: {t['nivel']:.2f}% ({t['cambio_pb']:+.0f} puntos básicos en el último día).\n"
                       "Es una aproximación (rendimientos de corto plazo), no el precio de los futuros de la Fed.\n"
                       "Posible mecanismo: si el mercado espera tipos más altos, tiende a fortalecer el dólar y presionar a metales, cripto y bolsa; si espera recortes, ocurre lo contrario.\n"
                       "Estado de la información: dato de mercado (Yahoo Finance).")

def tick(e, enviar, zona, ahora=None, macro_cada_s=900):
    """Un ciclo de vigilancia para los activos marcados."""
    ahora = ahora or datetime.now(timezone.utc)
    c = E.conectar()
    try:
        _latido(c, enviar, ahora, zona)
        cap, pct = E.config_riesgo(c)
        st = E.estadisticas(c)
        stats = f"baja; n={st['n']} escenarios cerrados (se requieren 30 para validar). Es una hipótesis, no una certeza"
        previo = E.kv_get(c, "macro_ts")
        toca_macro = not previo or (ahora - datetime.fromisoformat(previo)).total_seconds() >= macro_cada_s
        eventos = macro.escanear() if toca_macro else []
        ultimas = {}
        for sim in e["seleccion"][:MAX_ACTIVOS]:
            a = act.buscar(sim, e["personalizados"])
            if a:
                _activo(c, a, enviar, zona, ahora, cap, pct, ultimas, stats, eventos)
        if toca_macro:
            E.kv_set(c, "macro_ts", ahora.isoformat())
            _macro(c, e, enviar, zona, ahora, ultimas, eventos)
            _tasas(c, enviar, ahora, macro.tasas())
    finally:
        c.close()
