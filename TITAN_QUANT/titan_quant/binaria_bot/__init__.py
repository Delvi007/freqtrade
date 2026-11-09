"""TITAN QUANT · Bot de opciones BINARIAS (clase Binaria de IQ Option).

Alcance: solo Binaria. Blitz y Digital no forman parte de este paquete.
Este paquete NO envía órdenes por sí mismo. Las órdenes pasan por el adaptador
de PRACTICE (titan_quant/binaria_sim), que exige cuenta PRACTICE.

Módulos:
  datos.py        carga de velas 5 s y agregación a M1 sin información futura
  estadistica.py  intervalo de Wilson, punto de equilibrio y valor esperado
  riesgo.py       límites inmutables, gestor de riesgo, sin martingala
  backtest.py     laboratorio walk-forward (parámetros fijos por tramo, sin optimizar)
"""
