# -*- coding: utf-8 -*-
"""Todas las zonas horarias del mundo (base IANA del sistema): regiones, ciudades, búsqueda y desfase actual."""
import unicodedata
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, available_timezones

REGIONES = ["America", "Europe", "Asia", "Africa", "Australia", "Pacific", "Atlantic", "Indian", "Antarctica", "Arctic"]
RESPALDO = ["America/Santo_Domingo", "America/New_York", "America/Bogota", "America/Mexico_City", "America/Caracas",
            "America/Argentina/Buenos_Aires", "America/Santiago", "America/Sao_Paulo", "America/Lima", "America/Los_Angeles",
            "Europe/Madrid", "Europe/London", "Europe/Paris", "Europe/Berlin", "Europe/Moscow", "Asia/Tokyo", "Asia/Shanghai",
            "Asia/Dubai", "Asia/Kolkata", "Asia/Singapore", "Asia/Hong_Kong", "Africa/Cairo", "Africa/Johannesburg",
            "Africa/Lagos", "Australia/Sydney", "Pacific/Auckland", "Pacific/Honolulu"]
ALIAS = {"republica dominicana": "America/Santo_Domingo", "españa": "Europe/Madrid", "mexico": "America/Mexico_City",
         "colombia": "America/Bogota", "peru": "America/Lima", "argentina": "America/Argentina/Buenos_Aires",
         "chile": "America/Santiago", "venezuela": "America/Caracas", "ecuador": "America/Guayaquil", "panama": "America/Panama",
         "costa rica": "America/Costa_Rica", "guatemala": "America/Guatemala", "cuba": "America/Havana",
         "puerto rico": "America/Puerto_Rico", "uruguay": "America/Montevideo", "paraguay": "America/Asuncion",
         "bolivia": "America/La_Paz", "brasil": "America/Sao_Paulo", "nueva york": "America/New_York",
         "japon": "Asia/Tokyo", "china": "Asia/Shanghai", "india": "Asia/Kolkata", "emiratos": "Asia/Dubai",
         "londres": "Europe/London", "alemania": "Europe/Berlin", "italia": "Europe/Rome", "rusia": "Europe/Moscow",
         "turquia": "Europe/Istanbul", "sudafrica": "Africa/Johannesburg", "egipto": "Africa/Cairo",
         "nueva zelanda": "Pacific/Auckland", "sidney": "Australia/Sydney", "corea": "Asia/Seoul", "tailandia": "Asia/Bangkok"}

def _norm(s):
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn").replace("_", " ")

def todas():
    z = sorted(t for t in available_timezones() if "/" in t and t.split("/")[0] in REGIONES)
    return ["UTC"] + (z or RESPALDO)

def por_region(region):
    return [t for t in todas() if t.startswith(region + "/")]

def desfase(tz, ahora=None):
    off = (ahora or datetime.now(timezone.utc)).astimezone(ZoneInfo(tz)).utcoffset().total_seconds() / 3600
    h = int(abs(off))
    m = round((abs(off) - h) * 60)
    return f"UTC{'-' if off < 0 else '+'}{h}" + (f":{m:02d}" if m else "")

def etiqueta(tz):
    ciudad = tz.split("/")[-1].replace("_", " ")
    return f"{ciudad} ({desfase(tz)})"

def buscar(texto, limite=10):
    q = _norm(texto).strip()
    if not q:
        return []
    out = [v for k, v in ALIAS.items() if q in _norm(k)]
    out += [t for t in todas() if q in _norm(t) and t not in out]
    vistos, res = set(), []
    for t in out:
        if t not in vistos:
            vistos.add(t); res.append(t)
    return res[:limite]

def valida(tz):
    try:
        ZoneInfo(tz)
        return True
    except Exception:
        return False
