"""Escáner MULTIACTIVO y MULTITEMPORALIDAD del bot de binarias (IQ Option), con el concepto de binaria.

Temporalidades (todas con vencimiento de 5 minutos en IQ Option):
    1m → entrada en la apertura de la vela siguiente, vence al cierre de 5 velas M1
    5m → entrada en la apertura de la vela siguiente, vence al cierre de esa vela M5
Cada paso (lo llama el ciclo del bot):
  1. RANKING (aprendizaje continuo): siguiente lote de pares ABIERTOS en IQ Option (estado real de get_all_init_v2, nombres
     tal como los publica IQ Option), velas de cada temporalidad (el recolector continuo las mantiene al día) y backtest de cada
     estrategia activa con el PAYOUT REAL del par. 70 % dentro / 30 % fuera de muestra.
     APTO: ≥ min_ops operaciones decisivas fuera de muestra y acierto fuera de muestra > punto de equilibrio 1/(1+payout) + margen;
     fuera del modo exploración se exige además EV total > 0. El ranking se recalcula con datos recientes.
     MODO EXPLORACIÓN (solo cuentas de práctica): exigencia baja para que el bot opere, reúna resultados reales y aprenda.
  2. SEÑALES: en los pares/temporalidades aptos mejor clasificados, señal en la ÚLTIMA vela cerrada.
No envía órdenes: el autotrader aplica los controles y envía a la cuenta (PRACTICE o REAL) del bot.
"""
import json
import threading
import time

from . import almacen

TEMPORALIDADES = {"1m": {"paso": 60, "vencimiento": 5, "velas": 2000, "dias": 4},
                  "5m": {"paso": 300, "vencimiento": 1, "velas": 1500, "dias": 10}}

ESQUEMA = """
CREATE TABLE IF NOT EXISTS ranking_tf(activo TEXT NOT NULL, intervalo TEXT NOT NULL, estrategia TEXT NOT NULL, params TEXT NOT NULL, payout REAL,
    velas INTEGER, n_total INTEGER, ev_total REAL, n_fuera INTEGER, acierto_fuera REAL, equilibrio REAL, ev_fuera REAL,
    apto INTEGER NOT NULL DEFAULT 0, motivo TEXT, actualizado_ts INTEGER NOT NULL, PRIMARY KEY(activo, intervalo, estrategia));
CREATE TABLE IF NOT EXISTS ranking_tf_estricto(activo TEXT NOT NULL, intervalo TEXT NOT NULL, estrategia TEXT NOT NULL, params TEXT NOT NULL,
    payout REAL, velas INTEGER, n_total INTEGER, ev_total REAL, n_fuera INTEGER, acierto_fuera REAL, equilibrio REAL, ev_fuera REAL,
    apto INTEGER NOT NULL DEFAULT 0, motivo TEXT, actualizado_ts INTEGER NOT NULL, PRIMARY KEY(activo, intervalo, estrategia));
CREATE TABLE IF NOT EXISTS cursor_escaner(clave TEXT PRIMARY KEY, posicion INTEGER NOT NULL, total INTEGER, ts INTEGER)
"""
# Una tabla por criterio. Antes compartían ranking_tf (clave activo/intervalo/estrategia): el bot PRACTICE en exploración y el
# REAL en modo evidencia, funcionando a la vez, se sobrescribían las filas y cada uno perdía las candidatas del otro.
TABLAS = ("ranking_tf", "ranking_tf_estricto")


def tabla(estricto):
    return "ranking_tf_estricto" if estricto else "ranking_tf"


def _alm():
    a = almacen()
    a.asegurar(ESQUEMA)
    return a


def _es_divisa(n):
    from ..binaria_bot.escaner import es_par_otc
    return es_par_otc(n) or (len(n) == 6 and es_par_otc(n + "-OTC"))


def pares_abiertos(api, solo_divisas=False):
    import iqoption_data
    est = iqoption_data.estado_binarias(api) or {}
    return sorted(n for n, v in est.items() if v.get("turbo") and v.get("id") is not None and (not solo_divisas or _es_divisa(n)))


def payouts(api, timeout=20):
    """{par: payout turbo} leído de IQ Option (get_all_profit), con tiempo máximo. {} si no responde."""
    res = {}

    def _t():
        try:
            res["p"] = api.get_all_profit()
        except Exception as e:  # noqa: BLE001
            res["e"] = e
    h = threading.Thread(target=_t, daemon=True)
    h.start()
    h.join(timeout)
    out = {}
    for k, v in (res.get("p") or {}).items():
        x = v.get("turbo") if isinstance(v, dict) else None
        if isinstance(x, (int, float)) and not isinstance(x, bool) and 0 < x < 1.5:
            out[k] = float(x)
    return out


def evaluar(velas, payout, estrategia, params, min_ops, margen, intervalo="1m", exploracion=False, tendencia_emas=None, estricto=False):
    from .motor import metricas, ops_simple
    tf = TEMPORALIDADES[intervalo]
    corte = int(len(velas) * 0.7)
    ops = ops_simple(velas, payout, estrategia, params, tf["vencimiento"], tf["paso"], tendencia_emas)
    fuera = [o for o in ops if o.ts_senal >= velas[corte].ts] if corte < len(velas) else []
    mt, mf = metricas(ops, payout), metricas(fuera, payout)
    eq = mt["punto_equilibrio"]
    supera = (mf["tasa_acierto"] or 0) > eq + margen
    apto = mf["decisivas"] >= min_ops and supera and (exploracion or (mt["ev_por_unidad"] or -1) > 0)
    wil_total = (mt.get("ic95_wilson") or [None])[0]
    if estricto:      # MODO EVIDENCIA: límite inferior de Wilson (95 %) del acierto TOTAL por encima del equilibrio
        min_ops = max(min_ops, 20)
        apto = mf["decisivas"] >= min_ops and supera and wil_total is not None and wil_total > eq and (mt["ev_por_unidad"] or -1) > 0
    if mf["decisivas"] < min_ops:
        motivo = f"solo {mf['decisivas']} operaciones decisivas fuera de muestra (mínimo {min_ops})"
    elif estricto and not apto:
        motivo = f"sin ventaja demostrada: Wilson 95 % del acierto total {wil_total or 0:.1%} vs equilibrio {eq:.1%}"
    elif not apto:
        motivo = f"acierto fuera {mf['tasa_acierto'] or 0:.1%} vs equilibrio {eq:.1%} (+margen {margen:+.1%}); EV total {mt['ev_por_unidad'] or 0:+.3f}"
    else:
        motivo = (f"apto{' (EVIDENCIA: Wilson ' + format(wil_total, '.1%') + ')' if estricto else ' (exploración)' if exploracion else ''}: "
                  f"acierto fuera {mf['tasa_acierto']:.1%} vs equilibrio {eq:.1%} "
                  f"en {mf['decisivas']} ops")
    return {"n_total": mt["decisivas"], "ev_total": mt["ev_por_unidad"], "n_fuera": mf["decisivas"], "acierto_fuera": mf["tasa_acierto"],
            "equilibrio": eq, "ev_fuera": mf["ev_por_unidad"], "apto": bool(apto), "motivo": motivo}


def _avanzar_cursor(clave, pos, procesados, total):
    """Deja el cursor justo después de lo realmente procesado (si se agotó el tiempo, lo pendiente va primero en el próximo ciclo)."""
    with _alm().tx() as c:
        c.execute("INSERT OR REPLACE INTO cursor_escaner(clave,posicion,total,ts) VALUES(?,?,?,?)",
                  (clave, (pos + procesados) % max(1, total), total, int(time.time())))


def _posicion(clave, total):
    fila = _alm().q("SELECT posicion FROM cursor_escaner WHERE clave=?", (clave,))
    pos = fila[0]["posicion"] if fila else 0
    return 0 if pos >= total else pos


def _siguiente_lote(clave, pares, lote):
    a = _alm()
    fila = a.q("SELECT posicion FROM cursor_escaner WHERE clave=?", (clave,))
    pos = fila[0]["posicion"] if fila else 0
    if pos >= len(pares):
        pos = 0
    with a.tx() as c:
        c.execute("INSERT OR REPLACE INTO cursor_escaner(clave,posicion,total,ts) VALUES(?,?,?,?)",
                  (clave, (pos + lote) % max(1, len(pares)), len(pares), int(time.time())))
    return pares[pos:pos + lote]


def _temporalidades(cfg):
    out = [x for x in cfg.get("intervalos_binaria") or ["1m", "5m"] if x in TEMPORALIDADES]
    return out or ["1m"]


def actualizar_ranking(api, cfg, pagos=None, ahora=None):
    from .motor import _velas
    from .recolector import recopilar_iqoption, registrar_payout
    pares = pares_abiertos(api, cfg.get("solo_divisas", False))
    if cfg.get("pares"):
        quiero = {x.upper() for x in cfg["pares"]}
        pares = [p for p in pares if p in quiero]
    pagos = pagos if pagos is not None else payouts(api)
    a, ahora, hechos = _alm(), int(ahora or time.time()), []
    pos = _posicion("binaria|turbo", len(pares))
    limite = time.time() + float(cfg["presupuesto_s"]) if cfg.get("presupuesto_s") else None
    procesados = 0
    for par in pares[pos:pos + int(cfg.get("lote", 3))]:
        if limite and procesados and time.time() > limite:     # tiempo agotado: el resto, primero en el próximo ciclo
            break
        procesados += 1
        try:
            pago = pagos.get(par)
            if pago is None:
                hechos.append({"activo": par, "motivo": "sin payout de IQ Option"})
                continue
            registrar_payout(par, pago)
            for tfn in _temporalidades(cfg):
                tf = TEMPORALIDADES[tfn]
                recopilar_iqoption(par, tf["velas"], sesion=api, intervalo=tfn)
                velas = _velas(par, "iqoption", ahora - tf["dias"] * 86400, intervalo=tfn)
                for est, prm in cfg["estrategias"].items():
                    if len(velas) >= 300:
                        r = evaluar(velas, pago, est, prm, cfg["min_ops"], cfg["margen"], tfn, cfg.get("exploracion", False),
                                    cfg.get("tendencia"), cfg.get("estricto", False))
                        if cfg.get("tendencia"):
                            r["motivo"] += " · a favor de la tendencia"
                    else:
                        r = {"n_total": 0, "ev_total": None, "n_fuera": 0, "acierto_fuera": None, "equilibrio": 1 / (1 + pago), "ev_fuera": None,
                             "apto": False, "motivo": f"solo {len(velas)} velas {tfn}"}
                    prm_g = {**prm, "_criterio": "estricto" if cfg.get("estricto") else "exploracion" if cfg.get("exploracion") else "normal"}
                    if cfg.get("tendencia"):
                        prm_g["_tendencia"] = list(cfg["tendencia"])
                    with a.tx() as c:
                        c.execute(f"""INSERT OR REPLACE INTO {tabla(cfg.get("estricto"))}(activo,intervalo,estrategia,params,payout,velas,n_total,ev_total,n_fuera,
                                     acierto_fuera,equilibrio,ev_fuera,apto,motivo,actualizado_ts) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                  (par, tfn, est, json.dumps(prm_g), pago, len(velas), r["n_total"], r["ev_total"], r["n_fuera"], r["acierto_fuera"],
                                   r["equilibrio"], r["ev_fuera"], int(r["apto"]), r["motivo"], ahora))
            hechos.append({"activo": par, "payout": pago})
        except Exception as e:
            hechos.append({"activo": par, "error": f"{type(e).__name__}: {e}"[:200]})
    _avanzar_cursor("binaria|turbo", pos, procesados, len(pares))
    if pares:                       # los pares que IQ Option cerró o suspendió dejan de ser aptos hasta que reabran
        with a.tx() as c:
            for t in TABLAS:
                c.execute(f"UPDATE {t} SET apto=0, motivo='par cerrado/suspendido en IQ Option' WHERE apto=1 AND activo NOT IN (%s)"
                          % ",".join("?" * len(pares)), pares)
    return hechos


def mejores(limite=5, estrategias=None, intervalos=None, tendencia=None, estricto=False):
    sql, args = f"SELECT * FROM {tabla(estricto)} WHERE apto=1", []
    if estricto:
        sql += " AND params LIKE ?"
        args.append('%"_criterio": "estricto"%')
    if tendencia:                     # solo filas calculadas CON el mismo filtro de tendencia
        sql += " AND params LIKE ?"
        args.append('%"_tendencia": [' + f"{int(tendencia[0])}, {int(tendencia[1])}" + ']%')
    if estrategias:
        sql += " AND estrategia IN (%s)" % ",".join("?" * len(estrategias))
        args += list(estrategias)
    if intervalos:
        sql += " AND intervalo IN (%s)" % ",".join("?" * len(intervalos))
        args += list(intervalos)
    return _alm().q(sql + " ORDER BY (acierto_fuera - equilibrio) DESC, n_fuera DESC LIMIT ?", args + [int(limite)])


def ranking(limite=100):
    return _alm().q("SELECT *, activo AS simbolo FROM ranking_tf ORDER BY apto DESC, (acierto_fuera - equilibrio) DESC LIMIT ?", (int(limite),))


def senales_vivas(ad, cfg, ahora=None):
    """Señal en la última vela cerrada (M1 o M5) de IQ Option en TODOS los pares aptos del ranking (de mejor a peor), con
    tiempo máximo por ciclo (cfg['presupuesto_senales_s']). Las velas de cada par y temporalidad se piden una vez por ciclo."""
    from ..estrategias import simples
    ahora = ahora or time.time()
    limite = time.time() + float(cfg["presupuesto_senales_s"]) if cfg.get("presupuesto_senales_s") else None
    out, vistos, cache = [], set(), {}
    tend = cfg.get("tendencia")
    for fila in mejores(int(cfg.get("max_simbolos", 5)), list(cfg["estrategias"]), _temporalidades(cfg), tend, cfg.get("estricto", False)):
        if limite and time.time() > limite:                 # tiempo agotado: los mejor clasificados ya se miraron
            break
        par, tfn = fila["activo"], fila["intervalo"]
        if par in vistos:
            continue
        paso = TEMPORALIDADES[tfn]["paso"]
        n = max(120, int(tend[1]) + 60) if tend else 120          # la EMA lenta necesita su historia
        if (par, tfn) not in cache:
            try:
                cache[(par, tfn)] = ad.velas(par, tfn, n) if hasattr(ad, "velas") else ad.velas_m1(par, n)
            except Exception as e:                                   # un par que falla no aborta el escaneo de los demás
                print(f"[BINARIAS] {par} {tfn}: velas no disponibles ({type(e).__name__}: {str(e)[:120]})", flush=True)
                cache[(par, tfn)] = None
        velas = cache[(par, tfn)]
        if not velas:
            continue
        if len(velas) < (int(tend[1]) + 10 if tend else 40) or ahora - (velas[-1]["ts"] + paso) > 2 * paso:
            continue
        o, h, l, c = [v["open"] for v in velas], [v["high"] for v in velas], [v["low"] for v in velas], [v["close"] for v in velas]
        prm = {k: v for k, v in json.loads(fila["params"]).items() if not k.startswith("_")}
        ev = [e for e in simples.senales(fila["estrategia"], o, h, l, c, prm, tend) if e["indice"] == len(c) - 1]
        if not ev:
            continue
        vistos.add(par)
        out.append({"activo": par, "intervalo": tfn, "estrategia": fila["estrategia"], "direccion": "alcista" if ev[0]["direccion"] == "compra" else "bajista",
                    "precio_ref": c[-1], "vela_ts": velas[-1]["ts"], "payout": fila["payout"], "acierto_fuera": fila["acierto_fuera"],
                    "equilibrio": fila["equilibrio"], "n_fuera": fila["n_fuera"], "velas": velas, "proveedor": "iqoption"})
    return out
