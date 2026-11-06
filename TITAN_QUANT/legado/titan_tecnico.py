#!/usr/bin/env python3
import argparse
import csv
import math
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

BASE = Path(__file__).resolve().parent
DB = BASE / "titan_integral.db"

TEMPORALIDADES = {
    "1m", "5m", "15m", "1h", "4h", "1d", "1wk", "1mo"
}


def ema(valores, periodo):
    if len(valores) < periodo:
        return None
    alpha = 2.0 / (periodo + 1)
    resultado = sum(valores[:periodo]) / periodo
    for valor in valores[periodo:]:
        resultado = alpha * valor + (1 - alpha) * resultado
    return resultado


def rsi(valores, periodo=14):
    if len(valores) <= periodo:
        return None

    cambios = [
        valores[i] - valores[i - 1]
        for i in range(1, len(valores))
    ]
    ganancias = [max(x, 0.0) for x in cambios]
    perdidas = [max(-x, 0.0) for x in cambios]

    media_g = sum(ganancias[:periodo]) / periodo
    media_p = sum(perdidas[:periodo]) / periodo

    for i in range(periodo, len(cambios)):
        media_g = (media_g * (periodo - 1) + ganancias[i]) / periodo
        media_p = (media_p * (periodo - 1) + perdidas[i]) / periodo

    if media_p == 0:
        return 100.0 if media_g > 0 else 50.0

    return 100 - 100 / (1 + media_g / media_p)


def cargar_csv(ruta):
    precios = []
    maximos = []
    minimos = []

    with open(ruta, newline="", encoding="utf-8-sig") as archivo:
        lector = csv.DictReader(archivo)
        if not lector.fieldnames:
            raise ValueError("El CSV no contiene encabezados.")

        columnas = {
            nombre.strip().lower(): nombre
            for nombre in lector.fieldnames
        }
        if "close" not in columnas:
            raise ValueError("El CSV debe tener una columna 'close'.")

        for fila in lector:
            try:
                cierre = float(fila[columnas["close"]])
                if not math.isfinite(cierre) or cierre <= 0:
                    continue
                precios.append(cierre)

                if "high" in columnas and "low" in columnas:
                    alto = float(fila[columnas["high"]])
                    bajo = float(fila[columnas["low"]])
                    if (not math.isfinite(alto)
                            or not math.isfinite(bajo)
                            or alto < bajo):
                        raise ValueError("Máximo/mínimo inválido.")
                    maximos.append(alto)
                    minimos.append(bajo)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Fila con precio inválido: {fila}"
                ) from exc

    if not precios:
        raise ValueError("No hay precios de cierre válidos.")

    return precios, maximos, minimos


def analizar(precios, maximos=None, minimos=None):
    cierre = precios[-1]
    e20 = ema(precios, 20)
    e50 = ema(precios, 50)
    e200 = ema(precios, 200)
    indice_rsi = rsi(precios)

    disponibles = [x for x in (e20, e50, e200) if x is not None]

    if e20 is not None and e50 is not None:
        if cierre > e20 > e50 and (e200 is None or e50 > e200):
            tendencia = "alcista"
        elif cierre < e20 < e50 and (e200 is None or e50 < e200):
            tendencia = "bajista"
        else:
            tendencia = "lateral/mixta"
    else:
        tendencia = "datos insuficientes para determinar la tendencia"

    soporte = min(minimos[-20:]) if minimos else min(precios[-20:])
    resistencia = max(maximos[-20:]) if maximos else max(precios[-20:])

    return {
        "cierre": cierre,
        "ema20": e20,
        "ema50": e50,
        "ema200": e200,
        "rsi14": indice_rsi,
        "tendencia": tendencia,
        "soporte": soporte,
        "resistencia": resistencia,
        "velas": len(precios),
        "ema_disponibles": len(disponibles),
    }


def fmt(valor):
    return "no disponible" if valor is None else f"{valor:.6f}"


def guardar(simbolo, temporalidad, resultado):
    detalle = (
        f"Cierre={resultado['cierre']}; "
        f"EMA20={resultado['ema20']}; "
        f"EMA50={resultado['ema50']}; "
        f"EMA200={resultado['ema200']}; "
        f"RSI14={resultado['rsi14']}; "
        f"Soporte={resultado['soporte']}; "
        f"Resistencia={resultado['resistencia']}; "
        f"Velas={resultado['velas']}"
    )

    with sqlite3.connect(DB) as con:
        con.execute("""
            INSERT INTO analisis
            (simbolo, temporalidad, direccion, detalle, creado_en)
            VALUES (?, ?, ?, ?, ?)
        """, (
            simbolo.upper(),
            temporalidad,
            resultado["tendencia"],
            detalle,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ))


def main():
    parser = argparse.ArgumentParser(
        description="Análisis técnico local de TITAN INTEGRAL"
    )
    parser.add_argument("--csv", required=True, help="Archivo OHLCV CSV")
    parser.add_argument("--simbolo", required=True, help="Ej. XAUUSD o BTCUSD")
    parser.add_argument("--temporalidad", required=True, choices=sorted(TEMPORALIDADES))
    args = parser.parse_args()

    ruta = Path(args.csv)
    if not ruta.is_file():
        raise SystemExit(f"No existe el CSV: {ruta}")
    if not DB.is_file():
        raise SystemExit("No existe titan_integral.db; inicializa primero el proyecto.")

    precios, maximos, minimos = cargar_csv(ruta)
    resultado = analizar(precios, maximos, minimos)

    print("\n===== TITAN INTEGRAL | ANÁLISIS LOCAL =====")
    print("Símbolo:", args.simbolo.upper())
    print("Temporalidad declarada:", args.temporalidad)
    print("Velas leídas:", resultado["velas"])
    print("Último cierre:", fmt(resultado["cierre"]))
    print("EMA20:", fmt(resultado["ema20"]))
    print("EMA50:", fmt(resultado["ema50"]))
    print("EMA200:", fmt(resultado["ema200"]))
    print("RSI14:", fmt(resultado["rsi14"]))
    print("Tendencia:", resultado["tendencia"])
    print("Soporte aproximado:", fmt(resultado["soporte"]))
    print("Resistencia aproximada:", fmt(resultado["resistencia"]))

    if len(precios) < 200:
        print("Aviso: se necesitan al menos 200 cierres para calcular EMA200.")

    if resultado["rsi14"] is not None:
        if resultado["rsi14"] >= 70:
            print("RSI: zona elevada (>=70); no es señal de venta por sí sola.")
        elif resultado["rsi14"] <= 30:
            print("RSI: zona baja (<=30); no es señal de compra por sí sola.")

    guardar(args.simbolo, args.temporalidad, resultado)
    print("Análisis guardado en SQLite.")
    print("Modo exclusivamente analítico: no ejecuta operaciones.")


if __name__ == "__main__":
    main()
