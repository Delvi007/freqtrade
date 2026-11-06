"""Límite de peticiones por IP y por acción (ventana deslizante en memoria)."""
import threading
import time
from collections import defaultdict, deque

# acción: (peticiones, segundos)
REGLAS = {
    "login": (10, 300),
    "registro": (5, 3600),
    "olvide": (5, 3600),
    "restablecer": (10, 3600),
    "api": (240, 60),
    "analizar": (20, 60),
    "integracion": (20, 60),
}
_L = threading.Lock()
_V = defaultdict(deque)


def permitir(accion, ip):
    n, ventana = REGLAS.get(accion, (120, 60))
    ahora = time.monotonic()
    k = (accion, ip or "?")
    with _L:
        d = _V[k]
        while d and ahora - d[0] > ventana:
            d.popleft()
        if len(d) >= n:
            return False
        d.append(ahora)
        if len(_V) > 20000:          # no crecer sin límite
            _V.clear()
        return True


def reiniciar():
    with _L:
        _V.clear()
