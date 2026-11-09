"""Cerebro autónomo de TITAN (C6).

Cada ciclo (15 min, solo si el supervisor lo permite):
  1. EVIDENCIA REAL: lee las operaciones CERRADAS y VERIFICADAS por el broker de cada cuenta (nunca backtest ni simulación).
  2. INFERENCIA BAYESIANA por estrategia y por estrategia×activo: P(expectativa > 0) (Normal-Gamma, cTrader) o
     P(acierto > equilibrio) (Beta-Binomial, binarias). Con poca muestra, la previa escéptica impide conclusiones falsas.
  3. DETERIORO: CUSUM sobre la secuencia cronológica de resultados en R.
  4. PATRONES DE PÉRDIDA: por hora UTC, día, dirección, activo y estrategia (grupos con n ≥ 5 y P(positiva) < 0,2).
  5. ESTADO DEL MERCADO: régimen por modelo oculto de Markov, volatilidad GARCH(1,1), Hurst y entropía de permutación
     sobre velas reales de cTrader de los activos principales.
  6. DECISIONES con trazabilidad completa (evidencia numérica, versión del modelo, cuenta):
       · cuentas de PRÁCTICA: puede BLOQUEAR una combinación estrategia×activo perdedora (más prudente, nunca más riesgo).
       · cuentas REAL: SOLO recomienda; no cambia nada (lo decide el usuario).
     No puede tocar límites de riesgo protegidos, ni el MODO LIVE, ni la PARADA TOTAL (lo impone seguridad.interruptores).
     Todo bloqueo es reversible (versión anterior) desde la interfaz.
"""
import json
import sqlite3
import threading
import time
from contextlib import contextmanager

import numpy as np

from .. import config, db

VERSION = "1.0.0"
PERIODO_S = 900
MIN_PAR = 6               # operaciones mínimas en una combinación para poder bloquearla
P_BLOQUEO = 0.10          # bloquear si P(ventaja) < 10 %
ESQUEMA = """
CREATE TABLE IF NOT EXISTS ejecuciones(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, version TEXT, duracion_ms INTEGER, resumen TEXT);
CREATE TABLE IF NOT EXISTS evaluaciones(ejecucion_id INTEGER, cuenta TEXT, clave TEXT, n INTEGER, media_r REAL, p_ventaja REAL, deterioro INTEGER, detalle TEXT);
CREATE TABLE IF NOT EXISTS patrones(ejecucion_id INTEGER, cuenta TEXT, dimension TEXT, valor TEXT, n INTEGER, media_r REAL, p_positiva REAL);
CREATE TABLE IF NOT EXISTS mercado(ejecucion_id INTEGER, simbolo TEXT, intervalo TEXT, datos TEXT);
CREATE TABLE IF NOT EXISTS decisiones(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, ejecucion_id INTEGER, cuenta TEXT, tipo TEXT,
    estrategia TEXT, instrumento TEXT, evidencia TEXT, estado TEXT NOT NULL, origen TEXT NOT NULL DEFAULT 'ia', revertida_ts INTEGER, revertida_por INTEGER);
CREATE INDEX IF NOT EXISTS i_dec ON decisiones(cuenta, estado);
"""
_L = threading.local()
ESTADO = {"vivo": False, "ultima_ts": None, "error": None, "ejecuciones": 0, "ultima_duracion_ms": None}
_PARAR = threading.Event()


def ruta():
    return config.DATOS / "ia" / "cerebro.db"


def _con():
    r = str(ruta())
    c = getattr(_L, "c", None)
    if c is None or getattr(_L, "r", None) != r:
        ruta().parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(r, timeout=15, isolation_level=None, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA busy_timeout=15000")
        c.executescript(ESQUEMA)
        _L.c, _L.r = c, r
    return c


@contextmanager
def tx():
    c = _con()
    c.execute("BEGIN IMMEDIATE")
    try:
        yield c
        c.execute("COMMIT")
    except BaseException:
        c.execute("ROLLBACK")
        raise


def q(sql, a=()):
    return [dict(r) for r in _con().execute(sql, a).fetchall()]


def cerrar():
    c = getattr(_L, "c", None)
    if c is not None:
        c.close()
        _L.c = None


# ------------------------------------------------------------------------------------------------ evidencia
def operaciones_reales(m):
    from ..trader import almacen, autotrader
    filas = almacen.q(m, f"""SELECT instrumento, estrategia, direccion, resultado, riesgo_importe, monto, payout, tipo, abierta_ts, cerrada_ts
                            FROM operaciones WHERE {autotrader.VERIFICADA} ORDER BY cerrada_ts""")
    out = []
    for o in filas:
        base = o["riesgo_importe"] or (o["monto"] if o["tipo"] == "binaria" else None)
        if not base or o["resultado"] is None:
            continue
        out.append({**o, "r": o["resultado"] / base})
    return out


def _evaluar(ops, binaria):
    from ..ciencia import bayes, deterioro
    r = [o["r"] for o in ops]
    if binaria:
        g = sum(1 for o in ops if o["resultado"] > 0)
        pay = np.mean([o["payout"] for o in ops if o.get("payout")] or [0.83])
        b = bayes.tasa_acierto(g, len(ops) - g, umbral=1 / (1 + pay))
        p = b["p_sobre_umbral"]
        det = f"acierto {g}/{len(ops)} · posterior {b['media']:.1%} · equilibrio {1 / (1 + pay):.1%} · P(ventaja) {p:.0%}"
    else:
        e = bayes.expectativa_r(r)
        p = e["p_positiva"]
        det = f"expectativa posterior {e['media']:+.2f} R · P(>0) {p:.0%} · IC95 [{e['ic95'][0]:+.2f}, {e['ic95'][1]:+.2f}]"
    d = deterioro.deterioro(r)
    return {"n": len(ops), "media_r": float(np.mean(r)), "p_ventaja": float(p), "deterioro": bool(d["deterioro"]), "detalle": det}


def _patrones(ops):
    from ..ciencia import bayes
    dims = {"hora_utc": lambda o: time.gmtime(o["abierta_ts"] or 0).tm_hour, "dia": lambda o: ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"][time.gmtime(o["abierta_ts"] or 0).tm_wday],
            "direccion": lambda o: o["direccion"], "activo": lambda o: o["instrumento"], "estrategia": lambda o: o["estrategia"] or "—"}
    out = []
    for dim, fn in dims.items():
        grupos = {}
        for o in ops:
            grupos.setdefault(str(fn(o)), []).append(o["r"])
        for v, rs in grupos.items():
            if len(rs) >= 5:
                e = bayes.expectativa_r(rs)
                if e["p_positiva"] < 0.2:
                    out.append({"dimension": dim, "valor": v, "n": len(rs), "media_r": float(np.mean(rs)), "p_positiva": float(e["p_positiva"])})
    return sorted(out, key=lambda x: x["media_r"])[:15]


def estado_mercado(simbolos=("EURUSD", "XAUUSD", "GERMANY 40"), intervalo="1h", n=600):
    from ..backtest_ctrader import almacen as alm
    from ..ciencia import informacion, regimen, volatilidad
    out = {}
    a = alm()
    for s in simbolos:
        filas = a.q("SELECT ts, c FROM velas_historicas WHERE proveedor='ctrader-demo' AND simbolo=? AND intervalo=? ORDER BY ts DESC LIMIT ?", (s, intervalo, n))
        if len(filas) < 200:
            continue
        c = np.array([f["c"] for f in reversed(filas)], float)
        r = np.diff(np.log(c))
        try:
            hmm = regimen.describir(regimen.ajustar(r, 2))
            g = volatilidad.garch11(r)
            out[s] = {"regimen": hmm, "garch": {k: g[k] for k in ("alfa", "beta", "persistencia", "vol_siguiente", "vol_largo_plazo", "vida_media")},
                      "hurst": informacion.hurst(r), "entropia_permutacion": informacion.entropia_permutacion(r, 4),
                      "razon_varianzas": informacion.razon_varianzas(r, 4), "velas": len(c), "ultima_ts": filas[0]["ts"]}
        except Exception as e:
            out[s] = {"error": f"{type(e).__name__}: {e}"[:200]}
    return out


# ------------------------------------------------------------------------------------------------ decisiones
def bloqueado(m, estrategia, simbolo):
    """Lo consulta el autotrader: ¿el cerebro bloqueó esta combinación en esta cuenta de práctica?"""
    try:
        r = _con().execute("SELECT evidencia FROM decisiones WHERE cuenta=? AND tipo='bloquear' AND estado='aplicada' AND estrategia=? AND instrumento=? LIMIT 1",
                           (m, estrategia, simbolo)).fetchone()
        return json.loads(r["evidencia"]) if r else None
    except Exception:
        return None


def revertir(decision_id, uid):
    with tx() as c:
        n = c.execute("UPDATE decisiones SET estado='revertida', revertida_ts=?, revertida_por=? WHERE id=? AND estado IN ('aplicada','propuesta')",
                      (int(time.time()), uid, int(decision_id))).rowcount
    db.auditar(uid, "cerebro_decision_revertida", "ia", str(decision_id))
    return n == 1


def ciclo():
    from ..trader import autotrader
    t0 = time.time()
    with tx() as c:
        eid = c.execute("INSERT INTO ejecuciones(ts, version) VALUES(?,?)", (int(t0), VERSION)).lastrowid
    resumen = {"cuentas": {}, "decisiones": 0}
    for m in autotrader.MODALIDADES:
        ops = operaciones_reales(m)
        binaria = m in autotrader.BINARIAS
        info = {"operaciones": len(ops)}
        if ops:
            info["global"] = _evaluar(ops, binaria)
            claves = {}
            for o in ops:
                claves.setdefault(("estrategia", o["estrategia"] or "—", None), []).append(o)
                claves.setdefault(("par", o["estrategia"] or "—", o["instrumento"]), []).append(o)
            with tx() as c:
                for (tipo, est, inst), grupo in claves.items():
                    ev = _evaluar(grupo, binaria)
                    c.execute("INSERT INTO evaluaciones(ejecucion_id,cuenta,clave,n,media_r,p_ventaja,deterioro,detalle) VALUES(?,?,?,?,?,?,?,?)",
                              (eid, m, f"{est}|{inst or '*'}", ev["n"], ev["media_r"], ev["p_ventaja"], int(ev["deterioro"]), ev["detalle"]))
                    if tipo != "par" or ev["n"] < MIN_PAR or ev["p_ventaja"] >= P_BLOQUEO:
                        continue
                    ya = c.execute("SELECT 1 FROM decisiones WHERE cuenta=? AND tipo='bloquear' AND estrategia=? AND instrumento=? AND estado IN ('aplicada','propuesta','revertida')",
                                   (m, est, inst)).fetchone()
                    if ya:                                   # una decisión revertida por el usuario no se vuelve a imponer
                        continue
                    estado = "propuesta" if m in autotrader.REALES else "aplicada"
                    c.execute("INSERT INTO decisiones(ts,ejecucion_id,cuenta,tipo,estrategia,instrumento,evidencia,estado) VALUES(?,?,?,?,?,?,?,?)",
                              (int(time.time()), eid, m, "bloquear", est, inst, json.dumps({**ev, "version": VERSION}), estado))
                    resumen["decisiones"] += 1
            pats = _patrones(ops)
            with tx() as c:
                for p in pats:
                    c.execute("INSERT INTO patrones(ejecucion_id,cuenta,dimension,valor,n,media_r,p_positiva) VALUES(?,?,?,?,?,?,?)",
                              (eid, m, p["dimension"], p["valor"], p["n"], p["media_r"], p["p_positiva"]))
            info["patrones_perdida"] = len(pats)
        resumen["cuentas"][m] = info
    try:
        merc = estado_mercado()
        with tx() as c:
            for s, d in merc.items():
                c.execute("INSERT INTO mercado(ejecucion_id,simbolo,intervalo,datos) VALUES(?,?,?,?)", (eid, s, "1h", json.dumps(d, default=float)))
        resumen["mercado"] = sorted(merc)
    except Exception as e:
        resumen["mercado_error"] = f"{type(e).__name__}: {e}"[:200]
    ms = int((time.time() - t0) * 1000)
    with tx() as c:
        c.execute("UPDATE ejecuciones SET duracion_ms=?, resumen=? WHERE id=?", (ms, json.dumps(resumen), eid))
        viejas = [r[0] for r in c.execute("SELECT id FROM ejecuciones ORDER BY id DESC LIMIT -1 OFFSET 200").fetchall()]
        for v in viejas:                                    # se conservan 200 versiones (recuperables)
            for t in ("evaluaciones", "patrones", "mercado"):
                c.execute(f"DELETE FROM {t} WHERE ejecucion_id=?", (v,))
            c.execute("DELETE FROM ejecuciones WHERE id=?", (v,))
    ESTADO.update(ultima_ts=int(time.time()), ejecuciones=ESTADO["ejecuciones"] + 1, ultima_duracion_ms=ms)
    return {"ejecucion": eid, "duracion_ms": ms, **resumen}


def informe():
    ult = q("SELECT * FROM ejecuciones WHERE resumen IS NOT NULL ORDER BY id DESC LIMIT 1")
    if not ult:
        return {"ejecucion": None}
    e = ult[0]
    return {"ejecucion": {**e, "resumen": json.loads(e["resumen"])},
            "evaluaciones": q("SELECT * FROM evaluaciones WHERE ejecucion_id=? ORDER BY cuenta, p_ventaja", (e["id"],)),
            "patrones": q("SELECT * FROM patrones WHERE ejecucion_id=? ORDER BY media_r", (e["id"],)),
            "mercado": {r["simbolo"]: json.loads(r["datos"]) for r in q("SELECT * FROM mercado WHERE ejecucion_id=?", (e["id"],))},
            "decisiones": q("SELECT * FROM decisiones ORDER BY id DESC LIMIT 100"), "version": VERSION,
            "reglas": "Práctica: puede bloquear combinaciones perdedoras (reversible). REAL: solo recomienda. Nunca toca límites de riesgo, LIVE ni la PARADA TOTAL."}


def _bucle():
    from .. import supervisor
    ESTADO["vivo"] = True
    _PARAR.wait(60)
    while not _PARAR.is_set():
        try:
            if supervisor.permitido("cerebro"):
                ciclo()
            ESTADO["error"] = None
        except Exception as e:
            ESTADO["error"] = f"{type(e).__name__}: {e}"[:300]
        _PARAR.wait(PERIODO_S)
    ESTADO["vivo"] = False


def iniciar():
    if not ESTADO["vivo"]:
        _PARAR.clear()
        threading.Thread(target=_bucle, name="titan-cerebro", daemon=True).start()


def detener():
    _PARAR.set()
