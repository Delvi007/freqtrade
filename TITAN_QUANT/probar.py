#!/usr/bin/env python3
"""Autoprueba de TITAN GOLD NEWS. Funciona SIN internet y NO toca tus archivos reales:
trabaja en una copia temporal con un token falso. Uso:  python3 probar.py"""
import json, os, py_compile, shutil, subprocess, sys, tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

AQUI = Path(__file__).resolve().parent
res = []

def chequea(nombre, ok, detalle=""):
    res.append(bool(ok))
    print(("  OK     " if ok else "  FALLA  ") + nombre + ("" if ok or not detalle else "  → " + str(detalle)[:300]))

def entorno(modo):
    e = dict(os.environ)
    e["TITAN_FIXTURES"] = modo
    e["PYTHONPATH"] = str(AQUI / "pruebas") + os.pathsep + e.get("PYTHONPATH", "")
    return e

tmp = Path(tempfile.mkdtemp(prefix="titan_prueba_"))
trabajo = tmp / "TITAN"
shutil.copytree(AQUI, trabajo, ignore=shutil.ignore_patterns(
    "__pycache__", "archivo_historico", "registros_ejecucion", "*.db", ".telegram*", ".estado_bot.json",
    "noticias_*", "informe_*", "analisis_macro_v2.md", "*.bak"))
(trabajo / ".telegram_token").write_text("123456:TOKEN_FALSO_SOLO_PRUEBAS")
(trabajo / ".telegram_chat").write_text("123")

def pipeline(modo):
    return subprocess.run([sys.executable, "pipeline_titan.py"], cwd=trabajo, env=entorno(modo),
                          capture_output=True, text=True, timeout=180)

print("\n[1] Sintaxis de todos los módulos")
for f in sorted(trabajo.glob("*.py")):
    try:
        py_compile.compile(str(f), doraise=True); ok, d = True, ""
    except Exception as e:
        ok, d = False, e
    chequea(f.name, ok, d)

print("\n[2] Pipeline completo con internet simulado")
r = pipeline("ok")
chequea("pipeline termina con código 0", r.returncode == 0, (r.stdout + r.stderr)[-400:])
j = trabajo / "noticias_recopiladas.json"
n = len(json.loads(j.read_text(encoding="utf-8"))) if j.exists() else 0
chequea("noticias_recopiladas.json con noticias", n > 0, f"{n} noticias")
md = (trabajo / "analisis_macro_v2.md")
txt = md.read_text(encoding="utf-8") if md.exists() else ""
chequea("informe macro con datos de mercado", "## Datos de mercado" in txt and "no disponible" not in txt.split("## Datos de mercado")[-1][:900], txt[-300:])
antes = j.read_bytes()

print("\n[3] Sin internet: no se debe perder nada")
r = pipeline("caida")
chequea("pipeline se detiene con error (código 1)", r.returncode == 1, r.returncode)
chequea("noticias_recopiladas.json intacto", j.read_bytes() == antes)
r2 = subprocess.run([sys.executable, "titan_gold_news.py"], cwd=trabajo, env=entorno("caida"), capture_output=True, text=True, timeout=120)
chequea("titan_gold_news falla sin internet y conserva datos", r2.returncode == 1 and j.read_bytes() == antes, r2.returncode)

print("\n[4] Bot de Telegram (mensajes simulados)")
os.environ.update(entorno("ok"))
sys.path[:0] = [str(trabajo), str(trabajo / "pruebas")]
import fixtures_red; fixtures_red.install()
import titan_bot as b
enviados = []
def api(metodo, **d):
    enviados.append((metodo, d)); return {"ok": True, "result": []}
b.tb.api = api
documentos = []
_enviar_documento_real = b.tb.enviar_documento
b.tb.enviar_documento = lambda chat, contenido, nombre, texto="": documentos.append((nombre, contenido, texto))

def msgs(): return [d for m, d in enviados if m == "sendMessage"]
def texto(chat, t): b.manejar({"update_id": 1, "message": {"chat": {"id": chat}, "text": t}})
def boton(chat, data): b.manejar({"update_id": 2, "callback_query": {"id": "x", "data": data, "message": {"chat": {"id": chat}}}})
def boton_m(chat, data, mid): b.manejar({"update_id": 3, "callback_query": {"id": "x", "data": data, "message": {"chat": {"id": chat}, "message_id": mid}}})

enviados.clear(); texto(123, "hola")
chequea("texto cualquiera NO repite el menú", len(msgs()) == 1 and "reply_markup" not in msgs()[0])
enviados.clear(); texto(123, "/start")
chequea("/start muestra el menú", len(msgs()) == 1 and "reply_markup" in msgs()[0])
enviados.clear(); texto(999, "/start"); boton(999, "analizar")
chequea("chat no autorizado es ignorado", len(msgs()) == 0)
boton(123, "z:America/Santo_Domingo"); boton(123, "h:08:00")
e = b.cargar()
chequea("zona y hora se guardan", e["zona"] == "America/Santo_Domingo" and "08:00" in e["horas"], e)
boton(123, "toggle"); enviados.clear(); boton(123, "estado")
chequea("bot se enciende y el estado lo dice", b.cargar()["activo"] and "prendidos" in msgs()[0]["text"], msgs())
enviados.clear(); boton(123, "analizar")
t = [m["text"] for m in msgs()]
chequea("botón Analizar usa el pipeline y responde el resumen", any("Temas que más aparecen" in x for x in t), t[-3:])
chequea("Analizar añade las sesiones del mercado", any("Sesiones del mercado" in x for x in t))
enviados.clear(); boton(123, "sesgo")
chequea("sesgo del día responde", any("Sesgo del día" in m["text"] for m in msgs()))
e = b.cargar(); ahora = datetime.now(ZoneInfo(e["zona"])); e["horas"] = [ahora.strftime("%H:%M")]; b.guardar(e)
enviados.clear(); b.revisar_horario()
chequea("envío programado se dispara a su hora", any("Resumen programado" in m["text"] for m in msgs()))
enviados.clear(); b.revisar_horario()
chequea("el envío programado no se repite", len(msgs()) == 0)

print("\n[5] Agente multi-activo (noticias, técnico, horas, verificación)")
import sqlite3
from datetime import timedelta, timezone
import agente, activos as act
chequea("RSI de una serie siempre al alza = 100", agente.rsi([float(i) for i in range(1, 40)]) == 100.0)
chequea("EMA de una serie constante es constante", agente.ema([5.0, 5.0, 5.0], 2) == [5.0, 5.0, 5.0])
oro, eur, jpy = act.buscar("GC=F"), act.buscar("EURUSD=X"), act.buscar("JPY=X")
chequea("oro: 'falls as Fed signals higher yields' es adverso", agente.clasificar(oro, "Gold falls as Fed signals higher yields")[0] == -1)
chequea("oro: 'surges to record high' es favorable", agente.clasificar(oro, "Gold surges to record high as dollar weakens")[0] == 1)
chequea("dólar fuerte: adverso para EUR/USD y favorable para USD/JPY",
        agente.clasificar(eur, "Fed signals rate hike, strong dollar")[0] == -1 and agente.clasificar(jpy, "Fed signals rate hike, strong dollar")[0] == 1)
chequea("palabras completas: 'Enterprise' y 'Bank' no activan falsos positivos",
        agente.clasificar(oro, "Enterprise software review")[0] == 0 and agente.clasificar(oro, "Bank of Japan holds policy")[0] == 0)
chequea("con menos de 3 noticias relevantes no puntúan", agente.puntaje_noticias([{"impacto": 1, "edad_h": 1}] * 2) == 0)
chequea("5 noticias recientes favorables puntúan +2", agente.puntaje_noticias([{"impacto": 1, "edad_h": 1}] * 5) == 2)
zona = ZoneInfo("America/Santo_Domingo")
bars = agente.barras("BTC-USD", "1mo", "60m")
est = agente.estacionalidad(bars, zona)
chequea("estacionalidad horaria calculada", len(est) >= 20 and agente.proxima_ventana(est, datetime.now(zona)) is not None, len(est))
btc = act.buscar("BTC-USD")
r = agente.analizar(btc, zona)
chequea("análisis de Bitcoin sin error y con dirección válida", r["error"] is None and r["direccion"] in
        ("alcista", "ligeramente alcista", "lateral", "ligeramente bajista", "bajista"), r.get("error"))
chequea("hay noticias relevantes del activo", len(r["noticias"]) >= 3 and any(n["impacto"] for n in r["noticias"]), len(r["noticias"]))
tx = agente.texto(r, zona)
chequea("el texto trae hipótesis, niveles y advertencia", "Hipótesis" in tx and "soporte" in tx and "no predicción" in tx, tx[-200:])
cdb = sqlite3.connect(trabajo / "titan_activos.db")
chequea("el análisis y las noticias quedan guardados en SQLite",
        cdb.execute("select count(*) from analisis").fetchone()[0] >= 1 and cdb.execute("select count(*) from noticias_activo").fetchone()[0] >= 3)
n1 = cdb.execute("select count(*) from noticias_activo").fetchone()[0]
agente.analizar(btc, zona)
chequea("las noticias repetidas no se duplican", cdb.execute("select count(*) from noticias_activo").fetchone()[0] == n1)
os.environ["TITAN_FIXTURES"] = "caida"
r2 = agente.analizar(act.buscar("ETH-USD"), zona, guardar=False)
os.environ["TITAN_FIXTURES"] = "ok"
chequea("sin internet el análisis falla con aviso, sin romperse", r2["error"] and "⚠️" in agente.texto(r2, zona), r2["error"])
now = datetime.now(timezone.utc)
t5, t1 = (now - timedelta(hours=5)).isoformat(), (now - timedelta(hours=1)).isoformat()
b5 = [x for x in bars if x["t"] <= (now - timedelta(hours=5)).timestamp()][-1]["c"]
for dire, t in (("alcista", t5), ("bajista", t5), ("alcista", t1)):
    cdb.execute("insert into analisis(simbolo,creado_en,precio,punt_tecnico,punt_noticias,total,direccion,confianza,horizonte_h,atr_pct)"
                " values ('PRUEBA',?,?,0,0,0,?,'baja',4,0.001)", (t, b5, dire))
cdb.execute("update analisis set simbolo='BTC-USD' where simbolo='PRUEBA'"); cdb.commit()
cdb.execute("update analisis set evaluado_en='x', resultado='neutro' where evaluado_en is null and creado_en not in (?,?)", (t5, t1)); cdb.commit()
hechos = agente.evaluar_pendientes()
res_eval = sorted(x[0] for x in cdb.execute("select resultado from analisis where creado_en=?", (t5,)).fetchall())
chequea("la verificación evalúa a las 4 h: una alcista y una bajista dan un acierto y un fallo", res_eval == ["acierto", "fallo"], res_eval)
chequea("no evalúa antes de tiempo", cdb.execute("select evaluado_en from analisis where creado_en=?", (t1,)).fetchone()[0] is None)
st = agente.estadisticas("BTC-USD")
chequea("estadísticas de acierto correctas", st["n"] == 2 and st["aciertos"] == 1 and abs(st["tasa"] - 50) < 1e-9, st)
chequea("el reporte de precisión se genera", "Global" in agente.texto_precision())
cdb.close()

print("\n[6] Bot: elegir activos y analizarlos")
enviados.clear(); boton(123, "act")
kb = msgs()[0]["reply_markup"]["inline_keyboard"]
chequea("Mis activos muestra las categorías", len(kb) == len(act.CATEGORIAS) + 1, kb)
enviados.clear(); boton(123, "cat:1")
txtkb = json.dumps(msgs()[0]["reply_markup"])
chequea("la categoría Cripto lista Bitcoin", "a:1:BTC-USD" in txtkb)
boton(123, "a:1:BTC-USD"); boton(123, "a:0:GC=F")
chequea("marcar activos los guarda", b.cargar()["seleccion"] == ["BTC-USD", "GC=F"], b.cargar()["seleccion"])
boton(123, "a:1:BTC-USD")
chequea("tocar de nuevo lo quita", b.cargar()["seleccion"] == ["GC=F"])
boton(123, "a:1:BTC-USD")
enviados.clear(); texto(123, "/agregar DOGE-USD")
chequea("/agregar valida el símbolo y lo marca", "DOGE-USD" in b.cargar()["personalizados"] and "DOGE-USD" in b.cargar()["seleccion"], msgs())
enviados.clear(); texto(123, "/agregar $$$")
chequea("/agregar con símbolo inválido da instrucciones", "Uso:" in msgs()[0]["text"])
e = b.cargar(); e["seleccion"] = ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "AAPL", "TSLA", "NVDA", "MSFT"]; b.guardar(e)
enviados.clear(); boton(123, "a:3:AMZN")
chequea("máximo 8 activos", "Máximo" in msgs()[0]["text"] and "AMZN" not in b.cargar()["seleccion"])
e["seleccion"] = ["BTC-USD", "GC=F", "AMD"]; b.guardar(e)
enviados.clear(); boton(123, "mis")
t = [m["text"] for m in msgs()]
chequea("Analizar mis activos envía un análisis por activo", sum("Hipótesis" in x for x in t) == 3 and "Listo" in t[-1], t[-2:])
enviados.clear(); boton(123, "prec")
chequea("botón Precisión responde", "Precisión" in msgs()[0]["text"])
enviados.clear(); boton(123, "estado")
chequea("el estado lista los activos seguidos", "BTC-USD" in msgs()[0]["text"])
e = b.cargar(); e["enviadas"] = {}; e["horas"] = [datetime.now(ZoneInfo(e["zona"])).strftime("%H:%M")]; e["activo"] = True; b.guardar(e)
enviados.clear(); b.revisar_horario()
chequea("el envío programado incluye el análisis de mis activos", sum("Hipótesis" in m["text"] for m in msgs()) == 3)

print("\n[7] Flujo guiado: activo → zona → hora → Resumen previo")
import guiado
zsd = ZoneInfo("America/Santo_Domingo")
ref = datetime(2026, 10, 27, 15, 0, tzinfo=zsd).astimezone(timezone.utc)   # 15:00 en Santo Domingo
b21 = guiado.hora_objetivo(zsd, 21, ref)
b08 = guiado.hora_objetivo(zsd, 8, ref)
bn = guiado.hora_objetivo(zsd, None, ref, proxima=True)
chequea("21:00 es hoy y 08:00 es mañana", b21.day == 27 and b21.hour == 21 and b08.day == 28 and b08.hour == 8, (b21, b08))
chequea("'próxima hora' es la siguiente hora en punto", bn.hour == 16 and bn.minute == 0, bn)
chequea("frases naturales del momento", guiado.momento(b21, ref) == "esta noche" and guiado.momento(b08, ref) == "mañana por la mañana")
r5, tx5 = guiado.pronosticar(act.buscar("GC=F"), zsd, b21)
chequea("el Resumen previo trae título, momento, sesgo y niveles",
        all(k in tx5 for k in ("Resumen previo", "esta noche", "sesgo", "Ahora cotiza", "suele moverse", "no predicción")), tx5)
chequea("el sesgo usa la frase natural", any(f in tx5 for f in guiado.FRASE.values()), tx5[:200])
cdb = sqlite3.connect(trabajo / "titan_activos.db")
chequea("el pronóstico de la hora queda guardado", cdb.execute("select count(*) from pron_hora").fetchone()[0] >= 1)
tsp = int((datetime.now(timezone.utc) - timedelta(hours=6)).timestamp())
for dire in ("alcista", "bajista"):
    cdb.execute("insert into pron_hora(simbolo,creado_en,objetivo_ts,zona,direccion,total,atr_pct,precio_ref) values ('BTC-USD','x',?,'America/Santo_Domingo',?,0,0.001,1)", (tsp, dire))
cdb.commit()
guiado.evaluar_horas()
rr = sorted(x[0] for x in cdb.execute("select resultado from pron_hora where objetivo_ts=?", (tsp,)).fetchall())
chequea("la verificación por hora da un acierto y un fallo", rr == ["acierto", "fallo"], rr)
chequea("el reporte de precisión por hora existe", "Pronósticos por hora" in guiado.texto_precision_horas())
cdb.close()
chequea("el menú principal empieza por 'Activo analizar'", b.menu(b.cargar())["inline_keyboard"][0][0]["callback_data"] == "ga")
e = b.cargar(); e["zona"] = "America/Santo_Domingo"; b.guardar(e)
enviados.clear(); boton(123, "ga")
chequea("paso 1: categorías", "gc:1" in json.dumps(msgs()[0]["reply_markup"]), msgs())
enviados.clear(); boton(123, "gc:1")
chequea("paso 2: activos de la categoría", "gp:BTC-USD" in json.dumps(msgs()[0]["reply_markup"]))
enviados.clear(); boton(123, "gp:BTC-USD")
chequea("paso 3: pide la zona horaria (con 'mi zona')", "gz:BTC-USD:g" in json.dumps(msgs()[0]["reply_markup"]) and "zona" in msgs()[0]["text"].lower())
enviados.clear(); boton(123, "gz:BTC-USD:g")
horas_kb = json.dumps(msgs()[0]["reply_markup"])
chequea("paso 4: pide la hora (24 horas + próxima hora)", horas_kb.count('"gh:BTC-USD:g:') == 25 and "gh:BTC-USD:g:21" in horas_kb)
enviados.clear(); boton(123, "gh:BTC-USD:g:21")
t = [m["text"] for m in msgs()]
chequea("paso 5: Resumen previo con botones de seguir", any("Resumen previo" in x for x in t) and "gd:BTC-USD" in json.dumps(msgs()[-1]["reply_markup"]), t[-1][:200])
enviados.clear(); boton(123, "gh:BTC-USD:g:N")
chequea("'Próxima hora' también funciona", any("Resumen previo" in m["text"] for m in msgs()))
enviados.clear(); boton(123, "gd:BTC-USD")
chequea("'Análisis completo' muestra el análisis detallado", any("Hipótesis (4 h)" in m["text"] for m in msgs()))
e = b.cargar(); e["personalizados"] = []; b.guardar(e)
enviados.clear(); boton(123, "gc:%d" % act.CATEGORIAS.index("Personalizado"))
chequea("categoría personalizada vacía explica /agregar", any("/agregar" in m["text"] for m in msgs()))
enviados.clear(); boton(123, "prec")
chequea("Precisión incluye los pronósticos por hora", "Pronósticos por hora" in msgs()[0]["text"])
todas = [b.menu(b.cargar()), b.menu_flujo_categorias(), b.menu_flujo_activos(1, b.cargar()), b.menu_flujo_zonas("EURUSD=X", b.cargar()),
         b.menu_flujo_horas("EURUSD=X", "12"), b.menu_flujo_final("EURUSD=X", "12")]
largos = [len(x["callback_data"].encode()) for m in todas for f in m["inline_keyboard"] for x in f]
chequea("ningún botón supera el límite de Telegram (64 bytes)", max(largos) <= 64, max(largos))
b._ULT_EVAL[0] = 0.0
try:
    b.evaluar_si_toca(); ok_ev = True
except Exception as ex:
    ok_ev = ex
chequea("la verificación automática corre dentro del bot", ok_ev is True, ok_ev)

print("\n[8] Hoja de análisis (PDF), teclado fijo y preguntas en el mismo mensaje")
import re, zlib, urllib.request as _ur
import informe, pdfmini
chequea("tabla de anchos de fuente completa", len(pdfmini._W) == 95 and abs(pdfmini.ancho("Hello", 10) - 22.78) < 0.01)
chequea("el texto del PDF se limpia (flechas y emojis)", pdfmini.limpia("A → B ▲ 😀") == "A -> B (+) ")
ses = b.SESIONES
d = informe.reunir(act.buscar("GC=F"), zsd, guiado.hora_objetivo(zsd, 21, ref), ses, ref)
chequea("reunir devuelve todas las secciones", d["error"] is None and len(d["sesiones"]) == 5 and len(d["esc"]["senales"]) == 7
        and len(d["esc"]["filas"]) == 3 and d["con_vol"] and len(d["ctx"]) >= 1, list(d))
chequea("hay volumen típico para la hora objetivo", d["ah"] is not None and d["ah"]["vol"] > 0)
chequea("el escenario tiene nivel, umbral de volumen y veredicto", d["esc"]["peso"] in ("ruptura", "rechazo", "equilibrado")
        and "volumen" in d["esc"]["umbral"] and d["esc"]["conf"] in ("baja", "media"), d["esc"]["umbral"])
rc = informe.resumen_chat(d)
chequea("el resumen del chat es breve y apunta al PDF", "Resumen previo" in rc and "Nivel clave" in rc and "PDF" in rc and len(rc) < 1500, rc)
pdfb = informe.pdf(d)
chequea("el PDF empieza y termina bien", pdfb.startswith(b"%PDF-1.4") and pdfb.rstrip().endswith(b"%%EOF"))
ini = int(re.search(rb"startxref\n(\d+)", pdfb).group(1))
tabla = pdfb[ini:].split(b"\n")
nobj = int(tabla[1].split()[1]) - 1
offs = [int(x.split()[0]) for x in tabla[3:3 + nobj]]
chequea("el índice (xref) del PDF apunta a cada objeto", pdfb[ini:ini + 4] == b"xref" and all(pdfb[o:].startswith(f"{i} 0 obj".encode()) for i, o in enumerate(offs, 1)))
paginas = pdfb.count(b"/Type /Page ")
chequea("el PDF tiene entre 4 y 5 páginas", paginas in (4, 5), paginas)
contenido = b"".join(zlib.decompress(m) for m in re.findall(rb"stream\n(.*?)\nendstream", pdfb, re.S)).decode("cp1252")
chequea("el PDF trae todas las secciones", all(k in contenido for k in ("RESUMEN EJECUTIVO", "LECTURA T", "NOTICIAS", "CONTEXTO", "ACTIVIDAD Y VOLUMEN", "RUPTURA O RECHAZO", "CONCLUSI")))
os.environ["TITAN_FIXTURES"] = "caida"
dx = informe.reunir(act.buscar("ETH-USD"), zsd, guiado.hora_objetivo(zsd, 9, ref), ses, ref)
os.environ["TITAN_FIXTURES"] = "ok"
ceros = [dict(x, v=0) for x in d["r"]["barras"]]
ac0, cv0 = informe.actividad(ceros, zsd)
chequea("mercados sin volumen (divisas): se usa el rango como actividad", not cv0 and all(v["vol_x"] is None and v["rango_x"] for v in ac0.values()))
d0 = dict(d, con_vol=False, esc=informe.escenarios(d["r"], d["ah"], False, d["base"].hour))
chequea("la hoja también se genera sin volumen", informe.pdf(d0).startswith(b"%PDF") and "rango de la vela" in d0["esc"]["umbral"], d0["esc"]["umbral"])
chequea("sin internet la hoja avisa en vez de romperse", dx["error"] and informe.resumen_chat(dx).startswith("⚠️"))
cap = {}
class _R:
    def read(self): return b'{"ok": true}'
    def __enter__(self): return self
    def __exit__(self, *a): return False
_orig = _ur.urlopen
_ur.urlopen = lambda req, timeout=0: (cap.update(url=req.full_url, h=dict(req.header_items()), cuerpo=req.data) or _R())
_enviar_documento_real(123, b"%PDF-prueba", "x.pdf", "pie")
_ur.urlopen = _orig
chequea("sendDocument arma bien el formulario multipart", cap["url"].endswith("/sendDocument") and b'filename="x.pdf"' in cap["cuerpo"]
        and b"%PDF-prueba" in cap["cuerpo"] and b'name="chat_id"' in cap["cuerpo"] and "boundary=" in cap["h"]["Content-type"])
e = b.cargar(); e["zona"] = "America/Santo_Domingo"; e["horas"] = ["08:00"]; e["activo"] = False; b.guardar(e)
enviados.clear(); texto(123, "/start")
tk = msgs()[0]["reply_markup"]
chequea("teclado fijo con solo 2 botones (analizar y prender)", [[x["text"] for x in f] for f in tk["keyboard"]] == [["🎯 Analizar activo"], ["🟢 Prender bot"]]
        and tk.get("is_persistent") and tk.get("resize_keyboard"), tk)
enviados.clear(); texto(123, "🟢 Prender bot")
chequea("el botón fijo enciende el bot y cambia a 'Apagar'", b.cargar()["activo"] and msgs()[0]["reply_markup"]["keyboard"][1][0]["text"] == "🔴 Apagar bot", msgs())
enviados.clear(); texto(123, "🔴 Apagar bot")
chequea("el botón fijo lo apaga y vuelve a 'Prender'", not b.cargar()["activo"] and msgs()[0]["reply_markup"]["keyboard"][1][0]["text"] == "🟢 Prender bot")
enviados.clear(); texto(123, "🎯 Analizar activo")
chequea("el botón fijo inicia las preguntas (paso 1)", "Paso 1 de 4" in msgs()[0]["text"] and "gc:1" in json.dumps(msgs()[0]["reply_markup"]))
enviados.clear(); texto(123, "/menu")
chequea("/menu muestra las demás opciones", "ga" in json.dumps(msgs()[0]["reply_markup"]) and "analizar" in json.dumps(msgs()[0]["reply_markup"]))
enviados.clear(); texto(123, "/estado")
chequea("los comandos funcionan (/estado)", "Estado del bot" in msgs()[0]["text"] and "reply_markup" not in msgs()[0])
enviados.clear()
boton_m(123, "ga", 777); boton_m(123, "gc:1", 777); boton_m(123, "gp:BTC-USD", 777); boton_m(123, "gz:BTC-USD:g", 777)
ed = [(m, dd) for m, dd in enviados if m == "editMessageText"]
chequea("cada respuesta reemplaza el mismo mensaje (4 ediciones, ningún mensaje nuevo)",
        len(ed) == 4 and all(dd["message_id"] == 777 for _, dd in ed) and not msgs(), [m for m, _ in enviados])
chequea("las preguntas avanzan: categoría → activo → zona → hora",
        ["Paso 1 de 4", "Paso 2 de 4", "Paso 3 de 4", "Paso 4 de 4"] == [re.search(r"Paso \d de 4", dd["text"]).group(0) for _, dd in ed])
enviados.clear(); documentos.clear(); boton_m(123, "gh:BTC-USD:g:21", 777)
ed = [dd for m, dd in enviados if m == "editMessageText"]
chequea("al elegir la hora se borran los botones de la pregunta", len(ed) == 1 and ed[0]["reply_markup"] == {"inline_keyboard": []} and "Generando" in ed[0]["text"], ed)
chequea("se envía la hoja como documento PDF", len(documentos) == 1 and documentos[0][0].startswith("TITAN_BTC_USD_") and documentos[0][0].endswith(".pdf")
        and documentos[0][1].startswith(b"%PDF"), [x[0] for x in documentos])
chequea("después llega el resumen corto con opciones para seguir", "Resumen previo" in msgs()[-1]["text"] and "gz:BTC-USD:g" in json.dumps(msgs()[-1]["reply_markup"]))
enviados.clear(); boton_m(123, "h:16:00", 888)
chequea("las horas automáticas también se editan en el mismo mensaje", [m for m, _ in enviados if m == "editMessageText"] == ["editMessageText"] and not msgs())
enviados.clear(); boton_m(123, "z:America/Bogota", 889)
ed = [dd for m, dd in enviados if m == "editMessageText"]
chequea("al guardar la zona se confirma y se quitan los botones", ed and ed[0]["reply_markup"] == {"inline_keyboard": []} and b.cargar()["zona"] == "America/Bogota")
e = b.cargar(); e["zona"] = "America/Santo_Domingo"; b.guardar(e)

print("\n[9] TITAN QUANT: zonas del mundo, riesgo, vigilancia, alertas y explicación")
import zonas, escenarios as E, monitor, quant
chequea("el informe incluye TITAN QUANT sin errores", d["quant"].get("error") is None and len(d["quant"]["escenarios"]) == 5, d["quant"].get("error"))
contenido = b"".join(zlib.decompress(m) for m in re.findall(rb"stream\n(.*?)\nendstream", informe.pdf(d), re.S)).decode("cp1252")
chequea("el PDF trae las secciones nuevas", all(k in contenido for k in ("PAS", "MACRO, GOBIERNOS", "ESCENARIOS, STOP-LOSS", "FUENTES Y L", "Fuente de datos")))
chequea("el resumen del chat dice qué pasó y el escenario más cercano", "Qué pasó:" in informe.resumen_chat(d) and "Escenario más cercano:" in informe.resumen_chat(d))
tz_all = zonas.todas()
chequea("todas las zonas horarias del mundo (más de 400)", len(tz_all) > 400 and all(zonas.por_region(r) for r in ("America", "Europe", "Asia", "Africa", "Australia", "Pacific", "Atlantic", "Indian")), len(tz_all))
chequea("búsqueda por ciudad y país, con desfase", zonas.buscar("madrid") == ["Europe/Madrid"] and zonas.buscar("república dominicana") == ["America/Santo_Domingo"]
        and zonas.etiqueta("Asia/Kolkata") == "Kolkata (UTC+5:30)" and zonas.etiqueta("America/Santo_Domingo") == "Santo Domingo (UTC-4)")
SIM20, largos = "ABCDEFGHIJKLMNOPQRST", []
for rg in zonas.REGIONES:
    for pg in range((len(zonas.por_region(rg)) + 9) // 10):
        for sm in (None, SIM20):
            largos += [len(x["callback_data"].encode()) for f in b.menu_ciudades(rg, pg, sm)["inline_keyboard"] for x in f]
for sm in (None, SIM20):
    largos += [len(x["callback_data"].encode()) for f in b.menu_regiones(sm)["inline_keyboard"] for x in f]
chequea("ningún botón de zonas supera el límite de Telegram", max(largos) <= 64, max(largos))
enviados.clear(); boton(123, "zona")
chequea("el menú de zonas ofrece 'Todas las zonas del mundo'", "zR" in json.dumps(msgs()[0]["reply_markup"]))
enviados.clear(); boton_m(123, "zR", 900); boton_m(123, "zr:Asia:0", 900); boton_m(123, "zr:Asia:1", 900)
ed = [dd for m, dd in enviados if m == "editMessageText"]
chequea("regiones y páginas de ciudades se editan en el mismo mensaje", len(ed) == 3 and "zr:Asia:0" in json.dumps(ed[0]["reply_markup"])
        and json.dumps(ed[1]["reply_markup"]).count('"z:Asia/') >= 8 and "zr:Asia:1" in json.dumps(ed[1]["reply_markup"]) and "zr:Asia:0" in json.dumps(ed[2]["reply_markup"]) and "zr:Asia:2" in json.dumps(ed[2]["reply_markup"]))
boton_m(123, "z:Asia/Kolkata", 900)
chequea("cualquier zona del mundo se puede guardar", b.cargar()["zona"] == "Asia/Kolkata")
e = b.cargar(); e["zona"] = "America/Santo_Domingo"; b.guardar(e)
enviados.clear(); documentos.clear()
boton_m(123, "gR:BTC-USD", 901); boton_m(123, "gr:BTC-USD:Europe:1", 901); boton_m(123, "gz:BTC-USD:Europe/Madrid", 901)
ed = [dd for m, dd in enviados if m == "editMessageText"]
chequea("en las preguntas también se elige cualquier zona y pide la hora", len(ed) == 3 and "Europe/Madrid" in ed[2]["text"] and "Paso 4 de 4" in ed[2]["text"], [x["text"][:60] for x in ed])
enviados.clear(); boton_m(123, "gh:BTC-USD:Europe/Madrid:21", 901)
chequea("la hoja se genera en la zona elegida", documentos and "Europe/Madrid" in documentos[-1][2] and any("Europe/Madrid" in m["text"] for m in msgs()), documentos[-1][2:] if documentos else None)
enviados.clear(); texto(123, "/zona madrid")
chequea("/zona CIUDAD busca entre todas las zonas", "z:Europe/Madrid" in json.dumps(msgs()[0]["reply_markup"]))
enviados.clear(); texto(123, "/zona zzzzqq")
chequea("/zona sin resultados lo dice", "No encontré" in msgs()[0]["text"])
enviados.clear(); texto(123, "/riesgo")
chequea("/riesgo sin configurar explica el uso", "Uso: /riesgo" in msgs()[0]["text"])
enviados.clear(); texto(123, "/riesgo 10000 9")
chequea("/riesgo rechaza más del límite", "No se guardó" in msgs()[0]["text"])
enviados.clear(); texto(123, "/riesgo 10,000 1.5")
cc = E.conectar()
chequea("/riesgo guarda capital y porcentaje", E.config_riesgo(cc) == (10000.0, 1.5) and "Capital de referencia" in msgs()[0]["text"], msgs())
e = b.cargar(); e["seleccion"] = []; b.guardar(e)
enviados.clear(); texto(123, "/vigilar")
chequea("/vigilar sin activos pide marcarlos", "Primero marca" in msgs()[0]["text"] and not b.cargar()["monitor"])
e = b.cargar(); e["seleccion"] = ["GC=F"]; b.guardar(e)
enviados.clear(); texto(123, "/vigilar 3")
chequea("/vigilar N activa la vigilancia cada N minutos", b.cargar()["monitor"] and b.cargar()["frecuencia_min"] == 3 and "Vigilancia activada" in msgs()[0]["text"])
enviados.clear(); texto(123, "/escenarios")
chequea("/escenarios muestra el estado de la vigilancia", "activa cada 3 min" in msgs()[0]["text"])
llamadas = []
_tick_real = b.monitor.tick
b.monitor.tick = lambda e_, enviar_, zona_, *a_, **k_: llamadas.append(e_["seleccion"])
b._ULT_VIGILA[0] = 0.0; b.vigilar_si_toca(); b.vigilar_si_toca()
b.monitor.tick = _tick_real
chequea("el bot ejecuta la vigilancia y respeta la frecuencia", llamadas == [["GC=F"]], llamadas)
enviados.clear(); texto(123, "/vigilar apagar")
chequea("/vigilar apagar la detiene", not b.cargar()["monitor"])
# ---- vigilancia con velas sintéticas
T0 = int(datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc).timestamp())
def base_b(n=720):
    out = [{"t": T0 - 3600 * (n - i), "o": 105.0, "h": 105.5, "l": 104.5, "c": 105.0, "v": 1000} for i in range(n)]
    out[-30].update(h=110.0, l=109.0, o=109.5, c=109.5)
    out[-40].update(h=101.0, l=100.0, o=100.5, c=100.5)
    return out
vel = lambda k, o, h, l, c, v=3000: {"t": T0 + 3600 * k, "o": o, "h": h, "l": l, "c": c, "v": v}
cur = {"b": base_b(), "falla": False}
_barras_real = agente.barras
def _barras_falsa(sim, rango="1mo", intervalo="60m"):
    if cur["falla"]:
        raise ConnectionError("sin red")
    return list(cur["b"])
agente.barras = _barras_falsa
mon = []
em = {"seleccion": ["GC=F"], "personalizados": []}
at = lambda k, extra=0: datetime.fromtimestamp(T0 + 3600 * k + 300 + extra, timezone.utc)
def tk(k, extra=0, macro_s=10 ** 9):
    mon.clear(); monitor.tick(em, mon.append, zsd, at(k, extra), macro_cada_s=macro_s); return list(mon)
m1 = tk(0, macro_s=0)
cx = E.conectar()
chequea("el primer ciclo crea los 5 escenarios del activo", len(E.activos(cx, "GC=F")) == 5, len(E.activos(cx, "GC=F")))
chequea("sin cambios de estado no hay alertas de escenarios", not any(("RUPTURA" in t or "APROXIMACIÓN" in t or "SIN CONFIRMAR" in t) for t in m1), [t[:40] for t in m1])
chequea("un titular macro de alto impacto genera alerta con el activo afectado", any("ACONTECIMIENTO MACROECONÓMICO" in t and "Oro" in t and "sin verificación oficial" in t for t in m1), [t[:50] for t in m1])
cur["b"] = base_b() + [vel(0, 109.8, 110.6, 109.7, 110.4)]
m2 = tk(1)
chequea("cierre sobre la resistencia con volumen: ruptura confirmada con entrada, stop y objetivos",
        any("RUPTURA ALCISTA CONFIRMADA" in t and "Stop-loss propuesto" in t and "TP1" in t and "Tamaño" in t and "Invalidación" in t for t in m2), [t[:45] for t in m2])
chequea("también avisa de la hipótesis que se invalida (rechazo y rango)", sum("HIPÓTESIS INVALIDADA" in t for t in m2) >= 1)
m3 = tk(1, 60)
chequea("repetir el ciclo no duplica alertas", not any(("RUPTURA" in t or "INVALIDADA" in t or "SIN CONFIRMAR" in t) for t in m3), [t[:40] for t in m3])
cur["b"] = base_b() + [vel(0, 109.8, 110.6, 109.7, 110.4), vel(1, 110.4, 113.6, 110.3, 113.5)]
m4 = tk(2)
chequea("al llegar al TP1 avisa 'objetivo alcanzado'", any("OBJETIVO ALCANZADO" in t for t in m4), [t[:40] for t in m4])
cur["falla"] = True
m5 = [tk(2, 120 * i) for i in (1, 2, 3, 4)]
chequea("3 fallos de datos seguidos: un solo aviso de error", sum("ERROR DE DATOS" in t for ms in m5 for t in ms) == 1, [[t[:30] for t in ms] for ms in m5])
cur["falla"] = False
m6 = tk(2, 700)
chequea("al volver los datos avisa que se recuperaron", any("DATOS RECUPERADOS" in t for t in m6))
cur["b"] = base_b()
m7 = tk(10)
chequea("datos atrasados: avisa y no evalúa con ellos", any("DATOS OBSOLETOS" in t for t in m7))
m8 = tk(10, 120)
chequea("el aviso de datos obsoletos no se repite", not any("DATOS OBSOLETOS" in t for t in m8))
E.kv_set(cx, "latido", (at(11) - timedelta(hours=3)).isoformat())
bv = [dict(x, t=x["t"] + 3600 * 11) for x in base_b()]
for i in (-3, -2, -1):
    bv[i].update(h=108.0, l=102.0, o=105.0, c=105.0)
cur["b"] = bv
m9 = tk(11)
chequea("tras una parada larga avisa que el monitor se reanudó", any("MONITOR REANUDADO" in t for t in m9))
chequea("aumento excepcional de volatilidad", any("AUMENTO EXCEPCIONAL DE VOLATILIDAD" in t for t in m9))
m10 = tk(11, 60)
chequea("la alerta de volatilidad no se repite en la misma vela", not any("VOLATILIDAD" in t for t in m10))
mon.clear(); cc2 = E.conectar()
monitor._tasas(cc2, mon.append, at(12), [{"nombre": "Rendimiento a 13 semanas (^IRX)", "nivel": 5.2, "cambio_pb": 8.0}])
monitor._tasas(cc2, mon.append, at(12), [{"nombre": "Rendimiento a 13 semanas (^IRX)", "nivel": 5.2, "cambio_pb": 8.0}])
chequea("cambio de expectativas de tipos: una sola alerta por día y dirección", len(mon) == 1 and "EXPECTATIVAS DE TIPOS" in mon[0] and "aproximación" in mon[0])
agente.barras = _barras_real
# ---- explicación del movimiento
bx = base_b()
bx[-20].update(h=120.0, l=104.5)
bx[-6].update(o=105.0, h=108.2, l=104.9, c=108.0, v=1000)
nowx = datetime.fromtimestamp(T0 + 300, timezone.utc)
rx = {"barras": bx, "noticias": [], "atr": 0.9}
exa = quant.explicar(act.buscar("GC=F"), rx, nowx, zsd)
chequea("movimiento fuerte sin noticia, sin ruptura ni volumen: dice que NO identificó la causa", exa["sin_causa"] and any("NO se identificó" in x for x in exa["interpretacion"]), exa)
fecha_n = datetime.fromtimestamp(bx[-6]["t"] - 1800, timezone.utc).isoformat()
rx2 = dict(rx, noticias=[{"fecha": fecha_n, "titulo": "Fed sorprende", "fuente": "X", "impacto": 1, "edad_h": 5, "fuerza": 1}])
exb = quant.explicar(act.buscar("GC=F"), rx2, nowx, zsd)
chequea("con una noticia previa la lista como hecho publicado, sin afirmar causalidad", len(exb["previos"]) == 1 and not exb["sin_causa"] and any("no demuestra" in x for x in exb["interpretacion"]))
by = base_b(); by[-6].update(o=105.0, h=111.2, l=104.9, c=111.0, v=3500)
exc = quant.explicar(act.buscar("GC=F"), {"barras": by, "noticias": [], "atr": 0.9}, nowx, zsd)
chequea("ruptura con volumen alto: lo describe como hipótesis (no prueba) sin nombrar participantes",
        any("ruptura" in x for x in exc["interpretacion"]) and any("no prueba" in x for x in exc["hipotesis"]) and not exc["sin_causa"])
exd = quant.explicar(act.buscar("GC=F"), {"barras": base_b(), "noticias": [], "atr": 0.9}, nowx, zsd)
chequea("sin movimiento anormal no inventa explicaciones", any("No hubo un movimiento anormal" in x for x in exd["interpretacion"]) and not exd["hipotesis"])

shutil.rmtree(tmp, ignore_errors=True)
print(f"\nRESULTADO: {sum(res)} de {len(res)} pruebas correctas")
sys.exit(0 if all(res) else 1)
