# -*- coding: utf-8 -*-
"""Eventos macroeconómicos, gubernamentales y geopolíticos detectados en la prensa, y señales de tipos de interés.
Los datos son titulares de prensa: NO están verificados oficialmente ni traen dato publicado/esperado/anterior."""
import hashlib
import time

import agente

TIPOS = [
    {"id": "fed", "nombre": "Reserva Federal (tipos de interés)", "consulta": "Federal Reserve FOMC interest rate decision Powell",
     "claves": ["fomc", "federal reserve", "powell", "fed minutes", "fed holds", "fed cuts", "fed raises", "rate decision"], "alto": True,
     "afecta": ["metal", "divisa", "cripto", "accion", "indice"],
     "mecanismo": "Una decisión o un cambio de tono de la Fed altera las expectativas de tipos, los rendimientos de los bonos y el dólar, que presionan o apoyan a casi todos los activos."},
    {"id": "inflacion", "nombre": "Inflación (IPC/IPP/PCE)", "consulta": "US inflation CPI PPI PCE report",
     "claves": ["cpi", "inflation", "ppi", "pce", "consumer prices", "producer prices"], "alto": True,
     "afecta": ["metal", "divisa", "cripto", "accion", "indice", "energia"],
     "mecanismo": "Una inflación distinta de la esperada cambia las expectativas de tipos de interés y, con ellas, el dólar, los bonos y los activos de riesgo."},
    {"id": "empleo", "nombre": "Empleo (nóminas, desempleo)", "consulta": "US jobs report nonfarm payrolls unemployment rate",
     "claves": ["nonfarm", "payrolls", "jobs report", "unemployment rate", "jobless claims"], "alto": True,
     "afecta": ["metal", "divisa", "accion", "indice"],
     "mecanismo": "Un mercado laboral más fuerte o más débil de lo esperado cambia las expectativas sobre la Fed y la fortaleza del dólar."},
    {"id": "actividad", "nombre": "Actividad económica (PIB, ventas, PMI)", "consulta": "GDP retail sales PMI economy data",
     "claves": ["gdp", "retail sales", "pmi", "ism manufacturing", "industrial production"], "alto": False,
     "afecta": ["energia", "accion", "indice", "divisa"],
     "mecanismo": "Los datos de actividad indican la fortaleza de la demanda y de los beneficios empresariales, y influyen en materias primas y bolsas."},
    {"id": "bancos_centrales", "nombre": "Otros bancos centrales (BCE, BoE, BoJ, PBoC)", "consulta": "ECB Bank of England Bank of Japan central bank decision",
     "claves": ["ecb", "bank of england", "boe", "bank of japan", "boj", "pboc", "central bank"], "alto": True,
     "afecta": ["divisa", "metal", "indice"],
     "mecanismo": "Las decisiones de otros bancos centrales mueven la divisa correspondiente y el dólar por diferencia de tasas."},
    {"id": "comercio", "nombre": "Aranceles, sanciones y comercio", "consulta": "tariffs trade restrictions sanctions embargo",
     "claves": ["tariff", "sanction", "trade war", "export ban", "import ban", "embargo"], "alto": True,
     "afecta": ["metal", "energia", "divisa", "accion", "indice", "cripto"],
     "mecanismo": "Las barreras comerciales y sanciones alteran cadenas de suministro, precios de materias primas y el apetito de riesgo."},
    {"id": "geopolitica", "nombre": "Conflictos y tensiones geopolíticas", "consulta": "geopolitical conflict war tensions ceasefire",
     "claves": ["war", "conflict", "missile", "attack", "ceasefire", "tensions", "invasion"], "alto": False,
     "afecta": ["metal", "energia", "indice", "cripto"],
     "mecanismo": "La tensión aumenta la demanda de refugio (oro, dólar) y puede afectar la oferta de energía."},
    {"id": "energia", "nombre": "Energía y oferta de materias primas (OPEP)", "consulta": "OPEC oil supply production cut",
     "claves": ["opec", "oil supply", "production cut", "pipeline", "refinery"], "alto": True,
     "afecta": ["energia", "divisa"],
     "mecanismo": "Cambios en la oferta o la política de producción mueven el precio del petróleo y del gas."},
    {"id": "fiscal", "nombre": "Política fiscal, elecciones y deuda soberana", "consulta": "election government budget debt ceiling sovereign debt default",
     "claves": ["election", "budget", "debt ceiling", "sovereign debt", "default", "shutdown", "fiscal"], "alto": False,
     "afecta": ["divisa", "metal", "indice", "cripto"],
     "mecanismo": "Los cambios fiscales, electorales o de riesgo de impago afectan la confianza en la divisa, los bonos y los activos de riesgo."},
]
_CACHE = {"t": 0.0, "datos": []}

def escanear(horas=24, cache_s=600, ahora_t=None):
    t = ahora_t if ahora_t is not None else time.time()
    if _CACHE["datos"] and t - _CACHE["t"] < cache_s:
        return _CACHE["datos"]
    out = []
    for tp in TIPOS:
        pseudo = {"consulta": tp["consulta"], "claves": tp["claves"], "clase": "indice", "usd": 0}
        try:
            noticias = agente.noticias_activo(pseudo, horas)
        except Exception:
            continue
        for n in noticias[:4]:
            out.append({"tipo": tp["id"], "nombre": tp["nombre"], "titulo": n["titulo"], "fuente": n["fuente"], "fecha": n["fecha"],
                        "edad_h": n["edad_h"], "enlace": n["enlace"], "alto": tp["alto"], "afecta": tp["afecta"],
                        "mecanismo": tp["mecanismo"], "estado": "informado por prensa; sin verificación oficial"})
    out.sort(key=lambda x: x["edad_h"])
    _CACHE.update(t=t, datos=out)
    return out

def para_clase(clase, eventos):
    return [e for e in eventos if clase in e["afecta"]]

def clave(e):
    return hashlib.sha1(e["enlace"].encode()).hexdigest()[:16]

def tasas():
    """Señal de expectativas de tipos (aproximación): variación diaria de los rendimientos a 13 semanas y 5 años."""
    out = []
    for nombre, sim in (("Rendimiento a 13 semanas (^IRX)", "^IRX"), ("Rendimiento a 5 años (^FVX)", "^FVX")):
        try:
            c = [x["c"] for x in agente.barras(sim, "6mo", "1d")]
            out.append({"nombre": nombre, "nivel": c[-1], "cambio_pb": (c[-1] - c[-2]) * 100})
        except Exception:
            continue
    return out

def texto_alerta(e, afectados, zona):
    from datetime import datetime
    f = datetime.fromisoformat(e["fecha"]).astimezone(zona)
    L = ["TITAN QUANT — ACONTECIMIENTO MACROECONÓMICO", "", f"Acontecimiento: {e['nombre']}.", f"Titular: {e['titulo']}",
         f"Fuente: {e['fuente'] or 'prensa'} · {f.strftime('%d/%m %H:%M')} ({zona.key})",
         "Dato anterior / consenso / publicado: no disponible (esta versión no tiene un calendario económico verificado).", "",
         f"Posible mecanismo de impacto: {e['mecanismo']}",
         "Activos de tu lista potencialmente afectados: " + (", ".join(f"{n} ({p:+.2f}% en 1 h)" for n, p in afectados) if afectados else "ninguno"),
         "", f"Estado de la información: {e['estado']}.",
         "Revisa los escenarios de esos activos antes de actuar; la reacción real depende de las expectativas previas y del posicionamiento."]
    return "\n".join(L)
