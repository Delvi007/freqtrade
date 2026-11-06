#!/usr/bin/env python3
"""Auditor local para ejecutar TITAN y registrar su actividad sin mostrar el token."""
from __future__ import annotations
import ast, datetime as dt, importlib, json, linecache, os, runpy, sys, threading, traceback
from pathlib import Path

BASE = Path(__file__).resolve().parent
ENTRY = BASE / "titan_bot.py"
ROOT_LOG = BASE / "registros_ejecucion"
STAMP = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
OUT = ROOT_LOG / f"sesion_{STAMP}"
SRC = OUT / "codigo_fuente"
EVENTS = OUT / "eventos.log"
LINES = OUT / "lineas_ejecutadas.log"
OUT.mkdir(parents=True, exist_ok=True)
SRC.mkdir(parents=True, exist_ok=True)
LOCK = threading.RLock()  # reentrante: evita el bloqueo del tracer sobre sí mismo
MAX_TRACE_BYTES = 15 * 1024 * 1024
trace_size = 0
trace_limit_reported = False
ROOT = str(BASE.resolve())

def log(path, text):
    stamp = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    with LOCK, open(path, "a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {text}\n")

def event(text):
    log(EVENTS, text)

def copy_sources():
    count = 0
    for p in BASE.rglob("*.py"):
        if any(part in {".venv", "__pycache__", "registros_ejecucion"} for part in p.parts):
            continue
        try:
            target = SRC / p.relative_to(BASE)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(p.read_bytes())
            count += 1
        except Exception as exc:
            event(f"No se pudo copiar {p.name}: {type(exc).__name__}")
    event(f"Copia de código: {count} archivos Python en {SRC}")

def tracer(frame, kind, arg):
    global trace_size, trace_limit_reported
    filename = frame.f_code.co_filename
    try:
        resolved = str(Path(filename).resolve())
    except Exception:
        return tracer
    if not resolved.startswith(ROOT + os.sep) or not resolved.endswith(".py"):
        return tracer
    if "registros_ejecucion" in resolved or resolved == str(Path(__file__).resolve()):
        return tracer
    if kind == "call":
        record = f"CALL {resolved}:{frame.f_code.co_firstlineno} {frame.f_code.co_name}()"
    elif kind == "line":
        record = f"{resolved}:{frame.f_lineno} | {linecache.getline(resolved, frame.f_lineno).strip()}"
    elif kind == "exception":
        typ, exc, _ = arg
        record = f"EXCEPTION {resolved}:{frame.f_lineno} {getattr(typ, '__name__', 'Error')}: {exc}"
    else:
        return tracer
    size = len(record.encode("utf-8", errors="replace")) + 40
    if trace_size < MAX_TRACE_BYTES:
        log(LINES, record)
        trace_size += size
    elif not trace_limit_reported:
        event(f"Límite de líneas alcanzado ({MAX_TRACE_BYTES} bytes); el registro de eventos continúa.")
        trace_limit_reported = True
    return tracer

def summarize(update):
    out = []
    if not isinstance(update, dict):
        return out
    msg = update.get("message") or update.get("edited_message")
    if isinstance(msg, dict):
        chat = msg.get("chat") or {}
        body = msg.get("text") or msg.get("caption") or "[mensaje sin texto]"
        out.append(f"MENSAJE_RECIBIDO chat_id={chat.get('id', '?')} contenido={str(body)[:1000]!r}")
    cb = update.get("callback_query")
    if isinstance(cb, dict):
        msg = cb.get("message") or {}
        chat = msg.get("chat") or {}
        out.append(f"BOTON_CALLBACK chat_id={chat.get('id', '?')} data={str(cb.get('data', ''))[:500]!r}")
    if not out:
        out.append("UPDATE_RECIBIDO campos=" + ",".join(update.keys()))
    return out

def install_telegram_logging():
    try:
        tb = importlib.import_module("telegram_bot")
    except Exception as exc:
        event(f"No se pudo importar telegram_bot para instrumentación: {type(exc).__name__}: {exc}")
        return
    original = getattr(tb, "api", None)
    if not callable(original):
        event("No se encontró telegram_bot.api; API sin instrumentar.")
        return

    def wrapped(method, **params):
        # Nunca escribir tokens, claves ni secretos. Registrar método y parámetros útiles.
        safe = dict(params)
        for key in list(safe):
            if any(s in key.lower() for s in ("token", "password", "secret")):
                safe[key] = "[REDACTADO]"
            elif key == "text" and method == "sendMessage":
                safe[key] = str(safe[key])[:1200] + ("..." if len(str(safe[key])) > 1200 else "")
        event(f"TELEGRAM_API llamada={method} params={json.dumps(safe, ensure_ascii=False, default=str)[:2000]}")
        result = original(method, **params)
        if method == "getUpdates" and isinstance(result, dict):
            updates = result.get("result", [])
            event(f"TELEGRAM_API getUpdates recibió {len(updates) if isinstance(updates, list) else '?'} actualizaciones")
            if isinstance(updates, list):
                for u in updates:
                    for line in summarize(u):
                        event(line)
        else:
            event(f"TELEGRAM_API respuesta recibida para {method}")
        return result
    tb.api = wrapped
    event("Instrumentación de telegram_bot.api instalada.")

def main():
    if not ENTRY.is_file():
        print(f"ERROR: no existe {ENTRY}")
        raise SystemExit(2)
    sys.path.insert(0, str(BASE))
    event("===== INICIO AUDITORÍA TITAN =====")
    event(f"Proyecto={BASE}; Python={sys.version.split()[0]}; entrada={ENTRY.name}")
    event("El token no se imprime ni se copia deliberadamente a los logs.")
    event("Se registran mensajes entrantes y botones pulsados; protege estos archivos.")
    copy_sources()
    install_telegram_logging()
    linecache.checkcache()
    sys.settrace(tracer)
    try:
        event("ARRANCANDO titan_bot.py")
        runpy.run_path(str(ENTRY), run_name="__main__")
        event("Programa terminado normalmente.")
    except KeyboardInterrupt:
        event("Parada solicitada con Ctrl+C.")
        print("\nBot detenido con Ctrl+C.")
    except BaseException as exc:
        event(f"ERROR FATAL {type(exc).__name__}: {exc}")
        event(traceback.format_exc())
        raise
    finally:
        sys.settrace(None)
        event("===== FIN AUDITORÍA TITAN =====")
        print("\nRegistros guardados en:")
        print(f"Eventos, llamadas API y mensajes: {EVENTS}")
        print(f"Líneas de código ejecutadas: {LINES}")
        print(f"Copia de código Python: {SRC}")
        print("\nNota: el registro de líneas tiene un límite de 15 MB por sesión.")
        print("Este script no crea el botón 'Buscar noticia'; registrará esa acción si el bot ya la implementa.")

if __name__ == "__main__":
    main()
