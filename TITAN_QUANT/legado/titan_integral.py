#!/usr/bin/env python3
"""TITAN INTEGRAL: memoria de noticias, análisis y evaluación de pronósticos."""

import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

BASE = Path(__file__).resolve().parent
DB = BASE / "titan_integral.db"
NOTICIAS = BASE / "noticias_recopiladas.json"


def ahora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def conectar():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def inicializar():
    with conectar() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS noticias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            resumen TEXT DEFAULT '',
            enlace TEXT DEFAULT '',
            categoria TEXT DEFAULT 'Sin clasificar',
            fecha_fuente TEXT DEFAULT '',
            guardada_en TEXT NOT NULL,
            huella TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS analisis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            simbolo TEXT NOT NULL,
            temporalidad TEXT NOT NULL,
            direccion TEXT NOT NULL,
            detalle TEXT NOT NULL,
            creado_en TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS pronosticos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            simbolo TEXT NOT NULL,
            temporalidad TEXT NOT NULL,
            precio_inicial REAL,
            objetivo REAL,
            horizonte TEXT NOT NULL,
            direccion TEXT NOT NULL,
            creado_en TEXT NOT NULL,
            precio_final REAL,
            evaluado_en TEXT,
            resultado TEXT DEFAULT 'pendiente'
        );
        """)
    print(f"Base de datos lista: {DB.name}")


def importar_noticias():
    if not NOTICIAS.exists():
        print("No se encontró noticias_recopiladas.json")
        return

    try:
        datos = json.loads(NOTICIAS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print("No se pudieron leer las noticias:", type(exc).__name__)
        return

    if not isinstance(datos, list):
        print("Formato inesperado: se esperaba una lista JSON.")
        return

    import hashlib
    nuevas = 0

    with conectar() as con:
        for n in datos:
            if not isinstance(n, dict):
                continue

            titulo = str(
                n.get("titulo") or n.get("title") or ""
            ).strip()
            enlace = str(
                n.get("enlace") or n.get("link") or n.get("url") or ""
            ).strip()
            resumen = str(
                n.get("resumen") or n.get("summary")
                or n.get("description") or ""
            ).strip()
            categoria = str(
                n.get("categoria") or n.get("category")
                or "Sin clasificar"
            ).strip()
            fecha = str(
                n.get("fecha") or n.get("published") or ""
            ).strip()

            if not titulo:
                continue

            huella = hashlib.sha256(
                (titulo.lower() + "|" + enlace).encode("utf-8")
            ).hexdigest()

            cur = con.execute("""
                INSERT OR IGNORE INTO noticias
                (titulo, resumen, enlace, categoria, fecha_fuente,
                 guardada_en, huella)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                titulo, resumen, enlace, categoria, fecha, ahora(), huella
            ))
            nuevas += cur.rowcount

    print(f"Noticias procesadas: {len(datos)}")
    print(f"Noticias nuevas guardadas: {nuevas}")


def estado():
    with conectar() as con:
        for tabla in ("noticias", "analisis", "pronosticos"):
            total = con.execute(
                f"SELECT COUNT(*) FROM {tabla}"
            ).fetchone()[0]
            print(f"{tabla}: {total}")


def ultimas_noticias(limite=10):
    with conectar() as con:
        filas = con.execute("""
            SELECT titulo, categoria, fecha_fuente, enlace
            FROM noticias
            ORDER BY id DESC LIMIT ?
        """, (limite,)).fetchall()

    if not filas:
        print("Todavía no hay noticias en la memoria.")
        return

    for i, fila in enumerate(filas, 1):
        print(f"\n{i}. {fila['titulo']}")
        print(f"   Categoría: {fila['categoria']}")
        if fila["fecha_fuente"]:
            print(f"   Fecha: {fila['fecha_fuente']}")
        if fila["enlace"]:
            print(f"   Enlace: {fila['enlace']}")


def guardar_analisis(simbolo, temporalidad, direccion, detalle):
    with conectar() as con:
        con.execute("""
            INSERT INTO analisis
            (simbolo, temporalidad, direccion, detalle, creado_en)
            VALUES (?, ?, ?, ?, ?)
        """, (
            simbolo.upper(), temporalidad, direccion,
            detalle, ahora()
        ))
    print("Análisis guardado en la memoria.")


def guardar_pronostico(simbolo, temporalidad, precio, objetivo,
                       horizonte, direccion):
    with conectar() as con:
        con.execute("""
            INSERT INTO pronosticos
            (simbolo, temporalidad, precio_inicial, objetivo,
             horizonte, direccion, creado_en)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            simbolo.upper(), temporalidad, precio, objetivo,
            horizonte, direccion, ahora()
        ))
    print("Pronóstico registrado como pendiente de evaluación.")


def menu():
    inicializar()
    while True:
        print("""
====== TITAN INTEGRAL ======
1. Importar noticias existentes
2. Ver últimas noticias
3. Ver estado de la memoria
4. Guardar análisis manual
5. Registrar pronóstico
0. Salir
""")
        opcion = input("Selecciona una opción: ").strip()

        if opcion == "1":
            importar_noticias()
        elif opcion == "2":
            ultimas_noticias()
        elif opcion == "3":
            estado()
        elif opcion == "4":
            simbolo = input("Símbolo (ej. XAUUSD): ").strip()
            temporalidad = input("Temporalidad (ej. 1h): ").strip()
            direccion = input("Dirección (alcista/bajista/lateral): ").strip()
            detalle = input("Detalle del análisis: ").strip()
            if simbolo and temporalidad and direccion and detalle:
                guardar_analisis(simbolo, temporalidad, direccion, detalle)
            else:
                print("Todos los campos son obligatorios.")
        elif opcion == "5":
            simbolo = input("Símbolo: ").strip()
            temporalidad = input("Temporalidad: ").strip()
            precio_txt = input("Precio inicial (vacío si se desconoce): ").strip()
            objetivo_txt = input("Precio objetivo (vacío si se desconoce): ").strip()
            horizonte = input("Horizonte (ej. 4h o 1d): ").strip()
            direccion = input("Dirección (alcista/bajista/lateral): ").strip()
            try:
                precio = float(precio_txt) if precio_txt else None
                objetivo = float(objetivo_txt) if objetivo_txt else None
                if not all((simbolo, temporalidad, horizonte, direccion)):
                    raise ValueError("Faltan campos obligatorios.")
                guardar_pronostico(
                    simbolo, temporalidad, precio, objetivo,
                    horizonte, direccion
                )
            except ValueError as exc:
                print("Datos inválidos:", exc)
        elif opcion == "0":
            print("TITAN INTEGRAL finalizado.")
            break
        else:
            print("Opción no válida.")


if __name__ == "__main__":
    menu()
