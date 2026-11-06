import json
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import telegram_bot as tb
import agente
import activos as act
import guiado
import informe
import zonas
import escenarios
import monitor

MAX_ACTIVOS = 8

ESTADO = tb.BASE / ".estado_bot.json"
HORAS = ["08:00", "16:00", "20:00", "21:00"]
ZONAS = [
    ("República Dominicana", "America/Santo_Domingo"),
    ("Colombia / Perú / Ecuador", "America/Bogota"),
    ("México", "America/Mexico_City"),
    ("Venezuela", "America/Caracas"),
    ("Argentina", "America/Argentina/Buenos_Aires"),
    ("Chile", "America/Santiago"),
    ("España", "Europe/Madrid"),
]

def cargar():
    try:
        e = json.loads(ESTADO.read_text())
    except Exception:
        e = {}
    e.setdefault("horas", [])
    e.setdefault("activo", False)
    e.setdefault("zona", None)
    e.setdefault("enviadas", {})
    e.setdefault("seleccion", [])
    e.setdefault("personalizados", [])
    e.setdefault("monitor", False)
    e.setdefault("frecuencia_min", 5)
    return e

def guardar(e):
    ESTADO.write_text(json.dumps(e))

def menu(e):
    return {"inline_keyboard": [
        [{"text": "🎯 Activo analizar", "callback_data": "ga"}],
        [{"text": "📊 Oro y macro", "callback_data": "analizar"}, {"text": "🧭 Sesgo del día", "callback_data": "sesgo"}],
        [{"text": "🕐 Sesiones", "callback_data": "resumen"}, {"text": "📈 Precisión", "callback_data": "prec"}],
        [{"text": "📌 Activos automáticos", "callback_data": "act"}, {"text": "⏰ Horas automáticas", "callback_data": "horas"}],
        [{"text": "🌎 Zona horaria", "callback_data": "zona"}, {"text": "📋 Estado", "callback_data": "estado"}],
        [{"text": "🔴 Apagar bot" if e["activo"] else "🟢 Prender bot", "callback_data": "toggle"}],
    ]}

def menu_horas(e):
    filas, fila = [], []
    for h in HORAS:
        fila.append({"text": ("✅ " if h in e["horas"] else "") + h, "callback_data": "h:" + h})
        if len(fila) == 2:
            filas.append(fila)
            fila = []
    if fila:
        filas.append(fila)
    filas.append([{"text": "⬅️ Volver", "callback_data": "menu"}])
    return {"inline_keyboard": filas}

def texto_estado(e):
    horas = ", ".join(sorted(e["horas"])) or "ninguna"
    return ("Estado del bot\n"
            f"• Envíos automáticos: {'prendidos' if e['activo'] else 'apagados'}\n"
            f"• Horas elegidas: {horas}\n"
            f"• Zona horaria: {e['zona'] or 'sin elegir'}\n"
            f"• Activos seguidos: {', '.join(e['seleccion']) or 'ninguno'}")

import analisis_macro_v2 as am
from datetime import timedelta, timezone

SESIONES = [
    ("Sídney", "🇦🇺", "Australia/Sydney", (10, 0), 6.0),
    ("Tokio", "🇯🇵", "Asia/Tokyo", (9, 0), 6.5),
    ("Hong Kong", "🇭🇰", "Asia/Hong_Kong", (9, 30), 6.5),
    ("Londres", "🇬🇧", "Europe/London", (8, 0), 8.5),
    ("Nueva York", "🇺🇸", "America/New_York", (8, 0), 9.0),
]
ACTIVOS = [("Oro", "GC=F"), ("Dólar", "DX-Y.NYB"), ("Petróleo", "CL=F")]

def zona_de(e):
    return ZoneInfo(e["zona"] or "America/Santo_Domingo")

def ventana(tz, hm, horas, ahora):
    loc = ahora.astimezone(ZoneInfo(tz))
    ini = loc.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)
    if ini > loc:
        ini = ini - timedelta(days=1)
    while ini.weekday() >= 5:
        ini = ini - timedelta(days=1)
    return ini, ini + timedelta(hours=horas), loc

def intradia(simbolo):
    url = "https://query1.finance.yahoo.com/v8/finance/chart/" + simbolo + "?range=5d&interval=60m"
    r = json.loads(am.descargar(url))["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    return [(t, o, c) for t, o, c in zip(r["timestamp"], q["open"], q["close"])
            if o is not None and c is not None]

def variacion(datos, ini, fin, ahora):
    a = int(ini.timestamp())
    b = int(min(fin, ahora).timestamp())
    barras = [x for x in datos if a <= x[0] < b]
    if not barras:
        return None
    return (barras[-1][2] / barras[0][1] - 1) * 100

def rango_txt(ini, fin, zona):
    hoy = datetime.now(zona).date()
    dia = ini.astimezone(zona).date()
    if dia == hoy:
        etq = "hoy"
    elif dia == hoy - timedelta(days=1):
        etq = "ayer"
    else:
        etq = dia.strftime("%d/%m")
    return ini.astimezone(zona).strftime("%H:%M") + "–" + fin.astimezone(zona).strftime("%H:%M") + " (" + etq + ")"

def sesiones_texto(e, solo=None):
    zona = zona_de(e)
    ahora = datetime.now(timezone.utc)
    datos = {}
    for n, sim in ACTIVOS:
        try:
            datos[n] = intradia(sim)
        except Exception:
            datos[n] = None
    L = ["🌍 Sesiones del mercado", "Horas en: " + (e["zona"] or "America/Santo_Domingo"), ""]
    for nombre, bandera, tz, hm, h in SESIONES:
        if solo and solo != "todas" and solo != nombre:
            continue
        ini, fin, loc = ventana(tz, hm, h, ahora)
        abierta = ini <= loc < fin and loc.weekday() < 5
        mov = []
        vacios = 0
        for n, _ in ACTIVOS:
            v = variacion(datos[n], ini, fin, ahora) if datos[n] else None
            if v is None:
                vacios += 1
            mov.append(n + " " + ("s/d" if v is None else f"{v:+.2f}%"))
        L.append(f"{bandera} {nombre} · {rango_txt(ini, fin, zona)} · " + ("abierta ahora" if abierta else "cerrada"))
        if abierta and vacios == len(ACTIVOS):
            L.append("   Recién abierta: todavía no hay datos por hora")
        else:
            L.append("   " + " · ".join(mov))
    L.append("")
    L.append("Cada variación es el movimiento de los futuros durante la ventana de esa sesión (datos por hora). Las sesiones se solapan y los horarios son aproximados.")
    return "\n".join(L)

def menu_sesiones(e):
    zona = zona_de(e)
    ahora = datetime.now(timezone.utc)
    filas = []
    for nombre, bandera, tz, hm, h in SESIONES:
        ini, fin, _ = ventana(tz, hm, h, ahora)
        filas.append([{"text": f"{bandera} {nombre} · {rango_txt(ini, fin, zona)}", "callback_data": "s:" + nombre}])
    filas.append([{"text": "🌍 Ver todas", "callback_data": "s:todas"}])
    filas.append([{"text": "⬅️ Volver", "callback_data": "menu"}])
    return {"inline_keyboard": filas}

def etiqueta(p):
    if p > 0:
        return "a favor del oro"
    if p < 0:
        return "en contra del oro"
    return "neutral"

def sesgo_texto():
    L = ["🧭 Sesgo del día para el oro", ""]
    puntos, validos = 0, 0
    try:
        d = am.serie_tesoro()
        r = d[-1][1] - d[-6][1]
        p = 1 if r <= -0.05 else (-1 if r >= 0.05 else 0)
        puntos += p
        validos += 1
        L.append(f"• Rendimiento real 10 años: {r:+.2f} puntos en 5 sesiones → {etiqueta(p)}")
    except Exception:
        L.append("• Rendimiento real: no disponible")
    try:
        d = am.serie_yahoo("DX-Y.NYB")
        g = (d[-1][1] / d[-6][1] - 1) * 100
        p = 1 if g <= -0.3 else (-1 if g >= 0.3 else 0)
        puntos += p
        validos += 1
        L.append(f"• Dólar (DXY): {g:+.1f}% en 5 sesiones → {etiqueta(p)}")
    except Exception:
        L.append("• Dólar: no disponible")
    try:
        d = am.serie_yahoo("CL=F")
        g = (d[-1][1] / d[-6][1] - 1) * 100
        L.append(f"• Petróleo WTI: {g:+.1f}% en 5 sesiones (informativo: puede apoyar al oro por geopolítica o presionarlo por inflación y tasas; no puntúa)")
    except Exception:
        pass
    if validos < 2:
        v = "sin datos suficientes para dar un sesgo"
    elif puntos >= 2:
        v = "favorable al oro (señales alineadas)"
    elif puntos == 1:
        v = "ligeramente favorable al oro"
    elif puntos == 0:
        v = "mixto o neutral"
    elif puntos == -1:
        v = "ligeramente desfavorable al oro"
    else:
        v = "desfavorable al oro (señales alineadas)"
    L += ["", "Sesgo: " + v, "",
          "⚠️ Esto NO es una probabilidad ni una predicción: solo cuenta cuántas señales macro apuntan en cada dirección.",
          "Las noticias todavía no puntúan porque el programa aún no clasifica cada titular como favorable o adverso."]
    return "\n".join(L)

def menu_categorias(e):
    filas = []
    for i, cat in enumerate(act.CATEGORIAS):
        lista = act.por_categoria(cat, e["personalizados"])
        n = sum(a["simbolo"] in e["seleccion"] for a in lista)
        filas.append([{"text": f"{cat} ({n} marcados)", "callback_data": f"cat:{i}"}])
    filas.append([{"text": "⬅️ Volver", "callback_data": "menu"}])
    return {"inline_keyboard": filas}

def menu_activos(ci, e):
    filas, fila = [], []
    for a in act.por_categoria(act.CATEGORIAS[ci], e["personalizados"]):
        fila.append({"text": ("✅ " if a["simbolo"] in e["seleccion"] else "") + a["nombre"],
                     "callback_data": f"a:{ci}:{a['simbolo']}"})
        if len(fila) == 2:
            filas.append(fila)
            fila = []
    if fila:
        filas.append(fila)
    filas.append([{"text": "⬅️ Categorías", "callback_data": "act"}, {"text": "🏠 Menú", "callback_data": "menu"}])
    return {"inline_keyboard": filas}

def enviar_activos(chat, e):
    sel = [s for s in e["seleccion"] if act.buscar(s, e["personalizados"])]
    if not sel:
        tb.enviar(chat, "Aún no has elegido activos. Toca 📌 Mis activos.", tb.MENU)
        return
    tb.enviar(chat, f"Analizando {len(sel)} activo(s): noticias, técnico y horas de más movimiento. Puede tardar un par de minutos...")
    zona = zona_de(e)
    for s in sel[:MAX_ACTIVOS]:
        try:
            tb.enviar(chat, agente.texto(agente.analizar(act.buscar(s, e["personalizados"]), zona), zona))
        except Exception as ex:
            tb.enviar(chat, f"No pude analizar {s}: {type(ex).__name__}")
    tb.enviar(chat, "Listo. Cada hipótesis queda guardada y se verifica sola a las 4 h (botón 🎯 Precisión).", tb.MENU)

def agregar_activo(chat, e, crudo):
    partes = crudo.split()
    s = partes[1].upper() if len(partes) > 1 else ""
    if not re.fullmatch(r"[A-Z0-9^=.\-]{1,20}", s):
        tb.enviar(chat, "Uso: /agregar SIMBOLO (símbolo de Yahoo Finance). Ejemplos: /agregar AMD  o  /agregar DOGE-USD")
        return
    if act.buscar(s, e["personalizados"]) is None:
        try:
            agente.validar_simbolo(s)
        except Exception:
            tb.enviar(chat, f"No encontré datos de {s} en Yahoo Finance. Revisa el símbolo.")
            return
        e["personalizados"].append(s)
    if s not in e["seleccion"]:
        if len(e["seleccion"]) >= MAX_ACTIVOS:
            tb.enviar(chat, f"Máximo {MAX_ACTIVOS} activos marcados. Quita alguno en 📌 Mis activos.")
            return
        e["seleccion"].append(s)
    guardar(e)
    tb.enviar(chat, f"Añadido y marcado: {s}.", tb.MENU)

_ULTIMO_ACTIVO = {}

def menu_flujo_categorias():
    filas = [[{"text": c, "callback_data": f"gc:{i}"}] for i, c in enumerate(act.CATEGORIAS)]
    filas.append([{"text": "🏠 Menú", "callback_data": "menu"}])
    return {"inline_keyboard": filas}

def menu_flujo_activos(ci, e):
    filas, fila = [], []
    for a in act.por_categoria(act.CATEGORIAS[ci], e["personalizados"]):
        fila.append({"text": a["nombre"], "callback_data": f"gp:{a['simbolo']}"})
        if len(fila) == 2:
            filas.append(fila)
            fila = []
    if fila:
        filas.append(fila)
    filas.append([{"text": "⬅️ Categorías", "callback_data": "ga"}, {"text": "🏠 Menú", "callback_data": "menu"}])
    return {"inline_keyboard": filas}

def zona_flujo(e, idx):
    if idx == "g":
        return e["zona"] or "America/Santo_Domingo"
    if idx.isdigit():
        return ZONAS[int(idx)][1]
    return idx if zonas.valida(idx) else (e["zona"] or "America/Santo_Domingo")

def menu_flujo_horas(sim, idx):
    filas = [[{"text": "⏱ Próxima hora", "callback_data": f"gh:{sim}:{idx}:N"}]]
    fila = []
    for h in range(24):
        fila.append({"text": f"{h:02d}:00", "callback_data": f"gh:{sim}:{idx}:{h:02d}"})
        if len(fila) == 4:
            filas.append(fila)
            fila = []
    filas.append([{"text": "⬅️ Zona", "callback_data": f"gp:{sim}"}, {"text": "🏠 Menú", "callback_data": "menu"}])
    return {"inline_keyboard": filas}

def menu_flujo_final(sim, idx):
    return {"inline_keyboard": [
        [{"text": "🕐 Otra hora", "callback_data": f"gz:{sim}:{idx}"}, {"text": "🔁 Otro activo", "callback_data": "ga"}],
        [{"text": "📄 Análisis completo", "callback_data": f"gd:{sim}"}],
        [{"text": "🏠 Menú", "callback_data": "menu"}]]}

def flujo_resumen(chat, e, sim, idx, h):
    a = act.buscar(sim, e["personalizados"])
    if not a:
        return
    zona = ZoneInfo(zona_flujo(e, idx))
    tb.enviar(chat, f"Analizando {a['nombre']} para " + ("la próxima hora" if h == "N" else f"las {h}:00") + f" ({zona.key})...")
    base = guiado.hora_objetivo(zona, None if h == "N" else int(h), proxima=(h == "N"))
    r, resumen = guiado.pronosticar(a, zona, base)
    _ULTIMO_ACTIVO[sim] = agente.texto(r, zona)
    tb.enviar(chat, resumen, menu_flujo_final(sim, idx))

_ULT_EVAL = [0.0]

def evaluar_si_toca():
    if time.time() - _ULT_EVAL[0] < 900:
        return
    _ULT_EVAL[0] = time.time()
    agente.evaluar_pendientes()
    guiado.evaluar_horas()

BTN_ANALIZAR = "🎯 Analizar activo"
BTN_APAGAR, BTN_PRENDER = "🔴 Apagar bot", "🟢 Prender bot"
CMD = {"/analizar": "ga", "/oro": "analizar", "/sesgo": "sesgo", "/sesiones": "resumen", "/precision": "prec",
       "/horas": "horas", "/zona": "zona", "/estado": "estado", "/activos": "act", "/escenarios": "esc"}
COMANDOS = [
    {"command": "analizar", "description": "Analizar un activo paso a paso"},
    {"command": "oro", "description": "Resumen de oro y macro"},
    {"command": "sesgo", "description": "Sesgo del día para el oro"},
    {"command": "sesiones", "description": "Movimiento por sesión de mercado"},
    {"command": "precision", "description": "Acierto del bot"},
    {"command": "horas", "description": "Horas de envío automático"},
    {"command": "zona", "description": "Cambiar zona horaria"},
    {"command": "activos", "description": "Activos de los resúmenes automáticos"},
    {"command": "estado", "description": "Estado del bot"},
    {"command": "vigilar", "description": "Vigilancia con alertas de escenarios"},
    {"command": "escenarios", "description": "Escenarios activos"},
    {"command": "riesgo", "description": "Capital y riesgo por operación"},
    {"command": "menu", "description": "Más opciones"},
]

def refrescar_menus(e):
    tb.MENU = None
    tb.MENU_RES = {"inline_keyboard": [[{"text": "📄 Ver detalle completo", "callback_data": "detalle"}]]}

def teclado(e):
    return {"keyboard": [[{"text": BTN_ANALIZAR}], [{"text": BTN_APAGAR if e["activo"] else BTN_PRENDER}]],
            "resize_keyboard": True, "is_persistent": True}

def paso(chat, mid, texto, markup):
    """Cambia el mismo mensaje (se borran los botones anteriores y aparece la siguiente pregunta)."""
    if mid:
        try:
            tb.editar(chat, mid, texto, markup)
            return
        except Exception:
            pass
    if markup is not None and not markup.get("inline_keyboard", True):
        markup = None
    tb.enviar(chat, texto, markup)

def wiz_final(chat, mid, e, sim, idx, h):
    a = act.buscar(sim, e["personalizados"])
    if not a:
        return
    zona = ZoneInfo(zona_flujo(e, idx))
    cuando = "la próxima hora" if h == "N" else f"las {h}:00"
    paso(chat, mid, f"✅ {a['nombre']} · {zona.key} · {cuando}\nGenerando tu hoja de análisis (puede tardar 1 o 2 minutos)...",
         {"inline_keyboard": []})
    base = guiado.hora_objetivo(zona, None if h == "N" else int(h), proxima=(h == "N"))
    d = informe.reunir(a, zona, base, SESIONES)
    if d["error"]:
        tb.enviar(chat, informe.resumen_chat(d), menu_flujo_final(sim, idx))
        return
    _ULTIMO_ACTIVO[sim] = agente.texto(d["r"], zona)
    try:
        nombre = "TITAN_" + re.sub(r"[^A-Za-z0-9]+", "_", sim).strip("_") + "_" + datetime.now(zona).strftime("%Y%m%d_%H%M") + ".pdf"
        tb.enviar_documento(chat, informe.pdf(d), nombre, f"Hoja de análisis · {a['nombre']} · {base.hour:02d}:00 ({zona.key})")
    except Exception as ex:
        tb.enviar(chat, f"No pude generar el PDF ({type(ex).__name__}); te dejo el resumen.")
    tb.enviar(chat, informe.resumen_chat(d), menu_flujo_final(sim, idx))

def menu_zonas():
    filas = [[{"text": n, "callback_data": "z:" + tz}] for n, tz in ZONAS]
    filas.append([{"text": "🌍 Todas las zonas del mundo", "callback_data": "zR"}])
    filas.append([{"text": "⬅️ Volver", "callback_data": "menu"}])
    return {"inline_keyboard": filas}

def menu_flujo_zonas(sim, e):
    filas = []
    if e["zona"]:
        filas.append([{"text": "📍 Mi zona: " + e["zona"], "callback_data": f"gz:{sim}:g"}])
    for i, (n, tz) in enumerate(ZONAS):
        filas.append([{"text": n, "callback_data": f"gz:{sim}:{i}"}])
    filas.append([{"text": "🌍 Otra zona (todo el mundo)", "callback_data": f"gR:{sim}"}])
    filas.append([{"text": "⬅️ Categorías", "callback_data": "ga"}])
    return {"inline_keyboard": filas}

def menu_regiones(sim=None):
    filas, fila = [], []
    for r in zonas.REGIONES:
        fila.append({"text": r, "callback_data": f"gr:{sim}:{r}:0" if sim else f"zr:{r}:0"})
        if len(fila) == 2:
            filas.append(fila)
            fila = []
    if fila:
        filas.append(fila)
    filas.append([{"text": "UTC", "callback_data": f"gz:{sim}:UTC" if sim else "z:UTC"}])
    filas.append([{"text": "⬅️ Atrás", "callback_data": f"gp:{sim}" if sim else "zona"}])
    return {"inline_keyboard": filas}

def menu_ciudades(region, pagina, sim=None):
    zs = zonas.por_region(region)
    por = 10
    n = max(1, (len(zs) + por - 1) // por)
    pagina = max(0, min(pagina, n - 1))
    filas, fila = [], []
    for tz in zs[pagina * por:(pagina + 1) * por]:
        fila.append({"text": zonas.etiqueta(tz), "callback_data": f"gz:{sim}:{tz}" if sim else f"z:{tz}"})
        if len(fila) == 2:
            filas.append(fila)
            fila = []
    if fila:
        filas.append(fila)
    pref = f"gr:{sim}:{region}" if sim else f"zr:{region}"
    nav = []
    if pagina > 0:
        nav.append({"text": "◀️", "callback_data": f"{pref}:{pagina - 1}"})
    nav.append({"text": f"{pagina + 1}/{n}", "callback_data": "noop"})
    if pagina < n - 1:
        nav.append({"text": "▶️", "callback_data": f"{pref}:{pagina + 1}"})
    filas.append(nav)
    filas.append([{"text": "⬅️ Regiones", "callback_data": f"gR:{sim}" if sim else "zR"}])
    return {"inline_keyboard": filas}

def texto_escenarios(e):
    c = escenarios.conectar()
    try:
        nombres = {s: (act.buscar(s, e["personalizados"]) or {"nombre": s})["nombre"] for s in e["seleccion"]}
        estado = (f"Vigilancia: activa cada {e['frecuencia_min']} min." if e["monitor"] else "Vigilancia: apagada (usa /vigilar).")
        return estado + "\n\n" + escenarios.resumen_activos(c, nombres) + "\n\n" + escenarios.estadisticas(c)["texto"]
    finally:
        c.close()

_ULT_VIGILA = [0.0]

def vigilar_si_toca():
    e = cargar()
    if not (e["monitor"] and e["seleccion"]):
        return
    if time.time() - _ULT_VIGILA[0] < e["frecuencia_min"] * 60:
        return
    _ULT_VIGILA[0] = time.time()
    chat = tb.CHAT_FILE.read_text().strip()
    monitor.tick(e, lambda t: tb.enviar(chat, t), zona_de(e))

def comando_vigilar(chat, e, arg):
    arg = arg.strip().lower()
    if arg in ("apagar", "off", "no"):
        e["monitor"] = False
        guardar(e)
        tb.enviar(chat, "👁 Vigilancia apagada. Los escenarios guardados no se actualizan hasta que la vuelvas a activar.")
        return
    if not e["seleccion"]:
        tb.enviar(chat, "Primero marca los activos que quieres vigilar con /activos (hasta 8).")
        return
    if arg.isdigit():
        e["frecuencia_min"] = max(1, min(60, int(arg)))
    e["monitor"] = True
    guardar(e)
    _ULT_VIGILA[0] = 0.0
    tb.enviar(chat, f"👁 Vigilancia activada: {len(e['seleccion'])} activo(s) cada {e['frecuencia_min']} min ({', '.join(e['seleccion'])}).\n"
              "Recibirás alertas por Telegram cuando un escenario cambie de estado (aproximación, ruptura, confirmación, invalidación, objetivo o stop). "
              "TITAN no ejecuta órdenes. Ver escenarios: /escenarios · apagar: /vigilar apagar")

def comando_riesgo(chat, e, arg):
    c = escenarios.conectar()
    try:
        partes = arg.replace(",", "").split()
        if not partes:
            cap, pct = escenarios.config_riesgo(c)
            tb.enviar(chat, (f"Riesgo configurado: {pct:.1f}% de {cap:,.2f} por operación." if cap else "Aún no has configurado tu capital.") +
                      "\nUso: /riesgo CAPITAL PORCENTAJE (por ejemplo /riesgo 5000 1). El máximo permitido es " + f"{escenarios.RIESGO_MAX_PCT:.0f}%.")
            return
        try:
            escenarios.guardar_config_riesgo(c, float(partes[0]), float(partes[1]) if len(partes) > 1 else 1.0)
        except ValueError as ex:
            tb.enviar(chat, f"No se guardó: {ex}")
            return
        cap, pct = escenarios.config_riesgo(c)
        tb.enviar(chat, f"✅ Capital de referencia {cap:,.2f} y riesgo {pct:.1f}% por operación ({cap * pct / 100:,.2f}). "
                  "Se usa para calcular el tamaño de posición hipotético en las hojas y alertas.")
    finally:
        c.close()

def accion(chat, e, d, mid=None):
    if d == "analizar":
        tb.analizar(chat)
        tb.enviar(chat, sesiones_texto(e))
    elif d == "detalle":
        for parte in tb.partir(tb.ULTIMO or "Aún no hay análisis. Usa /oro."):
            tb.enviar(chat, parte)
    elif d == "menu":
        tb.enviar(chat, "Más opciones:", menu(e))
    elif d == "estado":
        tb.enviar(chat, texto_estado(e))
    elif d == "resumen":
        tb.enviar(chat, "¿Qué sesión quieres ver? Horas en " + (e["zona"] or "America/Santo_Domingo") + ":", menu_sesiones(e))
    elif d == "horas":
        paso(chat, mid, "Marca las horas en las que quieres recibir el resumen automático (toca para marcar o quitar):", menu_horas(e))
    elif d.startswith("s:"):
        tb.enviar(chat, "Consultando el mercado...")
        tb.enviar(chat, sesiones_texto(e, d[2:]), menu_sesiones(e))
    elif d == "sesgo":
        tb.enviar(chat, "Calculando el sesgo...")
        tb.enviar(chat, sesgo_texto())
    elif d.startswith("h:"):
        h = d[2:]
        if h in e["horas"]:
            e["horas"].remove(h)
        elif h in HORAS:
            e["horas"].append(h)
        guardar(e)
        paso(chat, mid, "Horas elegidas: " + (", ".join(sorted(e["horas"])) or "ninguna") + "\nToca para marcar o quitar:", menu_horas(e))
    elif d == "zona":
        paso(chat, mid, "¿En qué zona horaria estás?", menu_zonas())
    elif d.startswith("z:"):
        tz = d[2:]
        try:
            ZoneInfo(tz)
        except Exception:
            tb.enviar(chat, "No pude cargar esa zona horaria. Instala tzdata y reintenta.")
            return
        e["zona"] = tz
        guardar(e)
        paso(chat, mid, "✅ Zona horaria guardada: " + tz, {"inline_keyboard": []})
    elif d == "act":
        paso(chat, mid, "Activos para tus resúmenes automáticos (marca los que quieras). Para otro activo escribe /agregar SIMBOLO:", menu_categorias(e))
    elif d.startswith("cat:"):
        ci = int(d[4:])
        paso(chat, mid, "Toca para marcar o quitar (" + act.CATEGORIAS[ci] + "):", menu_activos(ci, e))
    elif d.startswith("a:"):
        _, ci, sim = d.split(":", 2)
        if sim in e["seleccion"]:
            e["seleccion"].remove(sim)
        elif len(e["seleccion"]) >= MAX_ACTIVOS:
            tb.enviar(chat, f"Máximo {MAX_ACTIVOS} activos marcados. Quita alguno primero.", menu_activos(int(ci), e))
            return
        elif act.buscar(sim, e["personalizados"]):
            e["seleccion"].append(sim)
        guardar(e)
        paso(chat, mid, "Marcados: " + (", ".join(e["seleccion"]) or "ninguno"), menu_activos(int(ci), e))
    elif d == "mis":
        enviar_activos(chat, e)
    elif d == "prec":
        tb.enviar(chat, agente.texto_precision() + "\n\n" + guiado.texto_precision_horas())
    elif d == "ga":
        paso(chat, mid, "Paso 1 de 4 · ¿Qué quieres analizar? Elige la categoría:", menu_flujo_categorias())
    elif d.startswith("gc:"):
        ci = int(d[3:])
        if not act.por_categoria(act.CATEGORIAS[ci], e["personalizados"]):
            paso(chat, mid, "Aún no tienes activos personalizados. Escribe /agregar SIMBOLO (ej. /agregar AMD).", menu_flujo_categorias())
        else:
            paso(chat, mid, "Paso 2 de 4 · ¿Cuál activo? (" + act.CATEGORIAS[ci] + ")", menu_flujo_activos(ci, e))
    elif d.startswith("gp:"):
        sim = d[3:]
        a = act.buscar(sim, e["personalizados"])
        if a:
            paso(chat, mid, f"Paso 3 de 4 · {a['nombre']}: ¿en qué zona horaria quieres analizarlo?", menu_flujo_zonas(sim, e))
    elif d.startswith("gz:"):
        _, sim, idx = d.split(":", 2)
        paso(chat, mid, "Paso 4 de 4 · ¿Para qué hora quieres saber qué podría pasar? (hora de " + zona_flujo(e, idx) + ")", menu_flujo_horas(sim, idx))
    elif d.startswith("gh:"):
        _, sim, idx, h = d.split(":", 3)
        wiz_final(chat, mid, e, sim, idx, h)
    elif d.startswith("gd:"):
        sim = d[3:]
        for parte in tb.partir(_ULTIMO_ACTIVO.get(sim) or "Aún no hay análisis de ese activo."):
            tb.enviar(chat, parte)
    elif d == "noop":
        pass
    elif d == "zR":
        paso(chat, mid, "🌍 Elige la región de tu zona horaria:", menu_regiones())
    elif d.startswith("zr:"):
        _, region, pg = d.split(":", 2)
        paso(chat, mid, f"{region}: elige tu zona horaria", menu_ciudades(region, int(pg)))
    elif d.startswith("gR:"):
        paso(chat, mid, "🌍 Elige la región:", menu_regiones(d[3:]))
    elif d.startswith("gr:"):
        _, sim, region, pg = d.split(":", 3)
        paso(chat, mid, f"{region}: elige la zona horaria", menu_ciudades(region, int(pg), sim))
    elif d == "esc":
        tb.enviar(chat, texto_escenarios(e))
    elif d == "toggle":
        if not e["zona"]:
            tb.enviar(chat, "Primero elige tu zona horaria:", menu_zonas())
        elif not e["horas"]:
            tb.enviar(chat, "Primero marca al menos una hora:", menu_horas(e))
        else:
            e["activo"] = not e["activo"]
            guardar(e)
            tb.enviar(chat, "Envíos automáticos " + ("prendidos. " if e["activo"] else "apagados. ") + texto_estado(e), teclado(e))

def manejar(u):
    e = cargar()
    refrescar_menus(e)
    if "message" in u:
        chat = u["message"]["chat"]["id"]
        if tb.autorizado(chat):
            crudo = (u["message"].get("text") or "").strip()
            txt = crudo.lower().split("@")[0] if crudo.startswith("/") else crudo.lower()
            if txt.startswith("/agregar"):
                agregar_activo(chat, e, crudo)
            elif txt in ("/start", "start"):
                tb.enviar(chat, "TITAN GOLD NEWS listo. Toca 🎯 Analizar activo para empezar. Más opciones: /menu", teclado(e))
            elif txt in ("/menu", "menu", "menú"):
                tb.enviar(chat, "Más opciones:", menu(e))
            elif crudo == BTN_ANALIZAR:
                accion(chat, e, "ga", None)
            elif crudo in (BTN_APAGAR, BTN_PRENDER):
                accion(chat, e, "toggle", None)
            elif txt.startswith("/zona ") and len(crudo.split()) > 1:
                res = zonas.buscar(crudo.split(None, 1)[1])
                if res:
                    tb.enviar(chat, "Elige tu zona horaria:", {"inline_keyboard": [[{"text": zonas.etiqueta(t), "callback_data": "z:" + t}] for t in res]})
                else:
                    tb.enviar(chat, "No encontré esa zona. Prueba con una ciudad o país (ej. /zona Madrid, /zona Tokio) o usa /zona para ver todas.")
            elif txt.startswith("/vigilar"):
                comando_vigilar(chat, e, crudo[8:])
            elif txt.startswith("/riesgo"):
                comando_riesgo(chat, e, crudo[7:])
            elif txt in CMD:
                accion(chat, e, CMD[txt], None)
            else:
                tb.enviar(chat, "Usa los botones de abajo o escribe /menu para más opciones.")
        return
    cb = u.get("callback_query")
    if not cb:
        return
    chat = cb["message"]["chat"]["id"]
    tb.api("answerCallbackQuery", callback_query_id=cb["id"])
    if not tb.autorizado(chat):
        return
    accion(chat, e, cb["data"], cb["message"].get("message_id"))

def revisar_horario():
    e = cargar()
    if not (e["activo"] and e["zona"] and e["horas"]):
        return
    ahora = datetime.now(ZoneInfo(e["zona"]))
    for h in e["horas"]:
        hh, mm = h.split(":")
        prog = ahora.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        retraso = (ahora - prog).total_seconds()
        clave = prog.strftime("%Y-%m-%d ") + h
        if 0 <= retraso < 600 and clave not in e["enviadas"]:
            e["enviadas"] = {clave: 1}
            guardar(e)
            refrescar_menus(e)
            chat = tb.CHAT_FILE.read_text().strip()
            tb.enviar(chat, f"⏰ Resumen programado de las {h}")
            tb.analizar(chat)
            tb.enviar(chat, sesiones_texto(e))
            if e["seleccion"]:
                enviar_activos(chat, e)
            if e["monitor"]:
                tb.enviar(chat, texto_escenarios(e))
            return

def main():
    print("Bot TITAN en marcha. Ctrl+C para detener.")
    try:
        tb.api("setMyCommands", commands=COMANDOS)
    except Exception:
        pass
    offset = None
    while True:
        try:
            revisar_horario()
            evaluar_si_toca()
            vigilar_si_toca()
            params = {"timeout": 25}
            if offset:
                params["offset"] = offset
            for u in tb.api("getUpdates", **params)["result"]:
                offset = u["update_id"] + 1
                manejar(u)
        except Exception as ex:
            print("Error:", type(ex).__name__)
            time.sleep(5)

if __name__ == "__main__":
    main()
