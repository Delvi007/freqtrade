# -*- coding: utf-8 -*-
"""Informe PDF para la interfaz web de TITAN QUANT.

Seguridad: el informe se genera sobre una COPIA TEMPORAL de titan_activos.db.
Las bases originales no se tocan. No hay brokers, ni órdenes, ni alertas.
La hoja se redacta con informe_pro (resumen explicado, cifras con significado, escenarios técnicos).
El PDF de Telegram (informe.pdf) no se modifica.
"""
import base64, re, shutil, tempfile, threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import activos
import agente
import guiado
import informe
import informe_pro

SESIONES = [
    ("Sídney", "🇦🇺", "Australia/Sydney", (10, 0), 6.0),
    ("Tokio", "🇯🇵", "Asia/Tokyo", (9, 0), 6.5),
    ("Hong Kong", "🇭🇰", "Asia/Hong_Kong", (9, 30), 6.5),
    ("Londres", "🇬🇧", "Europe/London", (8, 0), 8.5),
    ("Nueva York", "🇺🇸", "America/New_York", (8, 0), 9.0),
]
_LOCK = threading.Lock()


def _seguro(o):
    if o is None or isinstance(o, (str, int, float, bool)):
        return o
    if isinstance(o, dict):
        return {str(k): _seguro(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_seguro(v) for v in o]
    return str(o)


def _reunir_en_copia(a, zona, base):
    """Ejecuta informe.reunir() contra una copia temporal de la BD."""
    original = Path(agente.DB)
    tmpdir = tempfile.mkdtemp(prefix="titan_informe_")
    copia = Path(tmpdir) / original.name
    with _LOCK:
        try:
            if original.exists():
                shutil.copy2(original, copia)
            agente.DB = copia
            return informe.reunir(a, zona, base, SESIONES)
        finally:
            agente.DB = original
            shutil.rmtree(tmpdir, ignore_errors=True)


def generar(simbolo, hora=None, zona_nombre="America/Santo_Domingo", personalizados=()):
    simbolo = str(simbolo or "").strip().upper()
    if not simbolo or len(simbolo) > 30:
        raise ValueError("Símbolo vacío o demasiado largo.")
    a = activos.buscar(simbolo, list(personalizados))
    if a is None:
        raise ValueError("El símbolo no está en el catálogo ni en personalizados.")
    try:
        zona = ZoneInfo(zona_nombre)
    except Exception:
        zona = ZoneInfo("America/Santo_Domingo")
    if hora in (None, "", "N"):
        base = guiado.hora_objetivo(zona, None, proxima=True)
    else:
        h = int(hora)
        if not 0 <= h <= 23:
            raise ValueError("La hora debe estar entre 0 y 23.")
        base = guiado.hora_objetivo(zona, h)

    d = _reunir_en_copia(a, zona, base)
    if d.get("error"):
        raise RuntimeError("Sin datos para el informe: " + str(d["error"]))

    pdf_bytes = informe_pro.pdf(d)
    pro = informe_pro.panel(d)
    nombre = "TITAN_" + re.sub(r"[^A-Za-z0-9]+", "_", simbolo).strip("_") + "_" + \
        datetime.now(zona).strftime("%Y%m%d_%H%M") + ".pdf"
    panel = {
        "activo": a["nombre"], "simbolo": simbolo, "zona": zona.key,
        "generado": d["ahora"].astimezone(zona).strftime("%d/%m/%Y %H:%M"),
        "hora_objetivo": f"{base.hour:02d}:00",
        "items": pro["items"], "cifras": pro["cifras"], "tecnico": pro["tecnico"],
        "noticias": pro["noticias"], "quant_escenarios": pro["quant_escenarios"],
        "quant_error": (d.get("quant") or {}).get("error"),
        "aviso": "Hoja informativa. No es consejo financiero ni una predicción. No ejecuta operaciones ni guarda nada en las bases de datos.",
        "guardado_en_bd": False,
    }
    return {
        "panel": _seguro(panel),
        "nombre_pdf": nombre,
        "pdf_base64": base64.b64encode(pdf_bytes).decode("ascii"),
    }
