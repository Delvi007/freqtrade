import json
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from html import unescape

BASE = Path(__file__).resolve().parent
QUERIES = [
    "gold price XAU USD",
    "Federal Reserve interest rates gold",
    "US dollar Treasury yields gold",
    "central bank gold buying",
    "geopolitical risk gold safe haven",
    "US inflation employment gold",
    "precio del oro noticias"
]

def texto(nodo, etiqueta):
    elemento = nodo.find(etiqueta)
    if elemento is None:
        return ""
    return unescape(" ".join(elemento.itertext()).strip())

def recopilar():
    noticias = {}
    ahora = datetime.now(timezone.utc)
    limite = ahora - timedelta(days=7)
    cabeceras = {"User-Agent": "Mozilla/5.0"}

    for consulta in QUERIES:
        url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({
            "q": consulta, "hl": "es-419", "gl": "US", "ceid": "US:es-419"
        })
        try:
            solicitud = urllib.request.Request(url, headers=cabeceras)
            with urllib.request.urlopen(solicitud, timeout=20) as respuesta:
                raiz = ET.fromstring(respuesta.read())

            for noticia in raiz.findall(".//item"):
                titulo = texto(noticia, "title")
                enlace = texto(noticia, "link")
                descripcion = texto(noticia, "description")
                fecha_original = texto(noticia, "pubDate")

                try:
                    fecha = parsedate_to_datetime(fecha_original)
                    if fecha.tzinfo is None:
                        fecha = fecha.replace(tzinfo=timezone.utc)
                    if fecha < limite:
                        continue
                    fecha_texto = fecha.astimezone(timezone.utc).strftime(
                        "%Y-%m-%d %H:%M UTC"
                    )
                except Exception:
                    fecha_texto = fecha_original

                if titulo and enlace:
                    noticias[enlace] = {
                        "titulo": titulo,
                        "enlace": enlace,
                        "descripcion": descripcion,
                        "fecha": fecha_texto,
                        "fuente": texto(noticia, "source")
                    }
        except Exception as error:
            print(f"[AVISO] Consulta fallida: {consulta}: {error}")

    return list(noticias.values())


ALCISTAS = [
    "rate cut", "rate cuts", "recorte de tasas", "recortes de tasas",
    "war", "guerra", "conflict", "conflicto", "safe haven", "refugio",
    "central bank buying", "gold buying", "compras de oro",
    "weak dollar", "dólar débil", "recession", "recesión",
    "lower interest rates", "bajan las tasas"
]

BAJISTAS = [
    "rate hike", "rate hikes", "subida de tasas", "subidas de tasas",
    "higher yields", "rising yields", "rendimientos al alza",
    "strong dollar", "dólar fuerte", "hawkish",
    "restrictive policy", "política restrictiva",
    "real yields rise", "suben los rendimientos reales"
]


def clasificar(noticia):
    texto_completo = (
        noticia["titulo"] + " " + noticia["descripcion"]
    ).lower()

    puntos_alcistas = sum(p in texto_completo for p in ALCISTAS)
    puntos_bajistas = sum(p in texto_completo for p in BAJISTAS)

    if puntos_alcistas > puntos_bajistas:
        etiqueta = "Posible factor favorable para el oro"
    elif puntos_bajistas > puntos_alcistas:
        etiqueta = "Posible factor desfavorable para el oro"
    else:
        etiqueta = "Impacto mixto o indeterminado"

    return etiqueta, puntos_alcistas, puntos_bajistas


def generar_informe(noticias):
    ahora = datetime.now(timezone.utc)
    archivo_json = BASE / "noticias_recopiladas.json"
    archivo_informe = BASE / "informe_oro.md"

    noticias.sort(key=lambda n: n["fecha"], reverse=True)

    archivo_json.write_text(
        json.dumps(noticias, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    lineas = [
        "# TITAN GOLD NEWS",
        "## Informe de investigación de noticias sobre el oro",
        "",
        f"Generado: {ahora.strftime('%Y-%m-%d %H:%M UTC')}",
        f"Noticias recopiladas: {len(noticias)}",
        "",
        "## Resumen ejecutivo",
        "",
        "Este informe recopila titulares y descripciones de noticias recientes.",
        "Las clasificaciones son orientativas y se basan en palabras clave.",
        "No demuestran causalidad ni predicen por sí solas el movimiento de XAU/USD.",
        "",
        "## Cómo interpretar el posible impacto",
        "",
        "- Un dólar más débil y menores rendimientos reales pueden favorecer al oro.",
        "- Un dólar más fuerte y mayores rendimientos reales pueden presionar al oro.",
        "- La incertidumbre geopolítica puede aumentar la demanda de refugio,",
        "  aunque la reacción depende del contexto y de lo que el mercado ya esperaba.",
        "- Los datos económicos deben compararse con las expectativas publicadas.",
        "",
        "## Noticias analizadas",
        ""
    ]

    if not noticias:
        lineas.append(
            "No se recopilaron noticias. Comprueba la conexión a Internet e inténtalo de nuevo."
        )

    for numero, noticia in enumerate(noticias[:50], 1):
        etiqueta, alcistas, bajistas = clasificar(noticia)
        lineas.extend([
            f"### {numero}. {noticia['titulo']}",
            "",
            f"- Fuente: {noticia['fuente'] or 'No identificada'}",
            f"- Fecha: {noticia['fecha'] or 'No disponible'}",
            f"- Clasificación automática: {etiqueta}",
            f"- Coincidencias de palabras favorables/desfavorables: {alcistas}/{bajistas}",
            f"- Descripción: {noticia['descripcion'] or 'No disponible'}",
            f"- Enlace: {noticia['enlace']}",
            ""
        ])

    lineas.extend([
        "## Conclusión y probabilidades",
        "",
        "Este programa no asigna porcentajes de probabilidad de subida o bajada.",
        "El recuento de palabras no es una probabilidad estadística.",
        "Para calcular probabilidades defendibles se necesitan datos de mercado,",
        "expectativas económicas y un modelo probado con datos históricos fuera",
        "de muestra. No debe interpretarse este informe como una señal de compra o venta.",
        ""
    ])

    archivo_informe.write_text("\n".join(lineas), encoding="utf-8")
    print("\n===== TITAN GOLD NEWS =====")
    print(f"Noticias recopiladas: {len(noticias)}")
    print(f"Informe: {archivo_informe}")
    print(f"Datos: {archivo_json}")


if __name__ == "__main__":
    noticias = recopilar()
    if not noticias:
        print("[ERROR] No se obtuvo ninguna noticia (¿sin internet?). Se conservan los datos anteriores.")
        raise SystemExit(1)
    generar_informe(noticias)
