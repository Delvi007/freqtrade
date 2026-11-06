# -*- coding: utf-8 -*-
"""Planes de entrada (scalping, intradía, swing) con seguimiento automático.

- Analiza el activo con datos de Yahoo Finance (solo lectura) y propone un plan: dirección, entrada,
  stop, objetivos, hora límite y condiciones («entra si», «no entres si»).
- Cada plan accionable se guarda en titan_planes.db (archivo NUEVO; no toca titan_activos.db ni titan_integral.db).
- Un vigilante en segundo plano comprueba cada 15 s, con velas reales, si el plan se activó, tocó el stop
  o los objetivos, y guarda el resultado. Si la API estuvo apagada, al volver reconstruye lo ocurrido con las
  velas disponibles (Yahoo limita el historial de velas cortas).
- NO conecta brokers ni envía órdenes. Son hipótesis informativas, no predicciones ni consejo financiero.
"""
import json, sqlite3, threading, time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import agente
import chart_web

DB = Path(__file__).resolve().parent / "titan_planes.db"
_DBLOCK = threading.Lock()
_VIG = {"hilo": None, "ultimo": None, "error": None}
PERIODO_VIGILANTE = 15

# modo -> parámetros. trig/ctx: temporalidades de gatillo y de contexto; eval: velas con que se verifica.
MODOS = {
    "scalping":    {"nombre": "Scalping", "trig": "5m", "ctx": "15m", "eval": ("1m", "1m"), "niv": 24, "ventana_s": 15 * 60, "dur_s": 30 * 60, "r": (1.0, 2.0), "vela_s": 300,
                    "dur_txt": "hasta 15 min para entrar y 30 min de operación"},
    "intradia":    {"nombre": "Intradía", "trig": "15m", "ctx": "1h", "eval": ("5m", "5m"), "niv": 32, "ventana_s": 4 * 3600, "dur_s": 12 * 3600, "r": (1.5, 2.5), "vela_s": 900,
                    "dur_txt": "hasta 4 h para entrar y 12 h de operación"},
    "swing_corto": {"nombre": "Swing corto plazo", "trig": "4h", "ctx": "1d", "eval": ("1h", "60m"), "niv": 30, "ventana_s": 2 * 86400, "dur_s": 10 * 86400, "r": (2.0, 3.0), "vela_s": 4 * 3600,
                    "dur_txt": "hasta 2 días para entrar y 10 días de operación"},
    "swing_medio": {"nombre": "Swing mediano plazo", "trig": "1d", "ctx": "1w", "eval": ("1h", "60m"), "niv": 30, "ventana_s": 7 * 86400, "dur_s": 56 * 86400, "r": (2.0, 3.0), "vela_s": 86400,
                    "dur_txt": "hasta 7 días para entrar y 8 semanas de operación"},
    "swing_largo": {"nombre": "Swing largo plazo", "trig": "1w", "ctx": "1mo", "eval": ("1d", "1d"), "niv": 26, "ventana_s": 21 * 86400, "dur_s": 180 * 86400, "r": (2.0, 3.5), "vela_s": 7 * 86400,
                    "dur_txt": "hasta 3 semanas para entrar y 6 meses de operación"},
}
TF_TXT = {"1m": "M1", "5m": "M5", "15m": "M15", "30m": "M30", "1h": "H1", "4h": "H4", "1d": "D1", "1w": "W1", "1mo": "MN"}


# ----------------------------------------------------------------------------- base de datos
def _con():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    c.executescript("""
    CREATE TABLE IF NOT EXISTS planes(
        id INTEGER PRIMARY KEY AUTOINCREMENT, creado_ts INTEGER, simbolo TEXT, mostrar TEXT, fuente TEXT, modo TEXT,
        direccion INTEGER, tipo TEXT, entrada REAL, stop REAL, tp1 REAL, tp2 REAL, r1 REAL, r2 REAL, atr REAL,
        valido_hasta INTEGER, max_dur_s INTEGER, eval_tf TEXT, eval_int TEXT,
        estado TEXT, resultado TEXT, activada_ts INTEGER, cerrada_ts INTEGER, r_final REAL, mfe_r REAL, mae_r REAL,
        precio_ult REAL, eventos TEXT, detalle TEXT, actualizado_ts INTEGER);
    """)
    return c


def _fila(r):
    d = dict(r)
    d["eventos"] = json.loads(d.get("eventos") or "[]")
    d["detalle"] = json.loads(d.get("detalle") or "{}")
    return d


# ----------------------------------------------------------------------------- indicadores
def _atr(v, n=14):
    tr = []
    for i in range(1, len(v)):
        tr.append(max(v[i][2] - v[i][3], abs(v[i][2] - v[i - 1][4]), abs(v[i][3] - v[i - 1][4])))
    tr = tr[-n:]
    return sum(tr) / len(tr)


def _sgn(x):
    return (x > 0) - (x < 0)


def _lectura(v):
    c = [x[4] for x in v]
    if len(c) < 60:
        raise ValueError("Pocas velas para analizar (" + str(len(c)) + ").")
    e9, e21, e20, e50 = (agente.ema(c, n)[-1] for n in (9, 21, 20, 50))
    rs, mh = agente.rsi(c, 14), agente.macd_hist(c)
    return {"c": c[-1], "e9": e9, "e21": e21, "e20": e20, "e50": e50, "rsi": rs, "macd": mh, "atr": _atr(v)}


def _score_ctx(L):
    return _sgn(L["e20"] - L["e50"]) + _sgn(L["c"] - L["e50"]) + _sgn(L["macd"])


def _score_trg(L):
    s = _sgn(L["e9"] - L["e21"]) + _sgn(L["c"] - L["e21"]) + _sgn(L["macd"])
    s += 1 if (L["rsi"] >= 55 and L["rsi"] < 78) else -1 if (L["rsi"] <= 45 and L["rsi"] > 22) else 0
    if L["rsi"] >= 78:
        s -= 1
    elif L["rsi"] <= 22:
        s += 1
    return s


def _n(x):
    return agente._num(x)


def _hora(ts, zona):
    return datetime.fromtimestamp(ts, timezone.utc).astimezone(zona).strftime("%d/%m %H:%M")


# ----------------------------------------------------------------------------- análisis y creación
def analizar(activo, modo, zona, ahora_ts=None):
    if modo not in MODOS:
        raise ValueError("Modo no válido.")
    P = MODOS[modo]
    ahora_ts = ahora_ts or int(time.time())
    gt = chart_web.grafico(activo, P["trig"])
    gc = chart_web.grafico(activo, P["ctx"])
    vt, vc = gt["velas"], gc["velas"]
    Lt, Lc = _lectura(vt), _lectura(vc)
    precio = gt["precio"] or vt[-1][4]
    atr, N = Lt["atr"], P["niv"]
    st_, sc_ = _score_trg(Lt), _score_ctx(Lc)
    total = st_ + sc_
    prev = vt[-N - 1:-1]                                   # velas anteriores a la actual
    alto, bajo = max(x[2] for x in prev), min(x[3] for x in prev)
    k = max(5, N // 4)
    min_loc, max_loc = min(x[3] for x in vt[-k:]), max(x[2] for x in vt[-k:])
    razones = [
        f"Contexto {TF_TXT[P['ctx']]}: puntuación {sc_:+d} de ±3 (EMA20 {'>' if Lc['e20'] > Lc['e50'] else '<'} EMA50, precio {'sobre' if Lc['c'] > Lc['e50'] else 'bajo'} EMA50, MACD {'+' if Lc['macd'] > 0 else '-'}).",
        f"Gatillo {TF_TXT[P['trig']]}: puntuación {st_:+d} de ±4 (EMA9 {'>' if Lt['e9'] > Lt['e21'] else '<'} EMA21, RSI {Lt['rsi']:.0f}, MACD {'+' if Lt['macd'] > 0 else '-'}).",
        f"Rango {TF_TXT[P['trig']]} de las últimas {N} velas: máximo {_n(alto)}, mínimo {_n(bajo)}; ATR {TF_TXT[P['trig']]} = {_n(atr)}.",
    ]
    base = {"modo": modo, "nombre": P["nombre"], "simbolo": activo["simbolo"], "mostrar": gt["mostrar"], "fuente": gt["fuente"], "precio": precio,
            "creado_ts": ahora_ts, "creado": _hora(ahora_ts, zona), "zona": zona.key, "atr": atr, "razones": razones, "duracion": P["dur_txt"],
            "trig": P["trig"], "ctx": P["ctx"], "puntos": {"contexto": sc_, "gatillo": st_, "total": total}}
    prox = ahora_ts - ahora_ts % P["vela_s"] + P["vela_s"] if P["vela_s"] <= 86400 else ahora_ts
    base["proxima_vela"] = _hora(prox, zona) if P["vela_s"] <= 86400 else "cierre de la próxima vela " + TF_TXT[P["trig"]]

    d = 1 if (sc_ >= 1 and st_ >= 2 and total >= 3) else -1 if (sc_ <= -1 and st_ <= -2 and total <= -3) else 0
    if d == 0:
        base.update(accion="esperar", direccion=0, tono="neu",
                    titulo="Sin entrada clara por ahora",
                    resumen=("El contexto y el gatillo no coinciden con suficiente fuerza (se piden contexto y gatillo en el mismo sentido y un total de ±3 o más). "
                             "Entrar así sería operar sin ventaja."),
                    vigilar=[f"Compra: gatillo si una vela {TF_TXT[P['trig']]} cierra sobre {_n(alto)}.", f"Venta: gatillo si cierra bajo {_n(bajo)}."],
                    guardado=False)
        return base

    ext = abs(Lt["c"] - Lt["e9"]) / atr if atr else 0
    if d == 1:
        if precio <= alto and (alto - precio) <= 2 * atr and ext <= 1.5:
            tipo, entrada, nivel = "ruptura", alto + 0.1 * atr, alto
        else:
            ref = max(alto, Lt["e9"])
            entrada = ref if ref < precio else precio - 0.5 * atr
            tipo, nivel = "retroceso", ref
        stop = min(min_loc, entrada - 1.0 * atr) - 0.25 * atr
        riesgo = entrada - stop
        if riesgo > 3 * atr:
            stop, riesgo = entrada - 3 * atr, 3 * atr
    else:
        if precio >= bajo and (precio - bajo) <= 2 * atr and ext <= 1.5:
            tipo, entrada, nivel = "ruptura", bajo - 0.1 * atr, bajo
        else:
            ref = min(bajo, Lt["e9"])
            entrada = ref if ref > precio else precio + 0.5 * atr
            tipo, nivel = "retroceso", ref
        stop = max(max_loc, entrada + 1.0 * atr) + 0.25 * atr
        riesgo = stop - entrada
        if riesgo > 3 * atr:
            stop, riesgo = entrada + 3 * atr, 3 * atr
    r1, r2 = P["r"]
    tp1, tp2 = entrada + d * r1 * riesgo, entrada + d * r2 * riesgo
    valido = ahora_ts + P["ventana_s"]
    lado = "COMPRA" if d == 1 else "VENTA"
    cond_signo = "por encima de" if d == 1 else "por debajo de"
    avisos = []
    ext_ctx = max(x[2] for x in vc[-20:]) if d == 1 else min(x[3] for x in vc[-20:])
    if (d == 1 and tp1 > ext_ctx) or (d == -1 and tp1 < ext_ctx):
        avisos.append(f"El objetivo 1 ({_n(tp1)}) queda más allá del {'máximo' if d == 1 else 'mínimo'} reciente del contexto ({_n(ext_ctx)}): puede costar llegar.")
    if abs(precio - entrada) > 2 * atr:
        avisos.append("La entrada está a más de 2 ATR del precio: es una espera larga.")
    if (Lt["rsi"] >= 70 and d == 1) or (Lt["rsi"] <= 30 and d == -1):
        avisos.append(f"RSI {Lt['rsi']:.0f}: el movimiento ya está extendido; mayor riesgo de agotamiento.")
    entra = ([f"El precio cruza {_n(entrada)} {'al alza' if d == 1 else 'a la baja'} (ideal: una vela {TF_TXT[P['trig']]} que cierre {cond_signo} {_n(nivel)} con fuerza), antes de las {_hora(valido, zona)}."]
             if tipo == "ruptura" else
             [f"El precio retrocede hasta {_n(entrada)} (zona de {'soporte' if d == 1 else 'resistencia'}: {'EMA9 / nivel roto' if d == 1 else 'EMA9 / nivel roto'}) y se sostiene, antes de las {_hora(valido, zona)}."])
    no_entres = [f"Si el precio toca {_n(stop)} antes de activar la entrada: el plan queda invalidado.",
                 f"Si pasa de las {_hora(valido, zona)} sin activarse: el plan expira.",
                 f"Si el contexto {TF_TXT[P['ctx']]} cambia de sentido (EMA20/EMA50 y MACD) antes de entrar: descártalo (esto no se vigila solo)."]
    base.update(accion="compra" if d == 1 else "venta", direccion=d, tono="pos" if d == 1 else "neg", titulo=f"Plan de {lado} ({P['nombre']})", tipo=tipo,
                entrada=entrada, stop=stop, tp1=tp1, tp2=tp2, r1=r1, r2=r2, riesgo=riesgo, valido_hasta=valido, valido=_hora(valido, zona),
                entra_si=entra, no_entres_si=no_entres, avisos=avisos, guardado=False,
                resumen=(f"{lado} {'con ruptura' if tipo == 'ruptura' else 'en retroceso'}: entrada {_n(entrada)}, stop {_n(stop)}, objetivo 1 {_n(tp1)} (R/R {r1:.1f}) y objetivo 2 {_n(tp2)} (R/R {r2:.1f}). "
                         f"En el objetivo 1 se cierra la mitad y el stop pasa a la entrada; el resto va al objetivo 2. Duración: {P['dur_txt']}."))
    return base


def crear(simbolo, modo, zona_nombre="America/Santo_Domingo", personalizados=()):
    import re, activos
    s = str(simbolo or "").strip().upper()
    a = activos.buscar(s, list(personalizados))
    if a is None:
        if not re.fullmatch(r"[A-Z0-9.^=\-]{1,15}", s):
            raise ValueError("Símbolo no válido.")
        a = activos.personalizado(s)
    try:
        zona = ZoneInfo(zona_nombre)
    except Exception:
        zona = ZoneInfo("America/Santo_Domingo")
    plan = analizar(a, modo, zona)
    if plan["accion"] != "esperar":
        P = MODOS[modo]
        ev = [{"t": plan["creado_ts"], "texto": "Plan creado (precio " + _n(plan["precio"]) + ")"}]
        with _DBLOCK:
            c = _con()
            cur = c.execute("""INSERT INTO planes(creado_ts,simbolo,mostrar,fuente,modo,direccion,tipo,entrada,stop,tp1,tp2,r1,r2,atr,valido_hasta,max_dur_s,eval_tf,eval_int,
                               estado,eventos,detalle,precio_ult,actualizado_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (plan["creado_ts"], plan["simbolo"], plan["mostrar"], plan["fuente"], modo, plan["direccion"], plan["tipo"], plan["entrada"], plan["stop"], plan["tp1"], plan["tp2"],
                             plan["r1"], plan["r2"], plan["atr"], plan["valido_hasta"], P["dur_s"], P["eval"][0], P["eval"][1], "pendiente", json.dumps(ev),
                             json.dumps({"razones": plan["razones"], "entra_si": plan["entra_si"], "no_entres_si": plan["no_entres_si"], "avisos": plan["avisos"], "resumen": plan["resumen"],
                                         "puntos": plan["puntos"], "zona": zona.key}), plan["precio"], int(time.time())))
            plan["id"] = cur.lastrowid
            c.commit(); c.close()
        plan["guardado"] = True
        iniciar_vigilante()
    return plan


# ----------------------------------------------------------------------------- simulación / verificación
def simular(p, velas, ahora_ts):
    """Reproduce, con velas reales posteriores a la creación, qué le pasó al plan.
    Regla conservadora: si en una misma vela caben el stop y un objetivo, se asume que primero tocó el stop."""
    d, ent, stop, tp1, tp2, r1, r2 = p["direccion"], p["entrada"], p["stop"], p["tp1"], p["tp2"], p["r1"], p["r2"]
    riesgo = abs(ent - stop) or 1e-9
    est, res, act_ts, cierre_ts, rfin = "pendiente", None, None, None, None
    tp1_hit, fill, mfe, mae = False, ent, 0.0, 0.0
    ev = [{"t": p["creado_ts"], "texto": "Plan creado"}]
    ult = p.get("precio_ult")
    r_de = lambda px: (px - fill) * d / riesgo

    def cerrar(t, resultado, r, texto):
        nonlocal est, res, cierre_ts, rfin
        est, res, cierre_ts, rfin = "cerrada", resultado, t, r
        ev.append({"t": t, "texto": texto})

    for t, o, h, l, c, *_ in sorted(velas):
        if t < p["creado_ts"]:
            continue
        ult = c
        if est == "pendiente":
            if t >= p["valido_hasta"]:
                cerrar(p["valido_hasta"], "expirada_sin_entrada", 0.0, "Venció la ventana sin que el precio llegara a la entrada")
                break
            if p["tipo"] == "ruptura":
                activ = (h >= ent) if d == 1 else (l <= ent)
                fill = (max(ent, o) if d == 1 else min(ent, o)) if activ else ent
            else:
                activ = (l <= ent) if d == 1 else (h >= ent)
                fill = ent
            if activ:
                est, act_ts = "activa", t
                ev.append({"t": t, "texto": "Entrada activada en " + _n(fill)})
            elif (d == 1 and l <= stop) or (d == -1 and h >= stop):
                cerrar(t, "invalidada", 0.0, "El precio tocó el stop antes de activar la entrada: plan invalidado")
                break
        if est == "activa":
            mfe = max(mfe, ((h if d == 1 else -l) - (fill if d == 1 else -fill)) / riesgo)
            mae = min(mae, ((l if d == 1 else -h) - (fill if d == 1 else -fill)) / riesgo)
            stop_ef = ent if tp1_hit else stop
            tocó_stop = (l <= stop_ef) if d == 1 else (h >= stop_ef)
            if tocó_stop:
                if tp1_hit:
                    cerrar(t, "tp1_be", 0.5 * r1, "Stop en la entrada tras el objetivo 1: se asegura la mitad del beneficio")
                else:
                    cerrar(t, "stop", -1.0, "Stop alcanzado")
                break
            if (h >= tp2) if d == 1 else (l <= tp2):
                cerrar(t, "tp2", 0.5 * r1 + 0.5 * r2, "Objetivo 2 alcanzado")
                break
            if not tp1_hit and ((h >= tp1) if d == 1 else (l <= tp1)):
                tp1_hit = True
                ev.append({"t": t, "texto": "Objetivo 1 alcanzado: cerrar la mitad y mover el stop a la entrada"})
                if (l <= ent) if d == 1 else (h >= ent):
                    cerrar(t, "tp1_be", 0.5 * r1, "Tras el objetivo 1 el precio volvió a la entrada: se asegura la mitad del beneficio")
                    break
            if t - act_ts >= p["max_dur_s"]:
                rm = r_de(o)
                cerrar(t, "tiempo_agotado", (0.5 * r1 + 0.5 * rm) if tp1_hit else rm, "Se agotó el tiempo máximo de operación: cierre al precio de ese momento")
                break
    if est == "pendiente" and ahora_ts >= p["valido_hasta"]:
        cerrar(p["valido_hasta"], "expirada_sin_entrada", 0.0, "Venció la ventana sin que el precio llegara a la entrada")
    if est == "activa" and ahora_ts - act_ts >= p["max_dur_s"]:
        rm = r_de(ult if ult is not None else fill)
        cerrar(act_ts + p["max_dur_s"], "tiempo_agotado", (0.5 * r1 + 0.5 * rm) if tp1_hit else rm, "Se agotó el tiempo máximo de operación: cierre al último precio")
    r_flot = None
    if est == "activa" and ult is not None:
        r_flot = (0.5 * r1 + 0.5 * r_de(ult)) if tp1_hit else r_de(ult)
    return {"estado": est if est != "activa" else ("activa_tp1" if tp1_hit else "activa"), "resultado": res, "activada_ts": act_ts, "cerrada_ts": cierre_ts,
            "r_final": rfin, "r_flotante": r_flot, "mfe_r": mfe, "mae_r": mae, "precio_ult": ult, "eventos": ev}


def _rango_eval(tf_int, edad_s):
    d = edad_s / 86400
    if tf_int == "1m":
        return "1d" if d < 0.9 else "7d"
    if tf_int == "5m":
        return "5d" if d < 4.5 else "60d"
    if tf_int == "60m":
        return "1mo" if d < 25 else "730d"
    return "1y" if d < 300 else "max"


_CACHE_V = {}


def _velas_eval(fuente, intervalo, rango):
    clave = (fuente, intervalo, rango)
    hit = _CACHE_V.get(clave)
    if hit and time.time() - hit[0] < 8:
        return hit[1]
    v, _meta = chart_web._pedir(fuente, rango, intervalo)
    _CACHE_V[clave] = (time.time(), v)
    return v


def evaluar_abiertos():
    with _DBLOCK:
        c = _con()
        filas = [_fila(r) for r in c.execute("SELECT * FROM planes WHERE estado IN ('pendiente','activa','activa_tp1')").fetchall()]
        c.close()
    ahora = int(time.time())
    for p in filas:
        try:
            rango = _rango_eval(p["eval_int"], ahora - p["creado_ts"])
            velas = _velas_eval(p["fuente"], p["eval_int"], rango)
            s = simular(p, velas, ahora)
        except Exception as e:
            _VIG["error"] = type(e).__name__
            continue
        with _DBLOCK:
            c = _con()
            c.execute("""UPDATE planes SET estado=?, resultado=?, activada_ts=?, cerrada_ts=?, r_final=?, mfe_r=?, mae_r=?, precio_ult=?, eventos=?, actualizado_ts=? WHERE id=?""",
                      (s["estado"], s["resultado"], s["activada_ts"], s["cerrada_ts"], s["r_final"], s["mfe_r"], s["mae_r"], s["precio_ult"], json.dumps(s["eventos"]), ahora, p["id"]))
            c.commit(); c.close()
    _VIG["ultimo"] = ahora


def _bucle():
    while True:
        try:
            evaluar_abiertos()
        except Exception as e:
            _VIG["error"] = type(e).__name__
        time.sleep(PERIODO_VIGILANTE)


def iniciar_vigilante():
    h = _VIG["hilo"]
    if h and h.is_alive():
        return
    t = threading.Thread(target=_bucle, name="titan-vigilante-planes", daemon=True)
    t.start()
    _VIG["hilo"] = t


# ----------------------------------------------------------------------------- consulta
def cancelar(pid):
    pid = int(pid)
    with _DBLOCK:
        c = _con()
        r = c.execute("SELECT estado FROM planes WHERE id=?", (pid,)).fetchone()
        if not r:
            c.close()
            raise ValueError("Plan no encontrado.")
        if r["estado"] not in ("pendiente", "activa", "activa_tp1"):
            c.close()
            return {"cancelado": False, "motivo": "El plan ya estaba cerrado."}
        ev = json.loads(c.execute("SELECT eventos FROM planes WHERE id=?", (pid,)).fetchone()["eventos"] or "[]")
        ev.append({"t": int(time.time()), "texto": "Plan cancelado por el usuario"})
        c.execute("UPDATE planes SET estado='cerrada', resultado='cancelado', cerrada_ts=?, eventos=? WHERE id=?", (int(time.time()), json.dumps(ev), pid))
        c.commit(); c.close()
    return {"cancelado": True}


def eliminar_cancelados(pid=None):
    """Borra de titan_planes.db los planes que el usuario canceló (todos, o solo el indicado)."""
    with _DBLOCK:
        c = _con()
        if pid is not None:
            cur = c.execute("DELETE FROM planes WHERE id=? AND resultado='cancelado'", (int(pid),))
        else:
            cur = c.execute("DELETE FROM planes WHERE resultado='cancelado'")
        n = cur.rowcount
        c.commit(); c.close()
    return {"eliminados": n}


def estadisticas():
    with _DBLOCK:
        c = _con()
        filas = [dict(r) for r in c.execute("SELECT modo, resultado, r_final FROM planes WHERE estado='cerrada' AND resultado IN ('stop','tp1_be','tp2','tiempo_agotado')").fetchall()]
        c.close()
    out = {}
    for f in filas:
        m = out.setdefault(f["modo"], {"n": 0, "ganadoras": 0, "perdedoras": 0, "neutras": 0, "suma_r": 0.0})
        m["n"] += 1
        r = f["r_final"] or 0.0
        m["suma_r"] += r
        m["ganadoras" if r > 0.05 else "perdedoras" if r < -0.05 else "neutras"] += 1
    for m in out.values():
        m["r_medio"] = round(m["suma_r"] / m["n"], 2) if m["n"] else 0.0
        m["acierto_pct"] = round(100 * m["ganadoras"] / m["n"], 0) if m["n"] else None
        m["suma_r"] = round(m["suma_r"], 2)
    return out


def listar(simbolo="", limite=20, zona_nombre="America/Santo_Domingo"):
    iniciar_vigilante()
    limite = max(1, min(int(limite), 60))
    with _DBLOCK:
        c = _con()
        if simbolo:
            filas = c.execute("SELECT * FROM planes WHERE simbolo=? ORDER BY id DESC LIMIT ?", (simbolo.upper(), limite)).fetchall()
        else:
            filas = c.execute("SELECT * FROM planes ORDER BY id DESC LIMIT ?", (limite,)).fetchall()
        c.close()
    try:
        zona = ZoneInfo(zona_nombre)
    except Exception:
        zona = ZoneInfo("America/Santo_Domingo")
    out = []
    for r in filas:
        p = _fila(r)
        p["nombre_modo"] = MODOS.get(p["modo"], {}).get("nombre", p["modo"])
        p["creado"] = _hora(p["creado_ts"], zona)
        p["valido"] = _hora(p["valido_hasta"], zona)
        p["abierto"] = p["estado"] in ("pendiente", "activa", "activa_tp1")
        for e in p["eventos"]:
            e["hora"] = _hora(e["t"], zona)
        out.append(p)
    return {"planes": out, "stats": estadisticas(),
            "vigilante": {"activo": bool(_VIG["hilo"] and _VIG["hilo"].is_alive()), "ultimo_ts": _VIG["ultimo"], "error": _VIG["error"], "periodo_s": PERIODO_VIGILANTE}}
