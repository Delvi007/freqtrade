from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
NUEVAS = BASE / "noticias_en_vivo.json"
DESTINO = BASE / "noticias_recopiladas.json"

CLAVES_LISTA = (
    "noticias", "articles", "items", "news", "resultados",
    "results", "entries", "data"
)

def cargar(ruta):
    with ruta.open("r", encoding="utf-8") as archivo:
        return json.load(archivo)

def texto(obj, *claves):
    for clave in claves:
        valor = obj.get(clave)
        if valor is not None and str(valor).strip():
            return str(valor).strip()
    return ""

def normalizar(n):
    titulo = texto(n, "titulo", "title", "headline", "nombre")
    enlace = texto(n, "enlace", "link", "url", "web_url")
    resumen = texto(n, "resumen", "summary", "description", "snippet")
    fuente = texto(n, "fuente", "source", "publisher")
    fecha = texto(n, "fecha", "published", "published_at", "pubDate", "date")
    categoria = texto(n, "categoria", "category", "tema")

    # Se conservan alias habituales para compatibilidad con analizadores.
    return {
        **n,
        "titulo": titulo,
        "title": titulo,
        "enlace": enlace,
        "link": enlace,
        "url": enlace,
        "resumen": resumen,
        "summary": resumen,
        "description": resumen,
        "fuente": fuente,
        "source": fuente,
        "fecha": fecha,
        "date": fecha,
        "categoria": categoria,
    }

def encontrar_lista(obj):
    if isinstance(obj, list) and all(isinstance(x, dict) for x in obj):
        return obj, lambda nueva: nueva

    if not isinstance(obj, dict):
        return None, None

    for clave in CLAVES_LISTA:
        valor = obj.get(clave)
        if isinstance(valor, list) and all(isinstance(x, dict) for x in valor):
            return valor, lambda nueva, c=clave: {**obj, c: nueva}

    for clave, valor in obj.items():
        if isinstance(valor, dict):
            lista, reconstruir = encontrar_lista(valor)
            if lista is not None:
                def reconstruir_padre(nueva, c=clave, v=valor, r=reconstruir):
                    return {**obj, c: r(nueva)}
                return lista, reconstruir_padre

    return None, None

def clave_unica(n):
    enlace = texto(n, "enlace", "link", "url", "web_url").lower().rstrip("/")
    titulo = texto(n, "titulo", "title", "headline").lower()
    return enlace or titulo

def main():
    if not NUEVAS.exists():
        raise SystemExit("ERROR: falta noticias_en_vivo.json")
    if not DESTINO.exists():
        raise SystemExit("ERROR: falta noticias_recopiladas.json")

    actuales = cargar(DESTINO)
    nuevas_doc = cargar(NUEVAS)
    nuevas = nuevas_doc.get("noticias", []) if isinstance(nuevas_doc, dict) else nuevas_doc

    if not isinstance(nuevas, list):
        raise SystemExit("ERROR: formato inesperado en noticias_en_vivo.json")

    lista, reconstruir = encontrar_lista(actuales)
    if lista is None:
        raise SystemExit(
            "ERROR: no se encontró una lista de noticias compatible. "
            "No se modificó el archivo original."
        )

    normalizadas = [normalizar(n) for n in lista if isinstance(n, dict)]
    vistos = {clave_unica(n) for n in normalizadas if clave_unica(n)}
    agregadas = 0

    for noticia in nuevas:
        if not isinstance(noticia, dict):
            continue
        item = normalizar(noticia)
        clave = clave_unica(item)
        if not clave or clave in vistos:
            continue
        normalizadas.append(item)
        vistos.add(clave)
        agregadas += 1

    respaldo = DESTINO.with_name(
        "noticias_recopiladas.backup_" +
        datetime.now().strftime("%Y%m%d_%H%M%S") + ".json"
    )
    shutil.copy2(DESTINO, respaldo)

    resultado = reconstruir(normalizadas)
    temporal = DESTINO.with_suffix(".json.tmp")
    temporal.write_text(
        json.dumps(resultado, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    temporal.replace(DESTINO)

    print("Integración completada.")
    print("Noticias anteriores:", len(lista))
    print("Noticias nuevas recibidas:", len(nuevas))
    print("Noticias añadidas:", agregadas)
    print("Total integrado:", len(normalizadas))
    print("Copia de seguridad:", respaldo)
    print("Archivo integrado:", DESTINO)

if __name__ == "__main__":
    main()
