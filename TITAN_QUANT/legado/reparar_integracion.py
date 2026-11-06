import json
import re
import html
import shutil
import unicodedata
from pathlib import Path
from datetime import datetime
from html.parser import HTMLParser

BASE = Path(__file__).resolve().parent
ARCHIVO = BASE / "noticias_recopiladas.json"
VIVO = BASE / "noticias_en_vivo.json"


class TextoHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.partes = []

    def handle_data(self, data):
        texto = data.strip()
        if texto:
            self.partes.append(texto)


def texto_limpio(valor):
    if not valor:
        return ""
    valor = str(valor)
    parser = TextoHTML()
    try:
        parser.feed(valor)
        valor = " ".join(parser.partes)
    except Exception:
        pass
    valor = html.unescape(valor)
    return re.sub(r"\s+", " ", valor).strip()


def clave(valor):
    valor = unicodedata.normalize("NFKD", texto_limpio(valor))
    valor = "".join(c for c in valor if not unicodedata.combining(c))
    valor = valor.casefold()
    return re.sub(r"[^a-z0-9]+", " ", valor).strip()


def normalizar(n, vivo=False):
    if not isinstance(n, dict):
        return None

    titulo = texto_limpio(n.get("titulo") or n.get("title"))
    enlace = texto_limpio(
        n.get("enlace") or n.get("link") or n.get("url")
    )
    fuente = texto_limpio(n.get("fuente") or n.get("source"))
    fecha = texto_limpio(n.get("fecha") or n.get("date"))

    resumen = texto_limpio(
        n.get("resumen") or n.get("summary")
    )
    descripcion = texto_limpio(
        n.get("descripcion") or n.get("description")
    )

    # No tratar el propio titular como resumen editorial.
    if not resumen or clave(resumen) == clave(titulo):
        resumen = descripcion
    if clave(resumen) == clave(titulo):
        resumen = ""

    categoria = texto_limpio(
        n.get("categoria") or n.get("category")
    )

    if not titulo:
        return None

    # Clasificación de respaldo; no sustituye la categoría del RSS.
    if not categoria:
        t = clave(titulo)
        reglas = [
            ("Reserva Federal", ("fed", "reserva federal", "fomc", "powell")),
            ("Bonos y rendimientos", ("bono", "rendimiento", "yield", "treasury")),
            ("Inflación y energía", ("inflacion", "inflation", "petroleo", "crudo", "energia")),
            ("Geopolítica", ("guerra", "iran", "oriente proximo", "geopolitica")),
            ("Oro y dólar", ("oro", "gold", "xau", "dolar", "dxy")),
            ("Empleo y crecimiento", ("empleo", "desempleo", "nomina", "gdp", "pib", "crecimiento")),
            ("Mercados y economía", ("mercado", "economia", "acciones", "bolsa")),
        ]
        for nombre, palabras in reglas:
            if any(p in t for p in palabras):
                categoria = nombre
                break
        if not categoria:
            categoria = "Sin clasificar"

    return {
        "titulo": titulo,
        "enlace": enlace,
        "fuente": fuente,
        "fecha": fecha,
        "categoria": categoria,
        "resumen": resumen,
    }


def leer_lista(ruta):
    dato = json.loads(ruta.read_text(encoding="utf-8"))
    if isinstance(dato, dict):
        dato = dato.get("noticias", [])
    if not isinstance(dato, list):
        raise ValueError(f"{ruta.name}: se esperaba una lista de noticias")
    return dato


if not ARCHIVO.exists() or not VIVO.exists():
    raise SystemExit("ERROR: faltan noticias_recopiladas.json o noticias_en_vivo.json")

# La copia de seguridad se crea antes de cualquier escritura.
marca = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = BASE / f"noticias_recopiladas.pre_reparacion_{marca}.json"
shutil.copy2(ARCHIVO, backup)

anteriores = [normalizar(n) for n in leer_lista(ARCHIVO)]
en_vivo = [normalizar(n, vivo=True) for n in leer_lista(VIVO)]
anteriores = [n for n in anteriores if n]
en_vivo = [n for n in en_vivo if n]

# Índices para enriquecer registros existentes con la fuente en vivo.
por_url = {clave(n["enlace"]): n for n in en_vivo if n["enlace"]}
por_titulo = {clave(n["titulo"]): n for n in en_vivo if n["titulo"]}

combinadas = []
posiciones = {}

def agregar(n, preferir_nuevo=False):
    url_key = clave(n["enlace"]) if n["enlace"] else ""
    title_key = clave(n["titulo"])
    k = ("url", url_key) if url_key else ("titulo", title_key)

    # Si la URL difiere pero el titular coincide, todavía se considera
    # una posible repetición; se conserva un único registro.
    k_titulo = ("titulo", title_key)
    idx = posiciones.get(k, posiciones.get(k_titulo))

    if idx is None:
        idx = len(combinadas)
        combinadas.append(n.copy())
        posiciones[k] = idx
        posiciones[k_titulo] = idx
        return

    actual = combinadas[idx]
    campos = ("titulo", "enlace", "fuente", "fecha", "categoria", "resumen")
    for campo in campos:
        valor_nuevo = n.get(campo, "")
        valor_actual = actual.get(campo, "")
        if valor_nuevo and (preferir_nuevo or not valor_actual):
            actual[campo] = valor_nuevo

    posiciones[k] = idx
    posiciones[k_titulo] = idx


# Primero preservamos lo anterior y enriquecemos coincidencias con el RSS.
for n in anteriores:
    coincidencia = None
    if n["enlace"]:
        coincidencia = por_url.get(clave(n["enlace"]))
    if coincidencia is None:
        coincidencia = por_titulo.get(clave(n["titulo"]))

    if coincidencia:
        enriquecida = n.copy()
        for campo in ("categoria", "resumen", "fuente", "fecha", "enlace"):
            if coincidencia.get(campo):
                enriquecida[campo] = coincidencia[campo]
        agregar(enriquecida)
    else:
        agregar(n)

# Después agregamos las noticias nuevas; la deduplicación evita sumarlas
# dos veces cuando ya están en el conjunto anterior.
for n in en_vivo:
    agregar(n, preferir_nuevo=True)

# Alias compatibles con los scripts existentes.
salida = []
for n in combinadas:
    registro = n.copy()
    registro.update({
        "title": n["titulo"],
        "link": n["enlace"],
        "url": n["enlace"],
        "source": n["fuente"],
        "date": n["fecha"],
        "summary": n["resumen"],
        "description": n["resumen"],
    })
    salida.append(registro)

temporal = ARCHIVO.with_suffix(".json.tmp")
temporal.write_text(
    json.dumps(salida, ensure_ascii=False, indent=2),
    encoding="utf-8"
)
temporal.replace(ARCHIVO)

sin_categoria = sum(not n["categoria"] or n["categoria"] == "Sin clasificar" for n in salida)
sin_resumen = sum(not n["resumen"] for n in salida)

print("REPARACIÓN COMPLETADA")
print("Copia de seguridad:", backup)
print("Registros finales:", len(salida))
print("Sin categoría identificada:", sin_categoria)
print("Sin resumen editorial:", sin_resumen)
print("Archivo:", ARCHIVO)
