"""Cuatro niveles de inteligencia y tres políticas de procesamiento.

Los 23 motores están disponibles en TODOS los niveles. El nivel solo cambia profundidad,
datos, ventanas, modelos, simulaciones, validaciones, escenarios, concurrencia y frecuencia.
El sistema puede RECOMENDAR un nivel según el hardware, pero nunca cambia el elegido por el usuario.
"""

NIVELES = {
    "basico": {
        "nombre": "Básico", "rango_historico": "1mo", "intervalo": "60m", "ventanas": [20, 50],
        "activos_max": 3, "modelos_ml": ["logistica"], "ml_epocas": 150, "ml_minimo": 120,
        "montecarlo_sim": 300, "backtest_barras": 300, "walk_forward_cortes": 2,
        "escenarios": 2, "concurrencia": 1, "frecuencia_s": 900, "noticias_horas": 24,
        "investigacion": "resumen", "correlacion_activos": 3,
    },
    "intermedio": {
        "nombre": "Intermedio", "rango_historico": "3mo", "intervalo": "60m", "ventanas": [20, 50, 100],
        "activos_max": 6, "modelos_ml": ["logistica"], "ml_epocas": 300, "ml_minimo": 200,
        "montecarlo_sim": 1000, "backtest_barras": 800, "walk_forward_cortes": 3,
        "escenarios": 3, "concurrencia": 2, "frecuencia_s": 600, "noticias_horas": 48,
        "investigacion": "estandar", "correlacion_activos": 5,
    },
    "avanzado": {
        "nombre": "Avanzado", "rango_historico": "6mo", "intervalo": "60m", "ventanas": [20, 50, 100, 200],
        "activos_max": 10, "modelos_ml": ["logistica", "bayes"], "ml_epocas": 500, "ml_minimo": 300,
        "montecarlo_sim": 3000, "backtest_barras": 1500, "walk_forward_cortes": 4,
        "escenarios": 4, "concurrencia": 3, "frecuencia_s": 300, "noticias_horas": 72,
        "investigacion": "detallada", "correlacion_activos": 8,
    },
    "super": {
        "nombre": "Súper avanzado", "rango_historico": "1y", "intervalo": "60m", "ventanas": [20, 50, 100, 200],
        "activos_max": 16, "modelos_ml": ["logistica", "bayes"], "ml_epocas": 800, "ml_minimo": 400,
        "montecarlo_sim": 10000, "backtest_barras": 3000, "walk_forward_cortes": 5,
        "escenarios": 5, "concurrencia": 4, "frecuencia_s": 120, "noticias_horas": 96,
        "investigacion": "exhaustiva", "correlacion_activos": 12,
    },
}
ORDEN = ["basico", "intermedio", "avanzado", "super"]

POLITICAS = {
    "automatico": "Ajusta la carga al hardware disponible en cada ejecución (puede simplificar o aplazar tareas).",
    "equilibrado": "Usa el nivel elegido pero limita la concurrencia a la mitad de los núcleos.",
    "maximo": "Usa todos los recursos del nivel elegido; solo reduce si falta memoria.",
}

HORIZONTES = {
    "scalping": {"nombre": "Scalping", "intervalo": "5m", "rango": "5d", "vigencia_h": 1, "barras_adelante": 6},
    "intradia": {"nombre": "Intradía", "intervalo": "15m", "rango": "1mo", "vigencia_h": 6, "barras_adelante": 8},
    "corto": {"nombre": "Corto plazo", "intervalo": "60m", "rango": "3mo", "vigencia_h": 48, "barras_adelante": 12},
    "mediano": {"nombre": "Mediano plazo", "intervalo": "1d", "rango": "2y", "vigencia_h": 24 * 20, "barras_adelante": 10},
    "largo": {"nombre": "Largo plazo", "intervalo": "1wk", "rango": "10y", "vigencia_h": 24 * 120, "barras_adelante": 8},
}


def parametros(nivel):
    if nivel not in NIVELES:
        raise ValueError("Nivel desconocido: " + str(nivel))
    p = dict(NIVELES[nivel])
    p["id"] = nivel
    return p


def validar_politica(p):
    if p not in POLITICAS:
        raise ValueError("Política desconocida: " + str(p))
    return p


def validar_horizonte(h):
    if h not in HORIZONTES:
        raise ValueError("Horizonte desconocido: " + str(h))
    return h
