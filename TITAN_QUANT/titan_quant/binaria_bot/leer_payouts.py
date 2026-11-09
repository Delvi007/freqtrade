"""Lee los payouts de los pares OTC de divisas desde el broker. SOLO LECTURA: no envía órdenes.

La librería iqoptionapi 7.1.1 expone get_all_profit() con dos claves por activo:
  'binary' y 'turbo', valores como fracción (0.86 = 86 %).
Cuál clave corresponde a la "Binaria" de la plataforma NO está verificado: por eso el lector
escribe las dos y muestra una tabla para compararlas con la captura de la plataforma.

Credenciales: solo desde variables de entorno de la ventana actual; no se guardan ni se imprimen.
"""
import argparse
import json
import os

from titan_quant.binaria_bot.escaner import es_par_otc

CLAVES = ("binary", "turbo")
RANGO_VALIDO = (0.0, 1.5)


def payouts_desde_perfil(datos, clave):
    """Filtra a pares OTC de divisas y valida el rango del valor. Lanza ValueError si la clave no existe."""
    if clave not in CLAVES:
        raise ValueError(f"clave desconocida: {clave!r}")
    salida = {}
    for nombre, valores in datos.items():
        if not es_par_otc(nombre):
            continue
        v = valores.get(clave) if hasattr(valores, "get") else None
        if v is None:
            continue
        v = float(v)
        if not (RANGO_VALIDO[0] < v < RANGO_VALIDO[1]):
            continue
        salida[nombre] = round(v, 4)
    return salida


def tabla_comparativa(datos):
    """Texto con ambas claves por par, para comparar con la captura de la plataforma."""
    filas = ["par            binary   turbo"]
    for nombre in sorted(datos):
        if not es_par_otc(nombre):
            continue
        b = datos[nombre].get("binary") if hasattr(datos[nombre], "get") else None
        t = datos[nombre].get("turbo") if hasattr(datos[nombre], "get") else None
        fb = f"{float(b):.2f}" if b is not None else "  -  "
        ft = f"{float(t):.2f}" if t is not None else "  -  "
        filas.append(f"{nombre:<14} {fb:>6}   {ft:>5}")
    return "\n".join(filas)


def main(argv=None):
    p = argparse.ArgumentParser(description="Lector de payouts (solo lectura)")
    p.add_argument("--carpeta-salida", required=True)
    a = p.parse_args(argv)

    email = os.environ.get("IQOPTION_EMAIL", "")
    password = os.environ.get("IQOPTION_PASSWORD", "")
    if not email or not password:
        print("Faltan credenciales en esta ventana.")
        return 2

    from iqoptionapi.stable_api import IQ_Option
    try:
        iq = IQ_Option(email, password)
        ok, motivo = iq.connect()
    except Exception as e:  # noqa: BLE001
        print(f"Error al conectar: {type(e).__name__}")
        return 3
    if not ok:
        print(f"No se conectó: {motivo}")
        return 3

    datos = iq.get_all_profit()
    print("Comparar con la captura de la plataforma (pares OTC de divisas):")
    print(tabla_comparativa(datos))
    os.makedirs(a.carpeta_salida, exist_ok=True)
    for clave in CLAVES:
        ruta = os.path.join(a.carpeta_salida, f"payouts_broker_{clave}.json")
        payouts = payouts_desde_perfil(datos, clave)
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(payouts, f, indent=2, ensure_ascii=False)
        print(f"{len(payouts)} pares escritos: {ruta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
