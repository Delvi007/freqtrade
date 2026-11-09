"""TITAN UNIVERSAL BROKER CONNECTIVITY CENTER.

    catalogo.py        matriz de brokers (documentación oficial, APIs, autenticación, DEMO/REAL, requisitos, verificación en vivo)
    base.py            interfaz común de conector + cliente HTTP con límites, tiempo máximo y registro de actividad
    conectores/        conectores reales (OANDA, Alpaca, Tradier, Kraken, Coinbase Advanced) + puentes a cTrader e IQ Option
    centro.py          configuración por broker (interruptor ON/OFF, entorno, credenciales en la bóveda), diagnóstico y estado
    sincronizacion.py  el broker como fuente de verdad: cuenta, posiciones, órdenes y ejecuciones (comisiones, swaps, parciales)

Reglas: no se inventan endpoints ni capacidades; un conector solo figura «verificado» con prueba real; la cuenta REAL
nunca opera automáticamente; las credenciales viven cifradas en la bóveda y nunca salen en registros ni en la interfaz.
"""
