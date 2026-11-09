"""Herramientas de evaluación HISTÓRICA de la señal binaria original (Kernel Channel: Keltner + RCI).

Contenido que se conserva (backtesting, sin red, sin credenciales, sin órdenes):
  * senal.py         señal sobre velas M1 cerradas, vencimiento de 5 minutos
  * datos_csv.py     carga de velas desde un CSV exportado por el usuario (también la usa backtest_binaria.recolector)
  * backtest_csv.py  backtest y métricas de esa señal (antes llamado simulador.py): RESULTADOS HISTÓRICOS CALCULADOS

Retirado (v7.2.1-sin-simulacion): el «Bot binaria en modo simulación» (bot.py), su base de operaciones
simuladas (almacen.py), su gestor de riesgo (riesgo.py) y el adaptador desactivado (adaptador_iqoption.py).
No tenían uso en la operativa y abrían/cerraban operaciones ficticias. Las operaciones binarias reales se
ejecutan solo en IQ Option PRACTICE (trader/iqoption.py, modalidad 'binaria' del autotrader) y el backtesting
oficial del bot está en titan_quant/backtest_binaria.
"""
