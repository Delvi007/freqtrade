"""Esperas acotadas para la librería iqoptionapi (parche TITAN QUANT).

La librería original espera las respuestas del websocket con bucles `while X == None: pass`:
  * sin pausa  -> ocupan un núcleo de CPU al 100 % mientras esperan;
  * sin límite -> si la respuesta no llega (red caída, sesión expirada, mensaje que no se reconoce)
                  el hilo queda bloqueado para siempre, junto con cualquier cerrojo que tenga tomado.

`esperar()` sustituye esos bucles: comprueba la condición con una pausa corta y lanza
`EsperaAgotada` (subclase de TimeoutError) si no se cumple dentro del tiempo máximo.
"""
import os
import time

PAUSA_S = 0.02
ESPERA_MAX_S = float(os.environ.get("IQ_ESPERA_MAX_S", "30"))
HTTP_TIMEOUT = (10, 30)   # (conexión, lectura) en segundos para las peticiones HTTP de login/logout


class EsperaAgotada(TimeoutError):
    """IQ Option no respondió dentro del tiempo máximo."""


def esperar(condicion, timeout=None, que="respuesta"):
    """Espera hasta que `condicion()` sea verdadera. Lanza EsperaAgotada al vencer el plazo.

    Las excepciones de `condicion()` se tratan como "todavía no" (igual que los try/except
    vacíos de la librería original mientras el diccionario de respuesta aún no existe)."""
    plazo = ESPERA_MAX_S if timeout is None else float(timeout)
    limite = time.monotonic() + plazo
    while True:
        try:
            if condicion():
                return
        except Exception:  # noqa: BLE001 - la estructura de respuesta puede no existir todavía
            pass
        if time.monotonic() >= limite:
            raise EsperaAgotada(f"IQ Option no envió {que} en {plazo:.0f} s")
        time.sleep(PAUSA_S)
