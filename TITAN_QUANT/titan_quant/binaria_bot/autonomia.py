"""Cuatro niveles de autonomía y criterio de evidencia para operar.

Niveles (de menor a mayor autonomía):
  OBSERVAR          registra señales; nunca propone ni envía órdenes.
  SUGERIR           propone la orden; el operador decide fuera del bot.
  CONFIRMAR         envía solo si el operador confirma cada orden.
  AUTOMATICO_PRACTICE envía sin confirmación, SOLO en PRACTICE y solo con evidencia suficiente.

Ningún nivel permite cuenta REAL: esa restricción la aplica el adaptador (titan_quant/binaria_sim).
El nivel por defecto es OBSERVAR.
"""
from enum import Enum


class Autonomia(Enum):
    OBSERVAR = 1
    SUGERIR = 2
    CONFIRMAR = 3
    AUTOMATICO_PRACTICE = 4


def evidencia_suficiente(resumenes, min_tramos=4):
    """Exige evidencia FUERA DE MUESTRA y en TODOS los tramos walk-forward.

    Cada tramo debe declarar ventaja significativa (límite inferior de Wilson > equilibrio).
    Con menos tramos de los exigidos, no hay evidencia. Devuelve (bool, motivo)."""
    if not resumenes:
        return False, "sin datos de backtest"
    if len(resumenes) < min_tramos:
        return False, f"solo {len(resumenes)} tramos; se exigen {min_tramos}"
    malos = [r.indice for r in resumenes if not r.ventaja_significativa]
    if malos:
        return False, f"tramos sin ventaja significativa: {malos}"
    return True, "ventaja significativa en todos los tramos fuera de muestra"


def decidir_accion(nivel, evidencia_ok, confirmado_por_operador):
    """Devuelve la acción permitida: 'observar' | 'sugerir' | 'esperar_confirmacion' | 'enviar'."""
    if nivel is Autonomia.OBSERVAR:
        return "observar"
    if nivel is Autonomia.SUGERIR:
        return "sugerir"
    if nivel is Autonomia.CONFIRMAR:
        return "enviar" if confirmado_por_operador else "esperar_confirmacion"
    if nivel is Autonomia.AUTOMATICO_PRACTICE:
        return "enviar" if evidencia_ok else "sugerir"
    raise ValueError("nivel desconocido")
