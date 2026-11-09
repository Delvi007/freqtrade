"""TITAN AUTO TRADER — bots operadores con control de riesgo independiente y CUENTAS SEPARADAS.

Dos bots (cTrader e IQ Option), cada uno con una cuenta de práctica y otra REAL, cada cuenta con SU base de datos:
    demo          → bot cTrader, cuenta DEMO (host demo.ctraderapi.com)
    real          → bot cTrader, cuenta REAL/LIVE (host live.ctraderapi.com) — solo con el interruptor LIVE encendido
    binaria       → bot IQ Option, cuenta PRACTICE (se selecciona y verifica antes de cada orden)
    binaria_real  → bot IQ Option, cuenta REAL — solo con el interruptor LIVE encendido
La práctica y la real pueden funcionar a la vez. El interruptor LIVE de cada cuenta real se enciende con la contraseña.
La simulación interna de operaciones se RETIRÓ: no hay aperturas, cierres, resultados ni saldos ficticios.
Los resultados históricos calculados viven en los motores de backtesting (titan_quant/backtest_*), nunca aquí.

Ciclo de un bot:
  1. PARADA DE EMERGENCIA → no abre nada e intenta cerrar sus posiciones EN EL BROKER.
  2. Concilia sus órdenes vivas con el broker: confirma aperturas y registra cierres y resultados del broker.
  3. Pide un análisis a los motores (con las velas del propio broker). No modifica la señal.
  4. Pasa la solicitud por todos los controles de riesgo; si uno falla se descarta la OPORTUNIDAD con su motivo.
  5. Registra la orden como ENVIADA, la envía al broker y avanza de fase solo con la confirmación del broker:
       orden_enviada → orden_aceptada (id del broker) → abierta_confirmada → cerrada_confirmada → resultado_recibido
     Rechazo del broker → error_broker. Sin respuesta o estado dudoso → estado 'error' (requiere conciliación) y el bot
     no abre nada más hasta conciliarla. Nunca se inventa un resultado.
"""
import json
import threading
import time
from datetime import datetime, timezone

from .. import alertas, db
from . import almacen
from .base import ErrorAdaptador, OrdenNoConfirmada

MODALIDADES = almacen.MODALIDADES
REALES = ("real", "binaria_real")            # cuentas con dinero real: solo operan con el interruptor LIVE encendido
BINARIAS = ("binaria", "binaria_real")
MOTIVO_REAL = "Cuenta REAL apagada: enciende el interruptor LIVE de este bot (con tu contraseña) para operar con dinero real."
INTERVALOS_ESCANER = ("5m", "15m", "1h", "4h")
COMUN = {
    "mercado": "metales", "instrumento": "GC=F", "horizonte": "intradia", "estrategia": "fusion", "tipo": "margen",
    "payout": 0.80, "payout_min": 0.75, "expiracion_min": 15,
    "capital": 1000.0, "capital_desde_broker": True, "riesgo_pct": 1.0, "perdida_diaria_max_pct": 3.0, "perdida_semanal_max_pct": 6.0,
    "exposicion_max_pct": 3.0, "max_abiertas": 2, "max_perdidas_consecutivas": 3, "spread_max_pct": 0.15,
    "slippage_max_pct": 0.20, "datos_max_edad_s": 1800, "duplicado_ventana_s": 3600, "ciclo_s": 300,
    "cuenta_ctid": None, "simbolo_broker": "XAUUSD", "fuente_datos": "broker",
    "exigir_ventaja_real": True, "ventaja_min_operaciones": 30,
    # Configuración sencilla (panel). Umbral = % de confirmaciones blandas que deben cumplirse (0-100).
    # Las puertas de seguridad (riesgo, cuenta, datos, payout, duplicados) son obligatorias y no cuentan aquí.
    "umbral_puntuacion": 50.0, "confirmaciones_minimas": 2, "modo_exploracion": False,
    # Escáner multiactivo (estrategias básicas configurables + backtesting continuo de todos los activos del broker)
    "estrategias_activas": None, "intervalo_escaner": "15m", "atr_stop": 1.5, "atr_obj": 2.0, "min_ops_bt": 20, "exp_min": 0.0,
    "margen_bt": 0.0, "lote_escaner": 4, "max_simbolos": 10, "simbolos_escaner": "", "solo_divisas": False,
    "temporalidades": "5m,15m,1h,4h", "temporalidades_binaria": "1m,5m",
    # Filtro de tendencia: solo señales a favor (EMA rápida/lenta y precio respecto a la lenta)
    "filtro_tendencia": False, "tendencia_rapida": 50, "tendencia_lenta": 200,
    "pausa_racha_min": 60,
    # Objetivo por riesgo:beneficio (cTrader). El riesgo es riesgo_pct del capital (p. ej. 0,5 % → 100 USD) y el objetivo un
    # múltiplo de ese riesgo: SIEMPRE 1:rr_base (2 → 200 USD); 1:rr_tendencia (3) solo con ventaja: tendencia a favor y
    # backtest fuera de muestra ≥ ventaja_rr_tendencia R; 1:rr_max (4) con ventaja fuerte (≥ ventaja_rr_max R). Mínimo 20 ops.
    "rr_base": 2.0, "rr_tendencia": 3.0, "rr_max": 4.0, "ventaja_rr_tendencia": 0.1, "ventaja_rr_max": 0.3,
    # Trailing stop (cTrader): stop a la entrada en +be_r R; desde +trail_desde_r R persigue al precio a k·ATR
    # (k = trail_atr_fuerte con tendencia a favor, trail_atr_debil si se debilita). Nunca se aleja.
    "trailing": True, "be_r": 1.0, "trail_desde_r": 1.5, "trail_atr_fuerte": 1.5, "trail_atr_debil": 0.8,
    # Confirmación de cada señal con los 23 motores (FUSION ENGINE, régimen, macro, calidad de datos)
    "confirmar_motores": True, "umbral_contra": 0.15, "veto_macro": True,
    # SOLO PRÁCTICA: sin límites de pérdida (diaria, semanal, drawdown y pausa por racha) para que el bot no se detenga.
    # En una cuenta REAL se fuerza siempre a False.
    "sin_limites_perdida": False,
    # Exploración solo hasta reunir esta muestra de operaciones cerradas por el broker; después, MODO EVIDENCIA automático
    "muestra_exploracion": 30,
    # Aprendizaje con resultados REALES del broker: deja de operar combinaciones que pierden en real
    "aprendizaje_min_ops": 8,
}
# Perfil de EXPLORACIÓN (solo cuentas de práctica): exigencia baja para que los bots operen, reúnan resultados reales del
# broker y alimenten el aprendizaje. Nunca se aplica a una cuenta REAL (validar_ajustes lo impide).
PERFIL_EXPLORACION = {"estrategia": "multiactivo", "modo_exploracion": True, "min_ops_bt": 8, "exp_min": -0.05, "margen_bt": -0.03,
                      "max_simbolos": 1000,                       # señales en vivo en TODOS los pares aptos del broker
                      "max_abiertas": 3, "ventaja_min_operaciones": 10}
PERFIL_EXPLORACION_CTRADER = {**PERFIL_EXPLORACION, "riesgo_pct": 0.5, "lote_escaner": 10, "temporalidades": "5m,15m,1h,4h",
                              "atr_stop": 1.5, "atr_obj": 3.0, "rr_base": 2.0, "rr_tendencia": 3.0, "rr_max": 4.0, "ventaja_rr_tendencia": 0.1, "trailing": True,
                              "exposicion_max_pct": 3.0, "spread_max_pct": 0.5}
# Práctica: monto pequeño (0,5 %) y límites diarios amplios para reunir la muestra de operaciones reales sin quedarse bloqueado.
# Configuración del operador (09/11/2026): no detenerse nunca, 1 % del capital (leído del broker antes de CADA operación),
# hasta 10 operaciones simultáneas y sin límites de pérdida en PRACTICE.
PERFIL_EXPLORACION_BINARIA = {**PERFIL_EXPLORACION, "riesgo_pct": 1.0, "drawdown_max_pct": 10.0, "perdida_diaria_max_pct": 6.0,
                              "perdida_semanal_max_pct": 15.0, "exposicion_max_pct": 10.5, "max_abiertas": 10,
                              "sin_limites_perdida": True, "lote_escaner": 6, "temporalidades_binaria": "1m,5m",
                              "duplicado_ventana_s": 300, "filtro_tendencia": True, "slippage_max_pct": 0.6, "pausa_racha_min": 30,
                              "margen_bt": 0.02, "min_ops_bt": 12}         # umbral más alto: 2 puntos sobre el equilibrio

PRESUPUESTO_RANKING_S = {"ctrader": 150, "binaria": 40}
PRESUPUESTO_SENALES_S = {"ctrader": 150, "binaria": 45}      # barrido de señales en vivo por ciclo (de mejor a peor clasificado)


def _estrategias_defecto():
    from ..estrategias.simples import CATALOGO
    return {k: dict(v[2]) for k, v in CATALOGO.items()}
POR_DEFECTO = {
    "demo": {**COMUN, "broker": "ctrader", "estrategia": "multiactivo", **{k: v for k, v in PERFIL_EXPLORACION_CTRADER.items() if k != "riesgo_pct"}},
    "real": {**COMUN, "broker": "ctrader", "estrategia": "multiactivo", "riesgo_pct": 0.5},
    # Binarias OTC de divisas, solo PRACTICE (IQ Option). Configuración estándar confirmada por el operador.
    "binaria": {**COMUN, "broker": "iqoption", "tipo": "binaria", "mercado": "binarias", "estrategia": "multiactivo",
                "instrumento": "EURGBP-OTC", "simbolo_broker": "EURGBP-OTC", "horizonte": "scalping",
                "fuente_datos": "broker", "payout": 0.86, "payout_min": 0.75, "expiracion_min": 5,
                "capital": 1000.0, "capital_desde_broker": True, "riesgo_pct": 1.0,
                "perdida_diaria_max_pct": 3.0, "drawdown_max_pct": 5.0, "max_abiertas": 2,
                "ciclo_s": 60, "datos_max_edad_s": 120, "duplicado_ventana_s": 300,
                "ventaja_min_operaciones": 30, "exigir_ventaja_real": False, "cuenta_ctid": None,
                "lote_escaner": 3, "max_simbolos": 5},
}
POR_DEFECTO["binaria"].update(PERFIL_EXPLORACION_BINARIA)
POR_DEFECTO["binaria"]["filtro_tendencia"] = True          # IQ Option: siempre a favor de la tendencia
POR_DEFECTO["binaria_real"] = {**POR_DEFECTO["binaria"], "modo_exploracion": False, "min_ops_bt": 20, "exp_min": 0.0, "margen_bt": 0.0,
                               "max_abiertas": 2,
                               # REAL: límites de riesgo ESTRICTOS (no hereda los amplios del perfil de práctica)
                               "riesgo_pct": 1.0, "perdida_diaria_max_pct": 3.0, "drawdown_max_pct": 5.0, "perdida_semanal_max_pct": 6.0,
                               "exposicion_max_pct": 3.0, "pausa_racha_min": 60, "sin_limites_perdida": False}
LIMITES = {"riesgo_pct": (0.05, 5.0), "perdida_diaria_max_pct": (0.1, 20.0), "perdida_semanal_max_pct": (0.1, 40.0),
           "drawdown_max_pct": (0.1, 50.0),
           "exposicion_max_pct": (0.1, 50.0), "max_abiertas": (1, 10), "max_perdidas_consecutivas": (1, 20),
           "spread_max_pct": (0.001, 2.0), "slippage_max_pct": (0.001, 2.0), "datos_max_edad_s": (30, 172800),
           "duplicado_ventana_s": (60, 86400), "ciclo_s": (60, 86400), "capital": (10, 1e9), "payout": (0.1, 1.0),
           "payout_min": (0.1, 1.0), "expiracion_min": (1, 1440), "ventaja_min_operaciones": (10, 10000),
           "umbral_puntuacion": (0.0, 100.0), "confirmaciones_minimas": (0, 5),
           "atr_stop": (0.3, 5.0), "atr_obj": (0.3, 10.0), "min_ops_bt": (5, 500), "exp_min": (-0.5, 2.0), "margen_bt": (-0.1, 0.2),
           "lote_escaner": (1, 50), "max_simbolos": (1, 1000),
           "tendencia_rapida": (5, 200), "tendencia_lenta": (20, 500), "pausa_racha_min": (5, 1440),
           "rr_base": (1.0, 10.0), "rr_tendencia": (1.0, 10.0), "rr_max": (1.0, 10.0), "ventaja_rr_max": (0.0, 3.0), "ventaja_rr_tendencia": (0.0, 3.0),
           "be_r": (0.3, 5.0), "trail_desde_r": (0.5, 10.0), "trail_atr_fuerte": (0.2, 5.0), "trail_atr_debil": (0.2, 5.0),
           "umbral_contra": (0.0, 1.0), "muestra_exploracion": (0, 1000), "aprendizaje_min_ops": (3, 200)}
ENTEROS = ("max_abiertas", "max_perdidas_consecutivas", "datos_max_edad_s", "duplicado_ventana_s", "ciclo_s", "expiracion_min", "ventaja_min_operaciones",
           "confirmaciones_minimas", "min_ops_bt", "lote_escaner", "max_simbolos", "tendencia_rapida", "tendencia_lenta", "pausa_racha_min", "muestra_exploracion", "aprendizaje_min_ops")
BOOLEANOS = ("sin_limites_perdida", "capital_desde_broker", "exigir_ventaja_real", "modo_exploracion", "solo_divisas", "filtro_tendencia", "trailing", "confirmar_motores", "veto_macro")
# Modo fijo por modalidad: no editable desde el panel.
MODO_FIJO = {"demo": "trader", "real": "trader", "binaria": "binaria", "binaria_real": "binaria"}
ESTRATEGIAS = {"fusion": "Escenario completo del FUSION ENGINE (todas las puertas de seguridad)",
               "keltner_rci_m1": "Keltner + RCI sobre velas M1 (escáner binario, pares OTC de divisas)",
               "multiactivo": "Escáner MULTIACTIVO: estrategias básicas en TODOS los activos del broker, con backtesting continuo"}
# Cada bot tiene UN broker: binarias → IQ Option PRACTICE; cTrader → cTrader DEMO. No hay broker de simulación.
BROKERS_POR_MODALIDAD = {"demo": ("ctrader",), "real": ("ctrader",), "binaria": ("iqoption",), "binaria_real": ("iqoption",)}
FRASE_REAL = "ENTIENDO EL RIESGO Y AUTORIZO OPERACIONES REALES"
ENVIADA_MAX_S = 120              # una orden 'enviada' sin respuesta pasado este tiempo queda en 'error' (conciliar)
SIMBOLOS_SUGERIDOS = {"XAUUSD": "GC=F", "XAGUSD": "SI=F", "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDJPY": "JPY=X",
                      "US500": "^GSPC", "US30": "^DJI", "USTEC": "^IXIC", "BTCUSD": "BTC-USD", "ETHUSD": "ETH-USD",
                      "XTIUSD": "CL=F", "XBRUSD": "BZ=F"}
# SQL: operaciones con resultado verificado por el broker (las únicas que cuentan en saldos, límites e informes).
VERIFICADA = "estado='cerrada' AND fase='resultado_recibido' AND fuente_resultado='broker'"
_VIVOS_SQL = "(" + ",".join(f"'{x}'" for x in almacen.VIVOS) + ")"


def _ahora():
    return int(time.time())


def _mod(m):
    if m not in MODALIDADES:
        raise ValueError("Modalidad no válida (demo/real = cTrader | binaria/binaria_real = IQ Option). La simulación interna se retiró.")
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
    if not aj.get("estrategias_activas"):
        aj["estrategias_activas"] = _estrategias_defecto()
    if aj.get("broker") not in BROKERS_POR_MODALIDAD[m]:
        aj["broker"] = POR_DEFECTO[m]["broker"]
        if m == "demo":                     # una configuración antigua (p. ej. IQ Option en demo) vuelve al estándar de cTrader
            aj.update(tipo="margen", mercado=POR_DEFECTO[m]["mercado"])
    return {"modalidad": m, "estado": r["estado"], "ajustes": aj,
            "real_habilitado": bool(r["real_habilitado"]) if m in REALES else None,
            "live": bool(r["real_habilitado"]) if m in REALES else None, "actualizado_ts": r["actualizado_ts"]}


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
        elif k == "estrategias_activas":
            from ..estrategias import simples
            if v is None:
                continue
            if not isinstance(v, dict) or not v:
                raise ValueError("Activa al menos una estrategia.")
            v = {e: simples.validar_parametros(e, prm if isinstance(prm, dict) else {}) for e, prm in v.items()}
        elif k == "intervalo_escaner":
            if v not in INTERVALOS_ESCANER:
                raise ValueError("Intervalo del escáner no válido: " + ", ".join(INTERVALOS_ESCANER))
        elif k in ("temporalidades", "temporalidades_binaria"):
            from ..backtest_binaria.escaner import TEMPORALIDADES as TB
            validas = INTERVALOS_ESCANER if k == "temporalidades" else tuple(TB)
            lista = [x.strip() for x in str(v or "").split(",") if x.strip()]
            if not lista or any(x not in validas for x in lista):
                raise ValueError(f"Temporalidades no válidas; usa: {', '.join(validas)}")
            v = ",".join(dict.fromkeys(lista))
        elif k == "simbolos_escaner":
            v = ",".join(x.strip().upper() for x in str(v or "").split(",") if x.strip())[:4000]
        elif k == "cuenta_ctid":
            v = int(v) if str(v or "").strip().isdigit() else None
        elif isinstance(v, str):
            v = v.strip()[:40]
        out[k] = v
    out["simbolo_broker"] = (out.get("simbolo_broker") or "").upper()
    if not out.get("estrategias_activas"):
        out["estrategias_activas"] = _estrategias_defecto()
    if out["tendencia_rapida"] >= out["tendencia_lenta"]:
        raise ValueError("Filtro de tendencia: la EMA rápida debe ser menor que la lenta.")
    if not out["rr_base"] <= out["rr_tendencia"] <= out["rr_max"]:
        raise ValueError("Riesgo:beneficio: debe cumplirse base ≤ con tendencia ≤ máximo (p. ej. 2 ≤ 3 ≤ 5).")
    if out["trail_desde_r"] < out["be_r"]:
        raise ValueError("Trailing: debe empezar en o después del paso a la entrada (trail_desde_r ≥ be_r).")
    if m in REALES:                      # con dinero real nunca hay exploración ni exigencia por debajo del equilibrio
        out["modo_exploracion"] = False
        out["sin_limites_perdida"] = False          # con dinero real los límites de pérdida son obligatorios
        out["exp_min"] = max(0.0, float(out["exp_min"]))
        out["margen_bt"] = max(0.0, float(out["margen_bt"]))
        out["min_ops_bt"] = max(20, int(out["min_ops_bt"]))
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
    if m in BINARIAS:
        from ..binaria_bot.escaner import es_par_otc
        out["instrumento"] = str(out["instrumento"]).upper()
        if out["estrategia"] not in ("keltner_rci_m1", "multiactivo"):
            raise ValueError("El bot de IQ Option usa el escáner multiactivo o Keltner+RCI en un par.")
        if out["estrategia"] == "keltner_rci_m1" and not es_par_otc(out["instrumento"]):
            raise ValueError("En modo de un solo par, indica un par OTC de divisas (p. ej. EURGBP-OTC).")
        out["simbolo_broker"] = out["instrumento"]
        out["tipo"], out["mercado"], out["fuente_datos"], out["expiracion_min"] = "binaria", "binarias", "broker", 5
    if out["broker"] == "ctrader":
        if out["tipo"] != "margen":
            raise ValueError("cTrader opera con stop y objetivo (tipo margen).")
        if out["estrategia"] not in ("fusion", "multiactivo"):
            raise ValueError("El bot cTrader usa el escáner multiactivo o el FUSION ENGINE en un símbolo.")
        if out["estrategia"] == "fusion" and not out["simbolo_broker"]:
            raise ValueError("Indica el símbolo de cTrader (p. ej. XAUUSD).")
        out["fuente_datos"] = "broker"                        # toda la información del bot cTrader viene de cTrader
    out["modo"] = MODO_FIJO[m]   # no editable: binarias solo opera binarias; cTrader solo como trader
    return out


def restablecer(uid, modalidad):
    """Vuelve la configuración de la modalidad a su estándar. No borra operaciones, decisiones ni saldos.
    Solo con el bot pausado o detenido. Guarda la configuración anterior en la auditoría."""
    m = _mod(modalidad)
    e = estado(uid, m)
    if e["estado"] in ("activo", "emergencia"):
        raise ValueError("Pausa o detén el bot antes de restablecer su configuración.")
    nuevo = validar_ajustes(m, dict(POR_DEFECTO[m]))
    with almacen.tx(m) as c:
        c.execute("UPDATE bot_estado SET ajustes=?, actualizado_ts=? WHERE usuario_id=?", (json.dumps(nuevo), _ahora(), uid))
    db.auditar(uid, "restablecer_configuracion", f"bot_{m}", "ajustes", {"antes": e["ajustes"], "despues": nuevo})
    return estado(uid, m)


def guardar_ajustes(uid, modalidad, aj, origen="usuario"):
    """origen: 'usuario' (interfaz/CLI). Cualquier origen automático (IA, optimizador, aprendizaje) NO puede tocar los
    límites de riesgo protegidos (seguridad.interruptores.PROTEGIDOS)."""
    from ..seguridad import interruptores
    e = estado(uid, modalidad)
    if e["estado"] == "activo":
        raise ValueError("Pausa o detén este bot antes de cambiar su configuración.")
    interruptores.comprobar_cambio(origen, e["ajustes"], aj)
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
        from ..seguridad import interruptores
        ok, motivo = interruptores.permitido(e["ajustes"].get("broker"))
        if not ok:
            raise PermissionError(motivo + " — levántalo antes de iniciar el bot.")
        if modalidad in REALES and not e["real_habilitado"]:
            raise PermissionError(MOTIVO_REAL)
        if e["ajustes"]["broker"] == "ctrader" and not e["ajustes"].get("cuenta_ctid"):
            raise ValueError(f"Elige primero la cuenta cTrader {'REAL (live)' if modalidad == 'real' else 'DEMO'} de este bot.")
    with almacen.tx(modalidad) as c:
        c.execute("UPDATE bot_estado SET estado=?, actualizado_ts=? WHERE usuario_id=?", (nuevo, _ahora(), uid))
    db.auditar(uid, f"bot_{modalidad}_{nuevo}", "bot", modalidad, {"desde": e["estado"]})
    decision(uid, modalidad, None, {"activo": "iniciar", "pausado": "pausar", "detenido": "detener", "emergencia": "parada_emergencia"}[nuevo],
             f"Cambio de estado {e['estado']} → {nuevo} por el usuario")
    if nuevo == "emergencia":
        alertas.crear(uid, "riesgo", f"PARADA DE EMERGENCIA ({modalidad.upper()})", "critica", modalidad=modalidad,
                      justificacion="El bot no abrirá operaciones nuevas y pedirá al broker el cierre de sus posiciones.", motores=["risk"],
                      clave_dedupe=f"emerg|{modalidad}|{_ahora()}")
        _emergencia(uid, modalidad)
    return estado(uid, modalidad)


def requisitos_real(uid):
    """Estado de los interruptores LIVE (informativo)."""
    return {"cumple": True, "motivo": MOTIVO_REAL, "requisitos": [], "recomendaciones": [], "frase": FRASE_REAL,
            "live": {m: bool(estado(uid, m)["real_habilitado"]) for m in REALES}}


def aplicar_perfil_exploracion(uid, modalidad):
    """Pone un bot de PRÁCTICA en modo multiactivo con exigencia básica de exploración. Funciona con el bot en marcha
    (el siguiente ciclo ya lo usa). Conserva la cuenta cTrader elegida. Nunca se aplica a una cuenta REAL."""
    m = _mod(modalidad)
    if m in REALES:
        raise ValueError("El perfil de exploración es solo para cuentas de práctica (DEMO / PRACTICE).")
    e = estado(uid, m)
    perfil = PERFIL_EXPLORACION_BINARIA if m in BINARIAS else PERFIL_EXPLORACION_CTRADER
    base = {k: v for k, v in e["ajustes"].items() if k not in ("modalidad", "modo")}
    if m in BINARIAS:
        base["instrumento"] = base.get("instrumento") or POR_DEFECTO[m]["instrumento"]
    else:
        base["broker"], base["tipo"], base["mercado"] = "ctrader", "margen", POR_DEFECTO[m]["mercado"]
    nuevo = validar_ajustes(m, {**base, **perfil})
    with almacen.tx(m) as c:
        c.execute("UPDATE bot_estado SET ajustes=?, actualizado_ts=? WHERE usuario_id=?", (json.dumps(nuevo), _ahora(), uid))
    db.auditar(uid, "perfil_exploracion", f"bot_{m}", "ajustes", {"antes": e["ajustes"], "despues": nuevo})
    decision(uid, m, None, "configurar", "Perfil de EXPLORACIÓN aplicado: escáner multiactivo en todas las temporalidades con exigencia básica")
    return estado(uid, m)


def interruptor_live(uid, modalidad, encender, clave_ok=False, local=True, origen="usuario"):
    """Enciende o apaga el MODO LIVE (dinero real) de una cuenta real. Encender exige la contraseña de TITAN y hacerlo
    desde el propio dispositivo. Al encender, el bot de esa cuenta queda ACTIVO; al apagar, DETENIDO (sin abrir nada más)."""
    if encender and origen != "usuario":
        raise PermissionError("Solo el usuario puede encender el MODO LIVE: un proceso automático nunca activa dinero real.")
    m = _mod(modalidad)
    if m not in REALES:
        raise ValueError("El interruptor LIVE solo existe para las cuentas reales (cTrader REAL e IQ Option REAL).")
    e = estado(uid, m)
    if encender:
        if not clave_ok:
            raise PermissionError("Contraseña incorrecta: el MODO LIVE sigue apagado.")
        if not local:
            raise PermissionError("El MODO LIVE solo se enciende desde el propio dispositivo donde corre TITAN.")
        if e["ajustes"]["broker"] == "ctrader" and not e["ajustes"].get("cuenta_ctid"):
            raise ValueError("Elige y guarda primero la cuenta cTrader REAL (live) de este bot.")
        from ..seguridad import interruptores
        ok_int, motivo_int = interruptores.permitido(e["ajustes"].get("broker"))
        if not ok_int:
            raise PermissionError(motivo_int + " — levántalo antes de encender el MODO LIVE.")
        with almacen.tx(m) as c:
            c.execute("UPDATE bot_estado SET real_habilitado=1, estado='activo', actualizado_ts=? WHERE usuario_id=?", (_ahora(), uid))
        db.auditar(uid, "modo_live_encendido", f"bot_{m}", m)
        decision(uid, m, None, "iniciar", "MODO LIVE ACTIVADO por el usuario: el bot opera con dinero real")
        alertas.crear(uid, "riesgo", f"MODO LIVE ACTIVADO ({m.upper()})", "critica", modalidad=m,
                      justificacion="El bot enviará órdenes con dinero real en esta cuenta.", clave_dedupe=f"liveon|{m}|{_ahora()}")
    else:
        with almacen.tx(m) as c:
            c.execute("UPDATE bot_estado SET real_habilitado=0, estado=CASE estado WHEN 'emergencia' THEN 'emergencia' ELSE 'detenido' END, "
                      "actualizado_ts=? WHERE usuario_id=?", (_ahora(), uid))
        db.auditar(uid, "modo_live_apagado", f"bot_{m}", m)
        decision(uid, m, None, "detener", "MODO LIVE apagado por el usuario")
    return estado(uid, m)


def habilitar_real(uid, frase, clave_ok, local=True):
    """Compatibilidad: enciende el MODO LIVE de la cuenta cTrader REAL."""
    return interruptor_live(uid, "real", True, clave_ok, local)


def deshabilitar_real(uid):
    return interruptor_live(uid, "real", False)


# ----------------------------------------------------------------- registro (cada modalidad en su base)
def decision(uid, modalidad, instrumento, accion, motivo, controles=None, motores=None, operacion_id=None):
    with almacen.tx(modalidad) as c:
        c.execute("INSERT INTO decisiones_bot(ts,usuario_id,modalidad,instrumento,accion,motivo,controles,motores,operacion_id) VALUES(?,?,?,?,?,?,?,?,?)",
                  (_ahora(), uid, modalidad, instrumento, accion, (motivo or "")[:1000], json.dumps(controles or [], ensure_ascii=False),
                   json.dumps(motores or []), operacion_id))


def abiertas(uid, modalidad):
    """Órdenes vivas: enviadas, aceptadas, abiertas o sin confirmar. Todas cuentan para la exposición."""
    return almacen.q(modalidad, f"SELECT * FROM operaciones WHERE usuario_id=? AND estado IN {_VIVOS_SQL} ORDER BY id", (uid,))


def _cerradas_desde(uid, modalidad, desde):
    return almacen.q(modalidad, f"SELECT * FROM operaciones WHERE usuario_id=? AND {VERIFICADA} AND cerrada_ts>=? ORDER BY cerrada_ts DESC", (uid, desde))


def resumen(uid):
    """Por cuenta de broker: solo operaciones con resultado verificado por el broker en 'n', 'neto', 'ganadas', 'perdidas'."""
    out = {}
    for m in MODALIDADES:
        r = almacen.q1(m, f"""SELECT COUNT(*) n, COALESCE(SUM(resultado),0) neto, COALESCE(SUM(resultado>0),0) ganadas, COALESCE(SUM(resultado<0),0) perdidas
                            FROM operaciones WHERE usuario_id=? AND {VERIFICADA}""", (uid,))
        r["abiertas"] = almacen.q1(m, "SELECT COUNT(*) n FROM operaciones WHERE usuario_id=? AND estado='abierta'", (uid,))["n"]
        r["pendientes"] = almacen.q1(m, "SELECT COUNT(*) n FROM operaciones WHERE usuario_id=? AND estado IN ('enviada','aceptada')", (uid,))["n"]
        r["sin_confirmar"] = almacen.q1(m, "SELECT COUNT(*) n FROM operaciones WHERE usuario_id=? AND estado='error'", (uid,))["n"]
        r["rechazadas"] = almacen.q1(m, "SELECT COUNT(*) n FROM operaciones WHERE usuario_id=? AND estado='rechazada'", (uid,))["n"]
        r["estado"] = estado(uid, m)["estado"]
        r["moneda"] = (almacen.q1(m, "SELECT moneda FROM operaciones WHERE usuario_id=? AND moneda IS NOT NULL ORDER BY id DESC LIMIT 1", (uid,)) or {}).get("moneda")
        r["fuente"] = "operaciones verificadas por el broker"
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
    ult = almacen.q(m, f"SELECT resultado, cerrada_ts FROM operaciones WHERE usuario_id=? AND {VERIFICADA} ORDER BY cerrada_ts DESC LIMIT ?",
                    (uid, aj["max_perdidas_consecutivas"]))
    racha = len(ult) == aj["max_perdidas_consecutivas"] and all((x["resultado"] or 0) < 0 for x in ult)
    # La racha de pérdidas PAUSA el bot durante pausa_racha_min desde la última pérdida; después vuelve a operar
    # (si vuelve a perder, la racha sigue y se pausa otra vez). Así el control no bloquea para siempre.
    fin_pausa = (ult[0]["cerrada_ts"] or 0) + int(aj.get("pausa_racha_min", 60)) * 60 if racha else 0
    racha_activa = racha and ahora < fin_pausa
    riesgo_nuevo = sol["riesgo_importe"]
    riesgo_abierto = sum(_riesgo_op(o) for o in ab)
    dup = almacen.q1(m, f"SELECT id FROM operaciones WHERE usuario_id=? AND instrumento=? AND direccion=? AND estado IN {_VIVOS_SQL[:-1]},'cerrada') AND abierta_ts>=?",
                     (uid, sol["instrumento"], sol["direccion"], ahora - aj["duplicado_ventana_s"]))
    sin_conf = [o for o in ab if o["estado"] in ("enviada", "error")]
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
    from ..seguridad import interruptores
    ok_int, motivo_int = interruptores.permitido(aj.get("broker"))
    ctl("interruptores_seguridad", ok_int, motivo_int or "PARADA TOTAL inactiva y broker habilitado")
    ctl("parada_emergencia", e["estado"] != "emergencia", e["estado"])
    ctl("modalidad_confirmada", m not in REALES or bool(e["real_habilitado"]),
        m if m not in REALES else ("MODO LIVE ACTIVADO" if e["real_habilitado"] else MOTIVO_REAL))
    ctl("ordenes_conciliadas", not sin_conf,
        "ninguna orden pendiente de conciliar" if not sin_conf else
        f"órdenes sin confirmar por el broker: {', '.join(str(o['id']) for o in sin_conf)} — concíliala(s) antes de enviar otra")
    ctl("conexion", adaptador.conectado(), adaptador.nombre)
    ctl("datos_frescos", cot["edad_s"] <= aj["datos_max_edad_s"], f"edad {cot['edad_s']} s (máx {aj['datos_max_edad_s']})")
    ctl("riesgo_por_operacion", riesgo_nuevo <= cap * aj["riesgo_pct"] / 100 * 1.0001, f"{riesgo_nuevo:.2f} de {cap * aj['riesgo_pct'] / 100:.2f}")
    libre = bool(aj.get("sin_limites_perdida")) and m not in REALES     # práctica sin límites de pérdida
    ctl("perdida_diaria", libre or -neto_dia + riesgo_nuevo <= cap * aj["perdida_diaria_max_pct"] / 100,
        f"neto hoy {neto_dia:.2f}" + (" (sin límite en práctica)" if libre else f", máx pérdida {cap * aj['perdida_diaria_max_pct'] / 100:.2f}"))
    ctl("perdida_semanal", libre or -neto_sem + riesgo_nuevo <= cap * aj["perdida_semanal_max_pct"] / 100,
        f"neto 7 d {neto_sem:.2f}" + (" (sin límite en práctica)" if libre else ""))
    ctl("exposicion_total", riesgo_abierto + riesgo_nuevo <= cap * aj["exposicion_max_pct"] / 100, f"riesgo abierto {riesgo_abierto:.2f} + {riesgo_nuevo:.2f}")
    ctl("max_operaciones_abiertas", len(ab) < aj["max_abiertas"], f"{len(ab)} de {aj['max_abiertas']}")
    ctl("perdidas_consecutivas", libre or not racha_activa,
        f"{len(ult)} pérdidas seguidas: pausa hasta {datetime.fromtimestamp(fin_pausa).strftime('%H:%M')}" if racha_activa
        else (f"racha de {len(ult)} pérdidas: pausa cumplida" if racha else f"últimas {len(ult)} sin racha de pérdidas"))
    ctl("spread", spread_pct is None or spread_pct <= aj["spread_max_pct"],
        f"{round(spread_pct, 4) if spread_pct is not None else '—'} % ({fuente_spread})")
    ctl("slippage", desliz <= aj["slippage_max_pct"], f"{desliz:.3f} % desde el precio del análisis")
    ctl("volatilidad", not (reg and reg["salida"]["regimen"] == "alta_volatilidad"), reg["salida"]["regimen"] if reg else "sin régimen")
    ctl("duplicados", dup is None, "sin operación igual reciente" if dup is None else f"operación {dup['id']} en la ventana")
    if m in BINARIAS:
        # Decisión del escáner (estrategia + umbral estadístico). El tope de abiertas es solo otro control.
        b = analisis.get("binaria") or {}
        ctl("ventaja_escaner", bool(b.get("ok")), b.get("detalle") or "sin decisión del escáner")
        ctl("payout_minimo", b.get("payout") is not None and b["payout"] >= aj["payout_min"],
            f"payout del broker {b.get('payout')} | mínimo {aj['payout_min']}")
        # Drawdown DEL DÍA (UTC): desde el máximo alcanzado hoy. Se reinicia cada día; la pérdida semanal sigue vigilando lo acumulado.
        ops_c = almacen.q(m, f"SELECT resultado FROM operaciones WHERE usuario_id=? AND {VERIFICADA} AND cerrada_ts>=? ORDER BY cerrada_ts, id", (uid, dia))
        acum = pico = 0.0
        for o in ops_c:
            acum += o["resultado"] or 0.0
            pico = max(pico, acum)
        dd = pico - acum
        ctl("drawdown", libre or dd + riesgo_nuevo <= cap * aj["drawdown_max_pct"] / 100,
            f"drawdown de hoy {dd:.2f} desde el máximo del día" + (" (sin límite en práctica)" if libre else f" (máx {cap * aj['drawdown_max_pct'] / 100:.2f})"))
        ctl("monto_minimo", riesgo_nuevo >= 1.0, f"{riesgo_nuevo:.2f} USD (mínimo 1.00)")
    elif sol["tipo"] == "binaria":
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
    if aj["broker"] == "iqoption":
        from .iqoption import IQOption
        from .. import integraciones
        # El correo se guarda en la configuración (no es secreto); la clave, en la bóveda.
        return IQOption(integraciones._config(uid, "iqoption"), cuenta="REAL" if aj["modalidad"] == "binaria_real" else "PRACTICE")
    if aj["broker"] == "ctrader":
        from .ctrader import CTrader
        return CTrader(uid, aj["modalidad"], aj.get("cuenta_ctid"), aj.get("simbolo_broker"))
    raise ValueError("Broker desconocido (la simulación interna se retiró)")


# ----------------------------------------------------------------- ciclo de vida de las órdenes
def _fase(c, oid, estado_nuevo, fase, detalle=None, id_broker=None, **cols):
    sets = {"estado": estado_nuevo, "fase": fase, "actualizado_ts": _ahora(), **cols}
    c.execute(f"UPDATE operaciones SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), oid))
    almacen.evento(c, oid, fase, detalle, id_broker)


def _confirmar_apertura(uid, modalidad, o, ad):
    """Pide al broker la confirmación de que la orden aceptada está abierta. Devuelve True si quedó confirmada."""
    try:
        v = ad.verificar_apertura(o)
    except Exception as ex:
        v = {"confirmada": False, "detalle": f"{type(ex).__name__}: {ex}"[:300]}
    if not v or not v.get("confirmada"):
        return False
    with almacen.tx(modalidad) as c:
        extra = {}
        if v.get("precio_entrada") is not None:
            extra["precio_entrada"] = v["precio_entrada"]
        n = c.execute("SELECT estado FROM operaciones WHERE id=?", (o["id"],)).fetchone()
        if not n or n["estado"] != "aceptada":
            return False
        _fase(c, o["id"], "abierta", "abierta_confirmada", v.get("evidencia") or v.get("detalle"), o.get("id_externo"), **extra)
    return True


def actualizar_abiertas(uid, modalidad, adaptador=None, ahora=None):
    """Concilia las órdenes vivas con el broker. Solo el broker cierra una operación y solo él da su resultado."""
    e = estado(uid, modalidad)
    cerradas = 0
    for o in abiertas(uid, modalidad):
        if o["estado"] == "enviada":
            if _ahora() - o["abierta_ts"] > ENVIADA_MAX_S:      # p. ej. el proceso se reinició entre el envío y la respuesta
                with almacen.tx(modalidad) as c:
                    _fase(c, o["id"], "error", "error_broker",
                          "orden enviada sin respuesta del broker: estado desconocido, requiere conciliación manual")
            continue
        if o["estado"] == "error" or not o.get("id_externo"):
            continue                                              # sin id del broker no hay nada que consultar: conciliar
        try:
            ad = adaptador or adaptador_para(uid, {**e["ajustes"], "broker": o["broker"]})
            if o["estado"] == "aceptada":
                _confirmar_apertura(uid, modalidad, o, ad)
            elif o["estado"] == "abierta" and o["tipo"] == "margen" and e["ajustes"].get("trailing") and hasattr(ad, "gestionar_stop"):
                _trailing(uid, modalidad, o, ad, e["ajustes"])
            r = ad.actualizar(o, ahora) if ahora else ad.actualizar(o)
        except Exception as ex:
            alertas.crear(uid, "conexion", f"No se pudo consultar la operación {modalidad} {o['id']} en el broker", "media", o["instrumento"],
                          justificacion=str(ex)[:200], modalidad=modalidad, clave_dedupe=f"upd|{modalidad}|{o['id']}|{_ahora() // 3600}", notificar=False)
            continue
        if r and r.get("resultado") is not None:
            _cerrar(uid, modalidad, o, r)
            cerradas += 1
    return cerradas


def _trailing(uid, modalidad, o, ad, aj):
    """Mueve el stop A FAVOR en el broker y lo registra (evento 'ajuste_stop' con la evidencia de cTrader)."""
    cfg = {k: aj[k] for k in ("be_r", "trail_desde_r", "trail_atr_fuerte", "trail_atr_debil")}
    cfg["tf"] = (str(aj.get("temporalidades") or "15m").split(",") or ["15m"])[0]
    try:
        r = ad.gestionar_stop(o, cfg)
    except Exception as ex:
        alertas.crear(uid, "conexion", f"Trailing no aplicado en la operación {modalidad} {o['id']}", "media", o["instrumento"],
                      justificacion=str(ex)[:200], modalidad=modalidad, clave_dedupe=f"trail|{modalidad}|{o['id']}|{_ahora() // 3600}", notificar=False)
        return None
    if r and r.get("movido"):
        with almacen.tx(modalidad) as c:
            c.execute("UPDATE operaciones SET stop=?, stop_inicial=COALESCE(stop_inicial, ?), actualizado_ts=? WHERE id=?",
                      (r["stop_nuevo"], r["stop_actual"], _ahora(), o["id"]))
            almacen.evento(c, o["id"], "ajuste_stop", {"motivo": r["motivo"], **(r.get("evidencia") or {})}, o.get("id_externo"))
        decision(uid, modalidad, o["instrumento"], "ajustar_stop", f"Stop {r['stop_actual']} → {r['stop_nuevo']} · {r['motivo']}", operacion_id=o["id"])
    return r


def _cerrar(uid, modalidad, o, r):
    """Registra el cierre CONFIRMADO por el broker y su resultado. Sin resultado del broker no se cierra nada."""
    if r.get("resultado") is None:
        return
    rr = r.get("r")
    if rr is None and o.get("riesgo_importe"):
        rr = r["resultado"] / o["riesgo_importe"]
    with almacen.tx(modalidad) as c:
        fila = c.execute(f"SELECT estado FROM operaciones WHERE id=? AND estado IN ('aceptada','abierta')", (o["id"],)).fetchone()
        if not fila:
            return
        if fila["estado"] == "aceptada":            # el broker ya la tiene cerrada: la apertura queda confirmada por el cierre
            almacen.evento(c, o["id"], "abierta_confirmada", "confirmada por el registro de cierre del broker", o.get("id_externo"))
        almacen.evento(c, o["id"], "cerrada_confirmada", r.get("evidencia_cierre") or f"motivo: {r['motivo']}", o.get("id_externo"))
        _fase(c, o["id"], "cerrada", "resultado_recibido", r.get("evidencia") or {"resultado": r["resultado"], "motivo": r["motivo"]},
              o.get("id_externo"), cerrada_ts=_ahora(), precio_salida=r.get("precio_salida"), resultado=r["resultado"], r=rr,
              motivo_cierre=r["motivo"], fuente_resultado="broker")
    almacen.aprender(modalidad, o.get("estrategia"), o["instrumento"], o.get("horizonte"), o["direccion"], rr, r["motivo"])
    decision(uid, modalidad, o["instrumento"], "cerrar", f"{r['motivo']}: resultado del broker {r['resultado']:+.2f} {o.get('moneda') or ''}", operacion_id=o["id"])
    alertas.crear(uid, "operacion", f"Operación {modalidad.upper()} cerrada en el broker ({r['motivo']})", "media", o["instrumento"], o["mercado"], o["direccion"],
                  r.get("precio_salida"), modalidad=modalidad, justificacion=f"Resultado del broker {r['resultado']:+.2f} {o.get('moneda') or ''} (id {o.get('id_externo')})",
                  motores=json.loads(o["motores"] or "[]"), clave_dedupe=f"cerr|{modalidad}|{o['id']}")


def conciliar(uid, modalidad, operacion_id, resultado_broker, nota):
    """Conciliación MANUAL de una orden sin confirmar (estado 'error'), tras revisarla en el propio broker.
    resultado_broker: 'no_ejecutada' (el broker no la tiene) → queda rechazada; cualquier otro caso requiere
    que el bot la vuelva a consultar, así que solo se admite 'no_ejecutada' o 'id_broker:<id>' (se reintenta con ese id)."""
    m = _mod(modalidad)
    nota = (nota or "").strip()
    if len(nota) < 5:
        raise ValueError("Describe qué comprobaste en el broker (mínimo 5 caracteres).")
    o = almacen.q1(m, "SELECT * FROM operaciones WHERE id=? AND usuario_id=?", (int(operacion_id), uid))
    if not o or o["estado"] != "error":
        raise ValueError("Solo se concilian órdenes en estado 'error' (sin confirmar por el broker).")
    with almacen.tx(m) as c:
        if resultado_broker == "no_ejecutada":
            _fase(c, o["id"], "rechazada", "error_broker", f"conciliación manual: el broker no tiene la orden — {nota}",
                  motivo_cierre=("no ejecutada (conciliada) · " + nota)[:1000], clave_dedupe=None)
        elif str(resultado_broker).startswith("id_broker:") and str(resultado_broker)[10:].strip():
            idb = str(resultado_broker)[10:].strip()
            _fase(c, o["id"], "aceptada", "orden_aceptada", f"conciliación manual: el broker muestra la orden {idb} — {nota}", idb, id_externo=idb)
        else:
            raise ValueError("resultado_broker debe ser 'no_ejecutada' o 'id_broker:<id>'.")
    db.auditar(uid, "conciliar_orden", f"bot_{m}", str(o["id"]), {"resultado_broker": resultado_broker, "nota": nota})
    return almacen.q1(m, "SELECT * FROM operaciones WHERE id=?", (o["id"],))


def _emergencia(uid, modalidad, adaptador=None):
    e = estado(uid, modalidad)
    for o in abiertas(uid, modalidad):
        if not o.get("id_externo"):
            alertas.crear(uid, "riesgo", f"Orden {modalidad} {o['id']} sin id del broker durante la emergencia", "critica", o["instrumento"],
                          justificacion="Revisa el broker y concíliala manualmente.", modalidad=modalidad, clave_dedupe=f"emergsinid|{modalidad}|{o['id']}")
            continue
        try:
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
    else:                                        # el broker calcula volumen y niveles con su propio precio
        stop, objetivo = esc["stop_loss"], esc["take_profit"][0]
        stop_pct = abs(ref - stop) / ref
        obj_pct = abs(objetivo - ref) / ref
        monto = riesgo / stop_pct
        stop = cot["precio"] - sg * cot["precio"] * stop_pct
        objetivo = cot["precio"] + sg * cot["precio"] * obj_pct
    instrumento = aj["simbolo_broker"] if aj["broker"] == "ctrader" and aj.get("simbolo_broker") else aj["instrumento"]
    return {"instrumento": instrumento, "direccion": esc["direccion"], "tipo": aj["tipo"], "monto": round(monto, 2),
            "riesgo_importe": riesgo, "stop": stop, "objetivo": objetivo, "stop_dist_pct": stop_pct, "obj_dist_pct": obj_pct,
            "precio_ref": esc["precio_referencia"] if aj["fuente_datos"] == "broker" else cot["precio"],
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


def ruta_escaner_vivo():
    """Estadísticas del escáner binario (candidatas resueltas). No contiene saldos, IDs de cuenta ni operaciones."""
    from .. import config
    return config.DATOS / "binaria_bot" / "escaner_vivo.db"


def _enviar(uid, m, aj, sol, an, ad, ctl, motores, mercado, out):
    """Registra la orden ANTES de enviarla y la hace avanzar de fase solo con la respuesta del broker."""
    from ..seguridad import interruptores
    ok_int, motivo_int = interruptores.permitido(aj.get("broker"))
    if not ok_int:                               # defensa en profundidad: aunque un control fallara, nada sale al broker
        decision(uid, m, sol["instrumento"], "rechazar", "Bloqueada por seguridad: " + motivo_int, ctl, motores)
        out.update(accion="bloqueado_seguridad", error=motivo_int)
        return out
    clave = f"{sol['instrumento']}|{sol['direccion']}|{an['ts'] // max(60, aj['duplicado_ventana_s'])}"
    with almacen.tx(m) as c:
        cur = c.execute("""INSERT OR IGNORE INTO operaciones(usuario_id,modalidad,broker,cuenta,instrumento,simbolo_broker,mercado,tipo,direccion,monto,
                           riesgo_importe,stop,objetivo,payout,expira_ts,costo,estado,fase,abierta_ts,estrategia,horizonte,motores,controles,clave_dedupe,actualizado_ts)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,'enviada','orden_enviada',?,?,?,?,?,?,?)""",
                        (uid, m, aj["broker"], str(aj.get("cuenta_ctid") or m), sol["instrumento"], aj.get("simbolo_broker"), mercado, sol["tipo"],
                         sol["direccion"], sol["monto"], sol["riesgo_importe"], sol["stop"], sol["objetivo"], sol["payout"],
                         sol["expira_ts"] if aj["broker"] != "ctrader" else None, _ahora(), aj["estrategia"], aj["horizonte"],
                         json.dumps(motores), json.dumps(ctl, ensure_ascii=False), clave, _ahora()))
        oid = cur.lastrowid if cur.rowcount else None
        if oid:
            almacen.evento(c, oid, "orden_enviada", {k: sol[k] for k in ("instrumento", "direccion", "tipo", "monto", "riesgo_importe")})
    if not oid:
        decision(uid, m, sol["instrumento"], "rechazar", "Orden duplicada: ya se envió una igual en esta ventana", ctl, motores)
        out["accion"] = "duplicada"
        return out
    out["operacion_id"] = oid
    try:
        ej = ad.abrir(sol)
    except ErrorAdaptador as ex:                 # el broker (o el adaptador antes de enviar) la rechazó: no se ejecutó
        with almacen.tx(m) as c:
            _fase(c, oid, "rechazada", "error_broker", str(ex)[:1000], motivo_cierre=("rechazada: " + str(ex))[:1000],
                  clave_dedupe=None)            # no se ejecutó: la clave anti-duplicado queda libre
        decision(uid, m, sol["instrumento"], "rechazar", f"El broker rechazó: {ex}", ctl, motores, oid)
        alertas.crear(uid, "integracion", f"El broker rechazó una orden ({m.upper()})", "alta", sol["instrumento"], justificacion=str(ex),
                      modalidad=m, clave_dedupe=f"brk|{m}|{oid}")
        out.update(accion="rechazar", error=str(ex))
        return out
    except Exception as ex:                      # sin respuesta clara: PUDO ejecutarse. No se reintenta; se concilia.
        texto = f"{'Orden no confirmada' if isinstance(ex, OrdenNoConfirmada) else type(ex).__name__}: {ex}"[:1000]
        with almacen.tx(m) as c:
            _fase(c, oid, "error", "error_broker", texto + " — requiere conciliación en el broker",
                  motivo_cierre="sin confirmar: " + texto[:900])
        decision(uid, m, sol["instrumento"], "error", f"Orden sin confirmar por el broker: {texto}", ctl, motores, oid)
        alertas.crear(uid, "integracion", f"Orden {m.upper()} sin confirmar por el broker", "critica", sol["instrumento"],
                      justificacion=texto + " — revisa el broker y concíliala; el bot no enviará más órdenes hasta entonces.",
                      modalidad=m, clave_dedupe=f"sinconf|{m}|{oid}")
        out.update(accion="sin_confirmar", error=texto)
        _vigilar_errores_broker(uid, m, aj)
        return out
    if not ej or not ej.get("id_externo"):
        with almacen.tx(m) as c:
            _fase(c, oid, "error", "error_broker", "el broker no devolvió identificador de la orden — requiere conciliación",
                  motivo_cierre="sin id del broker")
        out["accion"] = "sin_confirmar"
        return out
    with almacen.tx(m) as c:
        _fase(c, oid, "aceptada", "orden_aceptada", ej.get("evidencia") or {"id": ej["id_externo"]}, ej["id_externo"],
              id_externo=str(ej["id_externo"]), precio_entrada=ej.get("precio_entrada"), costo=ej.get("costo") or 0.0,
              monto=ej.get("monto", sol["monto"]), riesgo_importe=ej.get("riesgo_importe", sol["riesgo_importe"]),
              volumen=ej.get("volumen"), moneda=ej.get("moneda"), stop=ej.get("stop", sol["stop"]),
              objetivo=ej.get("objetivo", sol["objetivo"]), payout=ej.get("payout", sol["payout"]), stop_inicial=ej.get("stop", sol["stop"]),
              simbolo_broker=ej.get("simbolo_broker") or aj.get("simbolo_broker"), fuente_precio=ej.get("fuente_precio"),
              evidencia=json.dumps(ej.get("evidencia") or {"id": ej["id_externo"]}, ensure_ascii=False, default=str))
    o = almacen.q1(m, "SELECT * FROM operaciones WHERE id=?", (oid,))
    confirmada = _confirmar_apertura(uid, m, o, ad)
    decision(uid, m, sol["instrumento"], "abrir",
             f"Orden aceptada por el broker (id {ej['id_externo']}); apertura {'CONFIRMADA' if confirmada else 'PENDIENTE de confirmar'}",
             ctl, motores, oid)
    alertas.crear(uid, "entrada", f"Orden {m.upper()} aceptada por el broker: {sol['direccion']} {ej.get('simbolo_broker') or sol['instrumento']}", "alta",
                  sol["instrumento"], mercado, sol["direccion"], ej.get("precio_entrada"), an["horizonte"],
                  f"id del broker {ej['id_externo']} · apertura {'confirmada' if confirmada else 'pendiente de confirmar'}. "
                  + " ".join((an.get("fusion") or {}).get("justificacion", [])[:3]), motores, m, {"operacion_id": oid}, clave_dedupe=f"abr|{m}|{oid}")
    out.update(accion="abrir", confirmada=confirmada, id_broker=str(ej["id_externo"]))
    return out


def _vigilar_errores_broker(uid, m, aj):
    from ..seguridad import interruptores
    try:
        n = 0
        for mm in MODALIDADES:
            if POR_DEFECTO[mm]["broker"] == aj.get("broker"):
                n += almacen.q1(mm, "SELECT COUNT(*) n FROM operaciones WHERE usuario_id=? AND fase='error_broker' AND estado='error' AND abierta_ts>?",
                                (uid, _ahora() - interruptores.VENTANA_ERRORES_S))["n"]
        interruptores.vigilar_errores(uid, aj.get("broker"), n)
    except Exception as ex:                      # la vigilancia nunca debe romper el ciclo; queda constancia
        decision(uid, m, None, "error", f"Vigilancia de errores del broker no disponible: {type(ex).__name__}")


def _descartar(uid, m, aj, sol, an, ctl, fallos, motores, mercado, out):
    """Oportunidad detectada y descartada por los controles: NO es una operación y nunca llega al broker."""
    with almacen.tx(m) as c:
        cur = c.execute("""INSERT INTO operaciones(usuario_id,modalidad,broker,cuenta,instrumento,simbolo_broker,mercado,tipo,direccion,monto,riesgo_importe,
                           stop,objetivo,payout,expira_ts,estado,fase,abierta_ts,motivo_cierre,estrategia,horizonte,motores,controles,actualizado_ts)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'rechazada','oportunidad_detectada',?,?,?,?,?,?,?)""",
                        (uid, m, aj["broker"], str(aj.get("cuenta_ctid") or m), sol["instrumento"], aj.get("simbolo_broker"), mercado, sol["tipo"],
                         sol["direccion"], sol["monto"], sol["riesgo_importe"], sol["stop"], sol["objetivo"], sol["payout"], sol["expira_ts"], _ahora(),
                         ("no enviada (controles): " + "; ".join(f"{x['control']}: {x['detalle']}" for x in fallos))[:1000], aj["estrategia"], aj["horizonte"],
                         json.dumps(motores), json.dumps(ctl, ensure_ascii=False), _ahora()))
        oid = cur.lastrowid
        almacen.evento(c, oid, "oportunidad_detectada", "descartada por controles: " + ", ".join(x["control"] for x in fallos))
    decision(uid, m, sol["instrumento"], "rechazar", "Oportunidad descartada por controles: " + ", ".join(x["control"] for x in fallos), ctl, motores, oid)
    alertas.crear(uid, "operacion", f"Oportunidad {m.upper()} descartada por controles de riesgo", "media", sol["instrumento"], mercado, sol["direccion"],
                  sol["precio_ref"], an["horizonte"], ", ".join(x["control"] for x in fallos), motores, m, clave_dedupe=f"rech|{m}|{oid}")
    out["accion"] = "rechazar"
    out["controles"] = ctl
    return out


def config_escaner(aj):
    """Configuración del escáner a partir de los ajustes del bot."""
    tfs = [x for x in str(aj.get("temporalidades") or aj.get("intervalo_escaner") or "15m").split(",") if x]
    tfb = [x for x in str(aj.get("temporalidades_binaria") or "1m").split(",") if x]
    return {"estrategias": aj.get("estrategias_activas") or _estrategias_defecto(), "intervalo": tfs[0], "intervalos": tfs,
            "intervalos_binaria": tfb, "exploracion": bool(aj.get("modo_exploracion")) and aj.get("modalidad") not in REALES,
            "tendencia": (int(aj.get("tendencia_rapida", 50)), int(aj.get("tendencia_lenta", 200))) if aj.get("filtro_tendencia") else None,
            "atr_stop": aj["atr_stop"], "atr_obj": aj["atr_obj"], "min_ops": aj["min_ops_bt"], "exp_min": aj["exp_min"],
            "margen": aj["margen_bt"], "lote": aj["lote_escaner"],
            # tiempo máximo del re-backtest por ciclo: la búsqueda de señales en vivo nunca espera al aprendizaje
            "presupuesto_s": PRESUPUESTO_RANKING_S["binaria" if aj.get("broker") == "iqoption" else "ctrader"],
            "presupuesto_senales_s": PRESUPUESTO_SENALES_S["binaria" if aj.get("broker") == "iqoption" else "ctrader"], "max_simbolos": aj["max_simbolos"], "solo_divisas": aj.get("solo_divisas", True),
            "simbolos": [x for x in (aj.get("simbolos_escaner") or "").split(",") if x], "pares": [x for x in (aj.get("simbolos_escaner") or "").split(",") if x]}


def _control_aprendizaje(m, aj, estrategia, simbolo):
    """Aprende de los resultados REALES del broker (conocimiento en R, solo de esta cuenta): bloquea una estrategia en un activo
    si pierde en real tras aprendizaje_min_ops operaciones, y la estrategia entera si pierde tras 2,5 veces esa muestra."""
    n_min = int(aj.get("aprendizaje_min_ops", 8))
    par = almacen.conocimiento(estrategia, simbolo, origen=m)
    tot = almacen.conocimiento(estrategia, origen=m)
    if par["n"] >= n_min and (par["expectativa_r"] or 0) < 0:
        return {"control": "aprendizaje_real", "ok": False,
                "detalle": f"{estrategia} en {simbolo} pierde en real: {par['expectativa_r']:+.2f} R en {par['n']} operaciones del broker"}
    if tot["n"] >= int(2.5 * n_min) and (tot["expectativa_r"] or 0) < 0:
        return {"control": "aprendizaje_real", "ok": False,
                "detalle": f"{estrategia} pierde en real en esta cuenta: {tot['expectativa_r']:+.2f} R en {tot['n']} operaciones"}
    return {"control": "aprendizaje_real", "ok": True,
            "detalle": f"resultados reales: {estrategia} en {simbolo} {par['n']} ops, en total {tot['n']} ops"
                       + (f" ({tot['expectativa_r']:+.2f} R)" if tot["n"] else "")}


def riesgo_beneficio(aj, cand, sg):
    """Objetivo como múltiplo del riesgo: SIEMPRE 1:rr_base (1:2). Solo con VENTAJA sube: 1:rr_tendencia (1:3) si la señal va
    a favor de la tendencia (EMA 50/200) y el backtest fuera de muestra da ≥ ventaja_rr_tendencia R; 1:rr_max (1:4) si esa
    expectativa llega a ventaja_rr_max R. Ambas con al menos 20 operaciones fuera de muestra."""
    a_favor = cand.get("tendencia") == sg
    exp, n = cand.get("exp_fuera") or 0, cand.get("n_fuera") or 0
    if a_favor and n >= 20 and exp >= aj["ventaja_rr_max"]:
        return aj["rr_max"], f"ventaja fuerte: tendencia a favor y {exp:+.2f} R fuera de muestra"
    if a_favor and n >= 20 and exp >= aj.get("ventaja_rr_tendencia", 0.1):
        return aj["rr_tendencia"], f"ventaja: tendencia a favor y {exp:+.2f} R fuera de muestra"
    return aj["rr_base"], "base 1:2" if aj["rr_base"] == 2 else "base"


def _ciclo_multiactivo(uid, m, aj, ad, out, adaptador_fijo=None):
    """Escanea TODOS los activos del broker: refresca el ranking por backtesting (aprendizaje continuo) y envía las señales
    de los pares activo-estrategia aptos, cada una pasando por todos los controles de riesgo y el flujo de fases."""
    cfg = config_escaner(aj)
    n_reales = almacen.q1(m, f"SELECT COUNT(*) n FROM operaciones WHERE usuario_id=? AND {VERIFICADA}", (uid,))["n"]
    if m in REALES or not aj.get("modo_exploracion") or n_reales >= aj["muestra_exploracion"]:
        cfg["exploracion"], cfg["estricto"] = False, True        # MODO EVIDENCIA: solo ventaja estadística demostrada
    out["fase"] = "evidencia" if cfg.get("estricto") else f"exploración ({n_reales}/{aj['muestra_exploracion']} operaciones reales)"
    cands, hechos = [], []
    try:
        if aj["broker"] == "ctrader":
            from ..backtest_ctrader import escaner as esc
            ses = ad._abrir()
            try:
                cat = ad._catalogo(ses)["simbolos"]
                hechos = esc.actualizar_ranking(ses, ad.entorno, cat, cfg)
                cands = esc.senales_vivas(ses, ad.entorno, cat, cfg)
            finally:
                ses.cerrar()
        else:
            from ..backtest_binaria import escaner as escb
            api = ad._sesion()
            hechos = escb.actualizar_ranking(api, cfg)
            cands = escb.senales_vivas(ad, cfg)
    except Exception as ex:
        decision(uid, m, None, "omitir", f"Escáner: broker no disponible: {str(ex)[:200]}")
        out["accion"] = "broker_no_disponible"
        return out
    out["escaneados"] = [h.get("simbolo") or h.get("activo") for h in hechos]
    out["candidatas"] = len(cands)
    if not cands:
        resumen_txt = f"Escáner: {len(hechos)} activos re-evaluados por backtest; sin señal en los aptos"
        ult = almacen.q1(m, "SELECT motivo, ts FROM decisiones_bot WHERE usuario_id=? AND accion='omitir' ORDER BY id DESC LIMIT 1", (uid,))
        if not ult or _ahora() - ult["ts"] > 900:
            decision(uid, m, None, "omitir", resumen_txt + " (" + ", ".join(out["escaneados"][:8]) + ")")
        out["accion"] = "omitir"
        return out
    resultados = []
    for cand in cands:
        if len(abiertas(uid, m)) >= aj["max_abiertas"]:
            break
        simbolo = cand.get("simbolo") or cand.get("activo")
        tf = cand.get("intervalo") or cfg["intervalo"]
        aj2 = {**aj, "instrumento": simbolo, "simbolo_broker": simbolo, "estrategia": cand["estrategia"],
               "horizonte": tf if aj["broker"] == "ctrader" else f"{tf}·vence 5 min"}
        sub = {"modalidad": m, "accion": None}
        try:
            if aj["broker"] == "ctrader":
                from .ctrader import CTrader
                ad_s = adaptador_fijo or CTrader(uid, m, aj.get("cuenta_ctid"), simbolo)
                cot = ad_s.cotizacion(simbolo)
                precio = cot["precio"]
                sg = 1 if cand["direccion"] == "alcista" else -1
                rr, por_que = riesgo_beneficio(aj, cand, sg)
                stop_pct = aj["atr_stop"] * cand["atr"] / precio
                obj_pct = stop_pct * rr
                riesgo = aj["capital"] * aj["riesgo_pct"] / 100
                sol = {"instrumento": simbolo, "direccion": cand["direccion"], "tipo": "margen", "monto": round(riesgo / stop_pct, 2),
                       "riesgo_importe": riesgo, "stop": precio - sg * precio * stop_pct, "objetivo": precio + sg * precio * obj_pct,
                       "stop_dist_pct": stop_pct, "obj_dist_pct": obj_pct, "precio_ref": cand["precio_ref"], "expira_ts": None, "payout": None,
                       "modalidad": m, "estrategia": cand["estrategia"], "clase": None}
                detalle = (f"{cand['estrategia']} {tf} en {simbolo} ({cand.get('descripcion') or 'cTrader'}): backtest fuera de muestra "
                           f"{cand['exp_fuera']:+.3f} R en {cand['n_fuera']} ops · objetivo 1:{rr:g} ({por_que})"
                           f"{' · EXPLORACIÓN' if cfg['exploracion'] else ''}")
                an = {"ts": cand["vela_ts"], "horizonte": tf, "motores": [], "fusion": {"justificacion": [detalle]}}
                mercado = "cTrader"
            else:
                ad_s = ad
                if aj.get("capital_desde_broker", True) and hasattr(ad, "saldo"):
                    try:                                       # capital actual del broker antes de CADA operación
                        aj["capital"] = ad.saldo()["balance"]
                    except Exception:                          # sin respuesta: se usa el último saldo leído de IQ Option
                        pass
                cot = ad.cotizacion(simbolo)
                riesgo = aj["capital"] * aj["riesgo_pct"] / 100
                sol = {"instrumento": simbolo, "direccion": cand["direccion"], "tipo": "binaria", "monto": round(riesgo, 2), "riesgo_importe": riesgo,
                       "stop": None, "objetivo": None, "stop_dist_pct": None, "obj_dist_pct": None, "precio_ref": cand["precio_ref"],
                       "expira_ts": _ahora() + 5 * 60, "payout": cand["payout"], "modalidad": m, "estrategia": cand["estrategia"], "clase": "binaria"}
                detalle = (f"{cand['estrategia']} {tf} en {simbolo}: acierto fuera de muestra {cand['acierto_fuera']:.1%} vs equilibrio "
                           f"{cand['equilibrio']:.1%} en {cand['n_fuera']} ops{' · EXPLORACIÓN' if cfg['exploracion'] else ''}")
                an = {"ts": cand["vela_ts"], "horizonte": f"{tf}·5min", "motores": [], "fusion": {"justificacion": [detalle]},
                      "binaria": {"ok": True, "payout": cand["payout"], "detalle": detalle}}
                mercado = "binarias"
        except Exception as ex:
            decision(uid, m, simbolo, "rechazar", f"Sin cotización del broker: {str(ex)[:200]}")
            resultados.append({"activo": simbolo, "accion": "rechazar"})
            continue
        extra = [_control_aprendizaje(m, aj, cand["estrategia"], simbolo)]
        usados = [cand["estrategia"]]
        if aj.get("confirmar_motores", True) and cand.get("velas"):
            from .. import confirmacion
            conf = confirmacion.confirmar(uid, simbolo, cand["direccion"], confirmacion.serie_desde(cand["velas"], cand.get("proveedor", aj["broker"]), simbolo, tf),
                                          tf, aj.get("umbral_contra", 0.15), veto_macro=aj.get("veto_macro", True))
            an["motores"] = conf["motores"]                    # el régimen de los motores también alimenta el control de volatilidad
            an["fusion"]["justificacion"].append(conf["detalle"])
            usados += [x["motor"] for x in conf["motores"] if x.get("estado") in ("completado", "simplificado")]
            extra.append({"control": "confirmacion_23_motores", "ok": conf["ok"], "detalle": conf["detalle"]})
        ctl = controles(uid, aj2, sol, cot, an, ad_s) + extra
        fallos = [x for x in ctl if not x["ok"]]
        if fallos:
            r = _descartar(uid, m, aj2, sol, an, ctl, fallos, usados, mercado, sub)
        else:
            r = _enviar(uid, m, aj2, sol, an, ad_s, ctl, usados, mercado, sub)
        resultados.append({"activo": simbolo, "estrategia": cand["estrategia"], "accion": r.get("accion"), "operacion_id": r.get("operacion_id")})
    out["resultados"] = resultados
    out["accion"] = "abrir" if any(x["accion"] == "abrir" for x in resultados) else (resultados[-1]["accion"] if resultados else "omitir")
    return out


def ciclo(uid, modalidad, analizar_fn=None, adaptador=None):
    """Un ciclo completo del bot de UNA modalidad. Devuelve lo que hizo (para pruebas y la interfaz)."""
    m = _mod(modalidad)
    e = estado(uid, m)
    aj = dict(e["ajustes"])
    out = {"modalidad": m, "estado": e["estado"], "cerradas": 0, "accion": None}
    if m in REALES and not e["real_habilitado"] and e["estado"] != "emergencia":
        if e["estado"] == "activo":
            with almacen.tx(m) as c:
                c.execute("UPDATE bot_estado SET estado='detenido', actualizado_ts=? WHERE usuario_id=?", (_ahora(), uid))
            decision(uid, m, aj["instrumento"], "rechazar", MOTIVO_REAL)
        out["cerradas"] = actualizar_abiertas(uid, m, adaptador)    # las órdenes vivas se siguen conciliando
        out["accion"] = "bloqueado"
        return out
    if e["estado"] == "emergencia":
        _emergencia(uid, m, adaptador)
        out["accion"] = "emergencia"
        return out
    out["cerradas"] = actualizar_abiertas(uid, m, adaptador)
    if e["estado"] != "activo":
        out["accion"] = "inactivo"
        return out
    from ..seguridad import interruptores
    ok_int, motivo_int = interruptores.permitido(aj.get("broker"))
    if not ok_int:
        ya = almacen.q1(m, "SELECT 1 FROM decisiones_bot WHERE usuario_id=? AND motivo=? AND ts>?", (uid, "Seguridad: " + motivo_int, _ahora() - 600))
        if not ya:
            decision(uid, m, None, "omitir", "Seguridad: " + motivo_int)
        out["accion"] = "bloqueado_seguridad"
        return out
    from ..motores import nucleo
    nivel = db.cfg_usuario(uid, "nivel", "intermedio")
    politica = db.cfg_usuario(uid, "politica", "automatico")
    ad = adaptador or adaptador_para(uid, aj)
    serie = None
    payout = None
    try:
        if aj.get("capital_desde_broker", True) and hasattr(ad, "saldo"):
            try:
                sal = ad.saldo()
            except Exception:
                # El broker no respondió a tiempo: se usa el último saldo REAL leído de esta cuenta si tiene < 15 min
                ult = almacen.q1(m, "SELECT balance, moneda FROM saldos WHERE usuario_id=? AND ts>? ORDER BY ts DESC LIMIT 1",
                                 (uid, _ahora() - 900))
                if not ult:
                    raise
                sal = {"balance": ult["balance"], "moneda": ult["moneda"]}
            aj["capital"] = sal["balance"]
            with almacen.tx(m) as c:
                c.execute("INSERT INTO saldos(ts,usuario_id,cuenta,balance,moneda) VALUES(?,?,?,?,?)",
                          (_ahora(), uid, str(aj.get("cuenta_ctid") or m), sal["balance"], sal.get("moneda")))
        if aj["estrategia"] == "multiactivo":
            pass                                             # el escáner pide sus propios datos al broker
        elif m in BINARIAS:
            serie = ad.velas_m1(aj["instrumento"], 120)      # solo velas M1 cerradas
            payout = ad.payout(aj["instrumento"])            # solo lectura; None => abstención
        elif aj["fuente_datos"] == "broker" and hasattr(ad, "serie"):
            serie = _serie_broker(ad, aj, nivel)
    except Exception as ex:
        decision(uid, m, aj["instrumento"], "omitir", f"Broker no disponible: {str(ex)[:200]}")
        alertas.crear(uid, "conexion", f"Bot {m.upper()}: broker no disponible", "alta", aj["instrumento"], justificacion=str(ex)[:300],
                      modalidad=m, clave_dedupe=f"brkoff|{m}|{_ahora() // 3600}")
        out["accion"] = "broker_no_disponible"
        return out
    if aj["estrategia"] == "multiactivo":
        return _ciclo_multiactivo(uid, m, aj, ad, out, adaptador)
    try:
        if m in BINARIAS:
            from ..binaria_bot import puente_trader
            fn = analizar_fn or puente_trader.analizar_binaria
            kw = {"usuario_id": uid, "riesgo": {"capital": aj["capital"], "riesgo_pct": aj["riesgo_pct"]},
                  "serie": serie, "payout": payout, "ruta_escaner": ruta_escaner_vivo(),
                  "min_resueltas": aj["ventaja_min_operaciones"]}
        else:
            fn = analizar_fn or nucleo.analizar
            kw = {"usuario_id": uid, "riesgo": {"capital": aj["capital"], "riesgo_pct": aj["riesgo_pct"]}}
            if aj.get("modo_exploracion"):
                kw["explorar"] = True
            if serie is not None:
                kw["serie"] = serie
        an = fn(aj["instrumento"], aj["horizonte"], nivel, politica, **kw)
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
        decision(uid, m, aj["instrumento"], "rechazar", f"Sin cotización del broker o solicitud inválida: {ex}", motores=motores)
        out["accion"] = "rechazar"
        return out
    ctl = controles(uid, aj, sol, cot, an, ad)
    fallos = [x for x in ctl if not x["ok"]]
    mercado = (an.get("fuente_datos") or {}).get("tipo") or aj["mercado"]
    if fallos:
        return _descartar(uid, m, aj, sol, an, ctl, fallos, motores, mercado, out)
    return _enviar(uid, m, aj, sol, an, ad, ctl, motores, mercado, out)


# ----------------------------------------------------------------- hilo de fondo (los bots)
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
