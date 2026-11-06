# -*- coding: utf-8 -*-
"""Flujo guiado de TITAN: activo -> zona -> hora -> 'Resumen previo'.
Además guarda el pronóstico de esa hora y lo verifica cuando pasa. INFORMATIVO: no es una predicción."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone

import agente

FRASE = {"alcista": "alcista", "ligeramente alcista": "ligeramente alcista pero débil",
         "lateral": "lateral, sin dirección clara", "ligeramente bajista": "ligeramente bajista pero débil",
         "bajista": "bajista"}

def hora_objetivo(zona, hora, ahora=None, proxima=False):
    """Próxima vez que el reloj de esa zona marque `hora`:00 (o la siguiente hora en punto)."""
    ahora_l = (ahora or datetime.now(timezone.utc)).astimezone(zona)
    if proxima:
        return (ahora_l + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    base = ahora_l.replace(hour=hora, minute=0, second=0, microsecond=0)
    return base + timedelta(days=1) if base <= ahora_l else base

def momento(base, ahora):
    h = base.hour
    parte = ("de madrugada" if h < 5 else "por la mañana" if h < 12 else "por la tarde" if h < 19 else "por la noche")
    esta = {"de madrugada": "esta madrugada", "por la mañana": "esta mañana",
            "por la tarde": "esta tarde", "por la noche": "esta noche"}[parte]
    if base.date() > ahora.astimezone(base.tzinfo).date():
        return "mañana " + parte
    return esta

def conectar():
    c = agente.conectar()
    c.execute("""CREATE TABLE IF NOT EXISTS pron_hora(id INTEGER PRIMARY KEY AUTOINCREMENT, simbolo TEXT,
        creado_en TEXT, objetivo_ts INTEGER, zona TEXT, direccion TEXT, total INTEGER, atr_pct REAL,
        precio_ref REAL, abre REAL, cierra REAL, mov_pct REAL, evaluado_en TEXT, resultado TEXT)""")
    return c

def resumen_previo(r, est, zona, base, ahora):
    a = r["activo"]
    if r["error"]:
        return f"⚠️ {a['nombre']} ({a['simbolo']}): {r['error']}."
    h, d, conf = base.hour, r["direccion"], r["confianza"]
    n = r["noticias"]
    fav, adv = sum(x["impacto"] > 0 for x in n), sum(x["impacto"] < 0 for x in n)
    L = [f"🧭 Resumen previo · {a['nombre']} ({a['simbolo']})",
         f"Para {momento(base, ahora)} ({h:02d}:00, {zona.key}): sesgo {FRASE[d]} (confianza {conf}).", ""]
    if "alcista" in d:
        niv = f"Si supera {agente._num(r['resistencia'])} el impulso seguiría; si cierra bajo {agente._num(r['soporte'])} la idea se invalida."
    elif "bajista" in d:
        niv = f"Si pierde {agente._num(r['soporte'])} la caída seguiría; si cierra sobre {agente._num(r['resistencia'])} la idea se invalida."
    else:
        niv = f"Se espera un rango entre {agente._num(r['soporte'])} y {agente._num(r['resistencia'])}."
    L.append(f"• Ahora cotiza {agente._num(r['precio'])}. {niv}")
    e = est.get(h)
    if e:
        pts = r["precio"] * e["rango"] / 100
        if e["sube"] >= 58:
            incl, signo = "con inclinación alcista", 1
        elif e["sube"] <= 42:
            incl, signo = "con inclinación bajista", -1
        else:
            incl, signo = "sin inclinación clara", 0
        s = agente.sgn(r["total"])
        if signo and s:
            conc = "las señales coinciden" if signo == s else "las señales se contradicen: prudencia"
        elif not s:
            conc = "sin sesgo general que confirmar"
        else:
            conc = "la hora no aporta dirección"
        L.append(f"• A las {h:02d}:00 suele moverse ≈{e['rango']:.2f}% (unos {agente._num(pts)} puntos) y ha subido en "
                 f"{e['sube']:.0f}% de los últimos {e['n']} días, {incl}: {conc}.")
    else:
        L.append(f"• A las {h:02d}:00 este mercado suele estar cerrado o hay pocos datos: el pronóstico es solo el sesgo general.")
    L.append(f"• Por qué: técnico {r['punt_t']:+d}, noticias {r['punt_n']:+d} ({len(n)} relevantes: {fav} favorables, {adv} adversas)"
             + (f", tendencia diaria {r['diaria']}." if r.get("diaria") else "."))
    horas = (base - ahora.astimezone(base.tzinfo)).total_seconds() / 3600
    if horas > 12:
        L.append(f"• Faltan {horas:.0f} h: el sesgo puede cambiar antes; consúltalo de nuevo más cerca de la hora.")
    L += [f"• {x}" for x in r["notas"]]
    s = estadisticas_horas(a["simbolo"])
    L.append(f"Acierto de pronósticos por hora en este activo: {s['tasa']:.0f}% (n={s['n']})" if s["n"] >= 5
             else "Aún no hay suficientes pronósticos por hora evaluados para medir el acierto.")
    L.append("⚠️ Hipótesis informativa, no predicción ni consejo financiero.")
    return "\n".join(L)

def pronosticar(a, zona, base, ahora=None):
    """Analiza el activo, guarda el pronóstico de esa hora y devuelve (resultado, texto del resumen)."""
    ahora = ahora or datetime.now(timezone.utc)
    r = agente.analizar(a, zona, ahora)
    if r["error"]:
        return r, resumen_previo(r, {}, zona, base, ahora)
    try:
        est = agente.estacionalidad(agente.barras(a["simbolo"], "1mo", "60m"), zona)
    except Exception:
        est = {}
    c = conectar()
    c.execute("INSERT INTO pron_hora(simbolo,creado_en,objetivo_ts,zona,direccion,total,atr_pct,precio_ref) "
              "VALUES (?,?,?,?,?,?,?,?)",
              (a["simbolo"], ahora.isoformat(), int(base.timestamp()), zona.key, r["direccion"], r["total"],
               r["atr"], r["precio"]))
    c.commit(); c.close()
    return r, resumen_previo(r, est, zona, base, ahora)

def evaluar_horas(ahora=None):
    """Cuando una hora ya pasó, compara lo previsto con lo que hizo la vela de esa hora."""
    ahora = ahora or datetime.now(timezone.utc)
    c = conectar()
    filas = c.execute("SELECT id,simbolo,objetivo_ts,direccion,atr_pct FROM pron_hora WHERE evaluado_en IS NULL").fetchall()
    cache, hechos = {}, 0
    for i, sim, ts, dire, atr in filas:
        if ahora.timestamp() < ts + 3600 + 300:
            continue
        rango = "5d" if ahora.timestamp() - ts < 4 * 86400 else "1mo"
        try:
            if (sim, rango) not in cache:
                cache[(sim, rango)] = agente.barras(sim, rango, "60m")
            vela = next((x for x in cache[(sim, rango)] if ts <= x["t"] < ts + 3600), None)
        except Exception:
            continue
        if vela is None:
            if ahora.timestamp() > ts + 72 * 3600:
                c.execute("UPDATE pron_hora SET evaluado_en=?, resultado='sin_datos' WHERE id=?", (ahora.isoformat(), i))
                hechos += 1
            continue
        mov = (vela["c"] / vela["o"] - 1) * 100
        if abs(mov) < 0.1 * atr:
            res = "neutro"
        elif "alcista" in dire:
            res = "acierto" if mov > 0 else "fallo"
        elif "bajista" in dire:
            res = "acierto" if mov < 0 else "fallo"
        else:
            res = "acierto" if abs(mov) < atr else "fallo"
        c.execute("UPDATE pron_hora SET abre=?, cierra=?, mov_pct=?, evaluado_en=?, resultado=? WHERE id=?",
                  (vela["o"], vela["c"], mov, ahora.isoformat(), res, i))
        hechos += 1
    c.commit(); c.close()
    return hechos

def estadisticas_horas(simbolo=None):
    c = conectar()
    q, p = "SELECT SUM(resultado='acierto'), SUM(resultado='fallo') FROM pron_hora WHERE resultado IN ('acierto','fallo')", ()
    if simbolo:
        q += " AND simbolo=?"; p = (simbolo,)
    ac, fa = c.execute(q, p).fetchone()
    pend = c.execute("SELECT COUNT(*) FROM pron_hora WHERE evaluado_en IS NULL").fetchone()[0]
    c.close()
    ac, fa = ac or 0, fa or 0
    n = ac + fa
    return {"n": n, "aciertos": ac, "tasa": ac / n * 100 if n else 0.0, "pendientes": pend}

def texto_precision_horas():
    s = estadisticas_horas()
    if not s["n"]:
        return f"⏱ Pronósticos por hora: ninguno evaluado todavía (pendientes: {s['pendientes']})."
    return (f"⏱ Pronósticos por hora: {s['tasa']:.0f}% de acierto en {s['n']} (pendientes: {s['pendientes']}). "
            "Con pocos datos no es concluyente; el azar daría ~50%.")
