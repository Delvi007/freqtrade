"""Arranca el servidor con datos SINTÉTICOS (sin internet) para pruebas de navegador. Uso: python3 -m titan_quant.pruebas.servidor_prueba PUERTO"""
import sys

from titan_quant.pruebas import sintetico

sintetico.instalar()
from titan_quant import servidor  # noqa: E402
from titan_quant.pruebas.ctrader_falso import CTraderFalso  # noqa: E402

CTraderFalso().iniciar()          # cTrader DEMO y LIVE simulados (client_id app-prueba / secreto-app / token tok-trading)

puerto = int(sys.argv[1]) if len(sys.argv) > 1 else 8799
srv = servidor.crear("127.0.0.1", puerto)
print("listo", puerto, flush=True)
srv.serve_forever()
