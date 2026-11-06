# -*- coding: utf-8 -*-
"""Hoja de análisis ampliada para la interfaz web de TITAN QUANT.
Explica cada número, marca lo positivo (verde) y lo negativo (rojo), y redacta los escenarios en
lenguaje técnico (estructura, soporte/resistencia, línea de tendencia, temporalidades).
No escribe en bases de datos. Es independiente del PDF de Telegram (informe.pdf no se modifica).
INFORMATIVO: no es consejo financiero ni una predicción."""
import math

import agente
import guiado
import informe
import pdfmini
import quant
from pdfmini import AZUL, GRIS, NARANJA, ROJO, VERDE, Pdf, M, W

N = agente._num
POS, NEG, NEU = "pos", "neg", "neu"
FONDO = {POS: (0.88, 0.96, 0.90), NEG: (0.99, 0.89, 0.89), NEU: (0.93, 0.94, 0.96)}
BARRA = {POS: VERDE, NEG: ROJO, NEU: GRIS}


def _tono(x):
    return POS if x > 0 else NEG if x < 0 else NEU


def _nombre_nivel(e):
    return e["nombre_nivel"]


# ------------------------------------------------------------------ cálculos de apoyo
def movimiento(r):
    """Qué está haciendo el precio ahora: últimas 6 velas de 1 h frente al rango típico."""
    b = r["barras"]
    if len(b) < 8:
        return {"signo": 0, "chg": 0.0, "texto": "no hay datos suficientes"}
    chg = (b[-1]["c"] / b[-6]["o"] - 1) * 100
    thr = 0.5 * r["atr"]
    sobre = r["precio"] > r["ema20"]
    signo = 1 if chg > thr and sobre else -1 if chg < -thr and not sobre else 0
    pos = "sobre" if sobre else "bajo"
    nom = {1: "alcista", -1: "bajista", 0: "lateral / sin impulso claro"}[signo]
    return {"signo": signo, "chg": chg, "nombre": nom,
            "texto": f"en las últimas 6 velas de 1 h el precio varió {chg:+.2f}% y cotiza {pos} su media EMA20; movimiento {nom}"}


def tendencia_lineal(b):
    c = [x["c"] for x in b[-48:]]
    n = len(c)
    if n < 10:
        return None
    mx, my = (n - 1) / 2, sum(c) / n
    sxx = sum((i - mx) ** 2 for i in range(n))
    pend = sum((i - mx) * (v - my) for i, v in enumerate(c)) / sxx
    b0 = my - pend * mx
    res = [v - (b0 + pend * i) for i, v in enumerate(c)]
    sst = sum((v - my) ** 2 for v in c) or 1e-12
    r2 = 1 - sum(x * x for x in res) / sst
    sig = math.sqrt(sum(x * x for x in res) / n)
    fin = b0 + pend * (n - 1)
    return {"pend_pct_h": pend / c[-1] * 100, "r2": r2, "fin": fin, "sup": fin + 2 * sig, "inf": fin - 2 * sig, "precio": c[-1]}


def estructura(b):
    h = [x["h"] for x in b[-60:]]
    l = [x["l"] for x in b[-60:]]
    ph = [h[i] for i in range(3, len(h) - 3) if h[i] == max(h[i - 3:i + 4])]
    pl = [l[i] for i in range(3, len(l) - 3) if l[i] == min(l[i - 3:i + 4])]
    if len(ph) >= 2 and len(pl) >= 2:
        if ph[-1] > ph[-2] and pl[-1] > pl[-2]:
            return 1, "máximos y mínimos crecientes (HH/HL): estructura alcista"
        if ph[-1] < ph[-2] and pl[-1] < pl[-2]:
            return -1, "máximos y mínimos decrecientes (LH/LL): estructura bajista"
        return 0, "máximos y mínimos mixtos: estructura sin tendencia definida (rango / transición)"
    return 0, "sin pivotes suficientes para definir estructura"


def _pesos_noticias(n):
    pesos = [1.0 if x["edad_h"] < 12 else 0.6 if x["edad_h"] < 24 else 0.3 for x in n]
    prom = sum(p * x["impacto"] for p, x in zip(pesos, n)) / sum(pesos) if n else 0.0
    return prom


# ------------------------------------------------------------------ resumen ejecutivo
def resumen_items(d):
    r, e, base, a = d["r"], d["esc"], d["base"], d["a"]
    n = r["noticias"]
    fav, adv = sum(x["impacto"] > 0 for x in n), sum(x["impacto"] < 0 for x in n)
    neu = len(n) - fav - adv
    sg_t = lambda v: "+1" if v > 0 else "-1" if v < 0 else "0"
    sp, se, sm = agente.sgn(r["precio"] - r["ema20"]), agente.sgn(r["ema20"] - r["ema50"]), agente.sgn(r["macd"])
    mov = movimiento(r)
    sesgo = {"alcista": 1, "ligeramente alcista": 1, "lateral": 0, "ligeramente bajista": -1, "bajista": -1}[r["direccion"]]
    L = []

    L.append({"tono": _tono(sesgo), "titulo": "1. Sesgo general",
              "texto": f"Para {guiado.momento(base, d['ahora'])} ({base.hour:02d}:00, {d['zona'].key}) el sesgo de {a['nombre']} es "
                       f"{guiado.FRASE[r['direccion']]}, con confianza {r['confianza']}. Es la suma de dos partes: análisis técnico "
                       f"{r['punt_t']:+d} y noticias {r['punt_n']:+d} = total {r['total']:+d}. Escala del total: +2 o más alcista, +1 ligeramente alcista, "
                       f"0 lateral, -1 ligeramente bajista, -2 o menos bajista. La confianza solo es «media» cuando técnico y noticias apuntan al mismo lado y suman 3 o más."})

    cuerpo = (f"Técnico {r['punt_t']:+d} de ±3. Se suman tres señales de ±1 cada una: precio frente a la EMA20 ({sg_t(sp)}: "
              f"{'sobre' if sp > 0 else 'bajo' if sp < 0 else 'igual a'} la media corta), EMA20 frente a EMA50 ({sg_t(se)}: "
              f"{'tendencia alcista' if se > 0 else 'tendencia bajista' if se < 0 else 'sin cruce'}) y MACD ({sg_t(sm)}: "
              f"{'momentum comprador' if sm > 0 else 'momentum vendedor' if sm < 0 else 'neutro'}).")
    if r["notas"]:
        cuerpo += " Ajuste del RSI: " + "; ".join(x for x in r["notas"] if "RSI" in x) + "." if any("RSI" in x for x in r["notas"]) else ""
    cuerpo += (" Un +3 significa que las tres señales empujan hacia arriba; un -3 que las tres empujan hacia abajo; 0 que se compensan.")
    L.append({"tono": _tono(r["punt_t"]), "titulo": f"2. Qué significa «técnico {r['punt_t']:+d} de 3»", "texto": cuerpo})

    prom = _pesos_noticias(n)
    if r["pocas"]:
        txt = (f"Noticias {r['punt_n']:+d} de ±2. Hay {len(n)} titulares relevantes ({fav} favorables, {adv} adversos, {neu} neutrales) y se exigen al menos "
               f"{agente.MIN_NOTICIAS} para puntuar; por eso las noticias no suman ni restan (0). No es que sean malas: son pocas.")
    else:
        txt = (f"Noticias {r['punt_n']:+d} de ±2. De {len(n)} titulares relevantes: favorables {fav} (+1 cada uno), adversos {adv} (-1) y neutrales {neu} (0). "
               f"Cada titular pesa más cuanto más reciente (menos de 12 h: 1.0; menos de 24 h: 0.6; más viejo: 0.3). El promedio ponderado hoy es {prom:+.2f}; "
               f"se multiplica por 3 y se limita a ±2, lo que da {r['punt_n']:+d}. Positivo: el flujo de noticias favorece al activo; negativo: lo presiona; 0: neutral.")
    L.append({"tono": _tono(r["punt_n"]) if not r["pocas"] else NEU, "titulo": f"3. Qué significa «noticias {r['punt_n']:+d} de 2»", "texto": txt})

    # ¿Apoya o no apoya el movimiento actual?
    if sesgo != 0 and mov["signo"] == sesgo:
        tono, veredicto = POS, "APOYA el movimiento actual"
        exp = ("El sesgo apunta en la misma dirección que lo que el precio está haciendo ahora: hay coincidencia entre la lectura y el movimiento. "
               "Aun así, un movimiento ya extendido puede estar cerca de agotarse; revisa el RSI y la distancia al nivel clave.")
    elif sesgo != 0 and mov["signo"] == -sesgo:
        tono, veredicto = NEG, "NO APOYA el movimiento actual (diverge)"
        exp = ("El sesgo apunta contra lo que el precio hace ahora. Eso sugiere agotamiento o una posible reversión, pero no está confirmado: "
               "espera a que el cierre de vela y el nivel clave lo validen antes de darlo por válido.")
    elif sesgo == 0 and mov["signo"] != 0:
        tono, veredicto = NEU, "NO CONFIRMA el movimiento actual"
        exp = "El sesgo es lateral, de modo que ni respalda ni contradice el movimiento; el impulso actual no tiene apoyo técnico claro."
    elif sesgo != 0 and mov["signo"] == 0:
        tono, veredicto = NEU, "El mercado aún no se mueve en esa dirección"
        exp = "Hay sesgo, pero el precio está lateral: todavía no hay un movimiento que el sesgo pueda apoyar. Falta confirmación."
    else:
        tono, veredicto = NEU, "Sin movimiento ni sesgo claros"
        exp = "Ni el precio ni el análisis marcan dirección: mercado de rango."
    L.append({"tono": tono, "titulo": "4. ¿Apoya o no el movimiento actual?",
              "texto": f"{veredicto}. Movimiento: {mov['texto']}. Sesgo del análisis: {guiado.FRASE[r['direccion']]}. {exp}", "veredicto": veredicto})

    col = POS if (e["peso"] == "ruptura" and e["arriba"]) or (e["peso"] == "rechazo" and not e["arriba"]) else \
        NEG if e["peso"] != "equilibrado" else NEU
    L.append({"tono": col, "titulo": "5. Nivel clave y qué se espera",
              "texto": f"A esa hora el precio estará cerca de la {_nombre_nivel(e)} de {N(e['nivel'])} (a {e['dist']:.1f} rangos horarios del precio actual). "
                       f"{informe._lectura_peso(d).capitalize()}. Para confirmar una ruptura se pide {e['umbral']}. "
                       f"Ruptura = una vela H1 que cierra fuera del nivel; rechazo = toca el nivel y vuelve (deja mecha larga)."})
    if d["coincide"]:
        L.append({"tono": NEU, "titulo": "6. Horario de sesión",
                  "texto": "Esa hora coincide con la apertura de " + ", ".join(d["coincide"]) + ": suele entrar más volumen y los movimientos pueden acelerarse."})
    return L


# ------------------------------------------------------------------ cifras clave
def cifras(d):
    r, e, base, ah = d["r"], d["esc"], d["base"], d["ah"]
    p, S, R = r["precio"], r["soporte"], r["resistencia"]
    atr_abs = p * r["atr"] / 100
    pos_rango = (p - S) / (R - S) * 100 if R > S else 50
    unidad = "clave"
    f = []

    def add(c, v, sig, pos, neg, lect, tono):
        f.append({"cifra": c, "valor": v, "significado": sig, "positivo": pos, "negativo": neg, "lectura": lect, "tono": tono})

    sobre = (p > r["ema20"]) + (p > r["ema50"])
    add("Precio actual", N(p), "Último cierre de vela de 1 h.", "Por encima de EMA20 y EMA50.", "Por debajo de EMA20 y EMA50.",
        {2: "sobre ambas medias", 1: "entre las medias", 0: "bajo ambas medias"}[sobre], {2: POS, 1: NEU, 0: NEG}[sobre])
    add("Soporte 48 h", N(S), "Mínimo de las últimas 48 h: zona donde antes entraron compradores.", "El precio rebota en él.", "Lo pierde con un cierre H1 (ruptura bajista).",
        f"a {abs(p / S - 1) * 100:.2f}% por debajo del precio", NEU)
    add("Resistencia 48 h", N(R), "Máximo de las últimas 48 h: zona donde antes entraron vendedores.", "Se rompe con un cierre H1 y volumen (ruptura alcista).", "El precio es rechazado en ella.",
        f"a {abs(R / p - 1) * 100:.2f}% por encima del precio", NEU)
    add("Posición en el rango 48 h", f"{pos_rango:.0f}%", "0% = sobre el soporte, 100% = sobre la resistencia.", "Cerca de 0-30% con rebote: espacio para subir.", "Cerca de 70-100%: poco espacio antes de la resistencia.",
        "cerca del soporte" if pos_rango <= 30 else "cerca de la resistencia" if pos_rango >= 70 else "zona media", POS if pos_rango <= 30 else NEG if pos_rango >= 70 else NEU)
    add("Rango típico por hora", f"{r['atr']:.2f}% (~{N(atr_abs)})", "Cuánto suele moverse una vela de 1 h; sirve para medir si un movimiento es grande o normal.",
        "Una vela mayor a lo típico con dirección clara = movimiento con fuerza.", "Muy por debajo de lo típico = mercado dormido, señales poco fiables.", "referencia de volatilidad", NEU)
    rs = r["rsi"]
    add("RSI (14, 1 h)", f"{rs:.0f}", "Fuerza relativa de 0 a 100: compara subidas y bajadas recientes.", "50-70: tendencia alcista sana; menos de 30: sobreventa (posible rebote).",
        "Más de 70: sobrecompra (riesgo de corrección); menos de 50: presión vendedora.",
        "sobrecompra" if rs >= 70 else "sobreventa" if rs <= 30 else "alcista sana" if rs >= 50 else "presión vendedora", NEG if rs >= 70 else POS if rs <= 30 or rs >= 50 else NEG)
    add("EMA20 / EMA50", f"{N(r['ema20'])} / {N(r['ema50'])}", "Medias móviles exponenciales de 20 y 50 velas: tendencia corta y media; también actúan como soporte/resistencia dinámicos.",
        "EMA20 sobre EMA50.", "EMA20 bajo EMA50.", "EMA20 sobre EMA50" if r["ema20"] > r["ema50"] else "EMA20 bajo EMA50", POS if r["ema20"] > r["ema50"] else NEG)
    add("MACD (histograma)", f"{r['macd']:+.3f}", "Diferencia entre dos medias: mide el impulso (momentum).", "Mayor que 0 y creciendo.", "Menor que 0 y cayendo.",
        "momentum comprador" if r["macd"] > 0 else "momentum vendedor", _tono(r["macd"]))
    dia = r.get("diaria")
    add("Tendencia diaria", dia or "sin dato", "Precio frente a la EMA50 en velas diarias: el contexto de fondo.", "Alcista (precio sobre la EMA50 diaria).", "Bajista (precio bajo la EMA50 diaria).",
        dia or "sin dato", POS if dia == "alcista" else NEG if dia == "bajista" else NEU)
    add("Puntuación técnica", f"{r['punt_t']:+d} de ±3", "Suma de 3 señales (precio/EMA20, EMA20/EMA50, MACD), con ajuste por RSI extremo.", "+2 o +3: técnico alcista.", "-2 o -3: técnico bajista.",
        "alcista" if r["punt_t"] >= 2 else "bajista" if r["punt_t"] <= -2 else "débil / mixta", _tono(r["punt_t"]) if abs(r["punt_t"]) >= 2 else NEU)
    add("Puntuación noticias", f"{r['punt_n']:+d} de ±2", f"Promedio ponderado por frescura de los titulares; no puntúa con menos de {agente.MIN_NOTICIAS} relevantes.", "+1 o +2: flujo favorable.", "-1 o -2: flujo adverso.",
        "sin puntuar (pocas noticias)" if r["pocas"] else "favorable" if r["punt_n"] > 0 else "adverso" if r["punt_n"] < 0 else "neutral", NEU if r["pocas"] else _tono(r["punt_n"]))
    add("Total (técnico + noticias)", f"{r['total']:+d}", "Suma de ambas partes; define el sesgo.", "+2 o más: alcista.", "-2 o menos: bajista.", guiado.FRASE[r["direccion"]],
        POS if r["total"] >= 2 else NEG if r["total"] <= -2 else NEU)
    nt = len(e["senales"]) - e["ruptura"] - e["rechazo"]
    add("Ruptura vs rechazo", f"{e['ruptura']} vs {e['rechazo']} (neutrales {nt})", "Cuántas de 7 señales favorecen romper el nivel clave o ser rechazado en él.", "Ruptura gana por 2 o más (si el nivel es resistencia).", "Rechazo gana por 2 o más (si el nivel es resistencia).",
        f"peso: {e['peso']}", POS if (e["peso"] == "ruptura" and e["arriba"]) or (e["peso"] == "rechazo" and not e["arriba"]) else NEG if e["peso"] != "equilibrado" else NEU)
    add("Distancia al nivel clave", f"{e['dist']:.1f} rangos horarios", f"Cuántas velas típicas separan el precio de la {_nombre_nivel(e)} ({N(e['nivel'])}).", "Menos de 1: el nivel se pondrá a prueba pronto.", "Más de 3: lejos; poco que confirmar a esa hora.",
        "cerca" if e["dist"] < 1 else "lejos" if e["dist"] > 3 else "intermedia", NEU)
    if ah:
        ratio = ah["vol_x"] if d["con_vol"] else ah["rango_x"]
        if ratio is not None:
            add("Actividad a la hora objetivo", f"{ratio:.1f}× el promedio", "Volumen (o rango, si no hay volumen) típico de esa hora frente al promedio horario.", "1.2× o más: hay participantes para sostener una ruptura.", "0.8× o menos: poca actividad, rupturas poco fiables.",
                "alta" if ratio >= 1.2 else "baja" if ratio <= 0.8 else "normal", POS if ratio >= 1.2 else NEG if ratio <= 0.8 else NEU)
    return f


# ------------------------------------------------------------------ escenarios en lenguaje técnico
def escenarios_tecnicos(d):
    r, e, base, zona = d["r"], d["esc"], d["base"], d["zona"]
    b = r["barras"]
    p, S, R = r["precio"], r["soporte"], r["resistencia"]
    atr_abs = p * r["atr"] / 100
    hh = f"{base.hour:02d}:00"
    s = 1 if e["arriba"] else -1
    nivel, nom = e["nivel"], _nombre_nivel(e)
    medio = (R + S) / 2
    tl, (est_signo, est_txt) = tendencia_lineal(b), estructura(b)
    est = []
    est.append({"tono": _tono(est_signo), "titulo": "Estructura de mercado (H1)", "texto": f"Últimas ~60 velas de 1 h: {est_txt}."})
    est.append({"tono": NEU, "titulo": "Soporte y resistencia (48 h)",
                "texto": f"Soporte horizontal en {N(S)} y resistencia horizontal en {N(R)}; el precio ({N(p)}) está al {(p - S) / (R - S) * 100 if R > S else 50:.0f}% del rango. "
                         f"El nivel a vigilar a las {hh} es la {nom} {N(nivel)}, a {e['dist']:.1f} rangos horarios."})
    if tl:
        pend = tl["pend_pct_h"]
        desc = "ascendente" if pend > 0.1 * r["atr"] else "descendente" if pend < -0.1 * r["atr"] else "casi horizontal"
        dentro = "dentro del canal" if tl["inf"] <= p <= tl["sup"] else ("por encima del canal (extensión alcista)" if p > tl["sup"] else "por debajo del canal (extensión bajista)")
        est.append({"tono": _tono(1 if desc == "ascendente" else -1 if desc == "descendente" else 0), "titulo": "Línea de tendencia (regresión lineal de 48 velas H1)",
                    "texto": f"Línea {desc}: pendiente {pend:+.3f}% por hora, R² = {tl['r2']:.2f} ({'tendencia limpia' if tl['r2'] >= 0.6 else 'tendencia ruidosa, poco fiable' if tl['r2'] < 0.3 else 'tendencia moderada'}). "
                             f"Canal de ±2 desviaciones: {N(tl['inf'])} a {N(tl['sup'])}; el precio está {dentro}. Un cierre H1 fuera del canal sería una señal de aceleración o de quiebre de la tendencia."})
    est.append({"tono": _tono(1 if r["ema20"] > r["ema50"] else -1), "titulo": "Soportes y resistencias dinámicos (medias móviles)",
                "texto": f"EMA20 en {N(r['ema20'])} y EMA50 en {N(r['ema50'])}: el precio {'se sostiene sobre' if p > r['ema20'] else 'cotiza bajo'} la EMA20 y {'sobre' if p > r['ema50'] else 'bajo'} la EMA50. "
                         f"En una tendencia {'alcista' if r['ema20'] > r['ema50'] else 'bajista'}, la EMA20 suele actuar como {'soporte' if r['ema20'] > r['ema50'] else 'resistencia'} en los retrocesos."})
    rng = R - S
    est.append({"tono": NEU, "titulo": "Retrocesos de Fibonacci del rango de 48 h",
                "texto": f"38.2% = {N(R - 0.382 * rng)}, 50% = {N(R - 0.5 * rng)}, 61.8% = {N(R - 0.618 * rng)} (medidos desde la resistencia hacia el soporte). Sirven como zonas de reacción intermedias."})
    est.append({"tono": _tono(1 if r["macd"] > 0 else -1), "titulo": "Momentum",
                "texto": f"MACD H1 {r['macd']:+.3f} ({'comprador' if r['macd'] > 0 else 'vendedor'}) y RSI {r['rsi']:.0f} ({'sobrecompra' if r['rsi'] >= 70 else 'sobreventa' if r['rsi'] <= 30 else 'zona neutral'})."})

    ru = POS if s == 1 else NEG
    rc = POS if s == -1 else NEG
    ruptura_lado = "alcista" if s == 1 else "bajista"
    nueva = "soporte" if s == 1 else "resistencia"
    tl_alin = ""
    if tl:
        tl_alin = (" La línea de tendencia está a favor de esta ruptura." if (tl["pend_pct_h"] > 0) == (s == 1) and abs(tl["pend_pct_h"]) > 0.1 * r["atr"]
                   else " La línea de tendencia va en contra: la ruptura tendría que vencer esa pendiente.")
    esc = [
        {"tono": ru, "titulo": f"Escenario A · Ruptura {ruptura_lado} de la {nom} {N(nivel)}",
         "texto": f"Condición: cierre de una vela H1 {'por encima' if s == 1 else 'por debajo'} de {N(nivel)} con {e['umbral']}. Confirmación: retest del nivel roto, que pasa a actuar como {nueva}, "
                  f"sin cierre H1 de vuelta dentro del rango. Objetivo técnico: {N(nivel + s * 1.5 * atr_abs)} (1.5 ATR desde el nivel). Invalidación: cierre H1 de vuelta {'bajo' if s == 1 else 'sobre'} {N(nivel)}.{tl_alin}"},
        {"tono": rc, "titulo": f"Escenario B · Rechazo en la {nom} {N(nivel)} (falsa ruptura)",
         "texto": f"Condición: el precio toca {N(nivel)} (a menos de 0.25 rangos) y la vela H1 cierra {'bajo' if s == 1 else 'sobre'} el nivel, con mecha larga o volumen alto (patrón de rechazo / pin bar). "
                  f"Objetivo técnico: retroceso hacia la mitad del rango, {N(medio)}, y después la zona de Fibonacci 61.8% ({N(R - 0.618 * rng)}). Invalidación: cierre H1 {'sobre' if s == 1 else 'bajo'} {N(nivel)} con volumen."},
        {"tono": NEU, "titulo": f"Escenario C · Rango entre {N(S)} y {N(R)}",
         "texto": f"Condición: ninguna vela H1 cierra fuera de {N(S)} - {N(R)}. El movimiento esperado queda limitado a unos {N(p * (d['ah']['rango'] if d['ah'] else r['atr']) / 100)} en esa hora. Mientras dure, los extremos del rango actúan como soporte y resistencia. "
                  f"Invalidación: cierre H1 fuera del rango con volumen."},
    ]
    zn = zona.key
    cond = [
        [f"Cierre de la vela que rompe {N(nivel)}", "H1", f"Al cierre de la vela {hh}-{base.hour:02d}:59 ({zn}). La mecha por sí sola no cuenta."],
        ["Volumen/rango de la vela ≥ umbral", "H1", e["umbral"]],
        ["Retest del nivel roto, sin cierre de vuelta", "M15 (detalle en M5)", "En las 1 o 2 horas siguientes a la ruptura; se busca que el nivel invertido aguante."],
        ["Rechazo: mecha larga y cierre del lado contrario", "H1 (detalle en M15)", f"En la vela de las {hh} o en la siguiente."],
        ["Línea de tendencia / canal se mantiene", "H1 y H4", "Mientras ningún cierre H1 salga del canal de ±2 desviaciones."],
        ["Contexto de fondo", "D1", f"Tendencia diaria {r.get('diaria') or 'sin dato'}: si contradice el escenario, las probabilidades de que se cumpla son menores."],
    ]
    return {"marco": f"Análisis hecho sobre velas de 1 hora (H1), con contexto diario (D1). Las condiciones se validan al cierre de la vela H1 de las {hh} ({zn}) y se afinan en M15/M5.",
            "estructura": est, "escenarios": esc, "condiciones": cond}


# ------------------------------------------------------------------ noticias
POR_QUE = {"metal": "Los metales reaccionan a tasas, dólar y refugio: noticias de tasas altas o dólar fuerte suelen presionarlos; recortes de tasas, tensión geopolítica o dólar débil los favorecen.",
           "energia": "Dependen de oferta (OPEP, inventarios) y demanda: recortes de producción o caída de inventarios suelen favorecerlos; exceso de oferta o recesión, presionarlos.",
           "cripto": "Reaccionan al apetito de riesgo y a eventos regulatorios o de flujos (ETF): entradas y adopción favorecen; hackeos, demandas o liquidaciones presionan.",
           "divisa": "Un par se mueve por diferencias de tasas y apetito de riesgo; el dólar fuerte presiona EUR/USD y GBP/USD.",
           "accion": "Guías de resultados, recompras o recortes de tasas favorecen; despidos, aranceles o recesión presionan.",
           "indice": "Ganancias empresariales y tasas bajas favorecen; recesión, aranceles o tasas altas presionan."}


def noticias(d, limite=10):
    r, a, zona = d["r"], d["a"], d["zona"]
    out = []
    for x in sorted(r["noticias"], key=lambda x: (-abs(x["impacto"]) * x["fuerza"], x["edad_h"]))[:limite]:
        try:
            from datetime import datetime
            fecha = datetime.fromisoformat(x["fecha"]).astimezone(zona).strftime("%d/%m/%Y %H:%M")
        except Exception:
            fecha = x.get("fecha", "")
        imp = x["impacto"]
        clase = "favorable" if imp > 0 else "adversa" if imp < 0 else "neutral"
        out.append({"titulo": x["titulo"], "fuente": x.get("fuente") or "", "fecha": fecha, "edad_h": round(x["edad_h"], 1),
                    "impacto": imp, "clase": clase, "fuerza": x["fuerza"], "motivo": x.get("motivo") or "",
                    "enlace": x.get("enlace") or "",
                    "explica": (f"Clasificada como {clase} (fuerza {x['fuerza']} de 2)" + (f" por los términos: {x['motivo']}." if x.get("motivo") else ".")
                               + " " + (POR_QUE.get(a["clase"], "") if imp else "No contiene términos que muevan este activo según el clasificador."))})
    return out


def quant_escenarios(d):
    q = d.get("quant")
    if not q or q.get("error") or not q.get("escenarios"):
        return []
    E = quant.E
    out = []
    for f in q["escenarios"]:
        pl = f.get("plan")
        out.append({"tipo": E.TIPOS[f["tipo"]][1], "estado": E.ETIQ[f["estado"]], "nivel": N(f["nivel"]) if f.get("nivel") else "-",
                    "entrada": N(pl["entrada"]) if pl else "-", "stop": N(pl["stop"]) if pl else "-",
                    "objetivos": " / ".join(f"{N(t['nivel'])} ({t['rr']:.1f})" for t in pl["tps"][:2]) if pl and pl.get("tps") else "-",
                    "operable": bool(pl and pl.get("ok"))})
    return out


def panel(d):
    """Todo lo que muestra el panel web (la misma información que el PDF)."""
    return {"items": resumen_items(d), "cifras": cifras(d), "tecnico": escenarios_tecnicos(d), "noticias": noticias(d), "quant_escenarios": quant_escenarios(d)}


# ------------------------------------------------------------------ PDF
class PdfPro(Pdf):
    def bloque(self, titulo, texto, tono, size=8.8):
        col, fondo = BARRA[tono], FONDO[tono]
        ancho = W - 2 * M - 14
        lt = self.envolver(titulo, size + 0.4, ancho, True)
        lc = self.envolver(texto, size, ancho)
        alto = (len(lt) * (size + 0.4) + len(lc) * size) * 1.3 + 10
        self.hueco(alto + 4)
        top = self.y
        self.rect(M, top - alto, W - 2 * M, alto, fill=fondo)
        self.rect(M, top - alto, 4, alto, fill=col)
        yy = top - 4
        for ln in lt:
            yy -= (size + 0.4) * 1.3
            self.texto(M + 10, yy, ln, size + 0.4, True, col)
        for ln in lc:
            yy -= size * 1.3
            self.texto(M + 10, yy, ln, size, False, (0.1, 0.1, 0.1))
        self.y = top - alto - 4


def _col(t):
    return VERDE if t == POS else ROJO if t == NEG else GRIS


def pdf(d):
    a, r, e, base, zona = d["a"], d["r"], d["esc"], d["base"], d["zona"]
    p = PdfPro("TITAN · Hoja informativa. No es consejo financiero ni una predicción. No se guarda nada en las bases de datos.")
    p.rect(0, pdfmini.H - 74, pdfmini.W, 74, fill=AZUL)
    p.texto(pdfmini.M, pdfmini.H - 34, "TITAN · HOJA DE ANÁLISIS", 17, True, (1, 1, 1))
    p.texto(pdfmini.M, pdfmini.H - 54, f"{a['nombre']} ({a['simbolo']})  ·  generado {d['ahora'].astimezone(zona).strftime('%d/%m/%Y %H:%M')} ({zona.key})  ·  hora objetivo {base.hour:02d}:00",
            8.5, False, (0.85, 0.9, 1))
    p.y = pdfmini.H - 74 - 8
    p.seccion("RESUMEN EJECUTIVO")
    p.parrafo("Verde = información a favor del activo · Rojo = información en contra · Gris = neutral.", 8, False, GRIS)
    for it in resumen_items(d):
        p.bloque(it["titulo"], it["texto"], it["tono"])

    p.seccion("CIFRAS CLAVE: QUÉ SIGNIFICA CADA VALOR")
    filas = [["Cifra", "Valor", "Qué significa", "Positivo si...", "Negativo si...", "Lectura hoy"]]
    for c in cifras(d):
        filas.append([(c["cifra"], (0, 0, 0), True), c["valor"], c["significado"], (c["positivo"], VERDE, False), (c["negativo"], ROJO, False), (c["lectura"], _col(c["tono"]), True)])
    p.tabla(filas, [66, 58, 118, 90, 90, 93], size=7.2)
    ser = [x["c"] for x in r["barras"][-48:]]
    p.grafico_lineas(ser, [(r["resistencia"], "Resistencia", ROJO), (r["soporte"], "Soporte", VERDE)], "PRECIO DE LAS ÚLTIMAS 48 HORAS (velas de 1 h)")

    p.seccion("1. LECTURA TÉCNICA")
    sg = lambda v: (f"{v:+d}", VERDE if v > 0 else ROJO if v < 0 else GRIS, True)
    sp, se, sm = agente.sgn(r["precio"] - r["ema20"]), agente.sgn(r["ema20"] - r["ema50"]), agente.sgn(r["macd"])
    p.tabla([["Indicador", "Valor", "Qué significa", "Señal"],
             ["Precio vs EMA20", f"{N(r['precio'])} vs {N(r['ema20'])}", "Sobre la media corta = impulso alcista de corto plazo; bajo ella = presión bajista.", sg(sp)],
             ["EMA20 vs EMA50", f"{N(r['ema20'])} vs {N(r['ema50'])}", "Media corta sobre la larga = tendencia alcista sostenida; debajo = bajista.", sg(se)],
             ["MACD (histograma)", f"{r['macd']:+.3f}", "Positivo = el momentum compra; negativo = el momentum vende.", sg(sm)],
             ["RSI (14)", f"{r['rsi']:.0f}", "Más de 70: sobrecompra (riesgo de corrección). Menos de 30: sobreventa (posible rebote).",
              ("-1" if r["rsi"] > 75 and r["punt_t"] >= 0 else "+1" if r["rsi"] < 25 else "0", GRIS, True)],
             ["Total técnico", f"{r['punt_t']:+d} de ±3", "Suma de las señales anteriores.", sg(r["punt_t"])]],
            [112, 100, 233, 70])

    p.seccion("2. NOTICIAS DE LAS ÚLTIMAS 48 HORAS")
    ns = noticias(d, 10)
    nn = r["noticias"]
    fav, adv = sum(x["impacto"] > 0 for x in nn), sum(x["impacto"] < 0 for x in nn)
    p.parrafo(f"{len(nn)} titulares relevantes: {fav} favorables, {adv} adversos y {len(nn) - fav - adv} neutrales. Puntaje de noticias: {r['punt_n']:+d} de ±2"
              + (" (con menos de 3 titulares relevantes no puntúa)." if r["pocas"] else "."), 9)
    for x in ns:
        tono = POS if x["impacto"] > 0 else NEG if x["impacto"] < 0 else NEU
        p.bloque(f"{x['clase'].upper()} · {x['fuente'][:30]} · {x['fecha']} (hace {x['edad_h']:.0f} h)", x["titulo"] + "\n" + x["explica"], tono, 8.2)
    p.parrafo("Las noticias se clasifican por palabras clave en el titular y el resumen. No entienden el contexto completo: abre y lee la noticia original antes de decidir.", 8, False, GRIS)

    p.seccion("3. CONTEXTO DE MERCADO: POR QUÉ IMPORTA")
    p.parrafo(informe.PORQUE.get(a["clase"], ""), 9)
    if d["ctx"]:
        p.tabla([["Variable", "Cambio 5 días", "Relación con el activo", "Lectura hoy"]] +
                [[c["nombre"], f"{c['cambio']:+.2f}%", "inversa (si ella sube, el activo tiende a bajar)" if c["rel"] < 0 else "directa (si ella sube, el activo tiende a subir)",
                  (c["lectura"], VERDE if c["lectura"].startswith("a favor") else ROJO if c["lectura"].startswith("en contra") else GRIS, True)] for c in d["ctx"]],
                [130, 70, 215, 100])
    quant.seccion_explicacion(p, d)
    quant.seccion_macro(p, d)

    p.seccion("6. ACTIVIDAD Y VOLUMEN POR SESIÓN")
    unidad = "volumen" if d["con_vol"] else "rango"
    clave = "vol_x" if d["con_vol"] else "rango_x"
    fx = lambda x, k: "n/d" if not x or x.get(k) is None else f"{x[k]:.1f}x"
    p.tabla([["Sesión", "Apertura (tu hora)", "Típico apertura", "Última vez", "Cierre (tu hora)", "Típico cierre", "Última vez"]] +
            [[s["nombre"], s["apertura"], fx(s["ap"], clave), fx(s["ap"], "ult_" + clave), s["cierre"], fx(s["ci"], clave), fx(s["ci"], "ult_" + clave)] for s in d["sesiones"]],
            [78, 78, 70, 62, 78, 70, 79])
    p.parrafo(f"Las cifras son veces el {unidad} promedio de una hora (1.0x = normal; 2.0x = el doble). "
              + ("" if d["con_vol"] else "Este mercado no publica volumen fiable, por eso se usa el rango de las velas como medida de actividad. "), 8, False, GRIS)
    ah = d["ah"]
    if ah:
        p.parrafo(f"A las {base.hour:02d}:00 el {unidad} típico es {ah[clave]:.1f} veces el promedio" + (f" (unos {ah['vol']:,.0f} por hora)." if d["con_vol"] else f" (rango medio {ah['rango']:.2f}%)."), 9, True)
    ap_h = {int(s["apertura"][:2]) for s in d["sesiones"]}
    barras = [(f"{h:02d}", (d["act"][h][clave] if h in d["act"] and d["act"][h].get(clave) else 0), NARANJA if h == base.hour else informe.TEAL if h in ap_h else informe.BASE_BARRA) for h in range(24)]
    p.grafico_barras(barras, f"ACTIVIDAD POR HORA ({unidad}, tu zona). Naranja = hora objetivo · Verde azulado = apertura de una sesión")

    p.hueco(300)
    tec = escenarios_tecnicos(d)
    p.seccion("7. ESCENARIOS EN LENGUAJE TÉCNICO")
    p.parrafo(tec["marco"], 9, True)
    p.parrafo("Estructura y niveles", 9.5, True, AZUL, despues=2)
    for x in tec["estructura"]:
        p.bloque(x["titulo"], x["texto"], x["tono"], 8.4)
    p.parrafo("Escenarios", 9.5, True, AZUL, despues=2)
    for x in tec["escenarios"]:
        p.bloque(x["titulo"], x["texto"], x["tono"], 8.4)
    p.parrafo("¿En qué temporalidad debe cumplirse cada condición?", 9.5, True, AZUL, despues=2)
    p.tabla([["Condición", "Temporalidad", "Cuándo se valida"]] + tec["condiciones"], [190, 85, 240], size=7.8)
    col_f = lambda f: (("ruptura", VERDE, True) if f == "ruptura" else ("rechazo", NARANJA, True) if f == "rechazo" else ("neutral", GRIS, False))
    p.tabla([["Señal", "Lectura actual", "Favorece a"]] + [[s[0], s[1], col_f(s[2])] for s in e["senales"]], [120, 285, 110])
    neutrales = len(e["senales"]) - e["ruptura"] - e["rechazo"]
    p.parrafo(f"Resultado: ruptura {e['ruptura']} · rechazo {e['rechazo']} · neutrales {neutrales}. Lectura: {informe._lectura_peso(d)}. Confianza relativa {e['conf']} (es coincidencia de señales, no una probabilidad).", 9, True)

    quant.seccion_escenarios(p, d)

    p.seccion("9. CONCLUSIÓN, FUENTES Y LÍMITES")
    quant.fuentes(p, d)
    p.parrafo(f"• Sesgo general: {guiado.FRASE[r['direccion']]}. Si a esa hora el precio hace lo que describe el escenario de {e['peso'] if e['peso'] != 'equilibrado' else 'ruptura o rechazo'}, la lectura se confirma; si ocurre lo contrario, descártala.", 9)
    p.parrafo("• Esta hoja ordena la información disponible (precio, volumen, noticias, contexto); no conoce órdenes grandes, anuncios que aún no salen ni liquidez real.", 9)
    p.parrafo("• Son hipótesis informativas: no son predicciones ni consejo financiero. Esta hoja web no guarda nada en las bases de datos.", 9)
    return p.construir()
