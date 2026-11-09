"""Escáner MULTIACTIVO del bot cTrader: analiza todos los símbolos de la cuenta, los prueba con backtesting y se ajusta.

Cada paso (lo llama el ciclo del bot):
  1. RANKING (aprendizaje continuo): toma el siguiente lote de símbolos de la cuenta (rota por todos), descarga sus velas
     de cTrader (incremental, base de backtesting propia) y hace backtest de cada estrategia activa: 70 % dentro de
     muestra / 30 % fuera, con coste = medio spread medido en cTrader. Guarda el resultado en `ranking`.
     Un par símbolo-estrategia es APTO con una exigencia BÁSICA: ≥ min_ops operaciones fuera de muestra, expectativa
     fuera de muestra > exp_min (en R) y expectativa total > 0. Como el ranking se recalcula con los datos más
     recientes, las estrategias que dejan de funcionar en un símbolo dejan de ser aptas: el bot se ajusta al mercado.
  2. SEÑALES: para los pares aptos mejor clasificados, mira si la ÚLTIMA vela cerrada de cTrader da señal.
Los datos (símbolos, nombres, velas, bid/ask) son los del propio cTrader, con sus nombres tal como los publica el broker.
Este módulo no envía órdenes: devuelve candidatas; el autotrader aplica los controles de riesgo y envía.
"""
import json
import statistics
import time

from . import almacen
from ..historico import SEG

INTERVALOS = ("5m", "15m", "1h", "4h")
DIAS_POR_INTERVALO = {"5m": 20, "15m": 45, "1h": 150, "4h": 400}
K_BARRAS = {"5m": 12, "15m": 8, "1h": 8, "4h": 6}       # salida por tiempo = 2k velas

ESQUEMA = """
CREATE TABLE IF NOT EXISTS ranking(proveedor TEXT NOT NULL, simbolo TEXT NOT NULL, intervalo TEXT NOT NULL, estrategia TEXT NOT NULL,
    params TEXT NOT NULL, descripcion TEXT, velas INTEGER, n_total INTEGER, exp_total REAL, n_fuera INTEGER, exp_fuera REAL,
    acierto_fuera REAL, ic_bajo_fuera REAL, costo_frac REAL, apto INTEGER NOT NULL DEFAULT 0, motivo TEXT, actualizado_ts INTEGER NOT NULL,
    PRIMARY KEY(proveedor, simbolo, intervalo, estrategia));
CREATE TABLE IF NOT EXISTS cursor_escaner(clave TEXT PRIMARY KEY, posicion INTEGER NOT NULL, total INTEGER, ts INTEGER)
"""


def _alm():
    a = almacen()
    a.asegurar(ESQUEMA)
    return a


def proveedor(entorno):
    return "ctrader-demo" if entorno == "demo" else "ctrader-live"


def _serie(prov, simbolo, intervalo, desde=None):
    filas = _alm().leer(prov, simbolo, intervalo, desde)
    return {"t": [f[0] for f in filas], "o": [f[1] for f in filas], "h": [f[2] for f in filas],
            "l": [f[3] for f in filas], "c": [f[4] for f in filas]}


def evaluar(s, estrategia, params, intervalo, costo_frac, atr_stop, atr_obj, min_ops, exp_min, exploracion=False, estricto=False):
    from .motor import metricas, operaciones_simple
    k = K_BARRAS.get(intervalo, 8)
    ops = operaciones_simple(s, estrategia, params, k, costo_frac, atr_stop, atr_obj)
    corte = int(len(s["c"]) * 0.7)
    fuera = [t for t in ops if t["i"] >= corte]
    mt, mf = metricas(ops), metricas(fuera)
    apto = mf.get("n", 0) >= min_ops and (mf.get("expectativa_r") if mf.get("expectativa_r") is not None else -9) > exp_min and         (exploracion or (mt.get("expectativa_r") or -1) > 0)
    if estricto:      # MODO EVIDENCIA: ventaja estadística demostrada (IC 95 % de la expectativa total > 0) y fuera de muestra > 0
        min_ops = max(min_ops, 20)
        ic_total = (mt.get("ic95_expectativa_r") or [None])[0]
        apto = mf.get("n", 0) >= min_ops and (mf.get("expectativa_r") or -1) > max(0.0, exp_min) and ic_total is not None and ic_total > 0
    if mf.get("n", 0) < min_ops:
        motivo = f"solo {mf.get('n', 0)} operaciones fuera de muestra (mínimo {min_ops})"
    elif estricto and not apto:
        motivo = (f"sin ventaja demostrada: IC95 de la expectativa total {(mt.get('ic95_expectativa_r') or [0])[0]:+.3f} R, "
                  f"fuera de muestra {mf.get('expectativa_r') or 0:+.3f} R")
    elif not apto:
        motivo = f"expectativa fuera de muestra {mf.get('expectativa_r', 0):+.3f} R / total {mt.get('expectativa_r', 0):+.3f} R"
    else:
        motivo = (f"apto{' (EVIDENCIA: ventaja demostrada)' if estricto else ' (exploración)' if exploracion else ''}: "
                  f"{mf['n']} ops fuera de muestra, {mf['expectativa_r']:+.3f} R")
    return {"n_total": mt.get("n", 0), "exp_total": mt.get("expectativa_r"), "n_fuera": mf.get("n", 0), "exp_fuera": mf.get("expectativa_r"),
            "acierto_fuera": mf.get("tasa_acierto"), "ic_bajo_fuera": (mf.get("ic95_expectativa_r") or [None])[0], "apto": bool(apto), "motivo": motivo}


def _avanzar_cursor(clave, pos, procesados, total):
    """Deja el cursor justo después de lo realmente procesado (si se agotó el tiempo, lo pendiente va primero en el próximo ciclo)."""
    with _alm().tx() as c:
        c.execute("INSERT OR REPLACE INTO cursor_escaner(clave,posicion,total,ts) VALUES(?,?,?,?)",
                  (clave, (pos + procesados) % max(1, total), total, int(time.time())))


def _posicion(clave, total):
    fila = _alm().q("SELECT posicion FROM cursor_escaner WHERE clave=?", (clave,))
    pos = fila[0]["posicion"] if fila else 0
    return 0 if pos >= total else pos


def _siguiente_lote(clave, simbolos, lote):
    a = _alm()
    fila = a.q("SELECT posicion FROM cursor_escaner WHERE clave=?", (clave,))
    pos = fila[0]["posicion"] if fila else 0
    if pos >= len(simbolos):
        pos = 0
    elegidos = simbolos[pos:pos + lote]
    with a.tx() as c:
        c.execute("INSERT OR REPLACE INTO cursor_escaner(clave,posicion,total,ts) VALUES(?,?,?,?)",
                  (clave, (pos + lote) % max(1, len(simbolos)), len(simbolos), int(time.time())))
    return elegidos


def intervalos(cfg):
    out = [x for x in (cfg.get("intervalos") or [cfg.get("intervalo", "15m")]) if x in INTERVALOS]
    return out or ["15m"]


def actualizar_ranking(ses, entorno, cat_simbolos, cfg, ahora=None):
    """Backtest de un lote de símbolos en CADA temporalidad y con cada estrategia activa."""
    hechos, tfs = [], intervalos(cfg)
    presupuesto = float(cfg.get("presupuesto_s") or 0)          # 0 = sin límite de tiempo
    for tf in tfs:
        limite = time.time() + presupuesto / len(tfs) if presupuesto else None
        hechos += _actualizar_tf(ses, entorno, cat_simbolos, {**cfg, "intervalo": tf, "_limite_ts": limite}, ahora)
    return hechos


SPREAD_VIGENCIA_S = 900


def _actualizar_tf(ses, entorno, cat_simbolos, cfg, ahora=None):
    a = _alm()
    prov = proveedor(entorno)
    intervalo = cfg["intervalo"]
    activos = sorted((x for x in cat_simbolos if x.get("activo", True) and x.get("nombre")), key=lambda x: x["nombre"])
    if cfg.get("simbolos"):
        quiero = {x.upper() for x in cfg["simbolos"]}
        activos = [x for x in activos if x["nombre"].upper() in quiero]
    clave = f"{prov}|{intervalo}"
    pos = _posicion(clave, len(activos))
    lote = activos[pos:pos + int(cfg.get("lote", 4))]
    limite = cfg.get("_limite_ts")
    ahora = int(ahora or time.time())
    fin = ahora - ahora % SEG[intervalo]
    hechos, procesados = [], 0
    for sim in lote:
        if limite and procesados and time.time() > limite:     # tiempo agotado: el resto, primero en el próximo ciclo
            break
        procesados += 1
        nombre = sim["nombre"]
        try:
            a.descargar_incremental(ses, prov, nombre, sim["id"], intervalo, fin - DIAS_POR_INTERVALO[intervalo] * 86400, fin, lote=1000)
            sp = None
            try:
                reciente = a.q("SELECT 1 FROM spreads WHERE simbolo=? AND ts>? LIMIT 1", (nombre, int(time.time()) - SPREAD_VIGENCIA_S))
                if reciente:
                    raise LookupError("spread reciente")             # ya medido en este ciclo / hace poco: no se espera a la cotización
                q = ses.cotizacion(sim["id"], espera=6)
                if q.get("bid") and q.get("ask"):
                    sp = q["ask"] - q["bid"]
                    with a.tx() as c:
                        c.execute("INSERT OR REPLACE INTO spreads(simbolo,ts,bid,ask,spread,fuente) VALUES(?,?,?,?,?,?)",
                                  (nombre, int(time.time()), q["bid"], q["ask"], sp, f"cTrader {entorno} spot (bid/ask)"))
            except Exception:
                pass
            filas = [r["spread"] for r in a.q("SELECT spread FROM spreads WHERE simbolo=? ORDER BY ts DESC LIMIT 20", (nombre,))]
            s = _serie(prov, nombre, intervalo, fin - DIAS_POR_INTERVALO[intervalo] * 86400)
            if len(s["c"]) < 200 or not filas:
                motivo = "sin datos suficientes de cTrader" if len(s["c"]) < 200 else "sin spread medido (mercado cerrado)"
                with a.tx() as c:
                    for est in cfg["estrategias"]:
                        c.execute("""INSERT OR REPLACE INTO ranking(proveedor,simbolo,intervalo,estrategia,params,descripcion,velas,apto,motivo,actualizado_ts)
                                     VALUES(?,?,?,?,?,?,?,0,?,?)""", (prov, nombre, intervalo, est, json.dumps(cfg["estrategias"][est]),
                                                                     sim.get("descripcion"), len(s["c"]), motivo, ahora))
                hechos.append({"simbolo": nombre, "motivo": motivo})
                continue
            costo = (statistics.median(filas) / 2) / statistics.median(s["c"])
            for est, prm in cfg["estrategias"].items():
                r = evaluar(s, est, prm, intervalo, costo, cfg["atr_stop"], cfg["atr_obj"], cfg["min_ops"], cfg["exp_min"], cfg.get("exploracion", False),
                            cfg.get("estricto", False))
                prm_g = {**prm, "_criterio": criterio(cfg)}
                with a.tx() as c:
                    c.execute("""INSERT OR REPLACE INTO ranking(proveedor,simbolo,intervalo,estrategia,params,descripcion,velas,n_total,exp_total,n_fuera,
                                 exp_fuera,acierto_fuera,ic_bajo_fuera,costo_frac,apto,motivo,actualizado_ts) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                              (prov, nombre, intervalo, est, json.dumps(prm_g), sim.get("descripcion"), len(s["c"]), r["n_total"], r["exp_total"],
                               r["n_fuera"], r["exp_fuera"], r["acierto_fuera"], r["ic_bajo_fuera"], costo, int(r["apto"]), r["motivo"], ahora))
            hechos.append({"simbolo": nombre, "intervalo": intervalo, "velas": len(s["c"])})
        except Exception as e:                                  # un símbolo con problemas no detiene el escaneo
            hechos.append({"simbolo": nombre, "error": f"{type(e).__name__}: {e}"[:200]})
    _avanzar_cursor(clave, pos, procesados, len(activos))
    return hechos


def criterio(cfg):
    return "estricto" if cfg.get("estricto") else "exploracion" if cfg.get("exploracion") else "normal"


def mejores(entorno, intervalo, limite=10, estrategias=None, crit=None):
    tfs = intervalo if isinstance(intervalo, (list, tuple)) else [intervalo]
    sql = "SELECT * FROM ranking WHERE proveedor=? AND apto=1 AND intervalo IN (%s)" % ",".join("?" * len(tfs))
    args = [proveedor(entorno)] + list(tfs)
    if crit == "estricto":            # en modo evidencia solo valen las filas calculadas con el criterio estricto
        sql += " AND params LIKE ?"
        args.append('%"_criterio": "estricto"%')
    if estrategias:
        sql += " AND estrategia IN (%s)" % ",".join("?" * len(estrategias))
        args += list(estrategias)
    return _alm().q(sql + " ORDER BY exp_fuera DESC, n_fuera DESC LIMIT ?", args + [int(limite)])


def ranking(entorno=None, intervalo=None, limite=100):
    sql, args = "SELECT * FROM ranking WHERE 1=1", []
    if entorno:
        sql += " AND proveedor=?"
        args.append(proveedor(entorno))
    if intervalo:
        sql += " AND intervalo=?"
        args.append(intervalo)
    return _alm().q(sql + " ORDER BY apto DESC, exp_fuera DESC LIMIT ?", args + [int(limite)])


def senales_vivas(ses, entorno, cat_simbolos, cfg, ahora=None):
    """Señal en la ÚLTIMA vela cerrada de cTrader en TODOS los pares aptos del ranking (de mejor a peor), con tiempo máximo
    por ciclo (cfg['presupuesto_senales_s']). Las velas de cada símbolo y temporalidad se piden una sola vez por ciclo."""
    from ..estrategias import simples
    from ..motores import mat
    por_nombre = {x["nombre"]: x for x in cat_simbolos if x.get("nombre")}
    ahora = int(ahora or time.time())
    limite = time.time() + float(cfg["presupuesto_senales_s"]) if cfg.get("presupuesto_senales_s") else None
    out, vistos, cache = [], set(), {}
    for fila in mejores(entorno, intervalos(cfg), int(cfg.get("max_simbolos", 10)), list(cfg["estrategias"]), criterio(cfg)):
        if limite and time.time() > limite:                 # tiempo agotado: los mejor clasificados ya se miraron
            break
        nombre = fila["simbolo"]
        sim = por_nombre.get(nombre)
        if not sim or nombre in vistos:
            continue
        intervalo = fila["intervalo"]
        paso = SEG[intervalo]
        hasta = (ahora - ahora % paso) * 1000                       # excluye la vela en formación
        if (nombre, intervalo) not in cache:
            try:
                cache[(nombre, intervalo)] = ses.velas(sim["id"], intervalo, hasta - 400 * paso * 1000, hasta, cuenta=400)
            except Exception:                               # límite de frecuencia u otro fallo puntual: se mira en el siguiente ciclo
                cache[(nombre, intervalo)] = None
        velas = cache[(nombre, intervalo)]
        if not velas:
            continue
        velas = [v for v in velas if v[0] + paso <= ahora]
        if len(velas) < 60 or ahora - (velas[-1][0] + paso) > 2 * paso:
            continue
        o, h, l, c = [v[1] for v in velas], [v[2] for v in velas], [v[3] for v in velas], [v[4] for v in velas]
        prm = {k: v for k, v in json.loads(fila["params"]).items() if not k.startswith("_")}
        ev = [e for e in simples.senales(fila["estrategia"], o, h, l, c, prm) if e["indice"] == len(c) - 1]
        if not ev:
            continue
        atr = mat.atr_serie(h, l, c, 14)[-1]
        if not atr:
            continue
        tend = simples.tendencia(c, 50, 200)[-1] if len(c) > 210 else 0
        vistos.add(nombre)
        out.append({"simbolo": nombre, "id": sim["id"], "intervalo": intervalo, "descripcion": sim.get("descripcion"), "estrategia": fila["estrategia"], "params": prm,
                    "direccion": "alcista" if ev[0]["direccion"] == "compra" else "bajista", "precio_ref": c[-1], "atr": atr,
                    "vela_ts": velas[-1][0], "exp_fuera": fila["exp_fuera"], "n_fuera": fila["n_fuera"], "tendencia": tend,
                    "velas": velas[-300:], "proveedor": proveedor(entorno)})
    return out
