# TITAN QUANT · Bot de binarias · ENTREGA PARCIAL

Estado: NO está listo para operar. Es una base verificada en sandbox, sin pruebas en vivo.

## Qué incluye (verificado con pruebas offline)
- `binaria_bot/datos.py`: velas 5 s → M1, con cobertura exigida y tramos sin huecos.
- `binaria_bot/estadistica.py`: punto de equilibrio, valor esperado, intervalo de Wilson.
- `binaria_bot/riesgo.py`: límites inmutables, monto fijo, sin martingala, kill switch.
- `binaria_bot/backtest.py`: walk-forward con parámetros fijos, entrada en apertura de j+1, salida en cierre de j+5.
- `binaria_bot/laboratorio.py`: informe por tramo sobre un archivo de la sonda (solo análisis).
- `binaria_bot/autonomia.py`: cuatro niveles; automático solo con evidencia en todos los tramos.
- `binaria_bot/almacen.py`: base SQLite propia (`binaria_bot.db`).
- `binaria_bot/orquestador.py`: une señal, autonomía, riesgo, adaptador y base de datos.
- `binaria_bot/motores_puente.py`: 10 motores de TITAN en modo offline, sin escribir en la base de TITAN.
- `binaria_sim/captura_options.py`: parche del mensaje `options` de iqoptionapi 7.1.1 (probado con módulo simulado).
- `binaria_sim/adaptador_practica.py`: adaptador de PRACTICE (sin cambios desde la revisión previa).

## Qué NO está hecho
1. Prueba en vivo del parche `options` con `prueba_lectura_practica.py` (la ejecuta el operador, solo lectura).
2. Evidencia de rentabilidad sobre datos reales: aún no se ha ejecutado el laboratorio sobre `sonda_iqoption/crudas`.
3. Las salidas de los motores NO afectan decisiones; están solo como información.
4. Panel BOT OPERADOR y enlace en `servidor.py` (requiere autorización explícita).
5. Parada de emergencia validada contra la UI real.

## Limitaciones conocidas
- Horizonte de los motores: `scalping` (6 velas), no 5 velas M1 exactas.
- `microstructure` usa un spread estimado (sin bid/ask del proveedor).
- Ninguna cifra de rentabilidad está demostrada.

## Cómo verificar
Desde la carpeta TITAN_QUANT:
    python -m unittest discover -s titan_quant/pruebas -t .
