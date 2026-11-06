import json
from pathlib import Path
from collections import Counter

base = Path("/root/TITAN_GOLD_NEWS")
archivo = base / "noticias_recopiladas.json"
salida = base / "resumen_cuantitativo.md"

if not archivo.exists():
    raise SystemExit("ERROR: no existe noticias_recopiladas.json")

noticias = json.loads(archivo.read_text(encoding="utf-8"))

alcistas = [
    "rate cut", "rate cuts", "recorte de tasas", "recortes de tasas",
    "war", "guerra", "conflict", "conflicto", "safe haven", "refugio",
    "central bank buying", "gold buying", "compras de oro",
    "weak dollar", "dólar débil", "recession", "recesión",
    "lower interest rates", "bajan las tasas"
]
bajistas = [
    "rate hike", "rate hikes", "subida de tasas", "subidas de tasas",
    "higher yields", "rising yields", "rendimientos al alza",
    "strong dollar", "dólar fuerte", "hawkish",
    "restrictive policy", "política restrictiva",
    "real yields rise", "suben los rendimientos reales"
]

conteo = Counter()
detalles = []

for noticia in noticias:
    texto = (
        noticia.get("titulo", "") + " " +
        noticia.get("descripcion", "")
    ).lower()

    a = sum(p in texto for p in alcistas)
    b = sum(p in texto for p in bajistas)

    if a > b:
        etiqueta = "Posible factor favorable"
    elif b > a:
        etiqueta = "Posible factor desfavorable"
    else:
        etiqueta = "Mixta o indeterminada"

    conteo[etiqueta] += 1
    detalles.append((etiqueta, noticia.get("titulo", "Sin título")))

lineas = [
    "# Resumen cuantitativo de noticias sobre el oro",
    "",
    f"Noticias examinadas: {len(noticias)}",
    f"Posibles factores favorables: {conteo['Posible factor favorable']}",
    f"Posibles factores desfavorables: {conteo['Posible factor desfavorable']}",
    f"Mixtas o indeterminadas: {conteo['Mixta o indeterminada']}",
    "",
    "## Clasificación por noticia",
    ""
]

for etiqueta, titulo in detalles:
    lineas.append(f"- **{etiqueta}:** {titulo}")

lineas.extend([
    "",
    "## Limitaciones",
    "",
    "La clasificación usa coincidencias de palabras clave en títulos y descripciones.",
    "No verifica la dirección real del mercado ni la importancia de cada noticia.",
    "Los recuentos no son probabilidades de subida o bajada del oro.",
    "Las noticias pueden estar duplicadas en contenido aunque tengan enlaces diferentes.",
    "Para estimar probabilidades se necesitarían datos históricos de XAU/USD,",
    "variables macroeconómicas y validación estadística fuera de muestra."
])

salida.write_text("\n".join(lineas) + "\n", encoding="utf-8")

print("===== RESUMEN CUANTITATIVO =====")
print(f"Noticias examinadas: {len(noticias)}")
print(f"Factores potencialmente favorables: {conteo['Posible factor favorable']}")
print(f"Factores potencialmente desfavorables: {conteo['Posible factor desfavorable']}")
print(f"Mixtas o indeterminadas: {conteo['Mixta o indeterminada']}")
print(f"Archivo generado: {salida}")
