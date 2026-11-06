# -*- coding: utf-8 -*-
"""TITAN QUANT en la hoja de análisis: explicación del movimiento, contexto macro, escenarios con stop/take-profit y riesgo."""
from __future__ import annotations
from datetime import datetime, timezone

import agente
import escenarios as E
import macro
from pdfmini import GRIS, NARANJA, ROJO, VERDE

N = agente._num

def _diverge(c):
    n = len(c)
    if n < 60:
        return None
    ult, prev = c[-24:], c[-48:-24]
    i1, i2 = max(range(24), key=lambda i: ult[i]), max(range(24), key=lambda i: prev[i])
    if ult[i1] >= prev[i2] and agente.rsi(c[:n - 24 + i1 + 1]) < agente.rsi(c[:n - 48 + i2 + 1]) - 3:
        return "el precio hizo un máximo más alto pero con RSI menor (divergencia bajista: posible agotamiento)"
    j1, j2 = min(range(24), key=lambda i: ult[i]), min(range(24), key=lambda i: prev[i])
    if ult[j1] <= prev[j2] and agente.rsi(c[:n - 24 + j1 + 1]) > agente.rsi(c[:n - 48 + j2 + 1]) + 3:
        return "el precio hizo un mínimo más bajo pero con RSI mayor (divergencia alcista: posible agotamiento de la caída)"
    return None

def explicar(a, r, ahora, zona):
    b = r["barras"]
    cer = E.cerradas(b, ahora)
    ult = cer[-24:]
    cierres = [x["c"] for x in cer]
    mov24 = (ult[-1]["c"] / ult[0]["o"] - 1) * 100
    k = max(range(len(ult)), key=lambda i: abs(ult[i]["c"] / ult[i]["o"] - 1))
    barra = ult[k]
    mov_b, atr_pct = (barra["c"] / barra["o"] - 1) * 100, r["atr"]
    vt = E.vol_tipico(b)
    hh = (barra["t"] // 3600) % 24
    vol_x = (barra["v"] / vt[hh]) if vt and vt.get(hh) and barra.get("v") else None
    t_bar = datetime.fromtimestamp(barra["t"], timezone.utc)
    anormal = abs(mov_b) >= 1.0 * atr_pct
    previos = [n for n in r["noticias"] if anormal and -1.5 <= (t_bar - datetime.fromisoformat(n["fecha"])).total_seconds() / 3600 <= 6]
    idx = cer.index(barra)
    prev48 = cer[max(0, idx - 48):idx]
    rotura = None
    if prev48:
        mx, mn = max(x["h"] for x in prev48), min(x["l"] for x in prev48)
        rotura = ("alcista", "máximo", mx) if barra["c"] > mx else ("bajista", "mínimo", mn) if barra["c"] < mn else None
    revertida = None
    for j in range(max(48, len(cer) - 6), len(cer) - 1):
        pm, pn = max(x["h"] for x in cer[j - 48:j]), min(x["l"] for x in cer[j - 48:j])
        if cer[j]["c"] > pm and any(cer[m]["c"] <= pm for m in range(j + 1, len(cer))):
            revertida = f"una vela cerró sobre {N(pm)} y luego el precio volvió bajo ese nivel (ruptura que se revirtió)"
        elif cer[j]["c"] < pn and any(cer[m]["c"] >= pn for m in range(j + 1, len(cer))):
            revertida = f"una vela cerró bajo {N(pn)} y luego el precio volvió sobre ese nivel (ruptura que se revirtió)"
    rg = [x["h"] - x["l"] for x in cer]
    salto = (sum(rg[-3:]) / 3) / (sum(rg[-17:-3]) / 14) if len(rg) >= 17 and sum(rg[-17:-3]) else 1.0
    div = _diverge(cierres)
    hora = t_bar.astimezone(zona).strftime("%H:%M")
    fuerte = abs(mov_b) >= 1.5 * atr_pct
    obs = [f"Variación de las últimas 24 h: {mov24:+.2f}% (rango típico por hora: {atr_pct:.2f}%).",
           f"La vela más movida fue la de las {hora} ({zona.key}): {mov_b:+.2f}%, {abs(mov_b) / atr_pct:.1f} veces el rango típico"
           + (f", con volumen {vol_x:.1f} veces lo normal." if vol_x else "; volumen no disponible.")]
    if rotura and not anormal:
        rotura = None
    if rotura:
        obs.append(f"Esa vela cerró {'sobre el máximo' if rotura[0] == 'alcista' else 'bajo el mínimo'} de las 48 velas previas ({N(rotura[2])}).")
    if revertida:
        obs.append("Reversión reciente: " + revertida + ".")
    if div:
        obs.append("Divergencia: " + div + ".")
    if salto >= 1.8:
        obs.append(f"Salto de volatilidad: las últimas 3 velas se mueven {salto:.1f} veces más que lo habitual.")
    inter, hip = [], []
    if previos:
        inter.append(f"Antes o durante ese movimiento se publicaron {len(previos)} titulares relevantes (tabla). Coinciden en el tiempo, pero la coincidencia no demuestra que causaran el movimiento.")
        hip.append("Posible reacción del mercado a las publicaciones citadas.")
    if rotura:
        inter.append("El movimiento coincide con una ruptura técnica del rango de las 48 h previas.")
        if vol_x and vol_x >= 1.3:
            hip.append("Posible entrada de órdenes de seguimiento y de stops por la ruptura (el volumen elevado es compatible, no prueba).")
    if vol_x and vol_x >= 1.5:
        inter.append("El volumen elevado indica que entraron muchas órdenes; con datos públicos gratuitos no se puede saber quién las envió.")
    if revertida:
        hip.append("Posible ruptura falsa: el mercado superó el nivel y volvió, lo que suele dejar atrapados a quienes entraron tarde (no demostrable con estos datos).")
    if div:
        hip.append("Posible pérdida de fuerza del movimiento anterior.")
    sin_causa = fuerte and not (previos or rotura or (vol_x and vol_x >= 1.5))
    if not anormal:
        inter.append("No hubo un movimiento anormal en las últimas 24 h: no hay nada extraordinario que explicar.")
    if sin_causa:
        inter.append("Hubo un movimiento fuerte y NO se identificó una causa con los datos disponibles.")
    return {"observado": obs, "previos": previos, "interpretacion": inter, "hipotesis": hip, "sin_causa": sin_causa}

def reunir(a, zona, base, r, d):
    ahora = d["ahora"]
    c = E.conectar()
    cap, pct = E.config_riesgo(c)
    filas = []
    try:
        for e in E.generar(a, r["barras"], ahora, cap, pct):
            res = E.evaluar(e, r["barras"], ahora, a, cap, pct)
            ind = __import__("json").loads(e["indicadores"])
            plan = res["plan"] or (E.calc_plan(a, e["tipo"], ind, e["entrada"], None, cap, pct) if e["entrada"] else None)
            filas.append({"tipo": e["tipo"], "estado": res["hitos"][-1][0] if res["hitos"] else "preparado", "nivel": e["nivel"], "plan": plan, "ind": ind})
    except Exception:
        filas = []
    ev = macro.escanear()
    out = {"explicacion": explicar(a, r, ahora, zona), "escenarios": filas, "capital": cap, "riesgo_pct": pct,
           "stats": E.estadisticas(c, a["simbolo"])["texto"], "monitoreado": bool(E.activos(c, a["simbolo"])),
           "eventos": macro.para_clase(a["clase"], ev)[:6], "tasas": macro.tasas(), "error": None}
    c.close()
    return out

def lineas_chat(d):
    q = d.get("quant")
    if not q or q.get("error"):
        return []
    L = []
    ex = q["explicacion"]
    L.append("Qué pasó: " + (ex["observado"][1] if len(ex["observado"]) > 1 else ex["observado"][0]).replace(" (" + d["zona"].key + ")", ""))
    if ex["sin_causa"]:
        L.append("Causa: no identificada con los datos disponibles.")
    cand = [f for f in q["escenarios"] if f["tipo"] != "lateral"]
    if cand:
        f = sorted(cand, key=lambda f: (-E.rank(f["estado"]) if E.rank(f["estado"]) < 4 else 0, abs(f["nivel"] - d["r"]["precio"])))[0]
        L.append(f"Escenario más cercano: {E.TIPOS[f['tipo']][1]} · {E.ETIQ[f['estado']]} · nivel {N(f['nivel'])}.")
    return L

# ------------------------------------------------------------ secciones del PDF
def _no_disponible(p, titulo, motivo):
    p.seccion(titulo)
    p.parrafo(f"Sección no disponible: {motivo}.", 9, False, GRIS)

def seccion_explicacion(p, d):
    q = d.get("quant")
    if not q or q.get("error"):
        return _no_disponible(p, "4. ¿QUÉ PASÓ Y POR QUÉ SE MOVIÓ?", "no se pudo calcular")
    ex = q["explicacion"]
    p.seccion("4. ¿QUÉ PASÓ Y POR QUÉ SE MOVIÓ?")
    p.parrafo("Datos observados (precio y volumen)", 9, True, GRIS, despues=1)
    for x in ex["observado"]:
        p.parrafo("• " + x, 8.8, despues=1)
    if ex["previos"]:
        p.parrafo("Hechos publicados (titulares con fuente, previos al movimiento)", 9, True, GRIS, despues=2)
        p.tabla([["Impacto teórico", "Titular", "Fuente", "Hace"]] + [
            [("(+) favorable", VERDE, True) if x["impacto"] > 0 else ("(-) adversa", ROJO, True) if x["impacto"] < 0 else "neutral",
             x["titulo"][:140], x["fuente"][:22], f"{x['edad_h']:.0f} h"] for x in ex["previos"][:4]], [70, 305, 100, 40])
    p.parrafo("Interpretación (lo que los datos sugieren)", 9, True, GRIS, despues=1)
    for x in ex["interpretacion"] or ["Sin elementos suficientes para interpretar."]:
        p.parrafo("• " + x, 8.8, despues=1)
    if ex["hipotesis"]:
        p.parrafo("Hipótesis (no demostradas)", 9, True, GRIS, despues=1)
        for x in ex["hipotesis"]:
            p.parrafo("• " + x, 8.8, False, NARANJA, despues=1)
    p.parrafo("Lo que NO se sabe: TITAN no puede identificar a bancos centrales, bancos, fondos, creadores de mercado ni empresas detrás de un movimiento, "
              "y no atribuye el movimiento a ninguno. Los datos de posicionamiento (COT), flujos de ETF, interés abierto y liquidaciones no están disponibles en esta versión.", 8.3, False, GRIS)

def seccion_macro(p, d):
    q = d.get("quant")
    p.seccion("5. MACRO, GOBIERNOS Y GEOPOLÍTICA")
    if not q or q.get("error"):
        return p.parrafo("Sección no disponible: no se pudo calcular.", 9, False, GRIS)
    ev = q["eventos"]
    if ev:
        p.tabla([["Evento", "Titular (prensa)", "Fuente", "Hace", "Impacto"]] + [
            [x["nombre"], x["titulo"][:110], x["fuente"][:18], f"{x['edad_h']:.0f} h", ("alto", ROJO, True) if x["alto"] else "medio"] for x in ev],
            [105, 245, 70, 35, 60])
        vistos = []
        for x in ev:
            if x["tipo"] not in vistos:
                vistos.append(x["tipo"])
                p.parrafo(f"• {x['nombre']}: {x['mecanismo']}", 8.5, despues=1)
    else:
        p.parrafo("No se detectaron titulares macro relevantes para este tipo de activo en las últimas 24 h.", 9)
    if q["tasas"]:
        p.parrafo("Expectativas de tipos de interés (aproximación por rendimientos de corto plazo):", 9, True, GRIS, despues=1)
        for t in q["tasas"]:
            p.parrafo(f"• {t['nombre']}: {t['nivel']:.2f}% ({t['cambio_pb']:+.0f} puntos básicos en el último día).", 8.8, despues=1)
    p.parrafo("Estado de la información: los eventos son titulares de prensa, sin verificación oficial. Esta versión no incluye un calendario económico con dato anterior, "
              "consenso y dato publicado; TITAN no inventa esas cifras.", 8.3, False, GRIS)

def seccion_escenarios(p, d):
    q = d.get("quant")
    p.seccion("8. ESCENARIOS, STOP-LOSS, TAKE-PROFIT Y RIESGO")
    if not q or q.get("error") or not q["escenarios"]:
        return p.parrafo("Sección no disponible: no hay datos suficientes para construir escenarios.", 9, False, GRIS)
    filas = [["Escenario", "Estado", "Disparador", "Entrada*", "Stop-loss", "Objetivos (R/R)", "Operable"]]
    avisos = []
    for f in q["escenarios"]:
        pl = f["plan"]
        if f["tipo"] == "lateral":
            filas.append([E.TIPOS[f["tipo"]][1], E.ETIQ[f["estado"]], f"rango {N(f['ind']['S'])} - {N(f['ind']['R'])}", "-", "-", "sin entrada direccional", "-"])
            continue
        tps = " / ".join(f"{N(t['nivel'])} ({t['rr']:.1f})" for t in pl["tps"][:2]) if pl else "-"
        filas.append([E.TIPOS[f["tipo"]][1], E.ETIQ[f["estado"]], ("cierre " + ("sobre " if f["tipo"] == "ruptura_alcista" else "bajo " if f["tipo"] == "ruptura_bajista" else "con rechazo en ") + N(f["nivel"])),
                      N(pl["entrada"]) if pl else "-", N(pl["stop"]) if pl else "-", tps or "sin recorrido",
                      ("sí", VERDE, True) if pl and pl["ok"] else ("no", ROJO, True)])
        if pl:
            avisos += [f"{E.TIPOS[f['tipo']][1]}: {x}" for x in pl["avisos"]]
    p.tabla(filas, [88, 76, 98, 50, 50, 105, 48], size=7.8)
    p.parrafo("*Entrada provisional: se recalcula con el cierre de la vela que confirme el escenario. Stop-loss: más allá de la estructura que invalida la hipótesis, "
              "con margen de 0.5 ATR. Objetivos: niveles técnicos reales (máximos/mínimos, extensión del rango) o volatilidad; R/R ya descuenta costes supuestos.", 8, False, GRIS)
    for x in avisos[:6]:
        p.parrafo("• " + x, 8.5, False, ROJO, despues=1)
    if q["capital"]:
        p.parrafo(f"Riesgo configurado: {q['riesgo_pct']:.1f}% de {N(q['capital'])} = {N(q['capital'] * q['riesgo_pct'] / 100)} por operación.", 9, True)
        for f in q["escenarios"]:
            t = f["plan"]["tamano"] if f["plan"] else None
            if t:
                p.parrafo(f"• {E.TIPOS[f['tipo']][1]}: {t['cantidad']} {t['unidad']} (pérdida hasta el stop ≈ {N(t['perdida_hasta_stop'])}; "
                          f"ganancia en TP1 ≈ {N(t['ganancia_tp'][0]) if t['ganancia_tp'] else '-'}). Verifica las especificaciones de tu bróker.", 8.5, despues=1)
    else:
        p.parrafo("Tamaño de posición: configura tu capital y el riesgo por operación con /riesgo CAPITAL PORCENTAJE (por ejemplo /riesgo 5000 1).", 8.8, False, NARANJA)
    p.parrafo("Validación estadística: " + q["stats"], 8.5)
    p.parrafo("Seguimiento: " + ("este activo ya tiene escenarios vigilados." if q["monitoreado"] else
              "para recibir alertas de estos escenarios en Telegram marca el activo en /activos y activa la vigilancia con /vigilar."), 8.5)

def fuentes(p, d):
    r, zona, b = d["r"], d["zona"], d["r"]["barras"]
    ult = datetime.fromtimestamp(b[-1]["t"], timezone.utc)
    edad = (d["ahora"] - ult).total_seconds() / 60
    cam = lambda n: f"{(b[-1]['c'] / b[-min(n, len(b))]['o'] - 1) * 100:+.2f}%"
    p.parrafo(f"• Fuente de datos: Yahoo Finance (velas de 1 hora y diarias) y Google News (titulares). Última vela: {ult.astimezone(zona):%d/%m/%Y %H:%M} ({zona.key}), "
              f"inicio hace {edad:.0f} min (la vela en curso se actualiza en tiempo casi real; puede haber retrasos del proveedor).", 8.8)
    p.parrafo(f"• Variación: 24 h {cam(24)} · 5 días {cam(120)} · 30 días {cam(len(b))}. Tendencia de corto plazo (1 h): "
              f"{'alcista' if r['ema20'] > r['ema50'] else 'bajista'}; medio plazo (diaria): {r.get('diaria') or 'sin dato'}; "
              f"largo plazo (30 días): {'alcista' if b[-1]['c'] > b[0]['o'] else 'bajista'}.", 8.8)
    s = d["a"]["simbolo"]
    inst = ("futuros continuos de Yahoo Finance (contrato más cercano; puede cambiar de contrato al vencimiento). " + ("No se mezcla con el contado XAU/USD, que esta fuente no ofrece: precios y volúmenes son solo de los futuros. " if s == "GC=F" else "")
            if s.endswith("=F") else "par de divisas al contado (el volumen que publica esta fuente no es fiable). " if s.endswith("=X")
            else "precio agregado de criptomoneda en dólares. " if s.endswith("-USD") else "acción o ETF cotizado.")
    p.parrafo(f"• Instrumento analizado ({s}): {inst}", 8.8)
    p.parrafo("• Separación de niveles de certeza: los precios y volúmenes son datos observados; los titulares son hechos publicados por la prensa (no verificados oficialmente); "
              "las lecturas técnicas son interpretaciones; los escenarios son hipótesis condicionadas. Ninguna es una certeza.", 8.8)
