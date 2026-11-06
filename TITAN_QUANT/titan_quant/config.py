"""Rutas y valores por defecto. Todo se puede cambiar por variables de entorno o desde la interfaz."""
import os
from pathlib import Path

RAIZ = Path(os.environ.get("TITAN_RAIZ") or Path(__file__).resolve().parent.parent)
DATOS = Path(os.environ.get("TITAN_DATOS") or RAIZ / "datos")
WEB = RAIZ / "web"
DB_PRINCIPAL = DATOS / "titan_quant.db"
CLAVE_MAESTRA = DATOS / ".clave_maestra"          # 32 bytes aleatorios, permiso 600
SALIDA_CORREO = DATOS / "correo_saliente"         # solo si no hay SMTP configurado
RESPALDOS = DATOS / "respaldos"
REGISTRO = DATOS / "titan.log"

# Servidor: por defecto SOLO este dispositivo. Para la red local: TITAN_HOST=0.0.0.0 (exige sesión igualmente).
HOST = os.environ.get("TITAN_HOST", "127.0.0.1")
PUERTO = int(os.environ.get("TITAN_PUERTO", "8765"))
HTTPS = os.environ.get("TITAN_HTTPS", "0") == "1"   # cookies Secure cuando se publique detrás de HTTPS

SESION_HORAS = 12
SESION_RECORDAR_DIAS = 14
INTENTOS_MAX = 5              # intentos fallidos antes de bloquear
BLOQUEO_MIN = 15
TOKEN_VERIF_HORAS = 24
TOKEN_RESET_MIN = 30
CLAVE_MIN = 10


def asegurar_directorios():
    for d in (DATOS, SALIDA_CORREO, RESPALDOS):
        d.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(d, 0o700)
        except OSError:
            pass
