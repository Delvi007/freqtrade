"""Puente entre el bot de binarias y los motores de TITAN QUANT, en modo OFFLINE.

Qué hace:
  * Convierte las velas M1 del bot al formato de serie de TITAN (claves t,o,h,l,c,v) y la entrega
    como `serie_externa`, de modo que MotorDatos NO consulta la red.
  * Ejecuta en orden de dependencias solo los motores que no necesitan red ni servicios externos.
  * Llama a `motor.calcular(ctx)` directamente. NO usa `Motor.ejecutar`, porque ese método
    persiste el estado en la base de datos de TITAN (db.tx), y el bot no debe escribir allí.

Limitaciones explícitas (no se ocultan):
  * El horizonte de TITAN más cercano es "scalping" (intervalo 5m, 6 barras adelante). Las etiquetas
    de los motores de ML y backtesting se calculan con 6 velas M1 y NO con las 5 de la binaria.
    Modificar niveles.py estaba fuera de alcance.
  * Un motor en estado 'sin_datos' no aporta nada; no se rellena con valores inventados.
"""
import time

from titan_quant import niveles
from titan_quant.motores import base
from titan_quant.motores import cuant, mercado  # noqa: F401  importar registra los motores
from titan_quant.binaria_bot.datos import Vela

HORIZONTE_PUENTE = "scalping"

MOTORES_OFFLINE = ("data", "features", "technical", "regime", "microstructure",
                   "statistical", "ml", "risk", "backtesting", "montecarlo")

EXCLUIDOS = {
    "cross_asset": "descarga otros activos desde la red",
    "portfolio": "descarga cartera desde la red",
    "macro": "fuentes macroeconómicas externas",
    "news": "noticias externas",
    "research": "investigación externa",
    "fusion": "depende de fuentes externas",
    "adaptive": "planificación de recursos del sistema",
    "hardware": "sondea el equipo",
    "monitoring": "servicio de monitorización",
    "api": "servicio de red",
    "web": "servicio de red",
    "telegram": "servicio de red",
}


def serie_desde_m1(velas, simbolo):
    """Formato de serie de TITAN a partir de velas M1 cerradas. Sin red, sin escritura."""
    if not velas:
        raise ValueError("sin velas")
    t = [int(v.ts) for v in velas]
    if any(b - a != 60 for a, b in zip(t, t[1:])):
        raise ValueError("las velas M1 deben ser contiguas; usa tramos_continuos antes")
    return {
        "simbolo": simbolo, "proveedor": "iqoption", "simbolo_proveedor": simbolo,
        "tipo": "cfd", "intervalo": "1m", "rango": "local",
        "t": t,
        "o": [float(v.open) for v in velas],
        "h": [float(v.high) for v in velas],
        "l": [float(v.low) for v in velas],
        "c": [float(v.close) for v in velas],
        "v": [0.0 for _ in velas],          # sin volumen real: el motor de calidad lo reportará
        "meta": {"origen": "bot_binaria_local"}, "obtenido_ts": int(time.time()),
    }


def _orden(ids):
    """Orden topológico por dependencias declaradas, limitado a `ids`."""
    pendientes = {i: set(d for d in base.REGISTRO[i].dependencias if d in ids) for i in ids}
    orden = []
    while pendientes:
        listos = sorted([i for i, d in pendientes.items() if not d], key=lambda x: base.REGISTRO[x].numero)
        if not listos:
            raise RuntimeError("dependencias circulares entre motores: " + ", ".join(pendientes))
        orden.extend(listos)
        for i in listos:
            del pendientes[i]
        for d in pendientes.values():
            d.difference_update(listos)
    return orden


def _ejecutar_sin_persistir(motor, ctx):
    t0 = time.monotonic()
    notas, faltantes, salida, error = [], [], {}, None
    try:
        r = motor.calcular(ctx) or {}
        salida = r.get("salida", r)
        notas = r.get("notas", [])
        faltantes = r.get("faltantes", [])
        estado = r.get("estado", "completado")
    except base.SinDatos as e:
        estado, faltantes = "sin_datos", [str(e)]
    except Exception as e:  # un motor roto no tumba al resto
        estado, error = "error", f"{type(e).__name__}: {e}"[:300]
    return {"motor": motor.id, "numero": motor.numero, "nombre": motor.nombre, "estado": estado,
            "duracion_ms": int((time.monotonic() - t0) * 1000), "salida": salida,
            "notas": notas, "faltantes": faltantes, "error": error}


def ejecutar(velas_m1, simbolo, nivel="basico", riesgo=None, motores=MOTORES_OFFLINE):
    """Ejecuta los motores offline sobre velas M1. Devuelve {motor_id: resultado}."""
    no_registrados = [m for m in motores if m not in base.REGISTRO]
    if no_registrados:
        raise ValueError("motores no registrados: " + ", ".join(no_registrados))
    excluidos_pedidos = [m for m in motores if m in EXCLUIDOS]
    if excluidos_pedidos:
        raise ValueError("motores que requieren red y no se usan offline: " + ", ".join(excluidos_pedidos))
    serie = serie_desde_m1(velas_m1, simbolo)
    ctx = {
        "activo": {"simbolo": simbolo, "clase": "binaria_otc"},
        "horizonte": HORIZONTE_PUENTE,
        "p": niveles.parametros(nivel),
        "res": {},
        "usuario_id": "bot_binaria_local",
        "serie_externa": serie,
        "riesgo_usuario": riesgo or {"capital": 1000.0, "riesgo_pct": 1.0},
    }
    for mid in _orden(set(motores)):
        ctx["res"][mid] = _ejecutar_sin_persistir(base.REGISTRO[mid], ctx)
    return ctx["res"]
