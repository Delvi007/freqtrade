import json
from pathlib import Path

BASE = Path("/root/TITAN_GOLD_NEWS")
ENTRADA = BASE / "noticias_recopiladas.json"
SALIDA = BASE / "analisis_macro.md"

REGLAS = [
    {
        "nombre": "Inflación y política monetaria",
        "claves": ["inflation", "inflación", "cpi", "pce", "interest rate",
                   "rate hike", "rate cut", "rate hikes", "rate cuts", "interest rates", "monetary policy", "fed rate", "federal reserve", "fed", "alza de tasas", "alza de tipos", "alza de tasas de la fed", "expectativas de alza", "subida de tipos", "recorte de tipos", "tasas de interés", "política monetaria"],
        "mecanismo": (
            "Una inflación mayor de la esperada puede reducir las expectativas "
            "de recortes de tasas o aumentar las expectativas de endurecimiento. "
            "Eso puede presionar al oro si eleva los rendimientos reales."
        ),
        "direccion": "Depende de la sorpresa frente a las expectativas y de la reacción de los rendimientos."
    },
    {
        "nombre": "Dólar estadounidense",
        "claves": ["us dollar", "dollar index", "dxy", "dólar", "dollar rises",
                   "dollar falls", "weak dollar", "strong dollar"],
        "mecanismo": (
            "El oro se cotiza internacionalmente en dólares. Un dólar más fuerte "
            "puede encarecerlo para compradores con otras monedas; uno más débil "
            "puede apoyarlo, aunque la relación no es constante."
        ),
        "direccion": "Comprueba el movimiento real del dólar y si coincide con el titular."
    },
    {
        "nombre": "Bonos y rendimientos reales",
        "claves": ["treasury yield", "bond yields", "real yields", "yields rise", "treasury yields", "rendimientos de los bonos", "bonos del tesoro",
                   "yields fall", "rendimientos", "bonos del tesoro"],
        "mecanismo": (
            "El aumento de rendimientos reales suele elevar el costo de oportunidad "
            "de mantener oro, que no paga intereses. La caída de rendimientos reales "
            "puede reducir ese costo."
        ),
        "direccion": "Verifica el rendimiento real; el rendimiento nominal por sí solo no cuenta toda la historia."
    },
    {
        "nombre": "Geopolítica y demanda de refugio",
        "claves": ["war", "guerra", "conflict", "conflicto", "attack", "ataque",
                   "safe haven", "refugio", "geopolitical", "geopolítica"],
        "mecanismo": (
            "Un aumento de incertidumbre puede impulsar la demanda de activos "
            "considerados refugio. El efecto puede ser breve o quedar compensado "
            "por movimientos del dólar, los tipos de interés o toma de beneficios."
        ),
        "direccion": "Evalúa la gravedad, novedad y escalada del evento, no solo su presencia."
    },
    {
        "nombre": "Compras de bancos centrales",
        "claves": ["central bank gold", "gold reserves", "gold buying",
                   "compras de oro", "reservas de oro", "banco central"],
        "mecanismo": (
            "Las compras oficiales pueden apoyar la demanda estructural de oro. "
            "Su efecto inmediato depende del tamaño, la confirmación y si el mercado ya lo anticipaba."
        ),
        "direccion": "Busca cifras verificables y distingue compras confirmadas de declaraciones o rumores."
    },
    {
        "nombre": "Empleo y crecimiento económico",
        "claves": ["payrolls", "jobs report", "unemployment", "employment", "nonfarm payrolls", "nóminas no agrícolas", "mercado laboral",
                   "empleo", "desempleo", "economic growth", "crecimiento económico"],
        "mecanismo": (
            "Los datos de empleo y crecimiento pueden modificar las expectativas "
            "sobre la Reserva Federal, el dólar y los rendimientos. El efecto sobre "
            "el oro depende de la sorpresa y de qué variable domine."
        ),
        "direccion": "Compara el dato con el consenso previo y revisiones de publicaciones anteriores."
    }
]

def analizar(noticia):
    texto = (
        noticia.get("titulo", "") + " " +
        noticia.get("descripcion", "")
    ).lower()

    coincidencias = []
    for regla in REGLAS:
        encontradas = [k for k in regla["claves"] if k in texto]
        if encontradas:
            coincidencias.append((regla, encontradas))

    return coincidencias

def main():
    if not ENTRADA.exists():
        raise SystemExit(f"No existe el archivo: {ENTRADA}")

    noticias = json.loads(ENTRADA.read_text(encoding="utf-8"))
    lineas = [
        "# TITAN GOLD NEWS — Análisis macroeconómico",
        "",
        f"Noticias examinadas: {len(noticias)}",
        "",
        "## Cómo leer este documento",
        "",
        "Los mecanismos descritos son hipótesis económicas generales, no una predicción.",
        "El titular y el resumen pueden omitir contexto; no se verifican automáticamente",
        "los datos frente al consenso ni los movimientos actuales del mercado.",
        "No se asignan probabilidades numéricas sin datos suficientes y validación.",
        ""
    ]

    for i, noticia in enumerate(noticias[:50], 1):
        lineas.extend([
            f"## {i}. {noticia.get('titulo', 'Sin título')}",
            "",
            f"- Fuente: {noticia.get('fuente') or 'No identificada'}",
            f"- Fecha: {noticia.get('fecha') or 'No disponible'}",
            f"- Enlace: {noticia.get('enlace') or 'No disponible'}",
            ""
        ])

        resultados = analizar(noticia)
        if not resultados:
            lineas.extend([
                "**Tema macroeconómico:** no identificado con las reglas actuales.",
                "Se necesita revisar la noticia completa para determinar su relevancia.",
                ""
            ])
            continue

        for regla, claves in resultados:
            lineas.extend([
                f"### Canal identificado: {regla['nombre']}",
                f"- Indicadores encontrados: {', '.join(claves)}",
                f"- Mecanismo posible: {regla['mecanismo']}",
                f"- Qué verificar: {regla['direccion']}",
                ""
            ])

        lineas.extend([
            "### Escenarios a considerar",
            "- **Escenario favorable al oro:** el contexto y los datos de mercado respaldan una demanda mayor o menores costos de oportunidad.",
            "- **Escenario desfavorable al oro:** el dólar o los rendimientos reales suben, o disminuye la demanda de refugio.",
            "- **Escenario mixto:** las variables reaccionan en direcciones opuestas o el evento ya estaba descontado.",
            "",
            "**Confirmación pendiente:** revisar la noticia original, las expectativas previas y la reacción de XAU/USD, DXY y rendimientos reales.",
            ""
        ])

    if not noticias:
        lineas.append("No hay noticias disponibles para analizar.")

    SALIDA.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print("Análisis macroeconómico generado.")
    print(f"Noticias procesadas: {len(noticias)}")
    print(f"Archivo: {SALIDA}")

if __name__ == "__main__":
    main()
