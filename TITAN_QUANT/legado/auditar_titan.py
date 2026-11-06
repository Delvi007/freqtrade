import ast
import importlib
import importlib.metadata
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)

ARCHIVOS = [
    "titan_bot.py",
    "telegram_bot.py",
    "titan_gold_news.py",
    "analisis_macro.py",
    "analisis_macro_v2.py",
    "resumen_noticias.py",
]

errores = []
avisos = []

def titulo(texto):
    print(f"\n{'=' * 65}\n{texto}\n{'=' * 65}")

titulo("TITAN GOLD NEWS — AUDITORÍA INTEGRAL")
print("Directorio:", ROOT)
print("Python:", sys.version.split()[0])

# 1. Archivos y sintaxis
titulo("1. ARCHIVOS Y SINTAXIS")
for nombre in ARCHIVOS:
    ruta = ROOT / nombre
    if not ruta.is_file():
        print(f"FALTA: {nombre}")
        errores.append(f"Falta {nombre}")
        continue

    try:
        contenido = ruta.read_text(encoding="utf-8")
        ast.parse(contenido, filename=nombre)
        print(f"OK sintaxis: {nombre} ({ruta.stat().st_size} bytes)")
    except SyntaxError as exc:
        print(f"ERROR sintaxis: {nombre}, línea {exc.lineno}: {exc.msg}")
        errores.append(f"Sintaxis en {nombre}, línea {exc.lineno}")
    except Exception as exc:
        print(f"ERROR lectura: {nombre}: {type(exc).__name__}")
        errores.append(f"Lectura de {nombre}")

# 2. Importaciones sin ejecutar los módulos del proyecto
titulo("2. DEPENDENCIAS INSTALADAS")
paquetes = [
    "python-telegram-bot",
    "requests",
    "schedule",
    "APScheduler",
    "yfinance",
    "feedparser",
]
for paquete in paquetes:
    try:
        print(f"OK {paquete}: {importlib.metadata.version(paquete)}")
    except importlib.metadata.PackageNotFoundError:
        print(f"NO INSTALADO: {paquete}")

# 3. Verificación de importaciones del proyecto
# Se realiza en un proceso separado porque importar un módulo puede
# ejecutar código definido por el propio proyecto.
titulo("3. IMPORTACIONES DEL PROYECTO")
for modulo in [
    "telegram_bot",
    "titan_gold_news",
    "analisis_macro_v2",
    "titan_bot",
]:
    try:
        resultado = subprocess.run(
            [
                sys.executable, "-c",
                "import importlib, sys; "
                "importlib.import_module(sys.argv[1]); "
                "print('IMPORTACION_OK')",
                modulo,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if resultado.returncode == 0 and "IMPORTACION_OK" in resultado.stdout:
            print(f"OK: {modulo}")
        else:
            print(f"ERROR: {modulo} (código {resultado.returncode})")
            salida = (resultado.stderr or resultado.stdout).strip()
            if salida:
                print("\n".join(salida.splitlines()[-8:]))
            errores.append(f"Importación de {modulo}")
    except subprocess.TimeoutExpired:
        print(f"TIEMPO AGOTADO: {modulo}")
        avisos.append(f"Importación lenta: {modulo}")
    except Exception as exc:
        print(f"ERROR: {modulo}: {type(exc).__name__}")
        errores.append(f"Importación de {modulo}")

# 4. Archivos de resultados y configuración
titulo("4. INFORMES Y CONFIGURACIÓN")
for nombre in [
    "informe_oro.md",
    "analisis_macro_v2.md",
    "noticias_recopiladas.json",
]:
    ruta = ROOT / nombre
    if ruta.is_file():
        print(f"OK: {nombre} ({ruta.stat().st_size} bytes)")
    else:
        print(f"AVISO: falta {nombre}")
        avisos.append(f"Falta informe o datos: {nombre}")

estado = ROOT / ".estado_bot.json"
if estado.is_file():
    try:
        datos = json.loads(estado.read_text(encoding="utf-8"))
        print("Estado JSON: válido")
        print("Activo configurado:", datos.get("activo"))
        print("Zona horaria:", datos.get("zona"))
        print("Horas programadas:", datos.get("horas"))
        if not isinstance(datos.get("horas"), list):
            avisos.append("El campo horas no es una lista")
    except Exception as exc:
        print("ERROR en .estado_bot.json:", type(exc).__name__)
        errores.append("Configuración JSON inválida")
else:
    print("AVISO: no existe .estado_bot.json")
    avisos.append("Falta .estado_bot.json")

# 5. Seguridad: solo comprobar la presencia del token
titulo("5. CREDENCIALES")
token_path = ROOT / ".telegram_token"
token = ""
if token_path.is_file():
    token = token_path.read_text(encoding="utf-8").strip()
    if token and ":" in token:
        print("Archivo de token: presente; contenido oculto")
    else:
        print("ERROR: token vacío o formato inesperado")
        errores.append("Token vacío o formato incorrecto")
else:
    print("ERROR: falta .telegram_token")
    errores.append("Falta .telegram_token")

# 6. Telegram getMe: petición de solo lectura
titulo("6. CONEXIÓN CON TELEGRAM")
if token:
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "TitanGoldNews-Audit/1.0"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            respuesta = json.loads(resp.read().decode("utf-8"))

        if respuesta.get("ok"):
            bot = respuesta.get("result", {})
            print("OK: Telegram acepta el token")
            print("Nombre:", bot.get("first_name", "No disponible"))
            print("Usuario:", "@" + bot["username"]
                  if bot.get("username") else "No disponible")
        else:
            print("ERROR: Telegram no validó el token")
            errores.append("Telegram rechazó getMe")
    except urllib.error.HTTPError as exc:
        print(f"ERROR HTTP de Telegram: {exc.code}")
        errores.append(f"Telegram HTTP {exc.code}")
    except urllib.error.URLError:
        print("ERROR: conexión de red con Telegram")
        avisos.append("No se pudo verificar Telegram por red")
    except Exception as exc:
        print("ERROR Telegram:", type(exc).__name__)
        avisos.append("No se pudo completar getMe")

# 7. Procesos activos
titulo("7. PROCESOS ACTIVOS")
try:
    proc = subprocess.run(
        ["ps", "-eo", "pid,etime,args"],
        capture_output=True, text=True, timeout=10
    )
    encontrados = [
        linea for linea in proc.stdout.splitlines()
        if ("titan_bot.py" in linea or "telegram_bot.py" in linea)
        and "auditar_titan.py" not in linea
        and "grep" not in linea
    ]
    if encontrados:
        for linea in encontrados:
            # No imprimir argumentos que pudieran contener credenciales.
            partes = linea.strip().split(None, 2)
            print("Proceso:", " ".join(partes[:2]))
        print("Hay procesos candidatos; comprobar que sean los correctos.")
    else:
        print("No se detectaron procesos con esos nombres.")
        avisos.append("Bot no detectado en ejecución")
except Exception as exc:
    print("No se pudo revisar procesos:", type(exc).__name__)
    avisos.append("No se pudo comprobar procesos")

# 8. Inspección estática del mecanismo de inicio y programación
titulo("8. INICIO Y PROGRAMACIÓN")
import re

for nombre in ("titan_bot.py", "telegram_bot.py"):
    ruta = ROOT / nombre
    if not ruta.is_file():
        continue
    try:
        lineas = ruta.read_text(encoding="utf-8").splitlines()
        patrones = re.compile(
            r"__main__|run_polling|run_webhook|asyncio\.run|"
            r"ApplicationBuilder|Updater\(|run_daily|run_repeating|"
            r"send_message|schedule|scheduler|20:00|while True|"
            r"create_task|JobQueue",
            re.I,
        )
        hallazgos = [
            (i, linea.strip()[:180])
            for i, linea in enumerate(lineas, 1)
            if patrones.search(linea)
        ]
        print(f"\n{nombre}:")
        if hallazgos:
            for numero, linea in hallazgos[:35]:
                print(f"  L{numero}: {linea}")
            if len(hallazgos) > 35:
                print("  ... hallazgos adicionales omitidos")
        else:
            print("  No se detectaron patrones habituales de inicio/programación.")
            avisos.append(f"Inicio/programación no identificados en {nombre}")
    except Exception:
        print(f"No se pudo inspeccionar {nombre}")

# Resultado final
titulo("RESULTADO FINAL")
print("Errores:", len(errores))
for item in errores:
    print("  ERROR:", item)
print("Avisos:", len(avisos))
for item in avisos:
    print("  AVISO:", item)

if errores:
    print("\nESTADO: REVISIÓN NECESARIA — hay errores que investigar.")
elif avisos:
    print("\nESTADO: AUDITORÍA PARCIAL — revisar avisos antes de iniciar.")
else:
    print("\nESTADO: COMPROBACIONES SUPERADAS; falta validar el envío real.")
print("\nNo se inició el bot ni se enviaron mensajes.")
