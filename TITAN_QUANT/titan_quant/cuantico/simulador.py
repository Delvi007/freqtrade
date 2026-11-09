"""Simulador exacto de vector de estado (convención: cúbit 0 = bit menos significativo)."""
import numpy as np

MAX_CUBITS = 16


def estado_cero(n):
    if n > MAX_CUBITS:
        raise ValueError(f"Máximo {MAX_CUBITS} cúbits en el simulador.")
    s = np.zeros(2 ** n, complex)
    s[0] = 1
    return s


def puerta1(s, n, q, U):
    s = s.reshape([2] * n)
    eje = n - 1 - q
    s = np.moveaxis(np.tensordot(U, np.moveaxis(s, eje, 0), axes=1), 0, eje)
    return s.reshape(-1)


H = np.array([[1, 1], [1, -1]], complex) / np.sqrt(2)


def rx(t):
    c, s = np.cos(t / 2), np.sin(t / 2)
    return np.array([[c, -1j * s], [-1j * s, c]])


def ry(t):
    c, s = np.cos(t / 2), np.sin(t / 2)
    return np.array([[c, -s], [s, c]], complex)


def cz(s, n, a, b):
    idx = np.arange(2 ** n)
    m = ((idx >> a) & 1) & ((idx >> b) & 1)
    return s * np.where(m, -1, 1)


def hadamard_todos(n):
    return np.full(2 ** n, 1 / np.sqrt(2 ** n), complex)


def bits(i, n):
    return [(i >> q) & 1 for q in range(n)]


def probabilidades(s):
    return np.abs(s) ** 2
