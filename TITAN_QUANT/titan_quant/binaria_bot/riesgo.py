"""Gestión de riesgo para binarias. Sin martingala: el monto NUNCA aumenta tras una pérdida.

Garantías:
  * LimitesRiesgo es inmutable (frozen). Ningún componente autónomo puede cambiarlo en ejecución;
    un cambio requiere crear un objeto nuevo desde configuración explícita del usuario.
  * El monto de cada operación es fijo (monto_base) y nunca supera monto_max.
  * Parada de emergencia (kill switch): bloquea órdenes nuevas hasta reactivación explícita.
  * Parada automática por pérdida diaria, drawdown, racha de pérdidas y número de operaciones.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class LimitesRiesgo:
    monto_base: float = 1.0          # monto fijo por operación (USD en PRACTICE)
    monto_max: float = 1.0           # tope absoluto; monto_base no puede superarlo
    perdida_diaria_max: float = 3.0  # en unidades de monto_base; al alcanzarla se detiene el día
    drawdown_max: float = 5.0        # caída desde el pico de equity acumulado; detiene la sesión
    racha_perdidas_max: int = 3       # pérdidas consecutivas; detiene hasta revisión manual
    ops_diarias_max: int = 20

    def __post_init__(self):
        if not (0 < self.monto_base <= self.monto_max):
            raise ValueError("monto_base debe ser > 0 y <= monto_max")
        if self.perdida_diaria_max <= 0 or self.drawdown_max <= 0:
            raise ValueError("los límites de pérdida deben ser positivos")
        if self.racha_perdidas_max < 1 or self.ops_diarias_max < 1:
            raise ValueError("los contadores deben ser >= 1")


class GestorRiesgo:
    def __init__(self, limites: LimitesRiesgo):
        if not isinstance(limites, LimitesRiesgo):
            raise TypeError("se requiere LimitesRiesgo")
        self.limites = limites
        self.kill_switch = False
        self.motivo_bloqueo = ""
        self.equity = 0.0
        self.pico = 0.0
        self.pnl_dia = 0.0
        self.ops_dia = 0
        self.racha = 0

    def apagar(self, motivo="parada manual"):
        self.kill_switch = True
        self.motivo_bloqueo = motivo

    def reactivar(self):
        """Solo reactivación explícita del operador. No la invoca ningún automatismo."""
        self.kill_switch = False
        self.motivo_bloqueo = ""

    def nuevo_dia(self):
        self.pnl_dia = 0.0
        self.ops_dia = 0

    def puede_operar(self, monto=None):
        """Devuelve (True, '') o (False, motivo). No modifica el estado."""
        m = self.limites
        if self.kill_switch:
            return False, "parada de emergencia activa: " + self.motivo_bloqueo
        if monto is not None and not (0 < monto <= m.monto_max):
            return False, "monto fuera de límite"
        if self.pnl_dia <= -m.perdida_diaria_max:
            return False, "pérdida diaria máxima alcanzada"
        if self.equity <= self.pico - m.drawdown_max:
            return False, "drawdown máximo alcanzado"
        if self.racha >= m.racha_perdidas_max:
            return False, "racha de pérdidas máxima alcanzada: revisión manual requerida"
        if self.ops_dia >= m.ops_diarias_max:
            return False, "número máximo de operaciones del día"
        return True, ""

    def registrar(self, neto):
        """Registra el neto de una operación cerrada (ganancia positiva, pérdida negativa)."""
        self.ops_dia += 1
        self.pnl_dia += neto
        self.equity += neto
        self.pico = max(self.pico, self.equity)
        if neto < 0:
            self.racha += 1
        elif neto > 0:
            self.racha = 0
        # Al alcanzar un límite se activa la parada automática.
        ok, motivo = self.puede_operar()
        if not ok:
            self.apagar(motivo)
        return ok
