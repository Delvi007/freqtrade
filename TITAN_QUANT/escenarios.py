# -*- coding: utf-8 -*-
"""Motor de escenarios de TITAN QUANT: escenarios estructurados con stop-loss y take-profit condicionales,
riesgo y tamaño de posición, máquina de estados, registro y estadísticas. INFORMATIVO: no ejecuta órdenes."""
from __future__ import annotations
import hashlib, json, math
from datetime import datetime, timedelta, timezone

import agente

N = agente._num
VERSION = "quant-1.0"
UMBRAL_VOL = 1.2
RIESGO_MAX_PCT = 5.0
FINALES = ("invalidado", "objetivo_alcanzado", "stop_alcanzado", "expirado", "cancelado")
RANGO = {"preparado": 0, "proximo": 1, "activado_provisional": 2, "confirmado": 3}
ETIQ = {"preparado": "Preparado", "proximo": "Próximo a activarse", "activado_provisional": "Activado provisionalmente",
        "confirmado": "Confirmado", "invalidado": "Invalidado", "objetivo_alcanzado": "Objetivo alcanzado",
        "stop_alcanzado": "Stop-loss alcanzado", "expirado": "Expirado", "cancelado": "Cancelado"}
TIPOS = {"ruptura_alcista": ("alcista", "Ruptura alcista"), "ruptura_bajista": ("bajista", "Ruptura bajista"),
         "rechazo_resistencia": ("bajista", "Rechazo de resistencia"), "rebote_soporte": ("alcista", "Rebote en soporte"),
         "lateral": ("lateral", "Mercado lateral")}
COSTES = {"divisa": 0.01, "metal": 0.02, "energia": 0.03, "indice": 0.02, "accion": 0.05, "cripto": 0.10}  # % por lado (supuesto)
MULT = {"GC=F": 100, "SI=F": 5000, "CL=F": 1000, "NG=F": 10000, "ES=F": 50, "NQ=F": 20}

def rank(estado):
    return RANGO.get(estado, 4)

def _ts(iso):
    return datetime.fromisoformat(iso).timestamp()

# ------------------------------------------------------------ base de datos
def conectar():
    c = agente.conectar()
    c.row_factory = __import__("sqlite3").Row
    c.executescript("""
    CREATE TABLE IF NOT EXISTS escenarios(id TEXT PRIMARY KEY, simbolo TEXT, tipo TEXT, direccion TEXT, creado_en TEXT,
        precio_ref REAL, nivel REAL, entrada REAL, stop REAL, tp1 REAL, tp2 REAL, tp3 REAL, atr REAL, costes_pct REAL,
        expira_en TEXT, estado TEXT, motivo TEXT, actualizado_en TEXT, confirmado_en TEXT, cerrado_en TEXT,
        max_fav REAL DEFAULT 0, max_adv REAL DEFAULT 0, resultado_r REAL, version TEXT, indicadores TEXT);
    CREATE TABLE IF NOT EXISTS eventos_escenario(id INTEGER PRIMARY KEY AUTOINCREMENT, escenario_id TEXT, ts TEXT,
        estado_ant TEXT, estado_nuevo TEXT, precio REAL, motivo TEXT);
    CREATE TABLE IF NOT EXISTS kv(clave TEXT PRIMARY KEY, valor TEXT, ts TEXT);
    """)
    return c

def kv_get(c, clave, defecto=None):
    f = c.execute("SELECT valor FROM kv WHERE clave=?", (clave,)).fetchone()
    return f[0] if f else defecto

def kv_set(c, clave, valor):
    c.execute("INSERT OR REPLACE INTO kv VALUES (?,?,?)", (clave, str(valor), datetime.now(timezone.utc).isoformat()))
    c.commit()

def config_riesgo(c):
    cap = kv_get(c, "capital")
    return (float(cap) if cap else None), float(kv_get(c, "riesgo_pct", "1.0"))

def guardar_config_riesgo(c, capital, pct):
    if capital <= 0 or pct <= 0:
        raise ValueError("El capital y el riesgo deben ser positivos.")
    if pct > RIESGO_MAX_PCT:
        raise ValueError(f"El riesgo por operación no puede superar {RIESGO_MAX_PCT:.0f}% del capital.")
    kv_set(c, "capital", capital)
    kv_set(c, "riesgo_pct", pct)

# ------------------------------------------------------------ datos de mercado
def cerradas(b, ahora):
    return [x for x in b if x["t"] + 3600 <= ahora.timestamp()]

def atr_precio(b, n=14):
    u = b[-n:]
    return sum(x["h"] - x["l"] for x in u) / len(u)

def vol_tipico(b):
    """Volumen medio por hora UTC; None si el volumen no es fiable (p. ej. divisas)."""
    vols = [x.get("v", 0) or 0 for x in b]
    if not b or sum(v > 0 for v in vols) < 0.5 * len(vols):
        return None
    g = {}
    for x in b:
        g.setdefault((x["t"] // 3600) % 24, []).append(x.get("v", 0) or 0)
    return {h: sum(v) / len(v) for h, v in g.items() if len(v) >= 8}

# ------------------------------------------------------------ plan: stop, take-profit, riesgo, tamaño
def valor_por_unidad(a, entrada):
    s = a["simbolo"]
    if s in MULT:
        return MULT[s], "contratos"
    if a["clase"] == "divisa":
        return (1.0 if s.endswith("USD=X") else 1.0 / entrada), "unidades de la divisa base"
    if s.endswith("=F"):
        return None, "contratos"
    return 1.0, "unidades"

def _plan(a, entrada, stop, s, cands, atr, capital, riesgo_pct, nivel=None, tarde_max=1.5):
    p = {"entrada": entrada, "stop": stop, "sentido": s, "ok": True, "avisos": [], "tps": [], "intermedios": [], "tamano": None}
    riesgo = abs(entrada - stop)
    costes = entrada * COSTES.get(a["clase"], 0.05) / 100 * 2
    p["costes"], p["riesgo"] = costes, riesgo
    if riesgo > 3 * atr:
        p["ok"] = False; p["avisos"].append("Stop demasiado amplio (más de 3 ATR): no operar este escenario.")
    if riesgo < 0.3 * atr:
        p["ok"] = False; p["avisos"].append("Stop demasiado ajustado (menos de 0.3 ATR): saltaría por el ruido normal.")
    if nivel is not None and abs(entrada - nivel) > tarde_max * atr:
        p["ok"] = False; p["avisos"].append("La entrada llega tarde (más de 1.5 ATR del nivel): el riesgo/beneficio ya no es aceptable.")
    vistos = set()
    for x, fund in sorted(cands, key=lambda c: abs(c[0] - entrada)):
        d = (x - entrada) * s
        if d <= 0.5 * atr or round(x, 6) in vistos:
            continue
        vistos.add(round(x, 6))
        rr = (d - costes) / (riesgo + costes)
        if rr >= 1.0 and len(p["tps"]) < 3:
            p["tps"].append({"nivel": x, "fundamento": fund, "rr": rr})
        elif rr < 1.0:
            p["intermedios"].append((x, fund))
    if not p["tps"]:
        p["ok"] = False; p["avisos"].append("No hay recorrido técnico suficiente (ningún objetivo con relación riesgo/beneficio de 1 o más).")
    if capital:
        if riesgo_pct > RIESGO_MAX_PCT:
            p["ok"] = False; p["avisos"].append("El riesgo configurado supera el límite permitido.")
        vu, unidad = valor_por_unidad(a, entrada)
        dinero = capital * riesgo_pct / 100
        if vu is None:
            p["avisos"].append("No se conoce el valor del punto de este contrato: no se calcula el tamaño.")
        else:
            perdida = (riesgo + costes) * vu
            tam = dinero / perdida if perdida > 0 else 0
            tam = math.floor(tam) if unidad == "unidades" and a["clase"] == "accion" else round(tam, 2 if a["clase"] != "cripto" else 6)
            p["tamano"] = {"cantidad": tam, "unidad": unidad, "riesgo_dinero": dinero, "perdida_hasta_stop": perdida * tam,
                           "ganancia_tp": [((abs(t["nivel"] - entrada) - costes) * vu * tam) for t in p["tps"]]}
    return p

def calc_plan(a, tipo, ind, entrada, vela=None, capital=None, riesgo_pct=1.0):
    atr, R, S = ind["atr"], ind["R"], ind["S"]
    medio = (R + S) / 2
    if tipo == "ruptura_alcista":
        return _plan(a, entrada, R - 0.5 * atr, 1, [(ind["H7"], "máximo de 7 días"), (ind["H30"], "máximo de 30 días"),
                     (entrada + (R - S), "extensión del rango (movimiento medido)"), (entrada + 3 * atr, "volatilidad (3 ATR)")],
                     atr, capital, riesgo_pct, R)
    if tipo == "ruptura_bajista":
        return _plan(a, entrada, S + 0.5 * atr, -1, [(ind["L7"], "mínimo de 7 días"), (ind["L30"], "mínimo de 30 días"),
                     (entrada - (R - S), "extensión del rango (movimiento medido)"), (entrada - 3 * atr, "volatilidad (3 ATR)")],
                     atr, capital, riesgo_pct, S)
    if tipo == "rechazo_resistencia":
        alto = vela["h"] if vela else R
        return _plan(a, entrada, max(R, alto) + 0.5 * atr, -1, [(medio, "mitad del rango de 48 h"), (S, "soporte del rango"),
                     (ind["L7"], "mínimo de 7 días"), (entrada - 3 * atr, "volatilidad (3 ATR)")], atr, capital, riesgo_pct)
    if tipo == "rebote_soporte":
        bajo = vela["l"] if vela else S
        return _plan(a, entrada, min(S, bajo) - 0.5 * atr, 1, [(medio, "mitad del rango de 48 h"), (R, "resistencia del rango"),
                     (ind["H7"], "máximo de 7 días"), (entrada + 3 * atr, "volatilidad (3 ATR)")], atr, capital, riesgo_pct)
    return None

# ------------------------------------------------------------ creación de escenarios
def generar(a, b, ahora, capital=None, riesgo_pct=1.0):
    cer = cerradas(b, ahora)
    if len(cer) < 60:
        raise ValueError("pocos datos")
    atr = atr_precio(cer)
    R, S = max(x["h"] for x in cer[-48:]), min(x["l"] for x in cer[-48:])
    vt = vol_tipico(b)
    ind = {"R": R, "S": S, "H7": max(x["h"] for x in cer[-168:]), "L7": min(x["l"] for x in cer[-168:]),
           "H30": max(x["h"] for x in cer), "L30": min(x["l"] for x in cer), "atr": atr,
           "vt": {str(k): v for k, v in vt.items()} if vt else None}
    prov = {"ruptura_alcista": (R, R + 0.1 * atr), "ruptura_bajista": (S, S - 0.1 * atr),
            "rechazo_resistencia": (R, R - 0.25 * atr), "rebote_soporte": (S, S + 0.25 * atr), "lateral": ((R + S) / 2, None)}
    out, ahora_iso = [], ahora.isoformat()
    for tipo, (nivel, entrada) in prov.items():
        horas = 48 if tipo == "lateral" else 24
        plan = calc_plan(a, tipo, ind, entrada, None, capital, riesgo_pct) if entrada else None
        tps = plan["tps"] if plan else []
        out.append({"id": hashlib.sha1(f"{a['simbolo']}|{tipo}|{nivel:.6f}|{ahora:%Y%m%d%H%M}".encode()).hexdigest()[:12],
                    "simbolo": a["simbolo"], "tipo": tipo, "direccion": TIPOS[tipo][0], "creado_en": ahora_iso,
                    "precio_ref": b[-1]["c"], "nivel": nivel, "entrada": entrada, "stop": plan["stop"] if plan else None,
                    "tp1": tps[0]["nivel"] if len(tps) > 0 else None, "tp2": tps[1]["nivel"] if len(tps) > 1 else None,
                    "tp3": tps[2]["nivel"] if len(tps) > 2 else None, "atr": atr, "costes_pct": COSTES.get(a["clase"], 0.05),
                    "expira_en": (ahora + timedelta(hours=horas)).isoformat(), "estado": "preparado", "motivo": "escenario creado",
                    "actualizado_en": ahora_iso, "version": VERSION, "indicadores": json.dumps(ind)})
    return out

def guardar(c, lista):
    for e in lista:
        cols = ",".join(e)
        c.execute(f"INSERT OR IGNORE INTO escenarios({cols}) VALUES ({','.join('?' * len(e))})", list(e.values()))
        c.execute("INSERT INTO eventos_escenario(escenario_id,ts,estado_ant,estado_nuevo,precio,motivo) VALUES (?,?,?,?,?,?)",
                  (e["id"], e["creado_en"], None, "preparado", e["precio_ref"], "escenario creado"))
    c.commit()

def activos(c, simbolo=None):
    q = "SELECT * FROM escenarios WHERE estado NOT IN ('invalidado','objetivo_alcanzado','stop_alcanzado','expirado','cancelado')"
    return c.execute(q + (" AND simbolo=?" if simbolo else "") + " ORDER BY simbolo, tipo", (simbolo,) if simbolo else ()).fetchall()

# ------------------------------------------------------------ máquina de estados (reproduce las velas desde la creación)
def _hora(ts, zona=None):
    d = datetime.fromtimestamp(ts, timezone.utc)
    return (d.astimezone(zona) if zona else d).strftime("%H:%M")

def evaluar(esc, b, ahora, a, capital=None, riesgo_pct=1.0):
    """Devuelve los hitos alcanzados desde la creación y el plan/seguimiento. No toca la base de datos."""
    ind = json.loads(esc["indicadores"])
    atr, L, tipo, R, S = ind["atr"], esc["nivel"], esc["tipo"], ind["R"], ind["S"]
    vt = {int(k): v for k, v in ind["vt"].items()} if ind.get("vt") else None
    now, t0, exp = ahora.timestamp(), _ts(esc["creado_en"]), _ts(esc["expira_en"])
    hitos, st, plan, fav, adv, resultado, debiles = [], "preparado", None, 0.0, 0.0, None, 0
    sent = {"alcista": 1, "bajista": -1}.get(esc["direccion"], 0)
    conf_i, vela_conf = None, None

    def vol_ok(x):
        if not vt:
            return True, "volumen no disponible: no se exige"
        tip = vt.get((x["t"] // 3600) % 24)
        if not tip:
            return True, "sin referencia de volumen para esa hora"
        return (x.get("v", 0) or 0) >= UMBRAL_VOL * tip, f"volumen {x.get('v', 0):,.0f} frente a umbral {UMBRAL_VOL * tip:,.0f}"

    for i, x in enumerate((x for x in b if x["t"] + 3600 > t0)):
        if x["t"] >= exp:
            break
        cerrada = x["t"] + 3600 <= now
        if tipo == "lateral":
            if cerrada and (x["c"] > R or x["c"] < S):
                hitos.append(("invalidado", f"el rango dejó de ser válido: cierre en {N(x['c'])} fuera de {N(S)} - {N(R)}", x["t"] + 3600)); st = "invalidado"; break
            continue
        arriba = tipo in ("ruptura_alcista", "rechazo_resistencia")
        if st in ("preparado", "proximo", "activado_provisional"):
            if tipo.startswith("ruptura"):
                cerca = (x["h"] >= L - 0.5 * atr) if arriba else (x["l"] <= L + 0.5 * atr)
                activa = (x["h"] > L) if arriba else (x["l"] < L)
            else:
                cerca = (x["h"] >= L - 0.5 * atr) if arriba else (x["l"] <= L + 0.5 * atr)
                activa = (x["h"] >= L - 0.25 * atr) if arriba else (x["l"] <= L + 0.25 * atr)
            if st == "preparado" and cerca and not activa:
                hitos.append(("proximo", f"el precio está a menos de 0.5 ATR de {'la resistencia' if arriba else 'el soporte'} {N(L)}", x["t"])); st = "proximo"
            if st in ("preparado", "proximo") and activa:
                que = "superó" if tipo.startswith("ruptura") else "tocó"
                hitos.append(("activado_provisional", f"el precio {que} {N(L)} a las {_hora(x['t'])} UTC ({'vela cerrada' if cerrada else 'vela en curso, sin cierre'})", x["t"])); st = "activado_provisional"
            if st == "activado_provisional" and cerrada:
                rng = x["h"] - x["l"]
                if tipo == "ruptura_alcista" or tipo == "ruptura_bajista":
                    dentro = x["c"] <= L if arriba else x["c"] >= L
                    if dentro:
                        hitos.append(("invalidado", f"falsa ruptura: la vela cerró de vuelta {'bajo' if arriba else 'sobre'} {N(L)} (cierre {N(x['c'])})", x["t"] + 3600)); st = "invalidado"; break
                    ok, det = vol_ok(x)
                    if ok:
                        vela_conf, conf_i = x, i
                        plan = calc_plan(a, tipo, ind, x["c"], x, capital, riesgo_pct)
                        hitos.append(("confirmado", f"cierre {'sobre' if arriba else 'bajo'} {N(L)} ({N(x['c'])}) con {det}", x["t"] + 3600)); st = "confirmado"
                    else:
                        debiles += 1
                        if debiles >= 3:
                            hitos.append(("invalidado", f"sin confirmación de volumen tras 3 cierres ({det})", x["t"] + 3600)); st = "invalidado"; break
                else:
                    toca = (x["h"] >= L - 0.25 * atr) if arriba else (x["l"] <= L + 0.25 * atr)
                    if not toca or rng <= 0:
                        continue
                    if (arriba and x["c"] > L) or (not arriba and x["c"] < L):
                        hitos.append(("invalidado", f"la vela cerró {'sobre la resistencia' if arriba else 'bajo el soporte'} {N(L)}: es una ruptura, no un rechazo", x["t"] + 3600)); st = "invalidado"; break
                    if arriba:
                        patron = x["c"] < x["o"] and (x["h"] - max(x["o"], x["c"])) >= 0.4 * rng and x["c"] <= x["l"] + 0.5 * rng
                        det = "vela bajista con mecha superior significativa y cierre en la mitad inferior"
                    else:
                        patron = x["c"] > x["o"] and (min(x["o"], x["c"]) - x["l"]) >= 0.4 * rng and x["c"] >= x["h"] - 0.5 * rng
                        det = "vela alcista con mecha inferior significativa y cierre en la mitad superior"
                    if patron:
                        vela_conf, conf_i = x, i
                        plan = calc_plan(a, tipo, ind, x["c"], x, capital, riesgo_pct)
                        hitos.append(("confirmado", f"{det} (cierre {N(x['c'])})", x["t"] + 3600)); st = "confirmado"
        elif st == "confirmado" and i > conf_i and plan and plan["tps"]:
            riesgo, entrada, stop, tp1 = plan["riesgo"], plan["entrada"], plan["stop"], plan["tps"][0]["nivel"]
            fav = max(fav, ((x["h"] - entrada) if sent == 1 else (entrada - x["l"])) / riesgo)
            adv = max(adv, ((entrada - x["l"]) if sent == 1 else (x["h"] - entrada)) / riesgo)
            if (sent == 1 and x["l"] <= stop) or (sent == -1 and x["h"] >= stop):
                hitos.append(("stop_alcanzado", f"el precio tocó el stop-loss {N(stop)}" + (" (si la misma vela tocó también el objetivo, se asume el stop primero)"), x["t"] + 3600)); resultado = -1.0; st = "stop_alcanzado"; break
            if (sent == 1 and x["h"] >= tp1) or (sent == -1 and x["l"] <= tp1):
                hitos.append(("objetivo_alcanzado", f"el precio alcanzó TP1 {N(tp1)}", x["t"] + 3600)); resultado = plan["tps"][0]["rr"]; st = "objetivo_alcanzado"; break
    if st not in FINALES and now >= exp:
        if st == "confirmado" and plan and b:
            resultado = ((b[-1]["c"] - plan["entrada"]) * sent) / plan["riesgo"]
        hitos.append(("expirado", "venció el horizonte del escenario" + (f" (resultado abierto: {resultado:+.2f} R)" if resultado is not None else ""), exp))
    return {"hitos": hitos, "plan": plan, "vela": vela_conf, "max_fav": fav, "max_adv": adv, "resultado_r": resultado,
            "precio": b[-1]["c"], "ultimo_t": b[-1]["t"]}

def aplicar(c, esc, res, ahora):
    """Guarda lo nuevo y devuelve solo los cambios de estado materiales (así no hay alertas duplicadas)."""
    nuevos = [h for h in res["hitos"] if rank(h[0]) > rank(esc["estado"])]
    sets, vals = {}, {}
    p = res["plan"]
    if p:
        sets.update(entrada=p["entrada"], stop=p["stop"], tp1=(p["tps"][0]["nivel"] if p["tps"] else None),
                    tp2=(p["tps"][1]["nivel"] if len(p["tps"]) > 1 else None), tp3=(p["tps"][2]["nivel"] if len(p["tps"]) > 2 else None))
    sets.update(max_fav=res["max_fav"], max_adv=res["max_adv"])
    for est, motivo, ts in nuevos:
        c.execute("INSERT INTO eventos_escenario(escenario_id,ts,estado_ant,estado_nuevo,precio,motivo) VALUES (?,?,?,?,?,?)",
                  (esc["id"], ahora.isoformat(), esc["estado"], est, res["precio"], motivo))
    if nuevos:
        est, motivo, _ = nuevos[-1]
        sets.update(estado=est, motivo=motivo, actualizado_en=ahora.isoformat())
        if est == "confirmado":
            sets["confirmado_en"] = ahora.isoformat()
        if est in FINALES:
            sets.update(cerrado_en=ahora.isoformat(), resultado_r=res["resultado_r"])
    c.execute("UPDATE escenarios SET " + ",".join(f"{k}=?" for k in sets) + " WHERE id=?", list(sets.values()) + [esc["id"]])
    c.commit()
    return [{"estado": h[0], "motivo": h[1], "precio": res["precio"]} for h in nuevos]

# ------------------------------------------------------------ estadísticas
def estadisticas(c, simbolo=None, minimo=30):
    q = "SELECT * FROM escenarios WHERE confirmado_en IS NOT NULL AND estado IN ('objetivo_alcanzado','stop_alcanzado','expirado') AND resultado_r IS NOT NULL"
    f = c.execute(q + (" AND simbolo=?" if simbolo else ""), (simbolo,) if simbolo else ()).fetchall()
    n = len(f)
    if not n:
        return {"n": 0, "texto": f"Escenarios confirmados y cerrados: 0. Sin muestra no hay validación estadística (se requieren al menos {minimo})."}
    g = sum(x["resultado_r"] > 0 for x in f)
    media = sum(x["resultado_r"] for x in f) / n
    t = (f"Escenarios confirmados y cerrados: {n}. Acertaron {g} ({g / n * 100:.0f}%); expectativa media {media:+.2f} R; "
         f"movimiento favorable medio {sum(x['max_fav'] for x in f) / n:.2f} R, adverso medio {sum(x['max_adv'] for x in f) / n:.2f} R (con costes supuestos). ")
    t += (f"Muestra suficiente (n>={minimo})." if n >= minimo else f"Muestra insuficiente (n={n} < {minimo}): no hay validación estadística todavía.")
    return {"n": n, "texto": t}

def resumen_activos(c, nombres):
    filas = activos(c)
    if not filas:
        return "No hay escenarios activos. Activa la vigilancia con /vigilar y marca activos en /activos."
    L = ["📋 Escenarios activos"]
    sim = None
    for f in filas:
        if f["simbolo"] != sim:
            sim = f["simbolo"]
            L.append(f"\n{nombres.get(sim, sim)} ({sim})")
        resta = max(0, (_ts(f["expira_en"]) - datetime.now(timezone.utc).timestamp()) / 3600)
        extra = f" · entrada {N(f['entrada'])} · stop {N(f['stop'])} · TP1 {N(f['tp1'])}" if f["estado"] == "confirmado" and f["stop"] else ""
        L.append(f"• {TIPOS[f['tipo']][1]}: {ETIQ[f['estado']]} · nivel {N(f['nivel'])}{extra} · expira en {resta:.0f} h")
    return "\n".join(L)

# ------------------------------------------------------------ mensajes de alerta (formatos A-D de la especificación)
def _plan_texto(p):
    if not p:
        return []
    L = [f"Entrada de referencia: {N(p['entrada'])}", f"Stop-loss propuesto: {N(p['stop'])} (riesgo {N(p['riesgo'])} por unidad)"]
    for i, t in enumerate(p["tps"], 1):
        L.append(f"TP{i}: {N(t['nivel'])} ({t['fundamento']}) · R/R {t['rr']:.2f}")
    if p["intermedios"]:
        L.append("Niveles intermedios a vigilar: " + ", ".join(N(x) for x, _ in p["intermedios"][:3]))
    L.append(f"Costes estimados (supuesto): {N(p['costes'])} por unidad ida y vuelta")
    if p["tamano"]:
        t = p["tamano"]
        L.append(f"Tamaño para arriesgar {N(t['riesgo_dinero'])}: {t['cantidad']} {t['unidad']} (pérdida hasta el stop ≈ {N(t['perdida_hasta_stop'])})")
    else:
        L.append("Tamaño: configura tu capital y riesgo con /riesgo CAPITAL PORCENTAJE.")
    L += [f"⚠️ {x}" for x in p["avisos"]]
    if not p["ok"]:
        L.append("Conclusión del filtro de riesgo: NO operar este escenario tal como está.")
    return L

def alerta(a, esc, estado, motivo, precio, plan, ahora, zona, vela_t=None, stats="", macro=""):
    tipo = esc["tipo"]
    nom = TIPOS[tipo][1].upper()
    res = tipo in ("ruptura_alcista", "rechazo_resistencia")
    nivel_n = "resistencia" if res else "soporte"
    L = []
    if estado == "proximo":
        L += [f"TITAN QUANT — APROXIMACIÓN A {nivel_n.upper()}", "", f"Activo: {a['nombre']} ({a['simbolo']})", f"Precio observado: {N(precio)}",
              f"Nivel: {nivel_n} {N(esc['nivel'])}", f"Escenario vigilado: {TIPOS[tipo][1]}", "", f"Condición observada: {motivo}.", "Estado: próximo a activarse. Todavía NO hay confirmación.",
              f"Próxima condición a vigilar: {'cierre de vela' if tipo.startswith('ruptura') else 'rechazo con cierre de vela'} respecto a {N(esc['nivel'])}."]
    elif estado == "activado_provisional":
        L += ["TITAN QUANT — ESCENARIO SIN CONFIRMAR", "", f"Activo: {a['nombre']} ({a['simbolo']})", f"Precio observado: {N(precio)}", f"Escenario: {TIPOS[tipo][1]} · nivel {N(esc['nivel'])}", "",
              f"{motivo[0].upper() + motivo[1:]}.", "La condición esperada no se ha completado: falta el cierre de la vela" + (" y el volumen." if tipo.startswith("ruptura") else " con el patrón de rechazo."),
              "", "Estado: activado provisionalmente (pendiente).", "No se considera confirmado ni se genera una recomendación de entrada basada solo en esta hipótesis."]
    elif estado == "confirmado":
        L += [f"TITAN QUANT — {nom} CONFIRMAD{'A' if tipo != 'rechazo_resistencia' else 'O'}".replace("RUPTURA BAJISTA", "RUPTURA BAJISTA DE SOPORTE"), "",
              f"Activo: {a['nombre']} ({a['simbolo']})", f"Precio observado: {N(precio)}", f"Nivel {'superado' if tipo == 'ruptura_alcista' else 'perdido' if tipo == 'ruptura_bajista' else 'de referencia'}: {N(esc['nivel'])}", "",
              "Condiciones cumplidas:", f"- {motivo}.", "", "Interpretación: el mercado cumple las condiciones definidas para este escenario.", ""] + _plan_texto(plan) + [
              "", f"Invalidación: cierre de vela {'bajo' if esc['direccion'] == 'alcista' else 'sobre'} {N(plan['stop']) if plan else N(esc['nivel'])} (stop-loss).", "", "Estado: escenario confirmado; no garantiza una operación rentable."]
    elif estado == "invalidado":
        falsa = motivo.startswith("falsa ruptura")
        L += [f"TITAN QUANT — {'FALSA RUPTURA' if falsa else 'HIPÓTESIS INVALIDADA'}", "", f"Activo: {a['nombre']} ({a['simbolo']})", f"Escenario anterior: {TIPOS[tipo][1]} ({esc['direccion']}).",
              f"Condición de invalidación: {motivo}.", f"Precio observado: {N(precio)}", "",
              "El escenario anterior deja de ser válido. TITAN recalculará soportes, resistencias y escenarios sin asumir que el movimiento contrario está automáticamente confirmado."]
    elif estado == "objetivo_alcanzado":
        L += ["TITAN QUANT — OBJETIVO ALCANZADO", "", f"Activo: {a['nombre']} ({a['simbolo']})", f"Escenario: {TIPOS[tipo][1]}", f"Precio observado: {N(precio)}", f"Detalle: {motivo}.",
              f"Entrada de referencia: {N(esc['entrada'])} · Stop: {N(esc['stop'])}", "Seguimiento hipotético: no se ejecutó ninguna orden."]
    elif estado == "stop_alcanzado":
        L += ["TITAN QUANT — STOP-LOSS ALCANZADO (seguimiento hipotético)", "", f"Activo: {a['nombre']} ({a['simbolo']})", f"Escenario: {TIPOS[tipo][1]}", f"Precio observado: {N(precio)}", f"Detalle: {motivo}.",
              f"Entrada de referencia: {N(esc['entrada'])} · Stop: {N(esc['stop'])}", "El escenario queda cerrado. No se ejecutó ninguna orden."]
    else:
        L += ["TITAN QUANT — ESCENARIO EXPIRADO", "", f"Activo: {a['nombre']} ({a['simbolo']})", f"Escenario: {TIPOS[tipo][1]}", f"Detalle: {motivo}."]
    if macro:
        L += ["", "Contexto macro: " + macro]
    if stats:
        L += ["", "Confianza: " + stats]
    fh = f"; última vela {_hora(vela_t, zona)} ({zona.key})" if vela_t else ""
    L += ["", f"Datos: Yahoo Finance{fh}. Informativo; no ejecuta órdenes ni es consejo financiero."]
    return "\n".join(L)
