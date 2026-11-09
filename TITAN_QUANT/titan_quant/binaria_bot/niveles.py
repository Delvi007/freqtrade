"""Niveles de exigencia para decidir operar. Se eligen a mano (--nivel); el sistema nunca los cambia solo.

  1 basico     Intervalo de Wilson al 95% sin corrección por comparaciones múltiples. Mínimo 30 resultados previos.
  2 estricto   Bonferroni sobre los pares analizados en el ciclo (alfa/k). Mínimo 100 resultados previos.
  3 exigente   Bonferroni sobre pares analizados. Mínimo 300 resultados previos.
               AVISO: no incluye aún validación fuera de muestra. Esa validación se añadirá cuando el bot
               opere y registre su historial. Hasta entonces, nivel 3 no es evidencia de rentabilidad.

Bonferroni: con k pares y alfa=0.05, cada par usa alfa/k en cada lado; z = Φ⁻¹(1 - alfa/(2k)).
"""
from statistics import NormalDist

ALFA = 0.05
NIVEL_DEFECTO = 2

NIVELES = {
    1: {"nombre": "basico", "corregido": False, "min_resueltas": 30},
    2: {"nombre": "estricto", "corregido": True, "min_resueltas": 100},
    3: {"nombre": "exigente", "corregido": True, "min_resueltas": 300},
}


def z_para(nivel, k_pares, alfa=ALFA):
    if nivel not in NIVELES:
        raise ValueError(f"nivel inválido: {nivel!r} (use 1, 2 o 3)")
    if not NIVELES[nivel]["corregido"]:
        return NormalDist().inv_cdf(1 - alfa / 2)
    if k_pares < 1:
        raise ValueError("k_pares debe ser >= 1")
    return NormalDist().inv_cdf(1 - alfa / (2 * k_pares))


def configurar(nivel=NIVEL_DEFECTO, k_pares=1, min_resueltas=None):
    """Devuelve {'nivel', 'nombre', 'z', 'min_resueltas'}. min_resueltas, si se indica, anula el del nivel."""
    if nivel not in NIVELES:
        raise ValueError(f"nivel inválido: {nivel!r} (use 1, 2 o 3)")
    minimo = NIVELES[nivel]["min_resueltas"] if min_resueltas is None else min_resueltas
    if not isinstance(minimo, int) or minimo < 1:
        raise ValueError("min_resueltas debe ser un entero >= 1")
    return {"nivel": nivel, "nombre": NIVELES[nivel]["nombre"],
            "z": z_para(nivel, k_pares), "min_resueltas": minimo}
