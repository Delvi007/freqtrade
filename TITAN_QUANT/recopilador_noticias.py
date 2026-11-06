from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from progreso_titan import progreso, titulo

BASE = Path(__file__).resolve().parent
SALIDA_JSON = BASE / "noticias_en_vivo.json"
SALIDA_MD = BASE / "noticias_en_vivo.md"

CATEGORIAS = [
    ("Economía mundial", "global economy inflation growth economic data"),
    ("Geopolítica", "geopolitics international conflict sanctions trade"),
    ("Reserva Federal", "Federal Reserve Fed interest rates Powell FOMC"),
    ("Bonos y rendimientos", "US Treasury bonds yields yield curve debt"),
    ("Oro y dólar", "gold price XAU USD dollar safe haven"),
]

MAX_NOTICIAS_POR_CATEGORIA = 12
TIMEOUT = 12

def limpiar_html(texto):
    texto = re.sub(r"<[^>]+>", " ", texto or "")
    return re.sub(r"\s+", " ", texto).strip()

def obtener_texto(elemento, etiqueta):
    nodo = elemento.find(etiqueta)
    return limpiar_html(nodo.text if nodo is not None else "")

def buscar_categoria(categoria, consulta):
    parametros = urllib.parse.urlencode({
        "q": consulta,
        "hl": "en-US",
        "gl": "US",
        "ceid": "US:en",
    })
    url = "https://news.google.com/rss/search?" + parametros
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "TITAN-GOLD-NEWS/1.0"}
    )

    with urllib.request.urlopen(req, timeout=TIMEOUT) as respuesta:
        xml = respuesta.read()

    raiz = ET.fromstring(xml)
    resultados = []

    for item in raiz.findall(".//item")[:MAX_NOTICIAS_POR_CATEGORIA]:
        titulo = obtener_texto(item, "title")
        enlace = obtener_texto(item, "link")
        fecha = obtener_texto(item, "pubDate")
        resumen = obtener_texto(item, "description")
        fuente = obtener_texto(item, "source")

        if not titulo or not enlace:
            continue

        resultados.append({
            "categoria": categoria,
            "titulo": titulo,
            "fuente": fuente or "Fuente indicada por Google News",
            "fecha": fecha,
            "enlace": enlace,
            "resumen": resumen[:1200],
            "recopilado_en": datetime.now().astimezone().isoformat(),
        })

    return resultados

def ejecutar():
    titulo("RECOPILACIÓN DE NOTICIAS EN TIEMPO REAL")
    noticias = []
    errores = []

    for indice, (categoria, consulta) in enumerate(CATEGORIAS, start=1):
        porcentaje = int((indice - 1) * 45 / len(CATEGORIAS))
        progreso(porcentaje, f"Buscando: {categoria}")

        try:
            encontrados = buscar_categoria(categoria, consulta)
            noticias.extend(encontrados)
            progreso(
                int(indice * 45 / len(CATEGORIAS)),
                f"{categoria}: {len(encontrados)} noticias",
                "OK"
            )
        except Exception as error:
            errores.append({
                "categoria": categoria,
                "error": type(error).__name__,
                "detalle": str(error)[:250],
            })
            progreso(
                int(indice * 45 / len(CATEGORIAS)),
                f"{categoria}: no disponible ({type(error).__name__})",
                "AVISO"
            )

        # Evita golpear el servicio innecesariamente.
        time.sleep(0.3)

    if not noticias:
        progreso(50, "Sin noticias: se conservan los datos anteriores", "ERROR")
        raise SystemExit(1)

    documento = {
        "generado_en": datetime.now().astimezone().isoformat(),
        "total_noticias": len(noticias),
        "categorias": [nombre for nombre, _ in CATEGORIAS],
        "errores": errores,
        "noticias": noticias,
    }

    temporal = SALIDA_JSON.with_suffix(".json.tmp")
    temporal.write_text(
        json.dumps(documento, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    temporal.replace(SALIDA_JSON)

    lineas = [
        "# TITAN GOLD NEWS — Recopilación",
        "",
        f"Generado: {documento['generado_en']}",
        f"Noticias recopiladas: {len(noticias)}",
        "",
        "> Las noticias son evidencia informativa; no prueban por sí solas "
        "causalidad ni determinan la dirección futura del oro.",
        "",
    ]

    for categoria, _ in CATEGORIAS:
        grupo = [n for n in noticias if n["categoria"] == categoria]
        lineas.extend([f"## {categoria}", ""])
        if not grupo:
            lineas.extend(["Sin resultados disponibles en esta consulta.", ""])
            continue
        for noticia in grupo:
            lineas.append(f"- **{noticia['titulo']}**")
            lineas.append(
                f"  - Fuente: {noticia['fuente'] or 'No identificada'}"
            )
            if noticia["fecha"]:
                lineas.append(f"  - Fecha: {noticia['fecha']}")
            lineas.append(f"  - Enlace: {noticia['enlace']}")
            if noticia["resumen"]:
                lineas.append(f"  - Resumen: {noticia['resumen']}")
            lineas.append("")

    if errores:
        lineas.extend(["## Fuentes con errores", ""])
        for error in errores:
            lineas.append(
                f"- {error['categoria']}: {error['error']} — "
                f"{error['detalle']}"
            )

    SALIDA_MD.write_text("\n".join(lineas) + "\n", encoding="utf-8")

    progreso(
        50,
        f"Recopilación terminada: {len(noticias)} noticias; "
        f"{len(errores)} categorías con errores",
        "OK" if noticias else "AVISO"
    )
    print(f"JSON: {SALIDA_JSON}", flush=True)
    print(f"Informe: {SALIDA_MD}", flush=True)
    return documento

if __name__ == "__main__":
    ejecutar()
