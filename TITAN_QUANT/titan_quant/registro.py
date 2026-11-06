"""Registro de actividad con rotación. Filtra cualquier cosa con forma de secreto antes de escribir."""
import logging
import re
from logging.handlers import RotatingFileHandler

from . import config

_PATRONES = [
    (re.compile(r"\d{6,12}:[A-Za-z0-9_-]{30,}"), "[token-telegram]"),
    (re.compile(r"(?i)(token|clave|password|secret|code|api_key|apikey|access_token|refresh_token)=([^&\s\"']+)"), r"\1=[oculto]"),
    (re.compile(r"(?i)(\"(?:token|clave|password|secret|api_key|access_token|refresh_token)\"\s*:\s*\")[^\"]*\""), r'\1[oculto]"'),
]


def limpiar(texto):
    t = str(texto)
    for rx, rep in _PATRONES:
        t = rx.sub(rep, t)
    return t


class _Filtro(logging.Filter):
    def filter(self, rec):
        rec.msg = limpiar(rec.getMessage())
        rec.args = ()
        return True


_LOG = None


def log():
    global _LOG
    if _LOG:
        return _LOG
    config.asegurar_directorios()
    lg = logging.getLogger("titan")
    lg.setLevel(logging.INFO)
    if not lg.handlers:
        h = RotatingFileHandler(config.REGISTRO, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        h.addFilter(_Filtro())
        lg.addHandler(h)
    _LOG = lg
    return lg
