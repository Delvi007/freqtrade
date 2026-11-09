"""Medias móviles y True Range, implementaciones de referencia.

- SMA: media simple.
- EMA: alpha = 2/(n+1), semilla = SMA de las primeras n observaciones (convención de Pine Script ta.ema).
- RMA: alpha = 1/n (suavizado de Wilder), semilla = SMA de las primeras n observaciones (convención ta.rma).
- True Range: max(H-L, |H-C_prev|, |L-C_prev|); en la primera barra es H-L.
"""


def _validar_periodo(n):
    if not isinstance(n, int) or n < 1:
        raise ValueError("El periodo debe ser un entero >= 1")


def sma(valores, n):
    _validar_periodo(n)
    out = [None] * len(valores)
    for i in range(n - 1, len(valores)):
        out[i] = sum(valores[i - n + 1:i + 1]) / n
    return out


def _suavizar(valores, n, alpha):
    _validar_periodo(n)
    out = [None] * len(valores)
    if len(valores) < n:
        return out
    prev = sum(valores[:n]) / n
    out[n - 1] = prev
    for i in range(n, len(valores)):
        prev = alpha * valores[i] + (1.0 - alpha) * prev
        out[i] = prev
    return out


def ema(valores, n):
    return _suavizar(valores, n, 2.0 / (n + 1))


def rma(valores, n):
    return _suavizar(valores, n, 1.0 / n)


def true_range(high, low, close):
    if not (len(high) == len(low) == len(close)):
        raise ValueError("High, low y close deben tener la misma longitud")
    out = []
    for i in range(len(close)):
        if i == 0:
            out.append(high[0] - low[0])
        else:
            pc = close[i - 1]
            out.append(max(high[i] - low[i], abs(high[i] - pc), abs(low[i] - pc)))
    return out
