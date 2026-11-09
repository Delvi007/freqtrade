"""Laboratorio cuántico EXPERIMENTAL de TITAN (C7) — aislado: no tiene acceso a los bots ni a los brokers.

Simula circuitos cuánticos con un simulador de vector de estado propio (numpy, exacto, hasta ~16 cúbits) y compara
SIEMPRE contra el óptimo clásico (fuerza bruta) y una heurística clásica (recocido simulado):
    qaoa.py   QAOA (Farhi, Goldstone & Gutmann 2014) para selección de cartera formulada como QUBO/Ising
    vqe.py    VQE (Peruzzo et al. 2014) con ansatz RY + CZ para el estado fundamental del mismo hamiltoniano
    qmc.py    estimación de amplitud cuántica (QAE canónica con QFT inversa) para el valor esperado de una distribución

No se atribuye ventaja cuántica: en un simulador clásico no la hay, y para estos tamaños el óptimo clásico es exacto.
Sirve para investigar formulaciones y estar preparado para hardware cuántico real (Qiskit/PennyLane) si algún día aporta.
"""
VERSION = "1.0.0"
