"""Carga de velas M1 desde un CSV exportado por el usuario. Solo lectura, sin red.

Formato aceptado (cabeceras sin distinguir mayúsculas):
  tiempo: time | timestamp | date | datetime | fecha  (epoch en segundos o milisegundos, o ISO 8601)
  open, high, low, close (obligatorias)

Supuestos explícitos:
  * Una fecha ISO sin zona horaria se interpreta como UTC.
  * Se rechaza el archivo completo ante cualquier fila inválida (no se descartan filas en silencio).
"""
import csv
import math
from datetime import datetime, timezone

COLUMNAS_TIEMPO = ("time", "timestamp", "date", "datetime", "fecha")
COLUMNAS_PRECIO = ("open", "high", "low", "close")


class ErrorCSV(ValueError):
    """El archivo no cumple el formato o contiene datos incoherentes."""


def _marca_tiempo(texto):
    v = (texto or "").strip()
    if not v:
        raise ErrorCSV("fecha vacía")
    try:
        n = float(v)
        if n > 1e12:  # milisegundos
            n /= 1000.0
        return int(n)
    except ValueError:
        pass
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError as e:
        raise ErrorCSV(f"fecha no reconocida: {v!r}") from e
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return int(d.timestamp())


def leer(ruta, instrumento, proveedor):
    """Devuelve (velas, meta). velas: lista de (ts, open, high, low, close) ordenada por tiempo."""
    if not instrumento or not proveedor:
        raise ErrorCSV("Se requiere instrumento y proveedor para identificar la fuente")
    with open(ruta, newline="", encoding="utf-8-sig") as f:
        lector = csv.DictReader(f)
        cab = {(c or "").strip().lower(): c for c in (lector.fieldnames or [])}
        col_t = next((cab[c] for c in COLUMNAS_TIEMPO if c in cab), None)
        if col_t is None:
            raise ErrorCSV("falta una columna de tiempo (time, timestamp, date, datetime o fecha)")
        for c in COLUMNAS_PRECIO:
            if c not in cab:
                raise ErrorCSV(f"falta la columna {c}")
        filas = {}
        for n, fila in enumerate(lector, start=2):
            try:
                ts = _marca_tiempo(fila[col_t])
                o, h, l, c = (float(fila[cab[k]]) for k in COLUMNAS_PRECIO)
            except (ValueError, KeyError, TypeError) as e:
                raise ErrorCSV(f"línea {n}: {e}") from e
            if not all(math.isfinite(x) for x in (o, h, l, c)):
                raise ErrorCSV(f"línea {n}: valor no finito")
            if h < max(o, c) or l > min(o, c) or h < l:
                raise ErrorCSV(f"línea {n}: OHLC incoherente")
            if ts in filas:
                raise ErrorCSV(f"línea {n}: marca de tiempo duplicada")
            filas[ts] = (o, h, l, c)
    if not filas:
        raise ErrorCSV("el archivo no contiene velas")
    velas = [(ts, *filas[ts]) for ts in sorted(filas)]
    meta = {"instrumento": instrumento, "proveedor": proveedor, "ruta": str(ruta),
            "velas": len(velas), "desde": velas[0][0], "hasta": velas[-1][0]}
    return velas, meta
