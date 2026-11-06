from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from progreso_titan import progreso, titulo

BASE = Path(__file__).resolve().parent
PYTHON = sys.executable

def ejecutar_modulo(archivo, inicio, fin):
    ruta = BASE / archivo
    if not ruta.is_file():
        progreso(inicio, f"No existe {archivo}", "ERROR")
        return False

    progreso(inicio, f"Iniciando {archivo}")
    print(f"\n>>> EJECUTANDO: {archivo}", flush=True)

    proceso = None
    try:
        proceso = subprocess.Popen(
            [PYTHON, "-u", str(ruta)],
            cwd=str(BASE),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        if proceso.stdout:
            for linea in proceso.stdout:
                print(f"[{archivo}] {linea}", end="", flush=True)

        codigo = proceso.wait()
        if codigo == 0:
            progreso(fin, f"{archivo} terminó correctamente", "OK")
            return True
        progreso(fin, f"{archivo} terminó con código {codigo}", "ERROR")
        return False

    except KeyboardInterrupt:
        if proceso and proceso.poll() is None:
            proceso.terminate()
            try:
                proceso.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proceso.kill()
        raise
    except Exception as error:
        progreso(fin, f"{archivo}: {type(error).__name__}: {error}", "ERROR")
        return False

def main():
    inicio = time.monotonic()
    titulo("PIPELINE INTEGRADO TITAN GOLD NEWS")
    progreso(0, "Preparando recopilación y análisis")

    etapas = [
        ("recopilador_noticias.py", 0, 40),
        ("titan_gold_news.py", 40, 60),
        ("integrar_noticias.py", 60, 70),
        ("analisis_macro_v2.py", 70, 95),
    ]

    resultados = []
    for archivo, desde, hasta in etapas:
        ok = ejecutar_modulo(archivo, desde, hasta)
        resultados.append((archivo, ok))

        # Si falla una etapa de datos, no se ejecuta un análisis
        # con datos incompletos o de una ejecución anterior.
        if not ok:
            print(
                f"\nPipeline detenido: falló {archivo}. "
                "Revisa el error antes de continuar.",
                flush=True
            )
            progreso(hasta, "Pipeline detenido por error", "ERROR")
            return 1

    duracion = time.monotonic() - inicio
    titulo("RESUMEN FINAL")
    print(f"Tiempo total: {duracion:.1f} segundos", flush=True)
    print("Noticias combinadas: noticias_recopiladas.json", flush=True)
    print("Informe de oro: informe_oro.md", flush=True)
    print("Informe macro: analisis_macro_v2.md", flush=True)
    progreso(100, "Todas las etapas completadas", "OK")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nEjecución interrumpida de forma segura.", flush=True)
        raise SystemExit(130)
