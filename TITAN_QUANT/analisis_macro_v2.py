import json
import re
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

BASE = Path(__file__).resolve().parent
ENTRADA = BASE / "noticias_recopiladas.json"
SALIDA = BASE / "analisis_macro_v2.md"
FUENTES_REF = ["reuters", "bloomberg", "world gold council",
               "financial times", "wall street journal", "cnbc", "kitco"]

REGLAS = [
    {"nombre": "Inflación",
     "claves": ["inflation", "inflación", "cpi", "pce", "ipc",
                "precios al consumidor", "consumer prices"],
     "mecanismo": "Una inflación mayor de la esperada puede reducir las expectativas de recortes de tasas y subir los rendimientos reales, lo que presiona al oro. Pero el oro también se usa como cobertura contra la inflación.",
     "verificar": "Compara el dato con el consenso y mira si los rendimientos reales subieron o bajaron.",
     "fav": "La inflación sorprende al alza pero los rendimientos reales caen o el mercado busca cobertura.",
     "des": "La inflación sube y el mercado anticipa tasas más altas por más tiempo.",
     "mix": "El dato coincide con lo esperado y el mercado apenas reacciona."},
    {"nombre": "Política de la Fed y tasas",
     "claves": ["fed", "federal reserve", "reserva federal", "powell",
                "rate hike", "rate hikes", "rate cut", "rate cuts",
                "interest rate", "interest rates", "monetary policy",
                "alza de tasas", "subida de tipos", "recorte de tipos",
                "tasas de interés", "política monetaria"],
     "mecanismo": "Tasas más altas o más duraderas elevan el costo de oportunidad de tener oro, que no paga intereses. Recortes o un tono más suave suelen aliviar esa presión.",
     "verificar": "Distingue lo que la Fed hizo de lo que el mercado esperaba y revisa la reacción de los rendimientos.",
     "fav": "La Fed suena más suave de lo esperado o se adelantan recortes.",
     "des": "La Fed refuerza un tono restrictivo o retrasa recortes.",
     "mix": "El mensaje es ambiguo o ya estaba descontado."},
    {"nombre": "Dólar estadounidense",
     "claves": ["us dollar", "dollar index", "dxy", "dólar", "dollar",
                "weak dollar", "strong dollar"],
     "mecanismo": "El oro cotiza en dólares: un dólar fuerte lo encarece para compradores con otras monedas y uno débil suele apoyarlo, aunque la relación no es constante.",
     "verificar": "Comprueba el movimiento real del DXY y si coincide con el titular.",
     "fav": "El dólar se debilita de forma sostenida.",
     "des": "El dólar se fortalece por datos o tasas.",
     "mix": "Dólar y oro suben a la vez por demanda de refugio."},
    {"nombre": "Bonos y rendimientos reales",
     "claves": ["treasury yield", "treasury yields", "bond yields",
                "real yields", "rendimientos reales",
                "rendimientos de los bonos", "bonos del tesoro",
                "rendimiento del bono"],
     "mecanismo": "Rendimientos reales más altos aumentan el costo de oportunidad del oro; más bajos lo reducen.",
     "verificar": "Mira el rendimiento real (ajustado por inflación), no solo el nominal.",
     "fav": "Los rendimientos reales caen.",
     "des": "Los rendimientos reales suben.",
     "mix": "Suben los nominales pero también la inflación esperada, y el real casi no cambia."},
    {"nombre": "Geopolítica y refugio",
     "claves": ["war", "guerra", "conflict", "conflicto", "attack",
                "ataque", "safe haven", "refugio", "geopolitical",
                "geopolítica", "tensions", "tensiones"],
     "mecanismo": "Más incertidumbre puede impulsar la demanda de activos refugio, aunque el efecto suele ser breve o quedar compensado por dólar y tasas.",
     "verificar": "Evalúa gravedad, novedad y escalada, no solo la presencia de la palabra.",
     "fav": "El conflicto escala y el miedo se sostiene.",
     "des": "Las tensiones se calman o el dólar sube más que la demanda de refugio.",
     "mix": "El oro sube al inicio y devuelve la subida días después."},
    {"nombre": "Compras de bancos centrales",
     "claves": ["central bank gold", "central banks buy", "gold reserves",
                "gold buying", "compras de oro", "reservas de oro",
                "bancos centrales compran"],
     "mecanismo": "Las compras oficiales apoyan la demanda estructural de oro; el efecto inmediato depende de la cifra y de si ya se anticipaba.",
     "verificar": "Busca cifras verificables y distingue compras confirmadas de rumores.",
     "fav": "Las compras confirmadas superan lo esperado.",
     "des": "Las compras se desaceleran.",
     "mix": "Las compras siguen, pero el mercado ya las tenía en el precio."},
    {"nombre": "Empleo y crecimiento",
     "claves": ["payrolls", "jobs report", "unemployment",
                "nonfarm payrolls", "nóminas no agrícolas",
                "mercado laboral", "desempleo", "economic growth",
                "crecimiento económico", "employment data",
                "datos de empleo"],
     "mecanismo": "Los datos de empleo y crecimiento cambian las expectativas sobre la Fed, el dólar y los rendimientos; el efecto sobre el oro depende de cuál domine.",
     "verificar": "Compara el dato con el consenso y con revisiones anteriores.",
     "fav": "Datos débiles aumentan las expectativas de recortes.",
     "des": "Datos fuertes refuerzan al dólar y a los rendimientos.",
     "mix": "El dato mezcla señales (empleo fuerte, salarios débiles)."},
]

REGLAS += [
    {"nombre": "Petróleo y energía",
     "claves": ["petróleo", "petroleo", "oil", "crude", "brent", "wti"],
     "mecanismo": "Un petróleo más caro puede alimentar expectativas de inflación y de tasas altas, lo que suele presionar al oro; también puede reflejar tensión geopolítica que lo apoya. Si el petróleo se modera, esa presión suele aliviarse.",
     "verificar": "Mira si el movimiento del petróleo vino acompañado de cambios en los rendimientos reales y en el dólar.",
     "fav": "El petróleo baja y se enfrían las expectativas de inflación, o sube por tensión geopolítica y aumenta la demanda de refugio.",
     "des": "El petróleo sube y el mercado anticipa inflación y tasas altas por más tiempo.",
     "mix": "El petróleo sube, pero el oro reacciona poco porque ya estaba descontado."},
    {"nombre": "Precio y análisis técnico",
     "claves": ["xau/usd", "xauusd", "rotura", "soporte", "resistencia",
                "mínimo", "mínimos", "máximo", "máximos", "sesión consecutiva",
                "pullback", "breakout", "support", "resistance"],
     "mecanismo": "Estas noticias describen movimientos y niveles de precio. Los niveles técnicos pueden amplificar movimientos de corto plazo, pero describen el precio y no explican por qué se mueve.",
     "verificar": "Busca qué factor macroeconómico se menciona como causa del movimiento y si el nivel técnico se respetó.",
     "fav": "El precio rompe resistencias con apoyo de factores macro favorables.",
     "des": "El precio pierde soportes y se suman factores macro adversos.",
     "mix": "El precio oscila en un rango sin una causa clara."},
    {"nombre": "ETF y demanda de inversión",
     "claves": ["etf", "etfs", "tenencias", "holdings", "spdr", "gld", "ishares"],
     "mecanismo": "Entradas de dinero en ETF de oro indican demanda de inversión; salidas indican lo contrario. Reflejan el ánimo de los inversores, pero también pueden llegar tarde frente al precio.",
     "verificar": "Comprueba si las tenencias suben mientras el precio cae o sube, y la fuente del dato.",
     "fav": "Las tenencias de ETF suben de forma sostenida.",
     "des": "Hay salidas continuas de los ETF.",
     "mix": "Las tenencias suben pero el precio cae, lo que indica señales opuestas."},
    {"nombre": "Demanda física y joyería",
     "claves": ["joyas", "joyería", "joyeria", "jewelry", "jewellery",
                "quilates", "india", "china", "demanda física", "physical demand"],
     "mecanismo": "Un precio muy alto suele frenar la demanda de joyería, sobre todo en Asia; caídas del precio pueden reactivarla. Es un apoyo de fondo, no un impulso inmediato.",
     "verificar": "Busca cifras de demanda (por ejemplo del World Gold Council) y no solo anécdotas de talleres o tiendas.",
     "fav": "La demanda física se reactiva en las caídas del precio.",
     "des": "El precio alto reduce las compras de joyería e inversión física.",
     "mix": "La demanda física cae pero compensan las compras de bancos centrales o ETF."},
    {"nombre": "Pronósticos de analistas",
     "claves": ["forecast", "pronóstico", "pronostico", "cibc", "goldman",
                "jpmorgan", "jp morgan", "ubs", "citi", "morgan stanley",
                "bank of america", "wall street", "verdict"],
     "mecanismo": "Las previsiones de bancos y analistas orientan las expectativas, pero son opiniones y suelen cambiar con el precio. Conviene leer sus supuestos, no solo la cifra.",
     "verificar": "Identifica los supuestos del pronóstico (tasas, dólar, demanda) y su historial de aciertos.",
     "fav": "Varias entidades independientes elevan sus previsiones por los mismos motivos.",
     "des": "Las entidades recortan previsiones por tasas o dólar más fuertes.",
     "mix": "Las previsiones divergen o dependen de supuestos distintos."},
]

AJUSTES = {
    "Política de la Fed y tasas": ["rate-hike", "rate-cut", "hike bets", "cut bets"],
    "Geopolítica y refugio": ["safe-haven"],
    "Pronósticos de analistas": ["bofa", "price target", "nuevo objetivo", "objetivo para el precio"],
}
for _r in REGLAS:
    _r["claves"] = _r["claves"] + AJUSTES.get(_r["nombre"], [])
REGLAS.append({
    "nombre": "Mineras y oferta",
    "claves": ["miner", "miners", "mining", "minera", "mineras", "minería", "mine supply", "oferta de oro"],
    "mecanismo": "Los resultados y la caja de las mineras muestran cómo les afecta el precio actual y qué pasa con la oferta. Es información de contexto del sector, no un impulsor directo del precio.",
    "verificar": "Mira si el dato es de producción, costos o resultados, y cómo se compara con trimestres anteriores.",
    "fav": "La oferta crece poco y los costos presionan a los productores.",
    "des": "La producción sube con fuerza o el precio alto estimula más oferta.",
    "mix": "Mejoran los márgenes de las mineras pero la producción no cambia.",
})

def patron(clave):
    return re.compile(r"(?<!\w)" + re.escape(clave) + r"(?!\w)")

for r in REGLAS:
    r["pats"] = [(k, patron(k)) for k in r["claves"]]

def normalizar(t):
    return re.sub(r"[^\w\s]", "", t.lower()).strip()

def deduplicar(noticias):
    unicas, vistos = [], []
    for n in noticias:
        t = normalizar(n.get("titulo", ""))
        for i, v in enumerate(vistos):
            if SequenceMatcher(None, t, v).ratio() >= 0.85:
                unicas[i]["_copias"] += 1
                break
        else:
            n["_copias"] = 1
            vistos.append(t)
            unicas.append(n)
    return unicas

def es_ref(n):
    f = (n.get("fuente") or "").lower()
    return any(x in f for x in FUENTES_REF)

def analizar(n):
    texto = (n.get("titulo", "") + " " + n.get("descripcion", "")).lower()
    res = []
    for r in REGLAS:
        hallados = [k for k, p in r["pats"] if p.search(texto)]
        if hallados:
            res.append((r, hallados))
    return res

GOLD_RE = re.compile(r"(?<!\w)(oro|gold|xau|xauusd|onza|onzas)(?!\w)")
RUIDO = ["serie mundial", "world series", "tomate", "cotizarse como oro", "datos de cotización en tiempo real", "noticias de cnbc tv18 en tradingview"]

def limpio(n):
    t = n.get("titulo", "Sin título")
    return re.sub(r"\s[-—–]\s[^-—–]{1,40}$", "", t).strip()

def es_ruido(n):
    texto = (n.get("titulo", "") + " " + n.get("descripcion", "")).lower()
    return any(x in texto for x in RUIDO) or not GOLD_RE.search(texto)

def conclusion(conteo, total, n_sin, n_ruido):
    L = ["## Conclusión en español", ""]
    if not conteo:
        L.extend(["No se identificaron temas con las reglas actuales.", ""])
        return L
    top = [n for n, _ in conteo.most_common(3)]
    asignadas = total - n_sin - n_ruido
    L.append("Los temas que más aparecen en las noticias son: " + ", ".join(top) + ".")
    L.append("")
    L.append("**Razones y lectura de conjunto:**")
    if "Petróleo y energía" in conteo and (
            "Inflación" in conteo or "Política de la Fed y tasas" in conteo):
        L.append("- Varias noticias vinculan el petróleo con la inflación y las tasas. La cadena que plantean es: petróleo más caro, más inflación esperada, tasas altas por más tiempo, rendimientos reales más altos y presión sobre el oro. Es una hipótesis que hay que confirmar con datos, no un hecho.")
    elif "Política de la Fed y tasas" in conteo:
        L.append("- La política de la Fed y las expectativas de tasas dominan la conversación. Para el oro importa sobre todo el costo de oportunidad: tasas altas o duraderas suelen pesar, y un tono más suave suele aliviar.")
    if "Precio y análisis técnico" in top:
        L.append("- Gran parte de la cobertura describe niveles de precio y no explica sus causas; conviene separar lo que informa de lo que solo describe.")
    if "Pronósticos de analistas" in top:
        L.append("- Muchas noticias son pronósticos de bancos y analistas. Son opiniones que cambian con el precio; importan sus supuestos más que la cifra.")
    if "Geopolítica y refugio" in conteo:
        L.append("- Hay noticias sobre refugio y geopolítica que pueden actuar como contrapeso frente a la presión de tasas y dólar.")
    L.extend(["", "**Qué confirmar con datos de mercado antes de sacar conclusiones:**",
              "- Movimiento real de XAU/USD en las últimas sesiones.",
              "- Rendimiento real del bono a 10 años (no solo el nominal).",
              "- Índice dólar (DXY).",
              "- Precio del petróleo y si el movimiento se sostiene.",
              "- Flujos y tenencias de ETF de oro.",
              "",
              f"**Cobertura:** {asignadas} de {total} noticias únicas se asignaron a algún canal; {n_sin} quedaron sin tema y {n_ruido} se descartaron por no tratar del oro.",
              "",
              "Este resumen indica de qué se habla, no hacia dónde irá el oro. No se asignan probabilidades: harían falta datos de mercado y validación estadística.",
              ""])
    return L

import csv
import io
import urllib.request

from datetime import datetime, timezone

FUENTES_YAHOO = [
    ("Oro (futuros COMEX, GC=F)", "GC=F"),
    ("Índice dólar (DXY)", "DX-Y.NYB"),
    ("Petróleo WTI (futuros)", "CL=F"),
    ("Rendimiento nominal 10 años EE. UU. (%)", "%5ETNX"),
]

def descargar(url, espera=25):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=espera) as r:
        return r.read().decode("utf-8", errors="replace")

def serie_yahoo(simbolo):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{simbolo}?range=15d&interval=1d"
    r = json.loads(descargar(url))["chart"]["result"][0]
    cierres = r["indicators"]["quote"][0]["close"]
    datos = [(datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d"), c)
             for t, c in zip(r["timestamp"], cierres) if c is not None]
    por_fecha = {}
    for f, c in datos:
        por_fecha[f] = c
    datos = sorted(por_fecha.items())
    if len(datos) < 6:
        raise ValueError("pocos datos")
    return datos

def serie_tesoro():
    anio = datetime.now().year
    url = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
           f"daily-treasury-rates.csv/{anio}/all?type=daily_treasury_real_yield_curve"
           f"&field_tdr_date_value={anio}&page&_format=csv")
    filas = list(csv.reader(io.StringIO(descargar(url, 40))))
    idx = filas[0].index("10 YR")
    datos = []
    for f in filas[1:]:
        try:
            datos.append((f[0], float(f[idx])))
        except (ValueError, IndexError):
            continue
    datos.reverse()
    if len(datos) < 6:
        raise ValueError("pocos datos")
    return datos

def mercado():
    L = ["## Datos de mercado", "",
         "Último precio disponible al ejecutar el programa. Si el mercado está abierto, el dato de hoy es parcial y cambia entre ejecuciones.",
         "Sirven para contrastar el relato de las noticias, no para predecir.", ""]
    res = {}
    for nombre, sim in FUENTES_YAHOO:
        try:
            d = serie_yahoo(sim)
            f1, v1 = d[-1]
            v5 = d[-6][1]
            res[sim] = (v1, v5)
            if "Rendimiento" in nombre:
                L.append(f"- {nombre}: {v1:.2f} ({f1}); hace 5 sesiones: {v5:.2f}")
            else:
                L.append(f"- {nombre}: {v1:,.2f} ({f1}); variación en 5 sesiones: {(v1 / v5 - 1) * 100:+.1f}%")
        except Exception as e:
            L.append(f"- {nombre}: no disponible ({type(e).__name__})")
    try:
        d = serie_tesoro()
        f1, v1 = d[-1]
        v5 = d[-6][1]
        res["real"] = (v1, v5)
        L.append(f"- Rendimiento real 10 años EE. UU. (Tesoro, %): {v1:.2f} ({f1}); hace 5 sesiones: {v5:.2f}")
    except Exception as e:
        L.append(f"- Rendimiento real 10 años EE. UU. (Tesoro): no disponible ({type(e).__name__})")

    L.extend(["", "### Contraste con las noticias", ""])
    oro, real = res.get("GC=F"), res.get("real")
    if oro and real:
        g = (oro[0] / oro[1] - 1) * 100
        r = real[0] - real[1]
        if r > 0 and g < 0:
            t = "El rendimiento real subió y el oro bajó: los datos son coherentes con la hipótesis de presión por tasas."
        elif r < 0 and g > 0:
            t = "El rendimiento real bajó y el oro subió: los datos son coherentes con un alivio del costo de oportunidad."
        elif r > 0 and g > 0:
            t = "El rendimiento real subió pero el oro también: otros factores (refugio, dólar, demanda) pesaron más."
        elif r < 0 and g < 0:
            t = "El rendimiento real bajó pero el oro cayó: la caída no se explica por los rendimientos reales y habría que revisar otros factores (flujos de ETF, toma de beneficios, petróleo)."
        else:
            t = "Sin un cambio claro en el rendimiento real o en el oro."
        L.append(f"- Oro: {g:+.1f}% en 5 sesiones. Rendimiento real: {r:+.2f} puntos.")
        L.append(f"- {t}")
        dx, pt = res.get("DX-Y.NYB"), res.get("CL=F")
        if dx:
            gd = (dx[0] / dx[1] - 1) * 100
            if gd < 0 and g < 0:
                td = "el dólar más débil no frenó la caída del oro"
            elif gd < 0 and g > 0:
                td = "el dólar más débil acompañó la subida del oro"
            elif gd > 0 and g < 0:
                td = "el dólar más fuerte es coherente con la caída del oro"
            elif gd > 0 and g > 0:
                td = "el oro subió pese a un dólar más fuerte"
            else:
                td = "sin cambio claro en el dólar"
            L.append(f"- Dólar (DXY): {gd:+.1f}%; {td}.")
        if pt:
            gp = (pt[0] / pt[1] - 1) * 100
            L.append(f"- Petróleo WTI: {gp:+.1f}% en 5 sesiones. Si las noticias citan precios mucho más altos, comprueba si hablan del Brent u otra fecha.")
    else:
        L.append("- No hay datos suficientes de oro y rendimiento real para contrastar.")
    L.extend(["", "Es una comparación de 5 sesiones: muestra coherencia, no causalidad ni predicción.", ""])
    return L

def main():
    if not ENTRADA.exists():
        raise SystemExit(f"No existe el archivo: {ENTRADA}")
    bruto = json.loads(ENTRADA.read_text(encoding="utf-8"))
    noticias = deduplicar(bruto)
    analisis = [(n, analizar(n)) for n in noticias]

    conteo = Counter()
    for n, res in analisis:
        for r, _ in res:
            conteo[r["nombre"]] += 1
    ruido = [n for n, res in analisis if not res and es_ruido(n)]
    sin_tema = [n for n, res in analisis if not res and not es_ruido(n)]

    L = ["# TITAN GOLD NEWS — Análisis macroeconómico v2", "",
         f"Noticias recopiladas: {len(bruto)}",
         f"Noticias únicas tras quitar duplicadas: {len(noticias)}", "",
         "## Resumen en español", ""]
    for nombre, c in conteo.most_common():
        L.append(f"- {nombre}: {c} noticias")
    L.append(f"- Sin tema identificado: {len(sin_tema)}")
    L.append(f"- Descartadas por no tratar del oro: {len(ruido)}")
    L.append("")
    if conteo:
        top = conteo.most_common(1)[0][0]
        L.append(f"El tema que más aparece en las noticias es: {top}. "
                 "Esto indica de qué se habla, no hacia dónde irá el oro.")
    L.extend(conclusion(conteo, len(noticias), len(sin_tema), len(ruido)))
    L.extend(mercado())
    L.extend(["## Detalle por noticia", ""])

    con_tema = [(n, res) for n, res in analisis if res]
    con_tema.sort(key=lambda x: (not es_ref(x[0]), -len(x[1])))
    for i, (n, res) in enumerate(con_tema, 1):
        marca = " (fuente de referencia)" if es_ref(n) else ""
        L.extend([f"### {i}. {limpio(n)}", "",
                  f"- Fuente: {n.get('fuente') or 'No identificada'}{marca}",
                  f"- Fecha: {n.get('fecha') or 'No disponible'}",
                  f"- Enlace: {n.get('enlace') or 'No disponible'}",
                  f"- Noticias similares agrupadas: {n['_copias']}", ""])
        for r, claves in res:
            L.extend([f"**Canal: {r['nombre']}**",
                      f"- Indicadores: {', '.join(claves)}",
                      f"- Mecanismo posible: {r['mecanismo']}",
                      f"- Qué verificar: {r['verificar']}",
                      f"- Favorable al oro si: {r['fav']}",
                      f"- Desfavorable si: {r['des']}",
                      f"- Mixto si: {r['mix']}", ""])
    if sin_tema:
        L.extend(["## Noticias sin tema identificado", ""])
        for n in sin_tema[:15]:
            L.append(f"- {limpio(n)}")
        L.append("")

    SALIDA.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("Análisis v2 generado.")
    print(f"Recopiladas: {len(bruto)} | Únicas: {len(noticias)}")
    print(f"Archivo: {SALIDA}")

if __name__ == "__main__":
    main()
