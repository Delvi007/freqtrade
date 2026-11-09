"""RCI (Rank Correlation Index), correlación de Spearman entre precio y tiempo en una ventana de n barras.

    d_i = rango(precio_i) - rango(tiempo_i)  dentro de la ventana (la barra más reciente tiene el mayor tiempo)
    RCI = (1 - 6 * sum(d_i^2) / (n * (n^2 - 1))) * 100        rango en [-100, +100]

Empates de precio: se asigna el rango medio (convención estándar de Spearman).
Umbrales habituales: sobrecompra +80, sobreventa -80. Periodo por defecto: 14 (decisión del usuario); otros usados: 9, 20, 26, 52.
"""


def _rangos(valores):
    orden = sorted(range(len(valores)), key=lambda i: valores[i])
    rangos = [0.0] * len(valores)
    i = 0
    while i < len(orden):
        j = i
        while j + 1 < len(orden) and valores[orden[j + 1]] == valores[orden[i]]:
            j += 1
        medio = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            rangos[orden[k]] = medio
        i = j + 1
    return rangos


def rci(cierres, periodo=14):
    if not isinstance(periodo, int) or periodo < 2:
        raise ValueError("El periodo del RCI debe ser un entero >= 2")
    n = periodo
    out = [None] * len(cierres)
    tiempo = list(range(1, n + 1))
    for i in range(n - 1, len(cierres)):
        ventana = cierres[i - n + 1:i + 1]
        rp = _rangos(ventana)
        d2 = sum((rp[k] - tiempo[k]) ** 2 for k in range(n))
        out[i] = (1.0 - 6.0 * d2 / (n * (n * n - 1))) * 100.0
    return out
