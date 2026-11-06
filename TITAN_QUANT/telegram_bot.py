import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
def _leer_token():
    t = os.environ.get("TELEGRAM_TOKEN", "").strip()
    if not t and (BASE / ".telegram_token").exists():
        t = (BASE / ".telegram_token").read_text().strip()
    if not t:  # v7: token cifrado en la bóveda de TITAN QUANT (Integraciones → Telegram)
        try:
            from titan_quant.motores.sistema import _credenciales_telegram
            t, chat, _ = _credenciales_telegram()
            t = t or ""
            if t and chat and not (BASE / ".telegram_chat").exists():
                (BASE / ".telegram_chat").write_text(str(chat))
                os.chmod(BASE / ".telegram_chat", 0o600)
        except Exception:
            t = ""
    if not t:
        raise SystemExit("Falta el token: guárdalo en .telegram_token (una sola línea) o define TELEGRAM_TOKEN.")
    return t

TOKEN = _leer_token()
CHAT_FILE = BASE / ".telegram_chat"
API = f"https://api.telegram.org/bot{TOKEN}/"
HORAS = ["08:00", "16:00", "20:00", "21:00"]

MENU = {"inline_keyboard": [
    [{"text": "📊 Analizar", "callback_data": "analizar"}],
    [{"text": "🟢 Prender bot", "callback_data": "prender"}],
    [{"text": "🕐 Pedir resumen", "callback_data": "resumen"}],
]}
MENU_HORAS = {"inline_keyboard": [
    [{"text": h, "callback_data": "hora:" + h} for h in HORAS[:2]],
    [{"text": h, "callback_data": "hora:" + h} for h in HORAS[2:]],
    [{"text": "⬅️ Volver", "callback_data": "menu"}],
]}

def api(metodo, **datos):
    req = urllib.request.Request(
        API + metodo, data=json.dumps(datos).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())

def autorizado(chat):
    if not CHAT_FILE.exists():
        CHAT_FILE.write_text(str(chat))
        print("Chat autorizado guardado:", chat)
    return CHAT_FILE.read_text().strip() == str(chat)

def enviar(chat, texto, teclado=None):
    datos = {"chat_id": chat, "text": texto}
    if teclado:
        datos["reply_markup"] = teclado
    api("sendMessage", **datos)

def editar(chat, mid, texto, teclado=None):
    datos = {"chat_id": chat, "message_id": mid, "text": texto}
    if teclado is not None:
        datos["reply_markup"] = teclado
    api("editMessageText", **datos)

def enviar_documento(chat, contenido, nombre, texto=""):
    f = "----titan" + os.urandom(8).hex()
    cuerpo = b""
    for k, v in (("chat_id", str(chat)), ("caption", texto[:1000])):
        if v:
            cuerpo += ('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (f, k, v)).encode("utf-8")
    cuerpo += ('--%s\r\nContent-Disposition: form-data; name="document"; filename="%s"\r\n'
               'Content-Type: application/pdf\r\n\r\n' % (f, nombre)).encode() + contenido + ("\r\n--%s--\r\n" % f).encode()
    req = urllib.request.Request(API + "sendDocument", data=cuerpo,
                                 headers={"Content-Type": "multipart/form-data; boundary=" + f})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())

ULTIMO = ""
MENU_RES = {"inline_keyboard": [[{"text": "📄 Ver detalle completo", "callback_data": "detalle"}]] + MENU["inline_keyboard"]}

def lineas(md, titulo):
    a = md.find(titulo)
    if a < 0:
        return []
    b = md.find("\n#", a + len(titulo))
    bloque = md[a:b if b > a else None]
    return [l[2:] for l in bloque.split("\n") if l.startswith("- ")]

def compacto(md):
    temas = [l for l in lineas(md, "## Resumen en español")
             if "noticias" in l and "Sin tema" not in l and "Descartadas" not in l][:3]
    mercado = lineas(md, "## Datos de mercado")
    contraste = lineas(md, "### Contraste con las noticias")[:3]
    t = ["📰 Temas que más aparecen:"] + ["• " + x for x in temas]
    t += ["", "📈 Mercado (último dato):"] + ["• " + x for x in mercado]
    t += ["", "🔎 Contraste:"] + ["• " + x for x in contraste]
    t += ["", "Muestra de qué se habla y si los datos acompañan; no predice el precio."]
    return "\n".join(t)

def partir(texto, n=3800):
    partes, actual = [], ""
    for linea in texto.split("\n"):
        if len(actual) + len(linea) + 1 > n:
            partes.append(actual)
            actual = ""
        actual += linea + "\n"
    if actual.strip():
        partes.append(actual)
    return partes

SALIDA = ""

def correr(script, espera):
    global SALIDA
    r = subprocess.run([sys.executable, script], cwd=str(BASE),
                       capture_output=True, text=True, timeout=espera)
    SALIDA = (r.stdout or "") + (r.stderr or "")
    return r.returncode == 0

def analizar(chat):
    enviar(chat, "Analizando noticias y mercado, puede tardar uno o dos minutos...")
    try:
        if not correr("pipeline_titan.py", 600):
            m = re.search(r"falló (\S+\.py)", SALIDA)
            etapa = m.group(1) if m else "una etapa"
            enviar(chat, f"El análisis se detuvo: falló {etapa}. Revisa la conexión a internet y reintenta; se conservaron los datos anteriores.", MENU)
            return
        md = (BASE / "analisis_macro_v2.md").read_text(encoding="utf-8")
    except Exception as e:
        enviar(chat, "Falló el análisis: " + type(e).__name__, MENU)
        return
    ini = md.find("## Resumen en español")
    fin = md.find("## Detalle por noticia")
    texto = md[ini:fin if fin > ini else None]
    texto = texto.replace("**", "").replace("### ", "").replace("## ", "")
    global ULTIMO
    ULTIMO = texto
    enviar(chat, compacto(md), MENU_RES)

def manejar(u):
    if "message" in u:
        chat = u["message"]["chat"]["id"]
        if autorizado(chat):
            enviar(chat, "TITAN GOLD NEWS. Elige una opción:", MENU)
    elif "callback_query" in u:
        cb = u["callback_query"]
        chat = cb["message"]["chat"]["id"]
        api("answerCallbackQuery", callback_query_id=cb["id"])
        if not autorizado(chat):
            return
        d = cb["data"]
        if d == "analizar":
            analizar(chat)
        elif d == "detalle":
            for parte in partir(ULTIMO or "Aún no hay análisis. Pulsa Analizar."):
                enviar(chat, parte)
            enviar(chat, "Elige una opción:", MENU)
        elif d == "prender":
            enviar(chat, "(Prueba) Aquí se activarán los envíos automáticos.", MENU)
        elif d == "resumen":
            enviar(chat, "¿Para qué hora quieres el resumen?", MENU_HORAS)
        elif d.startswith("hora:"):
            enviar(chat, f"(Prueba) Elegiste las {d[5:]}. Aquí irá el resumen.", MENU)
        elif d == "menu":
            enviar(chat, "Elige una opción:", MENU)

def main():
    print("Bot en marcha. Ctrl+C para detener.")
    offset = None
    while True:
        try:
            params = {"timeout": 30}
            if offset:
                params["offset"] = offset
            for u in api("getUpdates", **params)["result"]:
                offset = u["update_id"] + 1
                manejar(u)
        except Exception as e:
            print("Error de red:", type(e).__name__)
            time.sleep(5)

if __name__ == "__main__":
    main()
