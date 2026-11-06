# -*- coding: utf-8 -*-
"""TITAN QUANT · Laboratorio de Aprendizaje  (LAB_V1)

Dos motores independientes sobre la infraestructura que ya existe:
  Motor A · Inteligencia Operativa : espeja y supervisa los planes de plan_web (titan_planes.db).
  Motor B · Inteligencia Autonoma  : escanea los activos registrados, abre operaciones simuladas,
                                     las supervisa, registra todo y evalua modelos con validacion fuera de muestra.
Todo es SIMULACION INTERNA con precios de Yahoo Finance en modo lectura.
No se conecta a ningun broker ni envia ordenes reales.  Base de datos propia: titan_lab.db
"""
import hashlib, json, math, re, sqlite3, threading, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from zoneinfo import ZoneInfo

import activos, agente, chart_web, plan_web

ROOT = Path(__file__).resolve().parent
DB = ROOT / "titan_lab.db"
STATE_FILE = ROOT / ".estado_bot.json"
_L = threading.RLock()
_HILOS = {}
_CACHE = {}

P_SUPERVISOR, P_MOTOR_B, P_NOTICIAS, P_APRENDIZAJE = 15, 90, 600, 1800
LOTE_B, LOTE_NOTICIAS, MAX_ABIERTAS_B = 2, 3, 60
MIN_N, MIN_OOS, MIN_WF, MIN_CAND, MIN_PATRON = 30, 40, 60, 80, 15
ABIERTOS = ("PENDIENTE", "ACTIVADA", "EN_SEGUIMIENTO")
RES_VALIDOS = ("stop", "tp1_be", "tp2", "tiempo_agotado")
SQL_ABIERTOS = "('PENDIENTE','ACTIVADA','EN_SEGUIMIENTO')"
SQL_RES = "('stop','tp1_be','tp2','tiempo_agotado')"
BASE_PARAMS = {"min_abs_total": 3, "tipo": "todos", "noticias": "libre"}

# Supuestos de costo de ejecucion simulada (fraccion del precio). NO son datos medidos del mercado:
# Yahoo Finance no entrega spread ni comisiones. Son supuestos conservadores y configurables.
COSTOS = {  # clase: (spread, slippage por lado, comision por lado)
    "cripto": (0.0003, 0.0002, 0.0006), "divisa": (0.00008, 0.00004, 0.0), "metal": (0.0002, 0.0001, 0.00005),
    "energia": (0.0004, 0.0002, 0.00005), "indice": (0.0001, 0.0001, 0.00005), "accion": (0.0003, 0.0002, 0.0),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS lab_config(clave TEXT PRIMARY KEY, valor TEXT);
CREATE TABLE IF NOT EXISTS lab_procesos(nombre TEXT PRIMARY KEY, ultimo_ts INTEGER, ciclos INTEGER DEFAULT 0, ultimo_error TEXT, detalle TEXT);
CREATE TABLE IF NOT EXISTS lab_snapshots(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, simbolo TEXT, mostrar TEXT, precio REAL, atr_pct REAL);
CREATE TABLE IF NOT EXISTS lab_decisiones(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, motor TEXT, simbolo TEXT, modo TEXT, trig TEXT,
    accion TEXT, total INTEGER, ctx INTEGER, gat INTEGER, precio REAL, atr REAL, trade_id INTEGER, computa INTEGER, razon TEXT);
CREATE TABLE IF NOT EXISTS lab_trades(id INTEGER PRIMARY KEY AUTOINCREMENT, motor TEXT, origen_id INTEGER, creado_ts INTEGER, simbolo TEXT, mostrar TEXT,
    clase TEXT, fuente TEXT, modo TEXT, estrategia TEXT, trig TEXT, ctx TEXT, direccion INTEGER, tipo TEXT,
    entrada REAL, stop REAL, tp1 REAL, tp2 REAL, r1 REAL, r2 REAL, atr REAL, valido_hasta INTEGER, max_dur_s INTEGER, eval_tf TEXT, eval_int TEXT,
    estado TEXT, resultado TEXT, activada_ts INTEGER, cerrada_ts INTEGER,
    spread REAL, slip REAL, comision REAL, costo_r REAL, fill_sim REAL, r_bruto REAL, r_neto REAL, mfe_r REAL, mae_r REAL,
    precio_ult REAL, eventos TEXT, detalle TEXT, modelo_ver INTEGER, computa INTEGER DEFAULT 1, actualizado_ts INTEGER);
CREATE UNIQUE INDEX IF NOT EXISTS ux_lab_origen ON lab_trades(motor, origen_id) WHERE origen_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS lab_ejecuciones(id INTEGER PRIMARY KEY AUTOINCREMENT, trade_id INTEGER, t INTEGER, texto TEXT, UNIQUE(trade_id, t, texto));
CREATE TABLE IF NOT EXISTS lab_alertas(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, clave TEXT UNIQUE, trade_id INTEGER, motor TEXT,
    simbolo TEXT, mostrar TEXT, tf TEXT, estrategia TEXT, direccion TEXT, precio REAL, tipo TEXT, certeza TEXT,
    motivo TEXT, evidencia TEXT, riesgo TEXT, accion TEXT, leida INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS lab_noticias(huella TEXT PRIMARY KEY, ts INTEGER, simbolo TEXT, titulo TEXT, fuente TEXT, fecha_ts INTEGER, enlace TEXT,
    impacto INTEGER, fuerza INTEGER, motivo TEXT, categoria TEXT, evaluada INTEGER DEFAULT 0, mov_1h REAL, mov_4h REAL, ok_1h INTEGER, ok_4h INTEGER);
CREATE TABLE IF NOT EXISTS lab_errores(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, modulo TEXT, mensaje TEXT);
CREATE TABLE IF NOT EXISTS lab_patrones(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, clave TEXT, descripcion TEXT, n INTEGER, win_rate REAL,
    wilson_low REAL, expectancy REAL, consistente INTEGER, estado TEXT);
CREATE TABLE IF NOT EXISTS lab_modelos(id INTEGER PRIMARY KEY AUTOINCREMENT, ver INTEGER, creado_ts INTEGER, params TEXT, estado TEXT, notas TEXT, metricas TEXT);
CREATE TABLE IF NOT EXISTS lab_metricas(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, alcance TEXT, datos TEXT);
CREATE TABLE IF NOT EXISTS lab_aprendizaje(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, tipo TEXT, texto TEXT);
"""


# ============================================================================ base de datos
def _ahora():
    return int(time.time())


def _con():
    c = sqlite3.connect(str(DB), timeout=15)
    c.row_factory = sqlite3.Row
    return c


def _q(sql, args=()):
    with _L:
        c = _con()
        try:
            return [dict(r) for r in c.execute(sql, args).fetchall()]
        finally:
            c.close()


def _w(sql, args=()):
    """Escribe y devuelve (filas afectadas, ultimo id)."""
    with _L:
        c = _con()
        try:
            cur = c.execute(sql, args)
            c.commit()
            return cur.rowcount, cur.lastrowid
        finally:
            c.close()


def cfg_get(k, d=None):
    r = _q("SELECT valor FROM lab_config WHERE clave=?", (k,))
    return r[0]["valor"] if r else d


def cfg_set(k, v):
    _w("INSERT INTO lab_config(clave,valor) VALUES(?,?) ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor", (k, str(v)))


def init_db():
    with _L:
        c = _con()
        c.executescript(SCHEMA)
        # Reparación v7: filas de latido creadas con nombre=timestamp por el error de argumentos invertidos.
        # Son latidos técnicos (no historial de usuario); se conserva un recuento en lab_aprendizaje.
        n = c.execute("SELECT COUNT(*) FROM lab_procesos WHERE nombre GLOB '[0-9]*'").fetchone()[0]
        if n:
            c.execute("DELETE FROM lab_procesos WHERE nombre GLOB '[0-9]*'")
            c.execute("INSERT INTO lab_aprendizaje(ts,tipo,texto) VALUES(?,?,?)",
                      (_ahora(), "mantenimiento", "Reparación v7: eliminadas %d filas de latido corruptas en lab_procesos" % n))
        c.commit()
        c.close()
    modelo_activo()


def _err(modulo, e):
    try:
        _w("INSERT INTO lab_errores(ts,modulo,mensaje) VALUES(?,?,?)", (_ahora(), str(modulo)[:80], (type(e).__name__ + ": " + str(e))[:300]))
    except Exception:
        pass


def _latido(nombre, error=None, detalle=None):
    _w("""INSERT INTO lab_procesos(nombre,ultimo_ts,ciclos,ultimo_error,detalle) VALUES(?,?,1,?,?)
          ON CONFLICT(nombre) DO UPDATE SET ultimo_ts=excluded.ultimo_ts, ciclos=ciclos+1,
          ultimo_error=COALESCE(excluded.ultimo_error, ultimo_error), detalle=COALESCE(excluded.detalle, detalle)""",
       (nombre, _ahora(), error, detalle))


def _aprende(tipo, texto):
    _w("INSERT INTO lab_aprendizaje(ts,tipo,texto) VALUES(?,?,?)", (_ahora(), tipo, texto[:400]))


# ============================================================================ activos / utilidades
def _estado_bot():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _zona():
    try:
        return ZoneInfo(_estado_bot().get("zona") or "America/Santo_Domingo")
    except Exception:
        return ZoneInfo("America/Santo_Domingo")


def registrados():
    out, vistos = [], set()
    for a in list(activos.CATALOGO):
        if a["simbolo"] not in vistos:
            vistos.add(a["simbolo"]); out.append(a)
    for s in _estado_bot().get("personalizados", []):
        try:
            a = activos.personalizado(s)
            if a["simbolo"] not in vistos:
                vistos.add(a["simbolo"]); out.append(a)
        except Exception:
            continue
    return out


def _activo(simbolo):
    s = str(simbolo or "").strip().upper()
    a = activos.buscar(s, _estado_bot().get("personalizados", []))
    return a if a is not None else activos.personalizado(s)


def _cacheado(clave, seg, fn):
    hit = _CACHE.get(clave)
    if hit and time.time() - hit[0] < seg:
        return hit[1]
    v = fn()
    _CACHE[clave] = (time.time(), v)
    return v


def _vol_rel(velas):
    """Volumen de la ultima vela CERRADA frente al promedio de las 20 anteriores (None si no hay datos)."""
    try:
        vs = [v[5] for v in velas[-23:-1]]
        if len(vs) < 12:
            return None
        ult, prev = vs[-1], [x for x in vs[:-1] if x]
        if not prev or not ult:
            return None
        return round(ult / (sum(prev) / len(prev)), 3)
    except Exception:
        return None


def _costos(clase, vol_rel):
    sp, sl, co = COSTOS.get(clase or "accion", COSTOS["accion"])
    if vol_rel is not None and vol_rel < 0.3:      # liquidez baja: el deslizamiento se duplica
        sl *= 2
    return sp, sl, co


def _costo_r(entrada, riesgo, sp, sl, co):
    return entrada * (sp + 2 * sl + 2 * co) / riesgo if riesgo > 0 else 0.0


def _pasa(params, f):
    if abs(f.get("total") or 0) < params.get("min_abs_total", 3):
        return False
    tp = params.get("tipo", "todos")
    if tp != "todos" and f.get("tipo") != tp:
        return False
    if params.get("noticias") == "no_contra":
        pn, d = f.get("punt_n"), f.get("dir")
        if pn is not None and d and pn * d < 0:
            return False
    return True


def modelo_activo():
    r = _q("SELECT * FROM lab_modelos WHERE estado='ESTABLE' ORDER BY ver DESC LIMIT 1")
    if not r:
        _w("INSERT INTO lab_modelos(ver,creado_ts,params,estado,notas,metricas) VALUES(1,?,?,?,?,?)",
           (_ahora(), json.dumps(BASE_PARAMS), "ESTABLE", "Reglas base de plan_web (sin optimizar).", "{}"))
        r = _q("SELECT * FROM lab_modelos WHERE estado='ESTABLE' ORDER BY ver DESC LIMIT 1")
    m = r[0]
    m["params"] = json.loads(m["params"])
    return m


def _noticias_punt(simbolo):
    ahora = _ahora()
    filas = _q("SELECT impacto, fecha_ts FROM lab_noticias WHERE simbolo=? AND fecha_ts>=?", (simbolo, ahora - 48 * 3600))
    lista = [{"impacto": f["impacto"], "edad_h": max(0.0, (ahora - f["fecha_ts"]) / 3600)} for f in filas]
    if len(lista) < agente.MIN_NOTICIAS:
        return None
    return agente.puntaje_noticias(lista)


# ============================================================================ ciclo de vida de operaciones
def _etiqueta(sim_estado, resultado):
    if sim_estado == "pendiente":
        return "PENDIENTE"
    if sim_estado == "activa":
        return "ACTIVADA"
    if sim_estado == "activa_tp1":
        return "EN_SEGUIMIENTO"
    if resultado == "cancelado":
        return "CANCELADA"
    if resultado in ("invalidada", "expirada_sin_entrada", "contexto_invertido"):
        return "INVALIDADA"
    return "CERRADA"


TIPOS_ALERTA = {
    "ENTRADA_ACTIVADA": ("CONFIRMADA", "Entrada activada", "Operación simulada abierta. Vigila el stop; no se envía ninguna orden real."),
    "TP1": ("CONFIRMADA", "Objetivo 1 alcanzado", "Se cierra la mitad simulada y el stop pasa a la entrada."),
    "TP_ALCANZADO": ("CONFIRMADA", "Take Profit alcanzado", "Operación simulada cerrada con beneficio."),
    "SL_ALCANZADO": ("CONFIRMADA", "Stop Loss alcanzado", "Operación simulada cerrada con pérdida. Revisa el motivo en el Laboratorio."),
    "STOP_EN_ENTRADA": ("CONFIRMADA", "Cierre en la entrada tras el objetivo 1", "Se aseguró la mitad del beneficio simulado."),
    "INVALIDADA": ("CONFIRMADA", "Operación invalidada", "No se activó. No hay nada que gestionar."),
    "EXPIRADA": ("CONFIRMADA", "Operación expirada sin entrada", "El precio no llegó a la entrada dentro de la ventana."),
    "TIEMPO_AGOTADO": ("CONFIRMADA", "Tiempo máximo agotado", "Cierre simulado al precio de ese momento."),
    "OBJETIVO_PROXIMO": ("PROBABILISTICA", "Objetivo próximo", "El precio está cerca del objetivo 1; aún no se ha alcanzado."),
    "STOP_PROXIMO": ("PROBABILISTICA", "Stop Loss próximo", "El precio está cerca del stop; aún no se ha tocado."),
    "CAMBIO_TENDENCIA": ("PROBABILISTICA", "Posible cambio de tendencia", "Advertencia probabilística: revisa el gráfico antes de decidir."),
    "REVERSION": ("PROBABILISTICA", "Reversión potencial", "Advertencia probabilística: el movimiento podría agotarse."),
    "ESTRUCTURA": ("PROBABILISTICA", "Cambio de estructura", "Advertencia probabilística: se rompió un nivel reciente en contra."),
    "CONTEXTO_ADVERSO": ("PROBABILISTICA", "Contexto adverso", "El contexto cambió en contra. En planes tuyos no se cancela solo: valora cancelarlo."),
    "NOTICIA": ("PROBABILISTICA", "Noticia importante", "Revisa el activo; las operaciones simuladas siguen su plan."),
}


def _alerta(t, tipo, motivo, evidencia, ts=None, precio=None, clave=None):
    cert, titulo, accion = TIPOS_ALERTA[tipo]
    riesgo = ""
    d = "—"
    if t:
        rg = abs(t["entrada"] - t["stop"]) or 0
        riesgo = "1R = %.6g (%.2f%% del precio). Simulación: sin dinero real." % (rg, rg / t["entrada"] * 100 if t["entrada"] else 0)
        d = "LONG" if t["direccion"] == 1 else "SHORT"
    clave = clave or ("%s:%s" % (t["id"], tipo))
    n, _ = _w("""INSERT OR IGNORE INTO lab_alertas(ts,clave,trade_id,motor,simbolo,mostrar,tf,estrategia,direccion,precio,tipo,certeza,motivo,evidencia,riesgo,accion)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (ts or _ahora(), clave, t["id"] if t else None, t["motor"] if t else None, t["simbolo"] if t else None, t["mostrar"] if t else None,
               t["trig"] if t else None, t["estrategia"] if t else None, d, precio if precio is not None else (t or {}).get("precio_ult"),
               tipo, cert, titulo + ": " + motivo, evidencia, riesgo, accion))
    return n > 0


def _log_ejec(tid, t, texto):
    _w("INSERT OR IGNORE INTO lab_ejecuciones(trade_id,t,texto) VALUES(?,?,?)", (tid, int(t), texto))


def _aplicar(t, s, alertar=True):
    """Aplica a la operacion t (fila lab_trades) un resultado de simulacion s (formato plan_web.simular)."""
    det = json.loads(t.get("detalle") or "{}")
    d = t["direccion"]
    riesgo = abs(t["entrada"] - t["stop"]) or 1e-9
    nuevo = _etiqueta(s["estado"], s.get("resultado"))
    sp = sl = co = costo = fill = None
    if s.get("activada_ts"):
        sp, sl, co = _costos(t.get("clase"), (det.get("feat") or {}).get("vol_rel"))
        costo = _costo_r(t["entrada"], riesgo, sp, sl, co)
        fill = t["entrada"] + d * t["entrada"] * (sp / 2 + sl)
    r_bruto = s.get("r_final") if nuevo == "CERRADA" else None
    r_neto = (r_bruto - costo) if (r_bruto is not None and costo is not None) else None
    rf = s.get("r_flotante")
    det["r_flot"] = (rf - costo) if (rf is not None and costo is not None) else None
    ev = s.get("eventos") or []
    _w("""UPDATE lab_trades SET estado=?, resultado=?, activada_ts=?, cerrada_ts=?, spread=?, slip=?, comision=?, costo_r=?, fill_sim=?,
          r_bruto=?, r_neto=?, mfe_r=?, mae_r=?, precio_ult=?, eventos=?, detalle=?, actualizado_ts=? WHERE id=?""",
       (nuevo, s.get("resultado"), s.get("activada_ts"), s.get("cerrada_ts"), sp, sl, co, costo, fill, r_bruto, r_neto,
        s.get("mfe_r"), s.get("mae_r"), s.get("precio_ult"), json.dumps(ev), json.dumps(det), _ahora(), t["id"]))
    for e in ev:
        _log_ejec(t["id"], e["t"], e["texto"])
    if fill is not None:
        _log_ejec(t["id"], s["activada_ts"], "Ejecución simulada: entrada teórica %.6g → fill simulado %.6g (spread %.4f%%, slippage %.4f%%/lado, comisión %.4f%%/lado; vol. relativo %s)" % (
            t["entrada"], fill, sp * 100, sl * 100, co * 100, (det.get("feat") or {}).get("vol_rel")))
    if r_neto is not None:
        _log_ejec(t["id"], s.get("cerrada_ts") or _ahora(), "Salida simulada (%s): %+.2f R bruto, costos %.2f R, %+.2f R neto" % (s.get("resultado"), r_bruto, costo, r_neto))
    t2 = dict(t, estado=nuevo, precio_ult=s.get("precio_ult"), resultado=s.get("resultado"))
    if alertar:
        try:
            _alertas_estado(t2, s, fill, sp, sl, co, r_bruto, r_neto, costo)
        except Exception as e:
            _err("alertas_estado", e)
    return nuevo


def _alertas_estado(t, s, fill, sp, sl, co, r_bruto, r_neto, costo):
    res, ts_c = s.get("resultado"), s.get("cerrada_ts")
    if s.get("activada_ts"):
        _alerta(t, "ENTRADA_ACTIVADA", "%s %s" % ("LONG" if t["direccion"] == 1 else "SHORT", t["mostrar"]),
                "Entrada teórica %.6g, fill simulado %.6g (spread %.4f%%, slippage %.4f%%, comisión %.4f%%/lado). Stop %.6g, TP1 %.6g, TP2 %.6g." % (
                    t["entrada"], fill, sp * 100, sl * 100, co * 100, t["stop"], t["tp1"], t["tp2"]), ts=s["activada_ts"], precio=t["entrada"])
    if s["estado"] == "activa_tp1" or res in ("tp1_be", "tp2"):
        _alerta(t, "TP1", "objetivo 1 en %.6g" % t["tp1"], "Alcanzado según velas %s; el stop pasa a la entrada." % t["eval_tf"], precio=t["tp1"])
    cierre = {"tp2": ("TP_ALCANZADO", "objetivo 2 en %.6g" % t["tp2"]), "stop": ("SL_ALCANZADO", "stop en %.6g" % t["stop"]),
              "tp1_be": ("STOP_EN_ENTRADA", "stop en la entrada %.6g" % t["entrada"]), "invalidada": ("INVALIDADA", "tocó el stop antes de entrar"),
              "contexto_invertido": ("INVALIDADA", "el contexto se invirtió antes de entrar"), "expirada_sin_entrada": ("EXPIRADA", "venció la ventana"),
              "tiempo_agotado": ("TIEMPO_AGOTADO", "se agotó la duración máxima")}.get(res)
    if cierre:
        ev = "Según velas %s." % t["eval_tf"]
        if r_neto is not None:
            ev += " Resultado %+.2f R bruto, %+.2f R neto (costos %.2f R)." % (r_bruto, r_neto, costo)
        _alerta(t, cierre[0], cierre[1], ev, ts=ts_c, precio=t.get("precio_ult"))
    if t["estado"] in ("ACTIVADA", "EN_SEGUIMIENTO") and t.get("precio_ult"):
        d, riesgo, px = t["direccion"], abs(t["entrada"] - t["stop"]) or 1e-9, t["precio_ult"]
        if t["estado"] == "ACTIVADA":
            prog = (px - t["entrada"]) * d / (abs(t["tp1"] - t["entrada"]) or 1e-9)
            if prog >= 0.8:
                _alerta(t, "OBJETIVO_PROXIMO", "precio %.6g, a %.0f%% del camino al objetivo 1" % (px, prog * 100), "TP1 en %.6g." % t["tp1"], precio=px)
            adv = (t["entrada"] - px) * d / riesgo
            if adv >= 0.75:
                _alerta(t, "STOP_PROXIMO", "precio %.6g, a %.0f%% del riesgo hacia el stop" % (px, adv * 100), "Stop en %.6g." % t["stop"], precio=px)


def _fila_trade(r):
    r = dict(r)
    r["eventos"] = json.loads(r.get("eventos") or "[]")
    r["detalle"] = json.loads(r.get("detalle") or "{}")
    return r


# ---------------------------------------------------------------------------- Motor A: espejo de los planes
def espejo_a():
    with plan_web._DBLOCK:
        c = plan_web._con()
        filas = [plan_web._fila(r) for r in c.execute("SELECT * FROM planes").fetchall()]
        c.close()
    n = 0
    for p in filas:
        try:
            ex = _q("SELECT * FROM lab_trades WHERE motor='A' AND origen_id=?", (p["id"],))
            P = plan_web.MODOS.get(p["modo"], {})
            if not ex:
                try:
                    a = _activo(p["simbolo"])
                except Exception:
                    a = {"clase": "accion"}
                det = {"razones": p["detalle"].get("razones"), "avisos": p["detalle"].get("avisos"), "resumen": p["detalle"].get("resumen"),
                       "entra_si": p["detalle"].get("entra_si"), "no_entres_si": p["detalle"].get("no_entres_si"), "sup": [],
                       "feat": {"total": (p["detalle"].get("puntos") or {}).get("total"), "tipo": p["tipo"], "dir": p["direccion"], "punt_n": None, "vol_rel": None},
                       "origen_act": 0}
                _w("""INSERT OR IGNORE INTO lab_trades(motor,origen_id,creado_ts,simbolo,mostrar,clase,fuente,modo,estrategia,trig,ctx,direccion,tipo,entrada,stop,tp1,tp2,r1,r2,atr,
                      valido_hasta,max_dur_s,eval_tf,eval_int,estado,eventos,detalle,modelo_ver,computa,actualizado_ts)
                      VALUES('A',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'PENDIENTE','[]',?,0,1,?)""",
                   (p["id"], p["creado_ts"], p["simbolo"], p["mostrar"], a.get("clase"), p["fuente"], p["modo"], "%s · %s" % (P.get("nombre", p["modo"]), p["tipo"]),
                    P.get("trig"), P.get("ctx"), p["direccion"], p["tipo"], p["entrada"], p["stop"], p["tp1"], p["tp2"], p["r1"], p["r2"], p["atr"],
                    p["valido_hasta"], p["max_dur_s"], p["eval_tf"], p["eval_int"], json.dumps(det), _ahora()))
                ex = _q("SELECT * FROM lab_trades WHERE motor='A' AND origen_id=?", (p["id"],))
                primera = True
            else:
                primera = False
            t = ex[0]
            det = json.loads(t["detalle"] or "{}")
            if not primera and det.get("origen_act") == p.get("actualizado_ts") and t["estado"] in ("CERRADA", "INVALIDADA", "CANCELADA"):
                continue
            rf = None
            if p["estado"] in ("activa", "activa_tp1") and p.get("precio_ult") is not None:
                rg = abs(p["entrada"] - p["stop"]) or 1e-9
                r = (p["precio_ult"] - p["entrada"]) * p["direccion"] / rg
                rf = (0.5 * p["r1"] + 0.5 * r) if p["estado"] == "activa_tp1" else r
            s = {"estado": p["estado"], "resultado": p["resultado"], "activada_ts": p["activada_ts"], "cerrada_ts": p["cerrada_ts"], "r_final": p["r_final"],
                 "r_flotante": rf, "mfe_r": p["mfe_r"], "mae_r": p["mae_r"], "precio_ult": p["precio_ult"], "eventos": p["eventos"]}
            _aplicar(t, s, alertar=not primera)
            det = json.loads(_q("SELECT detalle FROM lab_trades WHERE id=?", (t["id"],))[0]["detalle"] or "{}")
            det["origen_act"] = p.get("actualizado_ts")
            _w("UPDATE lab_trades SET detalle=? WHERE id=?", (json.dumps(det), t["id"]))
            n += 1
        except Exception as e:
            _err("espejo_a", e)
    return n


# ---------------------------------------------------------------------------- Motor B: abrir operaciones autonomas
def _abrir_b(a, modo, plan, modelo, feat):
    P = plan_web.MODOS[modo]
    computa = 1 if _pasa(modelo["params"], feat) else 0
    ev = [{"t": plan["creado_ts"], "texto": "Operación simulada creada por la Inteligencia Autónoma (precio %s)" % plan_web._n(plan["precio"])}]
    det = {"razones": plan["razones"], "avisos": plan["avisos"], "resumen": plan["resumen"], "entra_si": plan["entra_si"],
           "no_entres_si": plan["no_entres_si"], "feat": feat, "sup": []}
    _, tid = _w("""INSERT INTO lab_trades(motor,origen_id,creado_ts,simbolo,mostrar,clase,fuente,modo,estrategia,trig,ctx,direccion,tipo,entrada,stop,tp1,tp2,r1,r2,atr,
                   valido_hasta,max_dur_s,eval_tf,eval_int,estado,eventos,detalle,modelo_ver,computa,precio_ult,actualizado_ts)
                   VALUES('B',NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'PENDIENTE',?,?,?,?,?,?)""",
                (plan["creado_ts"], plan["simbolo"], plan["mostrar"], a.get("clase"), plan["fuente"], modo, "%s · %s" % (P["nombre"], plan["tipo"]),
                 plan["trig"], plan["ctx"], plan["direccion"], plan["tipo"], plan["entrada"], plan["stop"], plan["tp1"], plan["tp2"], plan["r1"], plan["r2"], plan["atr"],
                 plan["valido_hasta"], P["dur_s"], P["eval"][0], P["eval"][1], json.dumps(ev), json.dumps(det), modelo["ver"], computa, plan["precio"], _ahora()))
    _log_ejec(tid, plan["creado_ts"], ev[0]["texto"])
    return tid, computa


def ciclo_b():
    if cfg_get("b_activo", "1") != "1":
        _latido("motor_b", detalle="pausado por el usuario")
        return
    lista = registrados()
    if not lista:
        return
    zona, ahora = _zona(), _ahora()
    cur = int(cfg_get("cursor_b", "0")) % len(lista)
    lote = [lista[(cur + i) % len(lista)] for i in range(min(LOTE_B, len(lista)))]
    cfg_set("cursor_b", (cur + len(lote)) % len(lista))
    modelo = modelo_activo()
    analiz = nuevas = 0
    for a in lote:
        snap = False
        for modo in plan_web.MODOS:
            P = plan_web.MODOS[modo]
            try:
                plan = plan_web.analizar(a, modo, zona)
            except Exception as e:
                _err("motor_b:%s:%s" % (a["simbolo"], modo), e)
                continue
            analiz += 1
            pt = plan.get("puntos") or {}
            if not snap:
                _w("INSERT INTO lab_snapshots(ts,simbolo,mostrar,precio,atr_pct) VALUES(?,?,?,?,?)",
                   (ahora, a["simbolo"], plan.get("mostrar"), plan.get("precio"), (plan["atr"] / plan["precio"] * 100) if plan.get("precio") else None))
                snap = True
            tid, computa, razon = None, None, plan.get("titulo")
            if plan["accion"] != "esperar":
                ab = _q("SELECT id FROM lab_trades WHERE motor='B' AND simbolo=? AND modo=? AND estado IN " + SQL_ABIERTOS + " LIMIT 1", (a["simbolo"], modo))
                ult = _q("SELECT creado_ts FROM lab_trades WHERE motor='B' AND simbolo=? AND modo=? ORDER BY id DESC LIMIT 1", (a["simbolo"], modo))
                tot = _q("SELECT COUNT(*) c FROM lab_trades WHERE motor='B' AND estado IN " + SQL_ABIERTOS)[0]["c"]
                if ab:
                    razon = "Ya hay una operación abierta para este activo y modo."
                elif ult and ahora - ult[0]["creado_ts"] < 2 * P["vela_s"]:
                    razon = "Enfriamiento: operación reciente en este activo y modo."
                elif tot >= MAX_ABIERTAS_B:
                    razon = "Límite de operaciones abiertas del Motor B alcanzado."
                else:
                    vr = None
                    try:
                        vr = _vol_rel(chart_web.grafico(a, plan["trig"])["velas"])
                    except Exception:
                        pass
                    feat = {"total": pt.get("total"), "ctx": pt.get("contexto"), "gat": pt.get("gatillo"), "tipo": plan["tipo"], "dir": plan["direccion"],
                            "punt_n": _noticias_punt(a["simbolo"]), "vol_rel": vr}
                    tid, computa = _abrir_b(a, modo, plan, modelo, feat)
                    nuevas += 1
                    razon = plan["titulo"] + (" · cuenta para el modelo v%s" % modelo["ver"] if computa else " · operación sombra (no pasa el filtro del modelo v%s)" % modelo["ver"])
            _w("INSERT INTO lab_decisiones(ts,motor,simbolo,modo,trig,accion,total,ctx,gat,precio,atr,trade_id,computa,razon) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (ahora, "B", a["simbolo"], modo, plan.get("trig"), plan["accion"], pt.get("total"), pt.get("contexto"), pt.get("gatillo"), plan.get("precio"), plan.get("atr"), tid, computa, razon))
    _latido("motor_b", detalle="lote %s · %d análisis · %d operaciones nuevas" % (",".join(x["simbolo"] for x in lote), analiz, nuevas))


# ---------------------------------------------------------------------------- Supervisor
def _simular_abiertas_b():
    ahora = _ahora()
    n = 0
    for r in _q("SELECT * FROM lab_trades WHERE motor='B' AND estado IN " + SQL_ABIERTOS):
        t = _fila_trade(r)
        try:
            p = {"direccion": t["direccion"], "entrada": t["entrada"], "stop": t["stop"], "tp1": t["tp1"], "tp2": t["tp2"], "r1": t["r1"], "r2": t["r2"],
                 "creado_ts": t["creado_ts"], "valido_hasta": t["valido_hasta"], "tipo": t["tipo"], "max_dur_s": t["max_dur_s"], "precio_ult": t["precio_ult"]}
            rango = plan_web._rango_eval(t["eval_int"], ahora - t["creado_ts"])
            velas = plan_web._velas_eval(t["fuente"], t["eval_int"], rango)
            s = plan_web.simular(p, velas, ahora)
            t["detalle"] = json.dumps(t["detalle"])
            _aplicar(dict(t), s)
            n += 1
        except Exception as e:
            _err("simular_b:%s" % t["id"], e)
    return n


def _lect(a, tf):
    g = chart_web.grafico(a, tf)
    v = g["velas"]
    return g, v, plan_web._lectura(v)


def revisar_contexto():
    ahora = _ahora()
    for r in _q("SELECT * FROM lab_trades WHERE estado IN " + SQL_ABIERTOS):
        t = _fila_trade(r)
        det = t["detalle"]
        if ahora - det.get("ctx_ts", 0) < 120:
            continue
        try:
            a, d = _activo(t["simbolo"]), t["direccion"]
            gt, vt, Lt = _lect(a, t["trig"])
            gc, vc, Lc = _lect(a, t["ctx"])
            st, sc = plan_web._score_trg(Lt), plan_web._score_ctx(Lc)
            vr = _vol_rel(vt)
            try:
                ratio = Lt["atr"] / plan_web._atr(vt[:-14])
            except Exception:
                ratio = None
            extra = " Volumen relativo %s; volatilidad %s." % ("%.2f" % vr if vr is not None else "n/d", ("x%.2f vs. previa" % ratio) if ratio else "n/d")
            ev_base = "Puntuación gatillo %+d/±4, contexto %+d/±3 (opera %s).%s" % (st, sc, "LONG" if d == 1 else "SHORT", extra)
            px = Lt["c"]
            if d * st <= -2:
                _alerta(t, "CAMBIO_TENDENCIA", "el gatillo %s se dio la vuelta" % t["trig"], ev_base, precio=px)
            if (d == 1 and Lt["rsi"] >= 78) or (d == -1 and Lt["rsi"] <= 22):
                _alerta(t, "REVERSION", "RSI %.0f en %s" % (Lt["rsi"], t["trig"]), ev_base, precio=px)
            k = max(5, plan_web.MODOS.get(t["modo"], {}).get("niv", 24) // 4)
            ref = vt[-k - 2:-2]
            if len(ref) >= 3 and ((d == 1 and vt[-2][4] < min(x[3] for x in ref)) or (d == -1 and vt[-2][4] > max(x[2] for x in ref))):
                _alerta(t, "ESTRUCTURA", "una vela %s cerró %s el %s de las últimas %d velas" % (t["trig"], "bajo el mínimo" if d == 1 else "sobre el máximo", "mínimo" if d == 1 else "máximo", len(ref)), ev_base, precio=px)
            if d * sc <= -2:
                if t["motor"] == "B" and t["estado"] == "PENDIENTE":
                    _invalidar_b(t, "El contexto %s se invirtió antes de la entrada (puntuación %+d)." % (t["ctx"], sc), px)
                    continue
                _alerta(t, "CONTEXTO_ADVERSO", "el contexto %s ya es adverso (puntuación %+d)" % (t["ctx"], sc), ev_base, precio=px)
            det["ctx_ts"], det["ctx_lectura"] = ahora, {"st": st, "sc": sc, "rsi": round(Lt["rsi"], 1)}
            _w("UPDATE lab_trades SET detalle=? WHERE id=?", (json.dumps(det), t["id"]))
        except Exception as e:
            _err("contexto:%s" % t["simbolo"], e)


def _invalidar_b(t, texto, px):
    ahora = _ahora()
    ev = t["eventos"] + [{"t": ahora, "texto": texto}]
    s = {"estado": "cerrada", "resultado": "contexto_invertido", "activada_ts": None, "cerrada_ts": ahora, "r_final": 0.0,
         "mfe_r": t.get("mfe_r"), "mae_r": t.get("mae_r"), "precio_ult": px, "eventos": ev}
    t2 = dict(t, detalle=json.dumps(t["detalle"]))
    _aplicar(t2, s)


def ciclo_supervisor():
    a = espejo_a()
    b = _simular_abiertas_b()
    revisar_contexto()
    _latido("supervisor", detalle="espejo A: %d · simuladas B: %d" % (a, b))


# ============================================================================ Inteligencia de noticias
CATEGORIAS = [
    ("banco_central", r"\b(fed|federal reserve|fomc|powell|ecb|lagarde|boj|bank of england|central bank|rate cut|rate hike|interest rate)\b"),
    ("macro", r"\b(inflation|cpi|ppi|gdp|payrolls|jobs report|unemployment|pmi|retail sales|treasury yield)\b"),
    ("regulacion", r"\b(sec|regulat\w*|lawsuit|etf approval|ban|tariffs?|sanctions?)\b"),
    ("geopolitica", r"\b(war|ceasefire|missile|election|geopolit\w*|conflict|opec|tensions?)\b"),
    ("corporativo", r"\b(earnings|revenue|guidance|ceo|merger|acquisition|buyback|dividend|quarterly|results)\b"),
    ("cripto", r"\b(bitcoin|crypto\w*|ethereum|binance|stablecoin)\b"),
]


def _categoria(titulo):
    for nombre, rx in CATEGORIAS:
        if re.search(rx, titulo or "", re.I):
            return nombre
    return "general"


def ciclo_noticias():
    lista = registrados()
    if not lista:
        return
    cur = int(cfg_get("cursor_n", "0")) % len(lista)
    lote = [lista[(cur + i) % len(lista)] for i in range(min(LOTE_NOTICIAS, len(lista)))]
    cfg_set("cursor_n", (cur + len(lote)) % len(lista))
    nuevas = 0
    for a in lote:
        try:
            nots = agente.noticias_activo(a, 48)
        except Exception as e:
            _err("noticias:%s" % a["simbolo"], e)
            continue
        for n in nots:
            clave = re.sub(r"\W+", " ", n["titulo"].lower()).strip()
            huella = hashlib.sha1((a["simbolo"] + "|" + clave).encode()).hexdigest()
            try:
                fts = int(datetime.fromisoformat(n["fecha"]).timestamp())
            except Exception:
                continue
            ins, _ = _w("""INSERT OR IGNORE INTO lab_noticias(huella,ts,simbolo,titulo,fuente,fecha_ts,enlace,impacto,fuerza,motivo,categoria)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        (huella, _ahora(), a["simbolo"], n["titulo"][:300], n.get("fuente"), fts, n.get("enlace"), n["impacto"], n["fuerza"], n.get("motivo"), _categoria(n["titulo"])))
            if ins:
                nuevas += 1
                if n["fuerza"] >= 2:
                    _alerta({"id": None, "motor": None, "simbolo": a["simbolo"], "mostrar": chart_web.ETIQUETA.get(a["simbolo"], a["simbolo"]), "trig": None,
                             "estrategia": "Noticias", "direccion": 0, "entrada": 0, "stop": 0, "precio_ult": None},
                            "NOTICIA", n["titulo"][:140], "Fuente: %s. Impacto estimado %s (fuerza %d; términos: %s). Clasificación por palabras clave, no es una confirmación." % (
                                n.get("fuente") or "n/d", {1: "alcista", -1: "bajista", 0: "neutro"}[n["impacto"]], n["fuerza"], n.get("motivo") or "—"),
                            ts=fts, clave="N:" + huella)
    _latido("noticias", detalle="lote %s · %d noticias nuevas" % (",".join(x["simbolo"] for x in lote), nuevas))


def evaluar_noticias():
    """Mide el movimiento POSTERIOR a cada noticia (sin usar informacion anterior ni futura al momento de la noticia)."""
    ahora = _ahora()
    pend = _q("SELECT * FROM lab_noticias WHERE evaluada=0 AND fecha_ts<=? ORDER BY fecha_ts LIMIT 60", (ahora - 5 * 3600,))
    por_sim = {}
    for n in pend:
        por_sim.setdefault(n["simbolo"], []).append(n)
    hechas = 0
    for sim, ns in por_sim.items():
        try:
            barras = _cacheado(("barras", sim), 600, lambda s=sim: agente.barras(s, "1mo", "60m"))
        except Exception as e:
            _err("eval_noticias:%s" % sim, e)
            continue
        for n in ns:
            idx = next((i for i, b in enumerate(barras) if b["t"] >= n["fecha_ts"]), None)
            if idx is None or idx + 3 >= len(barras):
                if n["fecha_ts"] < barras[0]["t"]:
                    _w("UPDATE lab_noticias SET evaluada=2 WHERE huella=?", (n["huella"],))
                continue
            ref = barras[idx]["o"]
            m1, m4 = (barras[idx]["c"] / ref - 1) * 100, (barras[idx + 3]["c"] / ref - 1) * 100
            sg = lambda x: (x > 0) - (x < 0)
            ok1 = (1 if sg(m1) == n["impacto"] else 0) if n["impacto"] and m1 else None
            ok4 = (1 if sg(m4) == n["impacto"] else 0) if n["impacto"] and m4 else None
            _w("UPDATE lab_noticias SET evaluada=1, mov_1h=?, mov_4h=?, ok_1h=?, ok_4h=? WHERE huella=?", (round(m1, 4), round(m4, 4), ok1, ok4, n["huella"]))
            hechas += 1
    return hechas


# ============================================================================ estadistica y metricas
def _wilson(k, n, z=1.96):
    if not n:
        return None, None
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, c - h), min(1.0, c + h)


def _exp(ts):
    return sum(t["r_neto"] for t in ts) / len(ts) if ts else None


def _mdd(ts):
    eq = peak = mdd = 0.0
    for t in ts:
        eq += t["r_neto"]
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    return mdd


def metricas(ts):
    """ts: operaciones cerradas con r_neto, ordenadas por cierre. Devuelve metricas con su tamano de muestra."""
    n = len(ts)
    out = {"n": n, "periodo": [ts[0]["cerrada_ts"], ts[-1]["cerrada_ts"]] if n else None, "muestra_suficiente": n >= MIN_N}
    if not n:
        return out
    rs = [t["r_neto"] for t in ts]
    gan, per = [r for r in rs if r > 0.05], [r for r in rs if r < -0.05]
    lo, hi = _wilson(len(gan), n)
    out.update(win_rate=round(len(gan) / n, 4), win_rate_ic=[lo and round(lo, 3), hi and round(hi, 3)], expectancy=round(sum(rs) / n, 3),
               profit_factor=round(sum(gan) / abs(sum(per)), 3) if per else None, r_total=round(sum(rs), 2), max_drawdown_r=round(_mdd(ts), 2))
    mf = [t for t in ts if t.get("mfe_r") is not None and t.get("mae_r") is not None]
    if mf:
        out["precision_direccional"] = round(sum(1 for t in mf if t["mfe_r"] > abs(t["mae_r"])) / len(mf), 3)
        out["calidad_entrada"] = {"mae_medio_r": round(sum(abs(t["mae_r"]) for t in mf) / len(mf), 3), "pct_mae_menor_0_5r": round(sum(1 for t in mf if abs(t["mae_r"]) < 0.5) / len(mf), 3)}
        cap = [max(-1.0, min(1.0, t["r_bruto"] / t["mfe_r"])) for t in mf if t["mfe_r"] > 0.2 and t.get("r_bruto") is not None]
        out["calidad_salida"] = {"captura_media_del_mfe": round(sum(cap) / len(cap), 3), "n": len(cap)} if cap else None
    if n >= MIN_N:
        k = 4
        bloques = [ts[i * n // k:(i + 1) * n // k] for i in range(k)]
        out["estabilidad"] = {"bloques_positivos": sum(1 for b in bloques if b and _exp(b) > 0), "bloques": k, "desv_r": round(math.sqrt(sum((r - sum(rs) / n) ** 2 for r in rs) / n), 3)}
    if n >= MIN_OOS:
        cut = int(n * 0.7)
        out["fuera_de_muestra"] = {"n_entrenamiento": cut, "expectancy_entrenamiento": round(_exp(ts[:cut]), 3), "n_prueba": n - cut, "expectancy_prueba": round(_exp(ts[cut:]), 3)}
    if n >= MIN_WF:
        res, i = [], 0
        while i + 45 <= n:
            res.append(_exp(ts[i + 30:i + 45]))
            i += 15
        if res:
            out["walk_forward"] = {"ventanas": len(res), "expectancy_media_prueba": round(sum(res) / len(res), 3), "ventanas_positivas": sum(1 for x in res if x > 0), "ventana": "30 entrenamiento + 15 prueba"}
    return out


def _cerradas(motor, solo_modelo=True):
    sql = "SELECT * FROM lab_trades WHERE estado='CERRADA' AND resultado IN " + SQL_RES + " AND r_neto IS NOT NULL AND motor=?"
    if motor == "B" and solo_modelo:
        sql += " AND computa=1"
    rows = _q(sql + " ORDER BY cerrada_ts, id", (motor,))
    for r in rows:
        r["detalle"] = json.loads(r.get("detalle") or "{}")
    return rows


def _grupo(ts, clave):
    g = {}
    for t in ts:
        g.setdefault(clave(t), []).append(t)
    return {k: dict(metricas(v), **{"clave": k}) for k, v in sorted(g.items(), key=lambda kv: -len(kv[1]))}


def paquete_metricas():
    def alcance(ts):
        eq, acc = [], 0.0
        for t in ts:
            acc += t["r_neto"]
            eq.append([t["cerrada_ts"], round(acc, 3)])
        if len(eq) > 300:
            paso = len(eq) / 300
            eq = [eq[int(i * paso)] for i in range(300)] + [eq[-1]]
        return {"global": metricas(ts), "por_estrategia": _grupo(ts, lambda t: t["estrategia"]), "por_activo": _grupo(ts, lambda t: t["mostrar"] or t["simbolo"]),
                "por_temporalidad": _grupo(ts, lambda t: t["trig"] or "?"), "equity": eq}
    return {"A": alcance(_cerradas("A")), "B": alcance(_cerradas("B", True)), "B_todas": alcance(_cerradas("B", False)),
            "definiciones": {
                "r": "Resultados en múltiplos de riesgo (R): 1 R = distancia entrada–stop. No hay capital simulado definido; no se inventa un saldo.",
                "neto": "R neto = R bruto – costo estimado de spread, slippage y comisión (supuestos configurables, no medidos).",
                "win_rate": "Operaciones cerradas con R neto > +0.05, sobre las operaciones cerradas que se activaron. Se muestra con intervalo de Wilson 95%.",
                "precision_direccional": "Porcentaje de operaciones cuyo movimiento favorable máximo superó al adverso (MFE > |MAE|).",
                "calidad_entrada": "MAE medio en R: cuánto fue en contra el precio tras entrar (menor es mejor).",
                "calidad_salida": "Fracción media del movimiento favorable máximo que se capturó al cerrar (–1 a 1).",
                "fuera_de_muestra": "70%% cronológico para entrenar y 30%% final para probar; requiere al menos %d operaciones." % MIN_OOS,
                "walk_forward": "Ventanas consecutivas de 30 operaciones de entrenamiento y 15 de prueba; requiere al menos %d operaciones." % MIN_WF,
                "min_muestra": "Con menos de %d operaciones cerradas, las cifras son meramente descriptivas." % MIN_N}}


# ============================================================================ Learning Engine
def detectar_patrones():
    ts = _cerradas("B", False)
    ahora = _ahora()
    grupos = {}
    for t in ts:
        f = t["detalle"].get("feat") or {}
        for nombre, clave in (("Estrategia+dirección", (t["modo"], t["direccion"], t["tipo"])), ("Activo+modo", (t["simbolo"], t["modo"])), ("Activo+dirección", (t["simbolo"], t["direccion"]))):
            grupos.setdefault((nombre,) + clave, []).append(t)
    _w("DELETE FROM lab_patrones")
    hallados = 0
    for clave, v in grupos.items():
        if len(v) < MIN_PATRON:
            continue
        gan = sum(1 for t in v if t["r_neto"] > 0.05)
        lo, _ = _wilson(gan, len(v))
        e = _exp(v)
        mitad = len(v) // 2
        cons = 1 if (_exp(v[:mitad]) > 0 and _exp(v[mitad:]) > 0) else 0
        estado = "candidato consistente" if (len(v) >= MIN_N and e > 0 and lo > 0.5 and cons) else "descriptivo (no validado)"
        desc = " · ".join(str(x) if not isinstance(x, int) else ("LONG" if x == 1 else "SHORT" if x == -1 else str(x)) for x in clave)
        _w("INSERT INTO lab_patrones(ts,clave,descripcion,n,win_rate,wilson_low,expectancy,consistente,estado) VALUES(?,?,?,?,?,?,?,?,?)",
           (ahora, json.dumps(clave, ensure_ascii=False), desc, len(v), round(gan / len(v), 4), round(lo, 4), round(e, 3), cons, estado))
        hallados += 1
    return hallados


def resumen_errores():
    todas = []
    for m in ("A", "B"):
        todas += _q("SELECT * FROM lab_trades WHERE motor=? AND estado IN ('CERRADA','INVALIDADA')", (m,))
    out = {"ruptura_falsa": 0, "entrada_lejana_expiro": 0, "contexto_invertido": 0, "noticias_en_contra_y_stop": 0, "stop_total": 0}
    for t in todas:
        det = json.loads(t.get("detalle") or "{}")
        f = det.get("feat") or {}
        if t["resultado"] == "stop":
            out["stop_total"] += 1
            if t["tipo"] == "ruptura" and (t.get("mfe_r") or 0) < 0.3:
                out["ruptura_falsa"] += 1
            if f.get("punt_n") is not None and f["punt_n"] * t["direccion"] < 0:
                out["noticias_en_contra_y_stop"] += 1
        elif t["resultado"] == "expirada_sin_entrada":
            out["entrada_lejana_expiro"] += 1
        elif t["resultado"] == "contexto_invertido":
            out["contexto_invertido"] += 1
    out["n_operaciones_revisadas"] = len(todas)
    out["errores_tecnicos"] = _q("SELECT modulo, COUNT(*) n, MAX(ts) ultimo, MAX(mensaje) mensaje FROM lab_errores GROUP BY modulo ORDER BY n DESC LIMIT 12")
    return out


def evaluar_candidatas():
    """Optimizacion CONTROLADA: elige con el tramo de entrenamiento, valida en el tramo final (fuera de muestra) y solo promueve
    si mejora de forma material. Una sola operacion nunca cambia una regla."""
    ts = _cerradas("B", False)
    n = len(ts)
    if n < MIN_CAND:
        _aprende("optimizacion", "Sin cambios de modelo: %d operaciones cerradas del Motor B (se piden al menos %d para evaluar candidatos)." % (n, MIN_CAND))
        return
    if n - int(cfg_get("cand_n", "0")) < 15:
        return
    cfg_set("cand_n", n)
    act = modelo_activo()
    base = act["params"]
    cut = int(n * 0.7)
    train, test = ts[:cut], ts[cut:]
    mejor = None
    for ms in (3, 4, 5):
        for tp in ("todos", "ruptura", "retroceso"):
            for nt in ("libre", "no_contra"):
                p = {"min_abs_total": ms, "tipo": tp, "noticias": nt}
                if p == {k: base.get(k) for k in p}:
                    continue
                sel = [t for t in train if _pasa(p, t["detalle"].get("feat") or {})]
                if len(sel) < 20:
                    continue
                e = _exp(sel)
                if mejor is None or e > mejor[1]:
                    mejor = (p, e, len(sel))
    if not mejor:
        _aprende("optimizacion", "Ningún candidato reunió 20 operaciones de entrenamiento.")
        return
    p = mejor[0]
    tc = [t for t in test if _pasa(p, t["detalle"].get("feat") or {})]
    tb = [t for t in test if _pasa(base, t["detalle"].get("feat") or {})]
    met = {"candidato": p, "entrenamiento": {"n": mejor[2], "expectancy": round(mejor[1], 3)},
           "prueba_candidato": {"n": len(tc), "expectancy": round(_exp(tc), 3) if tc else None, "mdd": round(_mdd(tc), 2) if tc else None},
           "prueba_estable": {"n": len(tb), "expectancy": round(_exp(tb), 3) if tb else None, "mdd": round(_mdd(tb), 2) if tb else None},
           "nota": "Se compararon 17 combinaciones: riesgo de sobreajuste; por eso se exige mejora fuera de muestra."}
    ult = _q("SELECT MAX(creado_ts) m FROM lab_modelos WHERE estado IN ('ESTABLE','ANTERIOR','REVERTIDA') AND ver>1")[0]["m"] or 0
    enfriado = _ahora() - ult >= 7 * 86400
    ok = bool(tc and tb and len(tc) >= 10 and _exp(tc) >= _exp(tb) + 0.10 and _exp(tc) > 0 and _mdd(tc) <= _mdd(tb) * 1.1 + 0.5 and enfriado)
    ver = (_q("SELECT MAX(ver) m FROM lab_modelos")[0]["m"] or 1) + 1
    if ok:
        _w("UPDATE lab_modelos SET estado='ANTERIOR' WHERE estado='ESTABLE'")
        newp = dict(p, previo=base)
        _w("INSERT INTO lab_modelos(ver,creado_ts,params,estado,notas,metricas) VALUES(?,?,?,?,?,?)", (ver, _ahora(), json.dumps(newp), "ESTABLE", "Promovido tras validación fuera de muestra.", json.dumps(met)))
        _aprende("modelo", "Modelo v%d promovido: %s. Prueba fuera de muestra: %+.2f R (n=%d) vs. %+.2f R (n=%d) del modelo anterior." % (ver, json.dumps(p), _exp(tc), len(tc), _exp(tb), len(tb)))
    else:
        motivo = "no cumple la mejora mínima (+0.10 R), tamaño de prueba (≥10), drawdown o enfriamiento de 7 días" if not (tc and tb) or True else ""
        _w("INSERT INTO lab_modelos(ver,creado_ts,params,estado,notas,metricas) VALUES(?,?,?,?,?,?)", (ver, _ahora(), json.dumps(p), "RECHAZADA", "Candidato rechazado: " + motivo, json.dumps(met)))
        _aprende("optimizacion", "Candidato %s rechazado fuera de muestra (prueba n=%d). Se mantiene el modelo v%d." % (json.dumps(p), len(tc), act["ver"]))


def revisar_reversion():
    act = modelo_activo()
    prev = act["params"].get("previo")
    if act["ver"] <= 1 or not prev:
        return
    desde = [t for t in _cerradas("B", False) if t["creado_ts"] >= act["creado_ts"]]
    if len(desde) < 20:
        return
    ea = _exp([t for t in desde if _pasa(act["params"], t["detalle"].get("feat") or {})])
    ep = _exp([t for t in desde if _pasa(prev, t["detalle"].get("feat") or {})])
    if ea is not None and ep is not None and ea < ep - 0.10:
        ver = (_q("SELECT MAX(ver) m FROM lab_modelos")[0]["m"] or 1) + 1
        _w("UPDATE lab_modelos SET estado='REVERTIDA', notas=? WHERE id=?", ("Revertido: en %d operaciones posteriores rindió %+.2f R vs. %+.2f R del modelo previo." % (len(desde), ea, ep), act["id"]))
        _w("INSERT INTO lab_modelos(ver,creado_ts,params,estado,notas,metricas) VALUES(?,?,?,?,?,?)", (ver, _ahora(), json.dumps(prev), "ESTABLE", "Reversión automática al modelo previo.", "{}"))
        _aprende("reversion", "Modelo v%d revertido: rindió %+.2f R frente a %+.2f R del anterior en %d operaciones posteriores." % (act["ver"], ea, ep, len(desde)))


def ciclo_aprendizaje():
    ev = evaluar_noticias()
    pat = detectar_patrones()
    paq = paquete_metricas()
    _w("INSERT INTO lab_metricas(ts,alcance,datos) VALUES(?,?,?)", (_ahora(), "resumen", json.dumps({k: paq[k]["global"] for k in ("A", "B", "B_todas")})))
    revisar_reversion()
    evaluar_candidatas()
    nB, nA = paq["B_todas"]["global"]["n"], paq["A"]["global"]["n"]
    _aprende("ciclo", "Ciclo de aprendizaje: %d operaciones cerradas del Motor B, %d del Motor A, %d noticias evaluadas, %d patrones con muestra ≥%d. %s" % (
        nB, nA, ev or 0, pat, MIN_PATRON, "Muestra aún insuficiente para sacar conclusiones." if max(nA, nB) < MIN_N else "Hay muestra mínima; las conclusiones siguen siendo estadísticas, no garantías."))
    for tabla, tope in (("lab_snapshots", 20000), ("lab_decisiones", 30000), ("lab_errores", 3000), ("lab_aprendizaje", 400), ("lab_metricas", 600)):
        _w("DELETE FROM %s WHERE id NOT IN (SELECT id FROM %s ORDER BY id DESC LIMIT %d)" % (tabla, tabla, tope))
    _latido("aprendizaje", detalle="%d patrones · %d noticias evaluadas" % (pat, ev or 0))


# ============================================================================ hilos
def _bucle(nombre, fn, periodo, retraso):
    time.sleep(retraso)
    while True:
        try:
            fn()
        except Exception as e:
            _err(nombre, e)
            try:
                _latido(nombre, error=(type(e).__name__ + ": " + str(e))[:200])
            except Exception:
                pass
        time.sleep(periodo)


def iniciar():
    init_db()
    for nombre, fn, per, ret in (("supervisor", ciclo_supervisor, P_SUPERVISOR, 6), ("motor_b", ciclo_b, P_MOTOR_B, 25),
                                 ("noticias", ciclo_noticias, P_NOTICIAS, 50), ("aprendizaje", ciclo_aprendizaje, P_APRENDIZAJE, 150)):
        h = _HILOS.get(nombre)
        if h and h.is_alive():
            continue
        t = threading.Thread(target=_bucle, args=(nombre, fn, per, ret), name="titan-lab-" + nombre, daemon=True)
        t.start()
        _HILOS[nombre] = t


# ============================================================================ API
def _conteos():
    out = {"A": {}, "B": {}}
    for r in _q("SELECT motor, estado, COUNT(*) n FROM lab_trades GROUP BY motor, estado"):
        out[r["motor"]][r["estado"]] = r["n"]
    return out


def estado_general():
    ahora = _ahora()
    proc = {p["nombre"]: p for p in _q("SELECT * FROM lab_procesos")}
    hilos = {k: bool(v and v.is_alive()) for k, v in _HILOS.items()}
    cont = _conteos()
    reg = registrados()
    estudiados = _q("SELECT COUNT(DISTINCT simbolo) c FROM lab_snapshots WHERE ts>=?", (ahora - 86400,))[0]["c"]
    pnl = {}
    for m in ("A", "B"):
        r = _q("SELECT COUNT(*) n, COALESCE(SUM(r_neto),0) s, COALESCE(SUM(CASE WHEN r_neto>0.05 THEN 1 ELSE 0 END),0) g FROM lab_trades WHERE motor=? AND estado='CERRADA' AND r_neto IS NOT NULL AND (motor='A' OR computa=1)", (m,))[0]
        fl = _q("SELECT detalle FROM lab_trades WHERE motor=? AND estado IN ('ACTIVADA','EN_SEGUIMIENTO')", (m,))
        flot = sum((json.loads(x["detalle"] or "{}").get("r_flot") or 0) for x in fl)
        pnl[m] = {"cerradas": r["n"], "r_neto_total": round(r["s"], 2), "ganadoras": r["g"], "r_flotante": round(flot, 2)}
    nt = _q("SELECT COUNT(*) total, COALESCE(SUM(evaluada=1),0) evaluadas, COALESCE(SUM(fecha_ts>=?),0) h24 FROM lab_noticias", (ahora - 86400,))[0]
    vig = plan_web._VIG
    return {"ok": True, "ahora": ahora,
            "motor_a": {"vigilante_planes": bool(vig["hilo"] and vig["hilo"].is_alive()), "ultimo_ts": vig["ultimo"], "abiertas": sum(cont["A"].get(e, 0) for e in ABIERTOS)},
            "motor_b": {"activo": cfg_get("b_activo", "1") == "1", "hilo_vivo": hilos.get("motor_b", False), "ultimo_ts": (proc.get("motor_b") or {}).get("ultimo_ts"),
                        "detalle": (proc.get("motor_b") or {}).get("detalle"), "periodo_s": P_MOTOR_B, "lote": LOTE_B, "abiertas": sum(cont["B"].get(e, 0) for e in ABIERTOS)},
            "activos": {"registrados": len(reg), "estudiados_24h": estudiados}, "conteos": cont, "resultados": pnl,
            "noticias": {"total": nt["total"], "evaluadas": nt["evaluadas"], "ultimas_24h": nt["h24"]},
            "alertas_sin_leer": _q("SELECT COUNT(*) c FROM lab_alertas WHERE leida=0")[0]["c"],
            "procesos": [dict(proc[k], hilo_vivo=hilos.get(k)) for k in ("supervisor", "motor_b", "noticias", "aprendizaje") if k in proc] +
                        [{"nombre": k, "ultimo_ts": None, "hilo_vivo": v, "detalle": "aún sin ciclos"} for k, v in hilos.items() if k not in proc],
            "modelo": {"ver": modelo_activo()["ver"], "params": modelo_activo()["params"]},
            "aviso": "Simulación interna con precios de Yahoo Finance. Sin órdenes reales, sin brokers. Resultados en R, no en dinero."}


def listar_trades(motor="", estado="todas", simbolo="", limite=40):
    sql, args = "SELECT * FROM lab_trades WHERE 1=1", []
    if motor in ("A", "B"):
        sql += " AND motor=?"; args.append(motor)
    if estado == "abiertas":
        sql += " AND estado IN " + SQL_ABIERTOS
    elif estado == "cerradas":
        sql += " AND estado NOT IN " + SQL_ABIERTOS
    if simbolo:
        sql += " AND simbolo=?"; args.append(simbolo.upper())
    rows = _q(sql + " ORDER BY id DESC LIMIT ?", tuple(args) + (max(1, min(int(limite), 100)),))
    out = []
    for r in rows:
        t = _fila_trade(r)
        t["eventos"] = sorted(t["eventos"] + t["detalle"].get("sup", []), key=lambda e: e["t"])
        t["ejecuciones"] = _q("SELECT t, texto FROM lab_ejecuciones WHERE trade_id=? ORDER BY t, id", (t["id"],))
        out.append(t)
    return out


def listar_alertas(limite=40, solo_sin_leer=False):
    sql = "SELECT * FROM lab_alertas" + (" WHERE leida=0" if solo_sin_leer else "") + " ORDER BY ts DESC, id DESC LIMIT ?"
    return _q(sql, (max(1, min(int(limite), 100)),))


def resumen_noticias():
    st = _q("""SELECT COUNT(*) n, COALESCE(SUM(ok_1h IS NOT NULL),0) n1, COALESCE(SUM(ok_1h),0) a1, COALESCE(SUM(ok_4h IS NOT NULL),0) n4, COALESCE(SUM(ok_4h),0) a4
               FROM lab_noticias WHERE evaluada=1""")[0]
    f = {"evaluadas": st["n"]}
    for h, n, a in (("1h", st["n1"], st["a1"]), ("4h", st["n4"], st["a4"])):
        lo, hi = _wilson(a, n)
        f["acierto_" + h] = {"n": n, "aciertos": a, "tasa": round(a / n, 3) if n else None, "ic95": [lo and round(lo, 3), hi and round(hi, 3)], "muestra_suficiente": n >= MIN_N}
    f["por_categoria"] = _q("SELECT categoria, COUNT(*) n, COALESCE(SUM(ok_4h IS NOT NULL),0) n4, COALESCE(SUM(ok_4h),0) a4 FROM lab_noticias GROUP BY categoria ORDER BY n DESC")
    f["recientes"] = _q("SELECT simbolo, titulo, fuente, fecha_ts, impacto, fuerza, categoria, mov_1h, mov_4h FROM lab_noticias ORDER BY fecha_ts DESC LIMIT 25")
    f["nota"] = "El acierto mide si el signo del movimiento horario posterior coincide con el impacto estimado por palabras clave. Con muestra pequeña no demuestra nada."
    return f


def paquete_aprendizaje():
    paq = _cacheado("paq", 20, paquete_metricas)
    mejores = []
    for g in paq["B_todas"]["por_estrategia"].values():
        if g["n"] >= MIN_N:
            mejores.append({"estrategia": g["clave"], "n": g["n"], "expectancy": g.get("expectancy")})
    mejores.sort(key=lambda x: -(x["expectancy"] or -9))
    return {"ok": True, "noticias": resumen_noticias(), "patrones": _q("SELECT * FROM lab_patrones ORDER BY (estado LIKE 'candidato%') DESC, n DESC LIMIT 25"),
            "errores": resumen_errores(),
            "modelos": [dict(m, params=json.loads(m["params"]), metricas=json.loads(m["metricas"] or "{}")) for m in _q("SELECT * FROM lab_modelos ORDER BY ver DESC LIMIT 15")],
            "actividad": _q("SELECT ts, tipo, texto FROM lab_aprendizaje ORDER BY id DESC LIMIT 30"),
            "tecnico": {"operaciones_cerradas_B": paq["B_todas"]["global"]["n"], "operaciones_cerradas_A": paq["A"]["global"]["n"],
                        "estrategias_con_muestra_suficiente": mejores,
                        "conclusion": ("Aún no hay estrategias con muestra suficiente (≥%d cerradas); no se afirma ningún aprendizaje." % MIN_N) if not mejores else "Resultados descriptivos por estrategia con muestra ≥%d." % MIN_N},
            "decisiones_recientes": _q("SELECT ts, simbolo, modo, accion, total, computa, razon FROM lab_decisiones ORDER BY id DESC LIMIT 15")}


def _qs(ruta_completa):
    return {k: v[0] for k, v in parse_qs(urlparse(ruta_completa).query).items()}


def manejar_get(h, ruta):
    """Devuelve True si atendio la ruta. h es el Handler de api_web (usa h.enviar_json)."""
    if not ruta.startswith("/api/lab/"):
        return False
    q = _qs(h.path)
    try:
        if ruta == "/api/lab/estado":
            h.enviar_json(200, estado_general())
        elif ruta == "/api/lab/trades":
            h.enviar_json(200, {"ok": True, "trades": listar_trades(q.get("motor", ""), q.get("estado", "todas"), q.get("symbol", ""), q.get("limit", 40))})
        elif ruta == "/api/lab/alertas":
            h.enviar_json(200, {"ok": True, "alertas": listar_alertas(q.get("limit", 40), q.get("unread") == "1")})
        elif ruta == "/api/lab/metricas":
            h.enviar_json(200, dict(_cacheado("paq", 20, paquete_metricas), ok=True))
        elif ruta == "/api/lab/aprendizaje":
            h.enviar_json(200, paquete_aprendizaje())
        else:
            h.enviar_json(404, {"ok": False, "error": "Endpoint del laboratorio desconocido."})
    except Exception as e:
        _err("api_get", e)
        h.enviar_json(500, {"ok": False, "error": str(e)})
    return True


def manejar_post(h, ruta):
    try:
        n = int(h.headers.get("Content-Length", "0"))
        datos = json.loads(h.rfile.read(n).decode("utf-8")) if 0 < n <= 4096 else {}
        if ruta == "/api/lab/motor":
            acc = datos.get("accion")
            if acc not in ("pausar", "reanudar"):
                raise ValueError("Acción no válida.")
            cfg_set("b_activo", "0" if acc == "pausar" else "1")
            h.enviar_json(200, {"ok": True, "motor_b_activo": acc == "reanudar"})
        elif ruta == "/api/lab/alertas/leer":
            _w("UPDATE lab_alertas SET leida=1")
            h.enviar_json(200, {"ok": True})
        elif ruta == "/api/lab/trade/cancelar":
            r = _q("SELECT * FROM lab_trades WHERE id=?", (int(datos.get("id")),))
            if not r:
                raise ValueError("Operación no encontrada.")
            t = _fila_trade(r[0])
            if t["estado"] not in ABIERTOS:
                h.enviar_json(200, {"ok": True, "cancelada": False, "motivo": "Ya estaba cerrada."})
            elif t["motor"] == "A":
                res = plan_web.cancelar(t["origen_id"])
                espejo_a()
                h.enviar_json(200, dict(res, ok=True))
            else:
                ahora = _ahora()
                s = {"estado": "cerrada", "resultado": "cancelado", "activada_ts": t["activada_ts"], "cerrada_ts": ahora, "r_final": None, "mfe_r": t["mfe_r"],
                     "mae_r": t["mae_r"], "precio_ult": t["precio_ult"], "eventos": t["eventos"] + [{"t": ahora, "texto": "Cancelada por el usuario"}]}
                _aplicar(dict(t, detalle=json.dumps(t["detalle"])), s, alertar=False)
                h.enviar_json(200, {"ok": True, "cancelada": True})
        else:
            h.enviar_json(404, {"ok": False, "error": "Endpoint del laboratorio desconocido."})
    except ValueError as e:
        h.enviar_json(400, {"ok": False, "error": str(e)})
    except Exception as e:
        _err("api_post", e)
        h.enviar_json(500, {"ok": False, "error": str(e)})
    return True


# ============================================================================ autoprueba (datos sinteticos, BD temporal, sin red)
def _autoprueba():
    import random, tempfile
    global DB
    tmp = Path(tempfile.mkdtemp(prefix="titan_lab_test_"))
    DB = tmp / "lab_test.db"
    plan_web.DB = tmp / "planes_test.db"
    rnd = random.Random(7)
    ahora = int(time.time())
    pasos = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "60m": 3600, "1d": 86400, "1wk": 7 * 86400, "1mo": 30 * 86400}

    def velas_sint(sim, rango, intervalo):
        paso = pasos[intervalo]
        n = 700 if intervalo not in ("1wk", "1mo") else 200
        px, out = 100.0 + (hash(sim) % 50), []
        tend = rnd.choice([-1, 1]) * 0.0004
        for i in range(n):
            t = ahora - (n - i) * paso
            o = px
            px = px * (1 + tend + rnd.gauss(0, 0.004))
            out.append([t, o, max(o, px) * 1.001, min(o, px) * 0.999, px, 1000 + rnd.randint(0, 500)])
        return out, {"regularMarketPrice": px, "chartPreviousClose": px * 0.99}
    chart_web._pedir = velas_sint
    chart_web._CACHE.clear()
    plan_web._CACHE_V.clear()

    def barras_sint(s, rango="1mo", intervalo="60m"):
        v, _m = velas_sint(s, rango, intervalo)
        return [{"t": x[0], "o": x[1], "h": x[2], "l": x[3], "c": x[4], "v": x[5]} for x in v]
    agente.barras = barras_sint
    agente.noticias_activo = lambda a, horas=48, ahora_=None: [{"titulo": "Fed signals rate cut as %s rallies" % a["nombre"], "fuente": "TestWire", "fecha": datetime.fromtimestamp(ahora - 8 * 3600, timezone.utc).isoformat(),
                                                           "enlace": "http://x/" + a["simbolo"], "impacto": 1, "fuerza": 2, "motivo": "rally", "edad_h": 8}]
    init_db()
    fallos = []

    def chk(cond, msg):
        print(("  OK  " if cond else "  FALLO ") + msg)
        if not cond:
            fallos.append(msg)
    # 1) motor B sobre datos sinteticos
    cfg_set("cursor_b", 0)
    for _ in range(4):
        ciclo_b()
    nb = _q("SELECT COUNT(*) c FROM lab_trades WHERE motor='B'")[0]["c"]
    chk(_q("SELECT COUNT(*) c FROM lab_decisiones")[0]["c"] > 0, "Motor B registra decisiones (%d)" % _q("SELECT COUNT(*) c FROM lab_decisiones")[0]["c"])
    chk(_q("SELECT COUNT(*) c FROM lab_snapshots")[0]["c"] > 0, "Motor B registra snapshots de mercado")
    print("      operaciones B abiertas en prueba:", nb)
    # 2) operacion con entrada alcanzada para probar el ciclo de vida completo
    a = _activo("BTC-USD")
    plan = {"creado_ts": ahora - 6 * 3600, "simbolo": a["simbolo"], "mostrar": "BTC-USD", "fuente": a["simbolo"], "modo": "intradia", "direccion": 1, "tipo": "retroceso", "entrada": 100.0, "stop": 99.0,
            "tp1": 101.5, "tp2": 102.5, "r1": 1.5, "r2": 2.5, "atr": 0.5, "valido_hasta": ahora + 3600, "trig": "15m", "ctx": "1h", "precio": 100.0, "razones": [], "avisos": [], "resumen": "x", "entra_si": [], "no_entres_si": []}
    tid, comp = _abrir_b(a, "intradia", plan, modelo_activo(), {"total": 4, "tipo": "retroceso", "dir": 1, "punt_n": None, "vol_rel": 1.0})
    t = _fila_trade(_q("SELECT * FROM lab_trades WHERE id=?", (tid,))[0])
    base = ahora - 5 * 3600
    vs = [[base + i * 300, 100.4, 100.6, 99.8, 100.2, 10] for i in range(5)] + [[base + 5 * 300, 100.2, 101.6, 100.3, 101.5, 10], [base + 6 * 300, 101.5, 102.6, 101.4, 102.5, 10]]
    s = plan_web.simular({k: t[k] for k in ("direccion", "entrada", "stop", "tp1", "tp2", "r1", "r2", "creado_ts", "valido_hasta", "tipo", "max_dur_s", "precio_ult")}, vs, ahora)
    t["detalle"] = json.dumps(t["detalle"])
    est = _aplicar(dict(t), s)
    fin = _q("SELECT * FROM lab_trades WHERE id=?", (tid,))[0]
    chk(est == "CERRADA" and fin["resultado"] == "tp2", "Ciclo de vida PENDIENTE→ACTIVADA→TP1→TP2→CERRADA (estado=%s, resultado=%s)" % (est, fin["resultado"]))
    chk(fin["r_neto"] is not None and fin["r_neto"] < fin["r_bruto"], "R neto descuenta costos (bruto %.2f, neto %.2f)" % (fin["r_bruto"], fin["r_neto"]))
    chk(_q("SELECT COUNT(*) c FROM lab_ejecuciones WHERE trade_id=?", (tid,))[0]["c"] >= 3, "Registro verificable de ejecuciones simuladas")
    tipos = {x["tipo"] for x in _q("SELECT tipo FROM lab_alertas WHERE trade_id=?", (tid,))}
    chk({"ENTRADA_ACTIVADA", "TP1", "TP_ALCANZADO"} <= tipos, "Alertas de estado generadas: " + ",".join(sorted(tipos)))
    chk(all(x["certeza"] in ("CONFIRMADA", "PROBABILISTICA") for x in _q("SELECT certeza FROM lab_alertas")), "Alertas diferencian confirmación vs. probabilística")
    # 3) Motor A: espejo de un plan real de plan_web (BD temporal)
    pl = plan_web.crear("ETH-USD", "intradia", "America/Santo_Domingo", [])
    print("      plan A creado por plan_web:", pl.get("accion"))
    # plan A sintetico directamente en titan_planes (como lo dejaria plan_web) para probar el espejo
    with plan_web._DBLOCK:
        c = plan_web._con()
        c.execute("""INSERT INTO planes(creado_ts,simbolo,mostrar,fuente,modo,direccion,tipo,entrada,stop,tp1,tp2,r1,r2,atr,valido_hasta,max_dur_s,eval_tf,eval_int,estado,eventos,detalle,precio_ult,actualizado_ts,activada_ts)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (ahora - 600, "ETH-USD", "ETH-USD", "ETH-USD", "intradia", 1, "ruptura", 100.0, 99.0, 101.5, 102.5, 1.5, 2.5, 0.5, ahora + 3600, 43200, "5m", "5m", "activa",
                   json.dumps([{"t": ahora - 600, "texto": "Plan creado"}, {"t": ahora - 300, "texto": "Entrada activada en 100"}]), json.dumps({"puntos": {"total": 4}, "razones": [], "avisos": []}), 100.6, ahora, ahora - 300))
        c.commit(); c.close()
    ciclo_supervisor()
    ea = _q("SELECT * FROM lab_trades WHERE motor='A'")
    chk(len(ea) == 1 and ea[0]["estado"] == "ACTIVADA", "Motor A espeja el plan de plan_web (estado=%s)" % (ea[0]["estado"] if ea else None))
    chk(ea and json.loads(ea[0]["detalle"]).get("r_flot") is not None, "R flotante calculado para operación activa del Motor A")
    errs = _q("SELECT modulo, mensaje FROM lab_errores")
    chk(not errs, "Sin errores internos registrados" + ("" if not errs else ": %s" % errs[:5]))
    # 4) aprendizaje con muestra grande sintetica
    for i in range(130):
        r = rnd.gauss(0.05, 1.1)
        _w("""INSERT INTO lab_trades(motor,creado_ts,simbolo,mostrar,clase,modo,estrategia,trig,ctx,direccion,tipo,entrada,stop,tp1,tp2,r1,r2,estado,resultado,activada_ts,cerrada_ts,
              costo_r,r_bruto,r_neto,mfe_r,mae_r,eventos,detalle,modelo_ver,computa) VALUES('B',?,?,?,?,?,?,?,?,?,?,100,99,101,102,1,2,'CERRADA','stop',?,?,0.05,?,?,?,?,'[]',?,1,1)""",
           (ahora - 90000 + i * 600, "T%d" % (i % 5), "T%d" % (i % 5), "accion", "intradia", "Intradía · " + rnd.choice(["ruptura", "retroceso"]), "15m", "1h", rnd.choice([1, -1]), rnd.choice(["ruptura", "retroceso"]),
            ahora - 90000 + i * 600, ahora - 89000 + i * 600, r + 0.05, r, max(0, r) + 0.5, -abs(rnd.gauss(0.4, 0.3)),
            json.dumps({"feat": {"total": rnd.choice([3, 4, 5, 6]), "tipo": rnd.choice(["ruptura", "retroceso"]), "dir": 1, "punt_n": rnd.choice([None, 1, -1]), "vol_rel": 1}})))
    ciclo_aprendizaje()
    paq = paquete_metricas()
    g = paq["B_todas"]["global"]
    chk(g["n"] >= 130 and "expectancy" in g and "profit_factor" in g and "max_drawdown_r" in g, "Métricas: n=%d, expectancy=%s, PF=%s, MaxDD=%s R" % (g["n"], g.get("expectancy"), g.get("profit_factor"), g.get("max_drawdown_r")))
    chk("fuera_de_muestra" in g and "walk_forward" in g, "Validación fuera de muestra y walk-forward calculadas")
    print("      modelos:", [(m["ver"], m["estado"]) for m in _q("SELECT ver, estado FROM lab_modelos ORDER BY ver")])
    # 5) API
    class H:
        path = "/api/lab/estado"
        def __init__(s): s.salida = None
        def enviar_json(s, c, d): s.salida = (c, d)
    for ruta in ("/api/lab/estado", "/api/lab/trades?estado=abiertas", "/api/lab/alertas", "/api/lab/metricas", "/api/lab/aprendizaje"):
        hh = H(); hh.path = ruta
        manejar_get(hh, ruta.split("?")[0])
        json.dumps(hh.salida[1])
        chk(hh.salida[0] == 200, "GET %s → 200" % ruta)
    print("RESULTADO AUTOPRUEBA:", "CORRECTA" if not fallos else "FALLÓ: %s" % fallos)
    return not fallos


if __name__ == "__main__":
    import sys
    if "--autoprueba" in sys.argv:
        sys.exit(0 if _autoprueba() else 1)
