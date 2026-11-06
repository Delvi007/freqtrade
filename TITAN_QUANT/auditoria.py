import ast
import re
import subprocess
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

BASE = Path("/root/TITAN_GOLD_NEWS")
TOKEN_RE = re.compile(r"\d{6,12}:[A-Za-z0-9_-]{30,}")
URL_RE = re.compile(r"https?://[^\s\"'<>)]+")
salida, avisos = [], []

def p(t=""):
    print(t)
    salida.append(t)

def nombre(n):
    if isinstance(n, ast.Name):
        return n.id
    if isinstance(n, ast.Attribute):
        base = nombre(n.value)
        return (base + "." if base else "") + n.attr
    return ""

LLAMADAS = {
    "eval": "ejecuta texto como código",
    "exec": "ejecuta texto como código",
    "os.system": "ejecuta comandos del sistema",
    "os.execv": "reinicia el proceso",
    "subprocess.run": "ejecuta otros programas",
    "subprocess.Popen": "ejecuta otros programas",
    "subprocess.call": "ejecuta otros programas",
    "urlopen": "conexión saliente HTTP/HTTPS",
    "socket.socket": "socket de red",
    "pickle.loads": "carga datos serializados (riesgo)",
    "os.chmod": "cambia permisos de archivos",
    "write_text": "escribe archivos",
    "open": "abre archivos",
}
ESCUCHA = ("bind", "listen", "serve_forever", "HTTPServer", "ThreadingHTTPServer")

archivos = sorted(BASE.glob("*.py"))
fuentes = {}

p("=== 1. ARCHIVOS Y SINTAXIS ===")
for f in archivos:
    try:
        src = f.read_text(encoding="utf-8")
    except Exception as ex:
        p(f"- {f.name}: no se pudo leer ({type(ex).__name__})")
        avisos.append(f.name + " no se pudo leer")
        continue
    fuentes[f.name] = src
    try:
        ast.parse(src)
        est = "OK"
    except SyntaxError as ex:
        est = f"ERROR en línea {ex.lineno}"
        avisos.append(f.name + " tiene error de sintaxis")
    p(f"- {f.name}: {len(src.splitlines())} líneas · sintaxis {est}")
if not archivos:
    avisos.append("no encontré archivos .py en " + str(BASE))

p("")
p("=== 2. CONEXIONES SALIENTES (dominios en el código) ===")
dominios = defaultdict(set)
for nom, src in fuentes.items():
    for url in URL_RE.findall(src):
        dominios[urlparse(url).netloc or url].add(nom)
        if url.startswith("http://"):
            avisos.append(nom + " usa una conexión sin cifrar (http): " + urlparse(url).netloc)
for host in sorted(dominios):
    p(f"- {host}  ← {', '.join(sorted(dominios[host]))}")
if not dominios:
    p("- ninguna URL encontrada")

p("")
p("=== 3. LLAMADAS SENSIBLES POR ARCHIVO ===")
escucha = []
for nom, src in fuentes.items():
    try:
        arbol = ast.parse(src)
    except SyntaxError:
        continue
    hallazgos = defaultdict(list)
    for n in ast.walk(arbol):
        if isinstance(n, ast.Call):
            nm = nombre(n.func)
            ult = nm.split(".")[-1]
            clave = nm if nm in LLAMADAS else (ult if ult in LLAMADAS else None)
            if clave:
                hallazgos[clave].append(n.lineno)
            if ult in ESCUCHA:
                escucha.append(f"{nom}:{n.lineno}")
    if hallazgos:
        p("- " + nom)
        for clave, lineas in sorted(hallazgos.items()):
            ls = ", ".join(str(x) for x in lineas[:6]) + ("…" if len(lineas) > 6 else "")
            p(f"    {clave} (líneas {ls}) → {LLAMADAS[clave]}")
            if clave in ("eval", "exec", "os.system", "pickle.loads"):
                avisos.append(f"{nom} usa {clave}: revisar de dónde viene lo que ejecuta")

p("")
p("=== 4. CONEXIONES ENTRANTES (puertos) ===")
if escucha:
    p("⚠ El código parece abrir un puerto en: " + ", ".join(escucha))
    avisos.append("el código abre un puerto de escucha")
else:
    p("✔ Ningún archivo abre puertos: el bot solo hace conexiones salientes (consulta a Telegram).")
try:
    r = subprocess.run(["ss", "-ltn"], capture_output=True, text=True, timeout=10)
    lineas = [l for l in r.stdout.splitlines()[1:] if l.strip()]
    p(f"- Puertos en escucha en este sistema: {len(lineas)}")
    for l in lineas[:8]:
        p("    " + l)
except Exception:
    p("- No pude consultar los puertos en escucha (herramienta 'ss' no disponible).")

p("")
p("=== 5. LIBRERÍAS EXTERNAS ===")
std = sys.stdlib_module_names
locales = {f.stem for f in archivos}
externos = set()
for nom, src in fuentes.items():
    try:
        arbol = ast.parse(src)
    except SyntaxError:
        continue
    for n in ast.walk(arbol):
        if isinstance(n, ast.Import):
            mods = [a.name.split(".")[0] for a in n.names]
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            mods = [n.module.split(".")[0]]
        else:
            continue
        for m in mods:
            if m not in std and m not in locales:
                externos.add(m)
p("- " + (", ".join(sorted(externos)) if externos else "ninguna: solo librerías estándar de Python"))

p("")
p("=== 6. SECRETOS Y PERMISOS ===")
for nom in (".telegram_token", ".telegram_chat", ".estado_bot.json"):
    f = BASE / nom
    if f.exists():
        modo = f.stat().st_mode & 0o777
        ok = (modo & 0o077) == 0
        p(f"- {nom}: permisos {oct(modo)[2:]} " + ("✔" if ok else "⚠ legible por otros usuarios"))
        if not ok and nom == ".telegram_token":
            avisos.append("el archivo del token es legible por otros usuarios (usa chmod 600)")
    else:
        p(f"- {nom}: no existe")
        if nom == ".telegram_chat":
            p("    (si no existe, el primer chat que escriba al bot queda autorizado)")
hallados = []
for f in BASE.rglob("*"):
    if not f.is_file() or f.name == ".telegram_token" or "__pycache__" in f.parts:
        continue
    try:
        if f.stat().st_size > 2000000:
            continue
        for i, linea in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if TOKEN_RE.search(linea):
                hallados.append(f"{f.name}:{i}")
    except Exception:
        pass
if hallados:
    p("⚠ Texto con forma de token en: " + ", ".join(hallados[:10]))
    avisos.append("hay texto con forma de token fuera del archivo protegido")
else:
    p("✔ No hay textos con forma de token en los archivos del proyecto (copias .bak incluidas).")
h = Path.home() / ".bash_history"
if h.exists():
    n = len(TOKEN_RE.findall(h.read_text(errors="ignore")))
    if n:
        p(f"⚠ El historial de comandos contiene {n} texto(s) con forma de token.")
        avisos.append("el historial de comandos contiene un token")
    else:
        p("✔ El historial de comandos no contiene tokens.")

p("")
p("=== 7. PROCESOS DEL BOT ACTIVOS ===")
try:
    r = subprocess.run(["pgrep", "-af", "python"], capture_output=True, text=True, timeout=10)
    vivos = [l for l in r.stdout.splitlines()
             if ("titan" in l or "telegram_bot" in l) and "auditoria" not in l]
    for l in vivos:
        p("- " + l[:110])
    if not vivos:
        p("- ninguno corriendo ahora")
    if len(vivos) > 1:
        avisos.append("hay varias instancias del bot: Telegram da conflicto si dos leen mensajes a la vez")
except Exception:
    p("- No pude listar procesos (herramienta 'pgrep' no disponible).")

p("")
p("=== 8. PRUEBA DE ALCANCE (no envía ningún dato) ===")
for host in sorted(dominios):
    if "{" in host:
        continue
    try:
        req = urllib.request.Request("https://" + host + "/", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            est = f"responde ({r.status})"
    except urllib.error.HTTPError as ex:
        est = f"responde ({ex.code})"
    except Exception as ex:
        est = f"sin respuesta ({type(ex).__name__})"
        avisos.append(host + " sin respuesta")
    p(f"- {host}: {est}")

p("")
p("=== RESUMEN ===")
if avisos:
    for a in avisos:
        p("⚠ " + a)
else:
    p("✔ Sin avisos.")
(BASE / "auditoria_bot.txt").write_text("\n".join(salida), encoding="utf-8")
print("\nInforme guardado en auditoria_bot.txt")
