# -*- coding: utf-8 -*-
"""Hoja de análisis de un activo: técnico, noticias, volumen por sesión, contexto y escenarios de
ruptura o rechazo para la hora elegida. Se entrega como PDF + resumen corto. INFORMATIVO."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import agente
import guiado
import pdfmini
import quant
from pdfmini import AZUL, GRIS, NARANJA, ROJO, VERDE, Pdf

N = agente._num
TEAL, BASE_BARRA = (0.15, 0.55, 0.60), (0.55, 0.62, 0.72)
CONTEXTO = {
    "metal": [("Dólar (DXY)", "DX-Y.NYB", -1), ("Rendimiento 10 años EE. UU.", "^TNX", -1)],
    "energia": [("Dólar (DXY)", "DX-Y.NYB", -1)],
    "cripto": [("Nasdaq", "^IXIC", 1)],
    "divisa": [("Dólar (DXY)", "DX-Y.NYB", None)],
    "accion": [("Volatilidad VIX", "^VIX", -1), ("Rendimiento 10 años EE. UU.", "^TNX", -1)],
    "indice": [("Volatilidad VIX", "^VIX", -1), ("Rendimiento 10 años EE. UU.", "^TNX", -1)],
}
PORQUE = {
    "metal": "Los metales no pagan interés: cuando suben el dólar y los rendimientos, mantenerlos cuesta más y pierden atractivo; cuando bajan, ocurre lo contrario.",
    "energia": "Se cotiza en dólares: un dólar fuerte lo encarece para el resto del mundo y frena la demanda. Además lo mueven la oferta (OPEP, inventarios) y la actividad económica.",
    "cripto": "Se comporta como activo de riesgo: sube cuando hay apetito de riesgo (bolsas al alza) y cae cuando hay aversión al riesgo o tasas altas.",
    "divisa": "Un par se mueve por la diferencia de tasas entre ambos países y el apetito de riesgo: el dólar fuerte presiona a EUR/USD y GBP/USD y favorece a USD/JPY y USD/DOP.",
    "accion": "Las acciones suben con ganancias fuertes y tasas bajas; un VIX alto (miedo) y rendimientos altos suelen presionarlas.",
    "indice": "Los índices suben con ganancias empresariales fuertes y tasas bajas; un VIX alto (miedo) y rendimientos altos suelen presionarlos.",
}

# ------------------------------------------------------------ cálculo
def macd_hist_serie(v):
    m = [a - b for a, b in zip(agente.ema(v, 12), agente.ema(v, 26))]
    return [x - y for x, y in zip(m, agente.ema(m, 9))]

def actividad(b, tz):
    """Por hora local: volumen y rango medios, veces el promedio horario, y la última vez."""
    g = {}
    for x in b:
        t = datetime.fromtimestamp(x["t"], timezone.utc).astimezone(tz)
        g.setdefault(t.hour, []).append((x.get("v", 0) or 0, (x["h"] - x["l"]) / x["o"] * 100))
    vols = [x.get("v", 0) or 0 for x in b]
    con_vol = sum(v > 0 for v in vols) >= 0.5 * len(vols)
    vprom = sum(vols) / len(vols) if con_vol else 0.0
    rprom = sum((x["h"] - x["l"]) / x["o"] * 100 for x in b) / len(b)
    out = {}
    for h, lst in g.items():
        if len(lst) >= 8:
            v, r = sum(a for a, _ in lst) / len(lst), sum(c for _, c in lst) / len(lst)
            out[h] = {"vol": v, "rango": r, "n": len(lst), "vol_x": v / vprom if vprom else None,
                      "rango_x": r / rprom if rprom else None,
                      "ult_vol_x": lst[-1][0] / vprom if vprom else None, "ult_rango_x": lst[-1][1] / rprom if rprom else None}
    return out, con_vol

def filas_sesiones(b, sesiones, zona, ahora):
    filas, cache = [], {}
    for nombre, bandera, tz, hm, dur in sesiones:
        z = ZoneInfo(tz)
        if tz not in cache:
            cache[tz] = actividad(b, z)
        act, con_vol = cache[tz]
        ap, ci = hm[0] * 60 + hm[1], hm[0] * 60 + hm[1] + int(dur * 60)
        hoy = ahora.astimezone(z).date()
        def local(minutos):
            return (datetime(hoy.year, hoy.month, hoy.day, tzinfo=z) + timedelta(minutes=minutos)).astimezone(zona).strftime("%H:%M")
        filas.append({"nombre": nombre, "apertura": local(ap), "cierre": local(ci), "ap": act.get(hm[0]),
                      "ci": act.get(((ci - 1) // 60) % 24), "con_vol": con_vol})
    return filas

def contexto(a):
    out = []
    for nombre, sim, rel in CONTEXTO.get(a["clase"], []):
        try:
            c = [x["c"] for x in agente.barras(sim, "6mo", "1d")]
            cambio = (c[-1] / c[-6] - 1) * 100
        except Exception:
            continue
        rel = a["usd"] if rel is None else rel
        if rel:
            lect = "neutral" if abs(cambio) < 0.2 else ("a favor del activo" if cambio * rel > 0 else "en contra del activo")
            out.append({"nombre": nombre, "cambio": cambio, "rel": rel, "lectura": lect})
    return out

def escenarios(r, ah, con_vol, hora):
    b = r["barras"]
    cierres = [x["c"] for x in b]
    precio, R, S = r["precio"], r["resistencia"], r["soporte"]
    atr = precio * r["atr"] / 100
    arriba = (R - precio) <= (precio - S)
    s, nivel = (1, R) if arriba else (-1, S)
    hs = macd_hist_serie(cierres)
    mh, mom = hs[-1], hs[-1] > hs[-4]
    tr = 1 if r["ema20"] > r["ema50"] and precio > r["ema20"] else -1 if r["ema20"] < r["ema50"] and precio < r["ema20"] else 0
    mc = 1 if (mh > 0 and mom) else -1 if (mh < 0 and not mom) else 0
    rs = r["rsi"] if s == 1 else 100 - r["rsi"]
    di = {"alcista": 1, "bajista": -1}.get(r.get("diaria"), 0)
    nw = 0 if r["pocas"] else agente.sgn(r["punt_n"])
    eh = r["est"].get(hora)
    up = None if not eh else (eh["sube"] if s == 1 else 100 - eh["sube"])
    ratio = None if not ah else (ah["vol_x"] if con_vol else ah["rango_x"])
    def lado(x):
        return "ruptura" if x == s else "rechazo" if x == -s else "neutral"
    sg = [
        ("Tendencia horaria", f"EMA20 {'>' if r['ema20'] > r['ema50'] else '<'} EMA50, precio {'sobre' if precio > r['ema20'] else 'bajo'} EMA20", lado(tr)),
        ("MACD (momentum)", f"histograma {mh:+.3f}, {'creciendo' if mom else 'cediendo'}", lado(mc)),
        ("RSI", f"{r['rsi']:.0f}: " + ("agotamiento probable" if rs >= 70 else "recorrido a favor" if rs >= 50 else "sin extremo"),
         "rechazo" if rs >= 70 else "ruptura" if rs >= 50 else "neutral"),
        ("Tendencia diaria", r.get("diaria") or "sin dato", lado(di)),
        ("Noticias", "pocas noticias relevantes" if r["pocas"] else f"puntaje {r['punt_n']:+d} de 2", lado(nw)),
        ("Historial de esa hora", "sin datos suficientes" if up is None else f"{up:.0f}% de los días fue a favor de la ruptura",
         "neutral" if up is None else "ruptura" if up >= 55 else "rechazo" if up <= 45 else "neutral"),
        ("Actividad de esa hora", "sin datos" if ratio is None else f"{ratio:.1f} veces el promedio horario",
         "neutral" if ratio is None else "ruptura" if ratio >= 1.2 else "rechazo" if ratio <= 0.8 else "neutral"),
    ]
    sr, sh = sum(x[2] == "ruptura" for x in sg), sum(x[2] == "rechazo" for x in sg)
    dif = sr - sh
    peso = "ruptura" if dif >= 2 else "rechazo" if dif <= -2 else "equilibrado"
    if con_vol and ah and ah["vol"]:
        umbral = f"volumen de la vela >= {1.3 * ah['vol']:,.0f} (1.3 veces lo típico de esa hora, {ah['vol']:,.0f})"
    elif ah:
        umbral = f"rango de la vela >= {1.3 * ah['rango']:.2f}% (1.3 veces lo típico de esa hora)"
    else:
        umbral = "cierre claro fuera del nivel (sin datos de actividad para esa hora)"
    medio = (R + S) / 2
    nom = "resistencia" if arriba else "soporte"
    return {"arriba": arriba, "nivel": nivel, "nombre_nivel": nom, "dist": abs(nivel - precio) / atr, "senales": sg,
            "ruptura": sr, "rechazo": sh, "peso": peso, "conf": "media" if abs(dif) >= 3 else "baja", "umbral": umbral,
            "filas": [
                ("Ruptura", f"La vela de esa hora cierra {'sobre' if arriba else 'bajo'} {N(nivel)} con {umbral}.",
                 f"Continuación probable hacia {N(nivel + s * 1.5 * atr)}.", f"Cierre de vuelta {'bajo' if arriba else 'sobre'} {N(nivel)}."),
                ("Rechazo", f"El precio toca {N(nivel)} (a menos de 0.25 rangos) pero la vela cierra {'bajo' if arriba else 'sobre'} el nivel, con mecha larga o volumen alto.",
                 f"Retroceso probable hacia la mitad del rango de 48 h ({N(medio)}).", f"Cierre {'sobre' if arriba else 'bajo'} {N(nivel)} con volumen."),
                ("Rango", f"No hay cierre fuera de {N(S)} - {N(R)}.", f"Movimiento limitado: unos {N(precio * (ah['rango'] if ah else r['atr']) / 100)} de rango en esa hora.",
                 "Cierre fuera del rango con volumen."),
            ]}

def _guardar(a, zona, base, r, ahora):
    c = guiado.conectar()
    c.execute("INSERT INTO pron_hora(simbolo,creado_en,objetivo_ts,zona,direccion,total,atr_pct,precio_ref) VALUES (?,?,?,?,?,?,?,?)",
              (a["simbolo"], ahora.isoformat(), int(base.timestamp()), zona.key, r["direccion"], r["total"], r["atr"], r["precio"]))
    c.commit(); c.close()

def reunir(a, zona, base, sesiones, ahora=None):
    ahora = ahora or datetime.now(timezone.utc)
    r = agente.analizar(a, zona, ahora)
    if r["error"]:
        return {"a": a, "r": r, "error": r["error"]}
    act, con_vol = actividad(r["barras"], zona)
    ah = act.get(base.hour)
    d = {"a": a, "zona": zona, "base": base, "ahora": ahora, "r": r, "act": act, "con_vol": con_vol, "ah": ah, "error": None,
         "sesiones": filas_sesiones(r["barras"], sesiones, zona, ahora), "ctx": contexto(a)}
    d["esc"] = escenarios(r, ah, con_vol, base.hour)
    try:
        d["quant"] = quant.reunir(a, zona, base, r, d)
    except Exception as ex:
        d["quant"] = {"error": type(ex).__name__}
    d["coincide"] = [s["nombre"] for s in d["sesiones"] if s["apertura"][:2] == f"{base.hour:02d}"]
    _guardar(a, zona, base, r, ahora)
    return d

# ------------------------------------------------------------ textos
def _lectura_peso(d):
    e = d["esc"]
    if e["peso"] == "equilibrado":
        return f"las señales no dan ventaja clara entre ruptura ({e['ruptura']}) y rechazo ({e['rechazo']})"
    mas, menos = (e["ruptura"], e["rechazo"]) if e["peso"] == "ruptura" else (e["rechazo"], e["ruptura"])
    return f"las señales dan más peso a {'una ruptura' if e['peso'] == 'ruptura' else 'un rechazo'} ({mas} señales contra {menos})"

def resumen_chat(d):
    if d["error"]:
        return f"⚠️ {d['a']['nombre']} ({d['a']['simbolo']}): {d['error']}."
    r, e, base = d["r"], d["esc"], d["base"]
    ex = d["ah"]
    L = [f"🧭 Resumen previo · {d['a']['nombre']} ({d['a']['simbolo']})",
         f"Para {guiado.momento(base, d['ahora'])} ({base.hour:02d}:00, {d['zona'].key}): sesgo {guiado.FRASE[r['direccion']]} (confianza {r['confianza']}).",
         f"Nivel clave: {e['nombre_nivel']} {N(e['nivel'])}. {_lectura_peso(d).capitalize()}.",
         f"Para confirmar una ruptura: {e['umbral']}."]
    if d["coincide"]:
        L.append("Esa hora coincide con la apertura de " + ", ".join(d["coincide"]) + ".")
    L += quant.lineas_chat(d)
    L.append("📄 Detalle completo en la hoja PDF adjunta. Hipótesis informativa, no consejo financiero.")
    return "\n".join(L)

def resumen_ejecutivo(d):
    r, e, base = d["r"], d["esc"], d["base"]
    n = r["noticias"]
    fav, adv = sum(x["impacto"] > 0 for x in n), sum(x["impacto"] < 0 for x in n)
    t = (f"Para {guiado.momento(base, d['ahora'])} ({base.hour:02d}:00, {d['zona'].key}) el sesgo de {d['a']['nombre']} es "
         f"{guiado.FRASE[r['direccion']]}, con confianza {r['confianza']}. El análisis técnico suma {r['punt_t']:+d} de 3 y las noticias "
         f"{r['punt_n']:+d} de 2 ({len(n)} titulares relevantes: {fav} favorables, {adv} adversos).")
    t += (f"\nA esa hora el precio estará cerca de la {e['nombre_nivel']} de {N(e['nivel'])} (a {e['dist']:.1f} rangos horarios de hoy); "
          f"{_lectura_peso(d)}. Para confirmar una ruptura se pide {e['umbral']}.")
    if d["coincide"]:
        t += "\nEsa hora coincide con la apertura de " + ", ".join(d["coincide"]) + ", cuando suele entrar más volumen."
    return t

# ------------------------------------------------------------ PDF
def pdf(d):
    a, r, e, base, zona = d["a"], d["r"], d["esc"], d["base"], d["zona"]
    p = Pdf("TITAN · Hoja informativa. No es consejo financiero ni una predicción.")
    p.rect(0, pdfmini.H - 74, pdfmini.W, 74, fill=AZUL)
    p.texto(pdfmini.M, pdfmini.H - 34, "TITAN · HOJA DE ANÁLISIS", 17, True, (1, 1, 1))
    p.texto(pdfmini.M, pdfmini.H - 54, f"{a['nombre']} ({a['simbolo']})  ·  generado {d['ahora'].astimezone(zona).strftime('%d/%m/%Y %H:%M')} ({zona.key})  ·  hora objetivo {base.hour:02d}:00",
            8.5, False, (0.85, 0.9, 1))
    p.y = pdfmini.H - 74 - 8
    p.seccion("RESUMEN EJECUTIVO")
    p.parrafo(resumen_ejecutivo(d), 9.2)
    col = VERDE if e["peso"] == "ruptura" and e["arriba"] or e["peso"] == "rechazo" and not e["arriba"] else ROJO if e["peso"] != "equilibrado" else GRIS
    p.parrafo(f"Mayor peso: {e['peso']}  ·  Confianza relativa: {e['conf']}  ·  Ruptura {e['ruptura']} señales / Rechazo {e['rechazo']} señales", 9, True, col)
    p.seccion("CIFRAS CLAVE")
    lab = lambda t: (t, GRIS, True)
    p.tabla([[lab("Precio actual"), (N(r["precio"]), (0, 0, 0), True), lab("Hora objetivo"), f"{base.hour:02d}:00 ({zona.key})"],
             [lab("Soporte 48 h"), (N(r["soporte"]), VERDE, True), lab("Resistencia 48 h"), (N(r["resistencia"]), ROJO, True)],
             [lab("Rango típico por hora"), f"{r['atr']:.2f}% (~{N(r['precio'] * r['atr'] / 100)})", lab("RSI (14, 1 h)"), f"{r['rsi']:.0f}"],
             [lab("EMA20 / EMA50"), f"{N(r['ema20'])} / {N(r['ema50'])}", lab("Tendencia diaria"), r.get("diaria") or "sin dato"]],
            [112, 145, 112, 146], cabecera=False)
    ser = [x["c"] for x in r["barras"][-48:]]
    p.grafico_lineas(ser, [(r["resistencia"], "Resistencia", ROJO), (r["soporte"], "Soporte", VERDE)], "PRECIO DE LAS ÚLTIMAS 48 HORAS (velas de 1 h)")

    p.seccion("1. LECTURA TÉCNICA")
    sg = lambda v: (f"{v:+d}", VERDE if v > 0 else ROJO if v < 0 else GRIS, True)
    sp = agente.sgn(r["precio"] - r["ema20"]); se = agente.sgn(r["ema20"] - r["ema50"]); sm = agente.sgn(r["macd"])
    p.tabla([["Indicador", "Valor", "Qué significa", "Señal"],
             ["Precio vs EMA20", f"{N(r['precio'])} vs {N(r['ema20'])}", "Sobre la media corta = impulso alcista de corto plazo; bajo ella = presión bajista.", sg(sp)],
             ["EMA20 vs EMA50", f"{N(r['ema20'])} vs {N(r['ema50'])}", "Media corta sobre la larga = tendencia alcista sostenida; debajo = bajista.", sg(se)],
             ["MACD (histograma)", f"{r['macd']:+.3f}", "Positivo = el momentum compra; negativo = el momentum vende.", sg(sm)],
             ["RSI (14)", f"{r['rsi']:.0f}", "Más de 70: sobrecompra (riesgo de corrección). Menos de 30: sobreventa (posible rebote).",
              ("-1" if r["rsi"] > 75 and r["punt_t"] >= 0 else "+1" if r["rsi"] < 25 else "0", GRIS, True)],
             ["Total técnico", f"{r['punt_t']:+d} de ±3", "Suma de las señales anteriores.", sg(r["punt_t"])]],
            [112, 100, 233, 70])
    n = r["noticias"]
    p.seccion("2. NOTICIAS DE LAS ÚLTIMAS 48 HORAS")
    fav, adv = sum(x["impacto"] > 0 for x in n), sum(x["impacto"] < 0 for x in n)
    p.parrafo(f"{len(n)} titulares relevantes: {fav} favorables, {adv} adversos y {len(n) - fav - adv} neutrales. Puntaje de noticias: {r['punt_n']:+d} de ±2"
              + (" (con menos de 3 titulares relevantes no puntúa)." if r["pocas"] else "."), 9)
    top = sorted(n, key=lambda x: (-abs(x["impacto"]) * x["fuerza"], x["edad_h"]))[:6]
    if top:
        p.tabla([["Impacto", "Titular", "Fuente", "Hace"]] +
                [[("(+) favorable", VERDE, True) if x["impacto"] > 0 else ("(-) adversa", ROJO, True) if x["impacto"] < 0 else "neutral",
                  x["titulo"][:150], x["fuente"][:22], f"{x['edad_h']:.0f} h"] for x in top], [64, 311, 100, 40])
    p.parrafo("Las noticias se clasifican por palabras clave en el titular y el resumen. No entienden el contexto completo: lee los titulares antes de decidir.", 8, False, GRIS)

    p.seccion("3. CONTEXTO DE MERCADO: POR QUÉ IMPORTA")
    p.parrafo(PORQUE.get(a["clase"], ""), 9)
    if d["ctx"]:
        p.tabla([["Variable", "Cambio 5 días", "Relación con el activo", "Lectura hoy"]] +
                [[c["nombre"], f"{c['cambio']:+.2f}%", "inversa (si ella sube, el activo tiende a bajar)" if c["rel"] < 0 else "directa (si ella sube, el activo tiende a subir)",
                  (c["lectura"], VERDE if c["lectura"].startswith("a favor") else ROJO if c["lectura"].startswith("en contra") else GRIS, True)] for c in d["ctx"]],
                [130, 70, 215, 100])
        for c in d["ctx"]:
            s1, s2 = ("más presión bajista", "apoyo alcista") if c["rel"] < 0 else ("apoyo alcista", "más presión bajista")
            p.parrafo(f"• Si {c['nombre']} sigue subiendo -> {s1} sobre {a['nombre']}; si baja -> {s2}.", 8.8)
    quant.seccion_explicacion(p, d)
    quant.seccion_macro(p, d)
    p.seccion("6. ACTIVIDAD Y VOLUMEN POR SESIÓN")
    unidad = "volumen" if d["con_vol"] else "rango"
    clave = "vol_x" if d["con_vol"] else "rango_x"
    fx = lambda x, k: "n/d" if not x or x.get(k) is None else f"{x[k]:.1f}x"
    p.tabla([["Sesión", "Apertura (tu hora)", "Típico apertura", "Última vez", "Cierre (tu hora)", "Típico cierre", "Última vez"]] +
            [[s["nombre"], s["apertura"], fx(s["ap"], clave), fx(s["ap"], "ult_" + clave), s["cierre"], fx(s["ci"], clave), fx(s["ci"], "ult_" + clave)]
             for s in d["sesiones"]], [78, 78, 70, 62, 78, 70, 79])
    p.parrafo(f"Las cifras son veces el {unidad} promedio de una hora (1.0x = normal; 2.0x = el doble). "
              + ("" if d["con_vol"] else "Este mercado no publica volumen fiable, por eso se usa el rango de las velas como medida de actividad. "), 8, False, GRIS)
    ah = d["ah"]
    if ah:
        p.parrafo(f"A las {base.hour:02d}:00 el {unidad} típico es {ah[clave]:.1f} veces el promedio" + (f" (unos {ah['vol']:,.0f} por hora)." if d["con_vol"] else f" (rango medio {ah['rango']:.2f}%)."), 9, True)
    ap_h = {int(s["apertura"][:2]) for s in d["sesiones"]}
    barras = [(f"{h:02d}", (d["act"][h][clave] if h in d["act"] and d["act"][h].get(clave) else 0), NARANJA if h == base.hour else TEAL if h in ap_h else BASE_BARRA)
              for h in range(24)]
    p.grafico_barras(barras, f"ACTIVIDAD POR HORA ({unidad}, tu zona). Naranja = hora objetivo · Verde azulado = apertura de una sesión")

    p.hueco(300)
    p.seccion("7. HORA ELEGIDA: ¿RUPTURA O RECHAZO?")
    p.parrafo(f"Nivel a vigilar: {e['nombre_nivel']} en {N(e['nivel'])}, a {e['dist']:.1f} rangos horarios del precio actual. "
              "Una ruptura es un cierre de vela fuera del nivel; un rechazo es tocarlo y volver, y suele dejar mechas largas.", 9)
    p.tabla([["Escenario", "Condición a esa hora", "Si ocurre", "Se invalida si"]] + [list(f) for f in e["filas"]], [58, 207, 140, 110])
    col_f = lambda f: (("ruptura", VERDE, True) if f == "ruptura" else ("rechazo", NARANJA, True) if f == "rechazo" else ("neutral", GRIS, False))
    p.tabla([["Señal", "Lectura actual", "Favorece a"]] + [[s[0], s[1], col_f(s[2])] for s in e["senales"]], [120, 285, 110])
    neutrales = len(e["senales"]) - e["ruptura"] - e["rechazo"]
    p.parrafo(f"Resultado: ruptura {e['ruptura']} · rechazo {e['rechazo']} · neutrales {neutrales}. Lectura: {_lectura_peso(d)}. "
              f"Confianza relativa {e['conf']} (es coincidencia de señales, no una probabilidad).", 9, True)

    quant.seccion_escenarios(p, d)

    p.seccion("9. CONCLUSIÓN, FUENTES Y LÍMITES")
    quant.fuentes(p, d)
    p.parrafo(f"• Sesgo general: {guiado.FRASE[r['direccion']]}. Si a esa hora el precio hace lo que describe el escenario de {e['peso'] if e['peso'] != 'equilibrado' else 'ruptura o rechazo'}, la lectura se confirma; si ocurre lo contrario, descártala.", 9)
    p.parrafo("• Esta hoja ordena la información disponible (precio, volumen, noticias, contexto); no conoce órdenes grandes, anuncios que aún no salen ni liquidez real.", 9)
    p.parrafo("• Son hipótesis informativas: no son predicciones ni consejo financiero. Cada una se guarda y se verifica sola cuando pasa la hora (botón de precisión del bot).", 9)
    return p.construir()
