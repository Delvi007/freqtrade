"""Puente entre el escáner binario (Keltner + RCI, pares OTC de divisas) y el bot operador, modalidad 'binaria'.

SOLO DECIDE. No envía órdenes: la ejecución la hace el adaptador de la modalidad (IQ Option, PRACTICE).

Reglas (confirmadas por el operador):
  * Solo pares OTC de divisas (escaner.es_par_otc). Cualquier otro activo se rechaza.
  * La decisión depende de la estrategia y del umbral estadístico (límite inferior de Wilson frente al
    punto de equilibrio del payout), NO del tope de operaciones abiertas. El tope es un control aparte.
  * Causal: las estadísticas solo usan candidatas YA VENCIDAS antes de la entrada (escaner.estadisticas_previas).
  * Datos no fiables (pocas velas, huecos, velas viejas, payout desconocido) => abstención con motivo.
  * La base del escáner (estadísticas) es independiente de las bases de cuenta: no contiene saldos ni IDs.

Entrada: velas M1 CERRADAS del broker, ordenadas por tiempo, como dicts {ts, open, high, low, close}.
"""
import time

from titan_quant.binaria_bot import escaner as es
from titan_quant.binaria_bot.almacen import Almacen
from titan_quant.binaria_bot.datos import Vela
from titan_quant.estrategias.keltner_rci import senales

VELAS_MINIMAS = 30          # calentamiento de Keltner(20) + RCI(14) + ventana
EDAD_MAX_S = 120            # la última vela cerrada no puede tener más de 2 min de antigüedad
SEG_VELA = es.SEG_VELA      # 60
VENCIMIENTO_VELAS = es.VENCIMIENTO_VELAS  # 5 => vencimiento de 5 minutos (clave turbo verificada)


def velas_desde_dicts(filas):
    out = []
    for f in filas or []:
        out.append(Vela(ts=int(f["ts"]), open=float(f["open"]), high=float(f["high"]),
                        low=float(f["low"]), close=float(f["close"])))
    return out


def _contiguas(velas):
    return all(b.ts - a.ts == SEG_VELA for a, b in zip(velas, velas[1:]))


def _senal_actual(activo, velas):
    """Señal Keltner+RCI SOLO en la última vela cerrada. Entrada: apertura de la vela siguiente."""
    high = [v.high for v in velas]
    low = [v.low for v in velas]
    close = [v.close for v in velas]
    ult = len(velas) - 1
    for e in senales(high, low, close):
        if e["indice"] == ult:
            return {"activo": activo,
                    "direccion": "CALL" if e["direccion"] == "compra" else "PUT",
                    "ts_entrada": velas[ult].ts + SEG_VELA,
                    "vence_ts": velas[ult].ts + SEG_VELA + VENCIMIENTO_VELAS * SEG_VELA,
                    "precio_ref": velas[ult].close}
    return None


def _an(instrumento, horizonte, ts, motivo, hay=False, senal=None, binaria=None):
    """Forma de análisis que espera autotrader.ciclo()."""
    esc = {"direccion": None, "precio_referencia": None, "stop_loss": None, "take_profit": [None], "vigencia_hasta_ts": None}
    if senal:
        esc = {"direccion": "alcista" if senal["direccion"] == "CALL" else "bajista",
               "precio_referencia": senal["precio_ref"], "stop_loss": None, "take_profit": [None],
               "vigencia_hasta_ts": senal["vence_ts"]}
    return {"ts": int(ts), "activo": {"simbolo": instrumento, "nombre": instrumento, "clase": "binaria"},
            "horizonte": horizonte, "hay_oportunidad": bool(hay), "escenario": esc,
            "fusion": {"justificacion": [motivo] if hay else [], "motivo_sin_oportunidad": [] if hay else [motivo]},
            "fuente_datos": {"tipo": "IQ Option PRACTICE (velas M1)"},
            "motores": [{"motor": "keltner_rci_m1", "estado": "completado" if hay or senal else "omitido", "salida": {}}],
            "binaria": binaria or {"ok": False, "calidad": None, "categoria": "abstencion", "detalle": motivo}}


def analizar_binaria(instrumento, horizonte, nivel=None, politica=None, usuario_id=None, riesgo=None,
                     serie=None, payout=None, ruta_escaner=None, min_resueltas=30, ahora=None):
    """Devuelve el análisis de la modalidad binaria. Nunca lanza excepciones por datos malos: abstiene."""
    ahora = time.time() if ahora is None else ahora
    inst = (instrumento or "").upper()
    if not es.es_par_otc(inst):
        return _an(instrumento, horizonte, ahora, f"{instrumento} no es un par OTC de divisas: fuera del escáner")
    velas = velas_desde_dicts(serie)
    if len(velas) < VELAS_MINIMAS:
        return _an(instrumento, horizonte, ahora, f"datos insuficientes: {len(velas)} velas M1 (se exigen {VELAS_MINIMAS})")
    if not _contiguas(velas[-VELAS_MINIMAS:]):
        return _an(instrumento, horizonte, ahora, "huecos en las velas M1 recientes: se abstiene")
    if ahora - (velas[-1].ts + SEG_VELA) > EDAD_MAX_S:
        return _an(instrumento, horizonte, ahora, "última vela M1 demasiado antigua: datos no frescos")
    if ruta_escaner is None:
        return _an(instrumento, horizonte, ahora, "sin base de estadísticas del escáner: se abstiene")
    from pathlib import Path
    Path(ruta_escaner).parent.mkdir(parents=True, exist_ok=True)
    almacen = Almacen(str(ruta_escaner))
    try:
        es._asegurar_esquema(almacen.con)
        con = almacen.con
        # Registro causal: candidatas cuyo vencimiento ya está en la ventana, resueltas con sus propias velas.
        es.registrar_candidatas(con, es.candidatas_de_par(inst, velas))
        es.resolver(con, {inst: {v.ts: v.close for v in velas}})
        senal = _senal_actual(inst, velas)
        if senal is None:
            return _an(instrumento, horizonte, ahora, "sin señal Keltner+RCI en la última vela cerrada")
        g, p = es.estadisticas_previas(con, inst, senal["ts_entrada"])
        ok, cal, cat, det = es.decidir(g, p, payout, min_resueltas)
    finally:
        almacen.cerrar()
    binaria = {"ok": bool(ok), "calidad": cal, "categoria": cat, "detalle": det, "ganadas": g, "perdidas": p,
               "payout": payout, "direccion": senal["direccion"], "ts_entrada": senal["ts_entrada"],
               "vence_ts": senal["vence_ts"]}
    return _an(instrumento, horizonte, ahora, det, hay=ok, senal=senal, binaria=binaria)
