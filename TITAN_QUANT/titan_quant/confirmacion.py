"""Confirmación de las señales de los bots con el análisis COMPLETO de los 23 motores.

Cada señal del escáner multiactivo (estrategia básica + backtest) pasa, antes de enviarse, por nucleo.analizar con las
MISMAS velas del broker que la generaron. La señal se VETA si:
  · el FUSION ENGINE (técnico, régimen, ML calibrado, noticias, intermarket…) apunta en contra con fuerza
    (puntuación combinada a favor < −umbral_contra),
  · el régimen es de alta volatilidad (percentil ≥ 90 %),
  · hubo un evento macro de alto impacto en las últimas 6 h (no aplica a los pares OTC, que son un mercado sintético del
    broker; se puede desactivar con veto_macro),
  · los datos son de baja calidad u obsoletos.
Una lectura neutra NO veta: los motores confirman o se oponen; la ventaja la aporta el backtest de la estrategia.
"""
import re
import time

HORIZONTE_POR_TF = {"1m": "scalping", "5m": "scalping", "15m": "intradia", "1h": "corto", "4h": "corto"}


def serie_desde(velas, proveedor, simbolo, intervalo):
    """Convierte velas del broker (listas [ts,o,h,l,c,(v)] o dicts {ts,open,high,low,close}) al formato de los motores."""
    if velas and isinstance(velas[0], dict):
        filas = [[v["ts"], v["open"], v["high"], v["low"], v["close"], v.get("volume", 0) or 0] for v in velas]
    else:
        filas = [list(v) + [0] * (6 - len(v)) for v in velas]
    return {"simbolo": simbolo, "proveedor": proveedor, "simbolo_proveedor": simbolo, "tipo": "cfd" if "ctrader" in proveedor else "binaria",
            "intervalo": intervalo, "rango": f"{len(filas)} velas", "t": [int(f[0]) for f in filas], "o": [float(f[1]) for f in filas],
            "h": [float(f[2]) for f in filas], "l": [float(f[3]) for f in filas], "c": [float(f[4]) for f in filas],
            "v": [float(f[5] or 0) for f in filas], "meta": {"precio": float(filas[-1][4]) if filas else None, "bid": None, "ask": None, "zona": "UTC"},
            "obtenido_ts": time.time()}


def _simbolo_motor(nombre):
    s = re.sub(r"[^A-Z0-9.^=\-]", "", str(nombre).upper())[:20]
    return s or "ACTIVO"


def confirmar(uid, nombre, direccion, serie, intervalo, umbral_contra=0.15, nivel="basico", analizar_fn=None, presupuesto_s=35,
              veto_macro=True):
    """Devuelve {'ok', 'detalle', 'puntuacion', 'motores'}. Nunca lanza: si el análisis falla, la señal NO se confirma."""
    from .motores import nucleo
    fn = analizar_fn or nucleo.analizar
    sg = 1 if direccion == "alcista" else -1
    try:
        an = fn(_simbolo_motor(nombre), HORIZONTE_POR_TF.get(intervalo, "intradia"), nivel, "automatico", usuario_id=uid,
                serie=serie, presupuesto_s=presupuesto_s)
    except Exception as e:
        return {"ok": False, "detalle": f"análisis de los 23 motores no disponible ({type(e).__name__}): señal no confirmada",
                "puntuacion": None, "motores": []}
    motores = an.get("motores") or []
    fu = an.get("fusion") or {}
    fu = fu.get("salida", fu)
    punt = fu.get("puntuacion")
    por_id = {m["motor"]: m for m in motores}
    reg = (por_id.get("regime") or {}).get("salida") or {}
    mac = (por_id.get("macro") or {}).get("salida") or {}
    dat = (por_id.get("data") or {}).get("salida") or {}
    vetos = []
    if punt is None:
        vetos.append("el FUSION ENGINE no pudo puntuar")
    elif sg * punt < -abs(umbral_contra):
        vetos.append(f"los 23 motores apuntan en contra (puntuación {punt:+.2f})")
    if reg.get("regimen") == "alta_volatilidad":
        vetos.append("régimen de alta volatilidad")
    otc = str(nombre).upper().endswith("-OTC")             # mercado sintético del broker: no reacciona a las noticias macro reales
    if veto_macro and not otc and mac.get("eventos_alto_impacto_6h"):
        vetos.append(f"{mac['eventos_alto_impacto_6h']} evento(s) macro de alto impacto en las últimas 6 h")
    cal = dat.get("calidad") or {}
    if cal.get("calidad") == "baja" or cal.get("obsoleto"):
        vetos.append("datos de baja calidad u obsoletos")
    completados = sum(1 for m in motores if m.get("estado") in ("completado", "simplificado"))
    if vetos:
        detalle = "VETADA por los motores: " + "; ".join(vetos)
    else:
        lectura = "a favor" if punt and sg * punt > 0.05 else "neutral"
        detalle = (f"confirmada por {completados} motores: lectura combinada {lectura} ({punt:+.2f}), "
                   f"régimen {reg.get('regimen', '—')}, sin eventos macro de alto impacto")
    return {"ok": not vetos, "detalle": detalle, "puntuacion": punt, "motores": motores, "completados": completados}
