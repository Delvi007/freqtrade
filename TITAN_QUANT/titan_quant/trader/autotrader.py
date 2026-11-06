"""TITAN AUTO TRADER — bot operador con control de riesgo independiente y CUENTAS SEPARADAS.

Hay tres bots independientes, uno por modalidad, cada uno con SU base de datos (trader/almacen.py):
    simulacion  → simulador TITAN (precios reales, operaciones ficticias)
    demo        → cTrader DEMO (o IQ Option PRACTICE para binarias)
    real (LIVE) → cTrader REAL, bloqueado hasta habilitarlo expresamente
Tú eliges en cuál operar (pueden funcionar a la vez). Lo único compartido es el conocimiento:
los motores, el Laboratorio y los resultados normalizados por estrategia (conocimiento.db).

Flujo de cada ciclo de un bot:
  1. PARADA DE EMERGENCIA → no abre nada y cierra sus posiciones (simuladas o en el broker).
  2. Actualiza sus operaciones abiertas con el broker y registra resultados (y alimenta el conocimiento compartido).
  3. Pide un análisis a los motores (con las velas del propio broker si así se configura). No modifica la señal.
  4. Pasa la solicitud por todos los controles de riesgo; si uno falla la operación se RECHAZA con su motivo.
  5. Ejecuta con el adaptador de su modalidad y verifica la orden.
"""
import json
import threading
import time
from datetime import datetime, timezone

from .. import alertas, db
from . import almacen
from .base import ErrorAdaptador
from .simulador import Simulador

MODALIDADES = almacen.MODALIDADES
COMUN = {
    "mercado": "metales", "instrumento": "GC=F", "horizonte": "intradia", "estrategia": "fusion", "tipo": "margen",
    "payout": 0.80, "payout_min": 0.75, "expiracion_min": 15,
    "capital": 1000.0, "capital_desde_broker": True, "riesgo_pct": 1.0, "perdida_diaria_max_pct": 3.0, "perdida_semanal_max_pct": 6.0,
    "exposicion_max_pct": 3.0, "max_abiertas": 2, "max_perdidas_consecutivas": 3, "spread_max_pct": 0.15,
    "slippage_max_pct": 0.20, "datos_max_edad_s": 1800, "duplicado_ventana_s": 3600, "ciclo_s": 300,
    "cuenta_ctid": None, "simbolo_broker": "XAUUSD", "fuente_datos": "broker",
    "exigir_ventaja_real": True, "ventaja_min_operaciones": 30,
}
POR_DEFECTO = {
    "simulacion": {**COMUN, "broker": "simulador", "fuente_datos": "yahoo"},
    "demo": {**COMUN, "broker": "ctrader"},
    "real": {**COMUN, "broker": "ctrader", "riesgo_pct": 0.5},
}
LIMITES = {"riesgo_pct": (0.05, 5.0), "perdida_diaria_max_pct": (0.1, 20.0), "perdida_semanal_max_pct": (0.1, 40.0),
           "exposicion_max_pct": (0.1, 50.0), "max_abiertas": (1, 10), "max_perdidas_consecutivas": (1, 20),
           "spread_max_pct": (0.001, 2.0), "slippage_max_pct": (0.001, 2.0), "datos_max_edad_s": (30, 172800),
           "duplicado_ventana_s": (60, 86400), "ciclo_s": (60, 86400), "capital": (10, 1e9), "payout": (0.1, 1.0),
           "payout_min": (0.1, 1.0), "expiracion_min": (1, 1440), "ventaja_min_operaciones": (10, 10000)}
ENTEROS = ("max_abiertas", "max_perdidas_consecutivas", "datos_max_edad_s", "duplicado_ventana_s", "ciclo_s", "expiracion_min", "ventaja_min_operaciones")
BOOLEANOS = ("capital_desde_broker", "exigir_ventaja_real")
ESTRATEGIAS = {"fusion": "Escenario completo del FUSION ENGINE (todas las puertas de seguridad)"}
BROKERS_POR_MODALIDAD = {"simulacion": ("simulador",), "demo": ("ctrader", "iqoption"), "real": ("ctrader",)}
FRASE_REAL = "ENTIENDO EL RIESGO Y AUTORIZO OPERACIONES REALES"
SIMBOLOS_SUGERIDOS = {"XAUUSD": "GC=F", "XAGUSD": "SI=F", "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDJPY": "JPY=X",
                      "US500": "^GSPC", "US30": "^DJI", "USTEC": "^IXIC", "BTCUSD": "BTC-USD", "ETHUSD": "ETH-USD",
                      "XTIUSD": "CL=F", "XBRUSD": "BZ=F"}


def _ahora():
    return int(time.time())


def _mod(m):
    if m not in MODALIDADES:
        raise ValueError("Modalidad no válida (simulacion | demo | real)")
    return m


# ----------------------------------------------------------------- estado y ajustes (por modalidad)
def estado(uid, modalidad):
    m = _mod(modalidad)
    r = almacen.q1(m, "SELECT * FROM bot_estado WHERE usuario_id=?", (uid,))
    if not r:
        with almacen.tx(m) as c:
            c.execute("INSERT OR IGNORE INTO bot_estado(usuario_id,estado,ajustes,actualizado_ts) VALUES(?,?,?,?)",
                      (uid, "detenido", json.dumps(POR_DEFECTO[m]), _ahora()))
        r = almacen.q1(m, "SELECT * FROM bot_estado WHERE usuario_id=?", (uid,))
    aj = {**POR_DEFECTO[m], **json.loads(r["ajustes"] or "{}"), "modalidad": m}
    if aj.get("broker") not in BROKERS_POR_MODALIDAD[m]:
        aj["broker"] = POR_DEFECTO[m]["broker"]
    return {"modalidad": m, "estado": r["estado"], "ajustes": aj, "real_habilitado": bool(r["real_habilitado"]) if m == "real" else None,
            "actualizado_ts": r["actualizado_ts"]}


def validar_ajustes(modalidad, aj):
    m = _mod(modalidad)
    out = dict(POR_DEFECTO[m])
    for k, v in aj.items():
        if k not in POR_DEFECTO[m]:
            continue
        if k in LIMITES:
            try:
                v = float(v)
            except (TypeError, ValueError):
                raise ValueError(f"{k}: debe ser numérico")
            lo, hi = LIMITES[k]
            if not lo <= v <= hi:
                raise ValueError(f"{k}: fuera de rango [{lo}, {hi}]")
            if k in ENTEROS:
                v = int(v)
        elif k in BOOLEANOS:
            v = v in (True, "true", "1", 1, "on", "si", "sí")
        elif k == "cuenta_ctid":
            v = int(v) if str(v or "").strip().isdigit() else None
        elif isinstance(v, str):
            v = v.strip()[:40]
        out[k] = v
    out["simbolo_broker"] = (out.get("simbolo_broker") or "").upper()
    out["modalidad"] = m
    if out["broker"] not in BROKERS_POR_MODALIDAD[m]:
        raise ValueError(f"En {m} el broker debe ser: {', '.join(BROKERS_POR_MODALIDAD[m])}.")
    if out["tipo"] not in ("margen", "binaria"):
        raise ValueError("Tipo no válido")
    if out["estrategia"] not in ESTRATEGIAS:
        raise ValueError("Estrategia no válida")
    if out["fuente_datos"] not in ("broker", "yahoo"):
        raise ValueError("Fuente de datos no válida")
    from ..niveles import validar_horizonte
    validar_horizonte(out["horizonte"])
    if out["broker"] == "iqoption" and out["tipo"] != "binaria":
        raise ValueError("IQ Option en TITAN solo opera binarias.")
    if out["broker"] == "ctrader":
        if out["tipo"] != "margen":
            raise ValueError("cTrader opera con stop y objetivo (tipo margen).")
        if not out["simbolo_broker"]:
            raise ValueError("Indica el símbolo del broker (p. ej. XAUUSD).")
    if out["broker"] == "simulador":
        out["fuente_datos"] = "yahoo"
    return out


def guardar_ajustes(uid, modalidad, aj):
    e = estado(uid, modalidad)
    if e["estado"] == "activo":
        raise ValueError("Pausa o detén este bot antes de cambiar su configuración.")
    nuevo = validar_ajustes(modalidad, {**e["ajustes"], **aj})
    with almacen.tx(modalidad) as c:
        c.execute("UPDATE bot_estado SET ajustes=?, actualizado_ts=? WHERE usuario_id=?", (json.dumps(nuevo), _ahora(), uid))
    db.auditar(uid, "cambio_configuracion", f"bot_{modalidad}", "ajustes", {"antes": e["ajustes"], "despues": nuevo})
    return nuevo


def cambiar_estado(uid, modalidad, nuevo, confirmado_real=False):
    if nuevo not in ("activo", "pausado", "detenido", "emergencia"):
        raise ValueError("Estado no válido")
    e = estado(uid, modalidad)
    if nuevo == "activo":
        if modalidad == "real":
            if not e["real_habilitado"]:
                raise PermissionError("El modo REAL no está habilitado. Habilítalo primero (requisitos, contraseña y frase).")
            if not confirmado_real:
                raise PermissionError("Para iniciar el bot REAL confirma con tu contraseña.")
        if e["ajustes"]["broker"] == "ctrader" and not e["ajustes"].get("cuenta_ctid"):
            raise ValueError("Elige primero la cuenta cTrader de este bot.")
    with almacen.tx(modalidad) as c:
        c.execute("UPDATE bot_estado SET estado=?, actualizado_ts=? WHERE usuario_id=?", (nuevo, _ahora(), uid))
    db.auditar(uid, f"bot_{modalidad}_{nuevo}", "bot", modalidad, {"desde": e["estado"]})
    decision(uid, modalidad, None, {"activo": "iniciar", "pausado": "pausar", "detenido": "detener", "emergencia": "parada_emergencia"}[nuevo],
             f"Cambio de estado {e['estado']} → {nuevo} por el usuario")
    if nuevo == "emergencia":
        alertas.crear(uid, "riesgo", f"PARADA DE EMERGENCIA ({modalidad.upper()})", "critica", modalidad=modalidad,
                      justificacion="El bot no abrirá operaciones nuevas y cerrará sus posiciones abiertas.", motores=["risk"],
                      clave_dedupe=f"emerg|{modalidad}|{_ahora()}")
        _emergencia(uid, modalidad)
    return estado(uid, modalidad)


def requisitos_real(uid):
    """Requisitos técnicos para habilitar el modo REAL (la decisión es del usuario; TITAN verifica que la vía funcione)."""
    demo_ct = almacen.q1("demo", "SELECT COUNT(*) n FROM operaciones WHERE usuario_id=? AND broker='ctrader' AND estado='cerrada'", (uid,))["n"]
    pruebas = db.cfg_sistema("ultima_bateria_pruebas") or {}
    from ..seguridad import boveda
    cred = boveda.mascaras(uid, "ctrader")
    k = almacen.conocimiento()
    req = [
        {"requisito": "Batería de pruebas superada (python3 -m titan_quant.cli probar)", "ok": bool(pruebas.get("ok")), "valor": pruebas.get("resumen")},
        {"requisito": "cTrader autorizado con token (Integraciones → cTrader)", "ok": "access_token" in cred, "valor": "sí" if "access_token" in cred else "no"},
        {"requisito": "Vía de ejecución verificada: ≥ 1 operación cTrader DEMO abierta y cerrada por TITAN", "ok": demo_ct >= 1, "valor": demo_ct},
    ]
    recomendaciones = [
        {"recomendacion": "≥ 30 operaciones demo cerradas antes de arriesgar dinero", "ok": demo_ct >= 30, "valor": demo_ct},
        {"recomendacion": "Expectativa positiva en el conocimiento compartido", "ok": (k["expectativa_r"] or 0) > 0 and k["n"] >= 30,
         "valor": f"{k['n']} operaciones, {k['expectativa_r'] if k['expectativa_r'] is not None else '—'} R"},
    ]
    return {"cumple": all(r["ok"] for r in req), "requisitos": req, "recomendaciones": recomendaciones, "frase": FRASE_REAL}


def habilitar_real(uid, frase, clave_ok, local=True):
    if not clave_ok:
        raise PermissionError("Contraseña incorrecta.")
    if not local:
        raise PermissionError("El modo REAL solo se habilita desde el propio dispositivo donde corre TITAN.")
    if frase != FRASE_REAL:
        raise ValueError("Escribe la frase de confirmación exacta.")
    r = requisitos_real(uid)
    if not r["cumple"]:
        db.auditar(uid, "intento_habilitar_real", "bot", None, {"rechazado": [x["requisito"] for x in r["requisitos"] if not x["ok"]]})
        raise PermissionError("No se cumplen los requisitos técnicos: " + "; ".join(x["requisito"] for x in r["requisitos"] if not x["ok"]))
    estado(uid, "real")
    with almacen.tx("real") as c:
        c.execute("UPDATE bot_estado SET real_habilitado=1, actualizado_ts=? WHERE usuario_id=?", (_ahora(), uid))
    db.auditar(uid, "modo_real_habilitado", "bot", "real", {"recomendaciones_pendientes": [x["recomendacion"] for x in r["recomendaciones"] if not x["ok"]]})


def deshabilitar_real(uid):
    estado(uid, "real")
    with almacen.tx("real") as c:
        c.execute("UPDATE bot_estado SET real_habilitado=0, estado=CASE estado WHEN 'activo' THEN 'detenido' ELSE estado END, actualizado_ts=? WHERE usuario_id=?",
                  (_ahora(), uid))
    db.auditar(uid, "modo_real_deshabilitado", "bot", "real")


# ----------------------------------------------------------------- registro (cada modalidad en su base)
def decision(uid, modalidad, instrumento, accion, motivo, controles=None, motores=None, operacion_id=None):
    with almacen.tx(modalidad) as c:
        c.execute("INSERT INTO decisiones_bot(ts,usuario_id,modalidad,instrumento,accion,motivo,controles,motores,operacion_id) VALUES(?,?,?,?,?,?,?,?,?)",
                  (_ahora(), uid, modalidad, instrumento, accion, (motivo or "")[:1000], json.dumps(controles or [], ensure_ascii=False),
                   json.dumps(motores or []), operacion_id))


def abiertas(uid, modalidad):
    return almacen.q(modalidad, "SELECT * FROM operaciones WHERE usuario_id=? AND estado='abierta'", (uid,))


def _cerradas_desde(uid, modalidad, desde):
    return almacen.q(modalidad, "SELECT * FROM operaciones WHERE usuario_id=? AND estado='cerrada' AND cerrada_ts>=? ORDER BY cerrada_ts DESC", (uid, desde))


def resumen(uid):
    out = {}
    for m in MODALIDADES:
        r = almacen.q1(m, """SELECT COUNT(*) n, COALESCE(SUM(resultado),0) neto, COALESCE(SUM(resultado>0),0) ganadas, COALESCE(SUM(resultado<0),0) perdidas
                            FROM operaciones WHERE usuario_id=? AND estado='cerrada'""", (uid,))
        r["abiertas"] = almacen.q1(m, "SELECT COUNT(*) n FROM operaciones WHERE usuario_id=? AND estado='abierta'", (uid,))["n"]
        r["rechazadas"] = almacen.q1(m, "SELECT COUNT(*) n FROM operaciones WHERE usuario_id=? AND estado='rechazada'", (uid,))["n"]
        r["estado"] = estado(uid, m)["estado"]
        r["moneda"] = (almacen.q1(m, "SELECT moneda FROM operaciones WHERE usuario_id=? AND moneda IS NOT NULL ORDER BY id DESC LIMIT 1", (uid,)) or {}).get("moneda")
        out[m] = r
    return out


# ----------------------------------------------------------------- controles de riesgo (8.4)
def _riesgo_op(o):
    if o.get("riesgo_importe"):
        return o["riesgo_importe"]
    if o["tipo"] == "binaria":
        return o["monto"]
    if o.get("stop") and o.get("precio_entrada"):
        return o["monto"] * abs(o["precio_entrada"] - o["stop"]) / o["precio_entrada"]
    return o["monto"]


def controles(uid, aj, sol, cot, analisis, adaptador):
    m = aj["modalidad"]
    ahora = _ahora()
    cap = aj["capital"]
    ab = abiertas(uid, m)
    dia = int(datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    neto_dia = sum(o["resultado"] or 0 for o in _cerradas_desde(uid, m, dia))
    neto_sem = sum(o["resultado"] or 0 for o in _cerradas_desde(uid, m, ahora - 7 * 86400))
    ult = almacen.q(m, "SELECT resultado FROM operaciones WHERE usuario_id=? AND estado='cerrada' ORDER BY cerrada_ts DESC LIMIT ?",
                    (uid, aj["max_perdidas_consecutivas"]))
    racha = len(ult) == aj["max_perdidas_consecutivas"] and all((x["resultado"] or 0) < 0 for x in ult)
    riesgo_nuevo = sol["riesgo_importe"]
    riesgo_abierto = sum(_riesgo_op(o) for o in ab)
    dup = almacen.q1(m, "SELECT id FROM operaciones WHERE usuario_id=? AND instrumento=? AND direccion=? AND estado IN ('abierta','cerrada') AND abierta_ts>=?",
                     (uid, sol["instrumento"], sol["direccion"], ahora - aj["duplicado_ventana_s"]))
    reg = next((x for x in analisis["motores"] if x["motor"] == "regime" and x["estado"] == "completado"), None)
    ml = next((x for x in analisis["motores"] if x["motor"] == "ml" and x["estado"] == "completado"), None)
    ms = next((x for x in analisis["motores"] if x["motor"] == "microstructure"), None)
    spread_pct, fuente_spread = None, "desconocido"
    if cot.get("spread") is not None and cot.get("precio"):
        spread_pct, fuente_spread = cot["spread"] / cot["precio"] * 100, "real del broker"
    elif ms and ms.get("salida"):
        spread_pct, fuente_spread = (ms["salida"].get("spread_estimado_pct") or {}).get("corwin_schultz"), "estimado"
    desliz = abs(cot["precio"] - sol["precio_ref"]) / sol["precio_ref"] * 100 if sol.get("precio_ref") else 0
    c = []

    def ctl(nombre, ok, detalle):
        c.append({"control": nombre, "ok": bool(ok), "detalle": detalle})
    e = estado(uid, m)
    ctl("parada_emergencia", e["estado"] != "emergencia", e["estado"])
    ctl("modalidad_confirmada", m != "real" or e["real_habilitado"], m)
    ctl("conexion", adaptador.conectado(), adaptador.nombre)
    ctl("datos_frescos", cot["edad_s"] <= aj["datos_max_edad_s"], f"edad {cot['edad_s']} s (máx {aj['datos_max_edad_s']})")
    ctl("riesgo_por_operacion", riesgo_nuevo <= cap * aj["riesgo_pct"] / 100 * 1.0001, f"{riesgo_nuevo:.2f} de {cap * aj['riesgo_pct'] / 100:.2f}")
    ctl("perdida_diaria", -neto_dia + riesgo_nuevo <= cap * aj["perdida_diaria_max_pct"] / 100, f"neto hoy {neto_dia:.2f}, máx pérdida {cap * aj['perdida_diaria_max_pct'] / 100:.2f}")
    ctl("perdida_semanal", -neto_sem + riesgo_nuevo <= cap * aj["perdida_semanal_max_pct"] / 100, f"neto 7 d {neto_sem:.2f}")
    ctl("exposicion_total", riesgo_abierto + riesgo_nuevo <= cap * aj["exposicion_max_pct"] / 100, f"riesgo abierto {riesgo_abierto:.2f} + {riesgo_nuevo:.2f}")
    ctl("max_operaciones_abiertas", len(ab) < aj["max_abiertas"], f"{len(ab)} de {aj['max_abiertas']}")
    ctl("perdidas_consecutivas", not racha, f"últimas {len(ult)}")
    ctl("spread", spread_pct is None or spread_pct <= aj["spread_max_pct"],
        f"{round(spread_pct, 4) if spread_pct is not None else '—'} % ({fuente_spread})")
    ctl("slippage", desliz <= aj["slippage_max_pct"], f"{desliz:.3f} % desde el precio del análisis")
    ctl("volatilidad", not (reg and reg["salida"]["regimen"] == "alta_volatilidad"), reg["salida"]["regimen"] if reg else "sin régimen")
    ctl("duplicados", dup is None, "sin operación igual reciente" if dup is None else f"operación {dup['id']} en la ventana")
    if m == "real" and aj.get("exigir_ventaja_real", True):
        k = almacen.conocimiento(aj["estrategia"], sol["instrumento"])
        ok = k["n"] >= aj["ventaja_min_operaciones"] and (k["expectativa_r"] or 0) > 0
        ctl("ventaja_demostrada", ok, f"{k['n']} operaciones previas (sim+demo+real), expectativa "
            f"{round(k['expectativa_r'], 3) if k['expectativa_r'] is not None else '—'} R; se exigen ≥ {aj['ventaja_min_operaciones']} y > 0")
    if sol["tipo"] == "binaria":
        cal = ml and ml["salida"].get("calibrada")
        p = ml["salida"]["probabilidad_alcista"] if ml else None
        p = p if sol["direccion"] == "alcista" else (1 - p if p is not None else None)
        umbral = 1 / (1 + aj["payout"]) + 0.02
        ctl("payout_minimo", aj["payout"] >= aj["payout_min"], f"{aj['payout']:.2f}")
        ctl("probabilidad_calibrada", bool(cal) and p is not None and p >= umbral,
            f"P={p:.3f} vs umbral {umbral:.3f}" if p is not None else "sin probabilidad calibrada: una binaria sin ventaja estimada no se abre")
    return c


# ----------------------------------------------------------------- adaptadores
def adaptador_para(uid, aj, clase=None):
    if aj["broker"] == "simulador":
        return Simulador({aj["instrumento"]: clase} if clase else None)
    from ..seguridad import boveda
    if aj["broker"] == "iqoption":
        from .iqoption import IQOption
        return IQOption(boveda.leer(uid, "iqoption"))
    if aj["broker"] == "ctrader":
        from .ctrader import CTrader
        return CTrader(uid, aj["modalidad"], aj.get("cuenta_ctid"), aj.get("simbolo_broker"))
    raise ValueError("Broker desconocido")


# ----------------------------------------------------------------- ciclo
def actualizar_abiertas(uid, modalidad, adaptador=None, ahora=None):
    e = estado(uid, modalidad)
    cerradas = 0
    for o in abiertas(uid, modalidad):
        try:
            ad = adaptador or adaptador_para(uid, {**e["ajustes"], "broker": o["broker"]})
            r = ad.actualizar(o, ahora) if ahora else ad.actualizar(o)
        except Exception as ex:
            alertas.crear(uid, "conexion", f"No se pudo actualizar la operación {modalidad} {o['id']}", "media", o["instrumento"],
                          justificacion=str(ex)[:200], modalidad=modalidad, clave_dedupe=f"upd|{modalidad}|{o['id']}|{_ahora() // 3600}", notificar=False)
            continue
        if r:
            _cerrar(uid, modalidad, o, r)
            cerradas += 1
    return cerradas


def _cerrar(uid, modalidad, o, r):
    rr = r.get("r")
    if rr is None and o.get("riesgo_importe"):
        rr = r["resultado"] / o["riesgo_importe"]
    with almacen.tx(modalidad) as c:
        n = c.execute("UPDATE operaciones SET estado='cerrada', cerrada_ts=?, precio_salida=?, resultado=?, r=?, motivo_cierre=? WHERE id=? AND estado='abierta'",
                      (_ahora(), r.get("precio_salida"), r["resultado"], rr, r["motivo"], o["id"])).rowcount
    if not n:
        return
    almacen.aprender(modalidad, o.get("estrategia"), o["instrumento"], o.get("horizonte"), o["direccion"], rr, r["motivo"])
    decision(uid, modalidad, o["instrumento"], "cerrar", f"{r['motivo']}: resultado {r['resultado']:+.2f} {o.get('moneda') or ''}", operacion_id=o["id"])
    alertas.crear(uid, "operacion", f"Operación {modalidad.upper()} cerrada ({r['motivo']})", "media", o["instrumento"], o["mercado"], o["direccion"],
                  r.get("precio_salida"), modalidad=modalidad, justificacion=f"Resultado {r['resultado']:+.2f} {o.get('moneda') or ''}",
                  motores=json.loads(o["motores"] or "[]"), clave_dedupe=f"cerr|{modalidad}|{o['id']}")


def _emergencia(uid, modalidad, adaptador=None):
    e = estado(uid, modalidad)
    for o in abiertas(uid, modalidad):
        try:
            if o["broker"] == "simulador":
                r = Simulador().cerrar(o, "emergencia")
            else:
                ad = adaptador or adaptador_para(uid, {**e["ajustes"], "broker": o["broker"]})
                r = ad.cerrar(o, "emergencia")
            _cerrar(uid, modalidad, o, r)
        except Exception as ex:
            alertas.crear(uid, "riesgo", f"No se pudo cerrar la operación {modalidad} {o['id']} en la emergencia", "critica", o["instrumento"],
                          justificacion=str(ex)[:200] + " — ciérrala manualmente en el broker.", modalidad=modalidad,
                          clave_dedupe=f"emergfallo|{modalidad}|{o['id']}")


def construir_solicitud(aj, analisis, cot):
    esc = analisis["escenario"]
    sg = 1 if esc["direccion"] == "alcista" else -1
    riesgo = aj["capital"] * aj["riesgo_pct"] / 100
    ref = esc["precio_referencia"]
    stop_pct = obj_pct = None
    if aj["tipo"] == "binaria":
        monto = riesgo
        stop = objetivo = None
    else:
        stop, objetivo = esc["stop_loss"], esc["take_profit"][0]
        stop_pct = abs(ref - stop) / ref
        obj_pct = abs(objetivo - ref) / ref
        if aj["broker"] == "simulador":
            dist = abs(cot["precio"] - stop) / cot["precio"]
            if dist <= 0 or (stop - cot["precio"]) * sg >= 0:
                raise ValueError("El precio actual ya está más allá del stop del escenario.")
            monto = riesgo / dist
        else:                                    # el broker calcula volumen y niveles con su propio precio
            monto = riesgo / stop_pct
            stop = cot["precio"] - sg * cot["precio"] * stop_pct
            objetivo = cot["precio"] + sg * cot["precio"] * obj_pct
    return {"instrumento": aj["instrumento"], "direccion": esc["direccion"], "tipo": aj["tipo"], "monto": round(monto, 2),
            "riesgo_importe": riesgo, "stop": stop, "objetivo": objetivo, "stop_dist_pct": stop_pct, "obj_dist_pct": obj_pct,
            "precio_ref": esc["precio_referencia"] if aj["fuente_datos"] == "broker" or aj["broker"] == "simulador" else cot["precio"],
            "expira_ts": _ahora() + aj["expiracion_min"] * 60 if aj["tipo"] == "binaria" else esc["vigencia_hasta_ts"],
            "payout": aj["payout"] if aj["tipo"] == "binaria" else None, "modalidad": aj["modalidad"], "estrategia": aj["estrategia"],
            "clase": analisis["activo"].get("clase")}


def _serie_broker(ad, aj, nivel):
    from ..motores import datos
    from ..niveles import HORIZONTES
    hz = HORIZONTES[aj["horizonte"]]
    rango = datos.rango_para(hz["intervalo"], nivel)
    dias = {"5d": 5, "1mo": 31, "60d": 60, "3mo": 92, "6mo": 183, "1y": 365, "2y": 730, "5y": 1826, "10y": 3652, "max": 3652}.get(rango, 92)
    return ad.serie(aj["instrumento"], hz["intervalo"], dias * 86400)


def ciclo(uid, modalidad, analizar_fn=None, adaptador=None):
    """Un ciclo completo del bot de UNA modalidad. Devuelve lo que hizo (para pruebas y la interfaz)."""
    m = _mod(modalidad)
    e = estado(uid, m)
    aj = dict(e["ajustes"])
    out = {"modalidad": m, "estado": e["estado"], "cerradas": 0, "accion": None}
    if e["estado"] == "emergencia":
        _emergencia(uid, m, adaptador)
        out["accion"] = "emergencia"
        return out
    out["cerradas"] = actualizar_abiertas(uid, m, adaptador)
    if e["estado"] != "activo":
        out["accion"] = "inactivo"
        return out
    if m == "real" and not e["real_habilitado"]:
        decision(uid, m, aj["instrumento"], "rechazar", "Modo REAL no habilitado")
        out["accion"] = "bloqueado"
        return out
    from ..motores import nucleo
    nivel = db.cfg_usuario(uid, "nivel", "intermedio")
    politica = db.cfg_usuario(uid, "politica", "automatico")
    ad = adaptador or adaptador_para(uid, aj)
    serie = None
    try:
        if aj["broker"] == "ctrader" and aj.get("capital_desde_broker", True) and hasattr(ad, "saldo"):
            sal = ad.saldo()
            aj["capital"] = sal["balance"]
            with almacen.tx(m) as c:
                c.execute("INSERT INTO saldos(ts,usuario_id,cuenta,balance,moneda) VALUES(?,?,?,?,?)",
                          (_ahora(), uid, str(aj.get("cuenta_ctid")), sal["balance"], sal.get("moneda")))
        if aj["fuente_datos"] == "broker" and hasattr(ad, "serie"):
            serie = _serie_broker(ad, aj, nivel)
    except Exception as ex:
        decision(uid, m, aj["instrumento"], "omitir", f"Broker no disponible: {str(ex)[:200]}")
        alertas.crear(uid, "conexion", f"Bot {m.upper()}: broker no disponible", "alta", aj["instrumento"], justificacion=str(ex)[:300],
                      modalidad=m, clave_dedupe=f"brkoff|{m}|{_ahora() // 3600}")
        out["accion"] = "broker_no_disponible"
        return out
    try:
        kw = {"usuario_id": uid, "riesgo": {"capital": aj["capital"], "riesgo_pct": aj["riesgo_pct"]}}
        if serie is not None:
            kw["serie"] = serie
        an = (analizar_fn or nucleo.analizar)(aj["instrumento"], aj["horizonte"], nivel, politica, **kw)
    except Exception as ex:
        decision(uid, m, aj["instrumento"], "omitir", f"Análisis fallido: {type(ex).__name__}")
        out["accion"] = "error_analisis"
        return out
    motores = [x["motor"] for x in an["motores"] if x["estado"] in ("completado", "simplificado")]
    if not an["hay_oportunidad"]:
        motivo = "; ".join((an.get("fusion") or {}).get("motivo_sin_oportunidad", [])[:3]) or "sin oportunidad"
        ult = almacen.q1(m, "SELECT motivo, ts FROM decisiones_bot WHERE usuario_id=? AND accion='omitir' ORDER BY id DESC LIMIT 1", (uid,))
        if not ult or ult["motivo"] != motivo[:1000] or _ahora() - ult["ts"] > 3600:
            decision(uid, m, aj["instrumento"], "omitir", motivo, motores=motores)
        out["accion"] = "omitir"
        return out
    try:
        cot = ad.cotizacion(aj["instrumento"])
        sol = construir_solicitud(aj, an, cot)
    except Exception as ex:
        decision(uid, m, aj["instrumento"], "rechazar", f"Sin cotización o solicitud inválida: {ex}", motores=motores)
        out["accion"] = "rechazar"
        return out
    ctl = controles(uid, aj, sol, cot, an, ad)
    fallos = [x for x in ctl if not x["ok"]]
    mercado = (an.get("fuente_datos") or {}).get("tipo") or aj["mercado"]
    if fallos:
        with almacen.tx(m) as c:
            cur = c.execute("""INSERT INTO operaciones(usuario_id,modalidad,broker,cuenta,instrumento,simbolo_broker,mercado,tipo,direccion,monto,riesgo_importe,
                               stop,objetivo,payout,expira_ts,estado,abierta_ts,motivo_cierre,estrategia,horizonte,motores,controles)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'rechazada',?,?,?,?,?,?)""",
                            (uid, m, aj["broker"], str(aj.get("cuenta_ctid") or m), sol["instrumento"], aj.get("simbolo_broker"), mercado, sol["tipo"],
                             sol["direccion"], sol["monto"], sol["riesgo_importe"], sol["stop"], sol["objetivo"], sol["payout"], sol["expira_ts"], _ahora(),
                             "; ".join(f"{x['control']}: {x['detalle']}" for x in fallos)[:1000], aj["estrategia"], aj["horizonte"],
                             json.dumps(motores), json.dumps(ctl, ensure_ascii=False)))
            oid = cur.lastrowid
        decision(uid, m, sol["instrumento"], "rechazar", "Controles fallidos: " + ", ".join(x["control"] for x in fallos), ctl, motores, oid)
        alertas.crear(uid, "operacion", f"Operación {m.upper()} rechazada por controles de riesgo", "media", sol["instrumento"], mercado, sol["direccion"],
                      sol["precio_ref"], an["horizonte"], ", ".join(x["control"] for x in fallos), motores, m, clave_dedupe=f"rech|{m}|{oid}")
        out["accion"] = "rechazar"
        out["controles"] = ctl
        return out
    clave = f"{sol['instrumento']}|{sol['direccion']}|{an['ts'] // max(60, aj['duplicado_ventana_s'])}"
    try:
        ej = ad.abrir(sol)
    except ErrorAdaptador as ex:
        decision(uid, m, sol["instrumento"], "rechazar", f"El broker rechazó: {ex}", ctl, motores)
        alertas.crear(uid, "integracion", f"El broker rechazó una orden ({m.upper()})", "alta", sol["instrumento"], justificacion=str(ex),
                      modalidad=m, clave_dedupe=f"brk|{m}|{_ahora()}")
        out["accion"] = "rechazar"
        out["error"] = str(ex)
        return out
    with almacen.tx(m) as c:
        cur = c.execute("""INSERT OR IGNORE INTO operaciones(usuario_id,modalidad,broker,cuenta,instrumento,simbolo_broker,mercado,tipo,direccion,monto,
                           riesgo_importe,volumen,moneda,precio_entrada,stop,objetivo,payout,expira_ts,costo,estado,abierta_ts,id_externo,fuente_precio,
                           estrategia,horizonte,motores,controles,clave_dedupe)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'abierta',?,?,?,?,?,?,?,?)""",
                        (uid, m, aj["broker"], str(aj.get("cuenta_ctid") or m), sol["instrumento"], ej.get("simbolo_broker") or aj.get("simbolo_broker"),
                         mercado, sol["tipo"], sol["direccion"], ej.get("monto", sol["monto"]), ej.get("riesgo_importe", sol["riesgo_importe"]),
                         ej.get("volumen"), ej.get("moneda"), ej["precio_entrada"], ej.get("stop", sol["stop"]), ej.get("objetivo", sol["objetivo"]),
                         sol["payout"], sol["expira_ts"] if aj["broker"] != "ctrader" else None, ej["costo"], _ahora(), ej["id_externo"],
                         ej.get("fuente_precio"), aj["estrategia"], aj["horizonte"], json.dumps(motores), json.dumps(ctl, ensure_ascii=False), clave))
        oid = cur.lastrowid if cur.rowcount else None
    if not oid:
        decision(uid, m, sol["instrumento"], "rechazar", "Orden duplicada detectada tras la ejecución", ctl, motores)
        out["accion"] = "duplicada"
        return out
    verif = ad.verificar({"id_externo": ej["id_externo"]})
    decision(uid, m, sol["instrumento"], "abrir", f"Escenario {sol['direccion']} validado; verificación en el broker {'OK' if verif else 'PENDIENTE'}",
             ctl, motores, oid)
    alertas.crear(uid, "entrada", f"Operación {m.upper()} abierta: {sol['direccion']} {ej.get('simbolo_broker') or sol['instrumento']}", "alta",
                  sol["instrumento"], mercado, sol["direccion"], ej["precio_entrada"], an["horizonte"],
                  " ".join((an.get("fusion") or {}).get("justificacion", [])[:3]), motores, m, {"operacion_id": oid}, clave_dedupe=f"abr|{m}|{oid}")
    out["accion"] = "abrir"
    out["operacion_id"] = oid
    return out


# ----------------------------------------------------------------- hilo de fondo (los tres bots)
_HILO = {"t": None, "parar": False, "ultimo": {}, "error": None}


def _bucle():
    while not _HILO["parar"]:
        try:
            for m in MODALIDADES:
                for r in almacen.q(m, "SELECT usuario_id, estado, ajustes FROM bot_estado WHERE estado IN ('activo','emergencia','pausado')"):
                    uid = r["usuario_id"]
                    aj = {**POR_DEFECTO[m], **json.loads(r["ajustes"] or "{}")}
                    k = (m, uid)
                    if r["estado"] in ("activo", "emergencia") and time.time() - _HILO["ultimo"].get(k, 0) >= aj["ciclo_s"]:
                        _HILO["ultimo"][k] = time.time()
                        ciclo(uid, m)
                    elif time.time() - _HILO["ultimo"].get(("upd",) + k, 0) >= 60:
                        _HILO["ultimo"][("upd",) + k] = time.time()
                        actualizar_abiertas(uid, m)
            _HILO["error"] = None
        except Exception as ex:
            _HILO["error"] = f"{type(ex).__name__}: {ex}"[:200]
        for _ in range(15):
            if _HILO["parar"]:
                break
            time.sleep(1)


def iniciar_hilo():
    if _HILO["t"] and _HILO["t"].is_alive():
        return
    _HILO["parar"] = False
    _HILO["t"] = threading.Thread(target=_bucle, name="titan-autotrader", daemon=True)
    _HILO["t"].start()


def hilo_vivo():
    return bool(_HILO["t"] and _HILO["t"].is_alive())
