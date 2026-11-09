"""BACKTESTING DEL BOT CTRADER — sistema independiente del backtesting binario.

Todo lo que produce este paquete es un RESULTADO HISTÓRICO CALCULADO sobre velas pasadas de cTrader. Nunca es una
operación de cTrader, nunca entra en las bases de cuenta (datos/cuentas/*.db) ni en saldos o informes del broker.

Datos propios, separados de cualquier otro mercado:
    datos/backtest_ctrader/historico.db
        velas_historicas   velas (trendbars) validadas de cTrader DEMO, proveedor 'ctrader-demo'
        spreads            bid/ask observados en cTrader al recopilar (para costes medidos, no supuestos)
        informes           resultados de cada backtest, con su etiqueta, parámetros, costes y datos usados

Módulos:
    recolector.py   descarga incremental de trendbars de la cuenta cTrader DEMO (solo lectura) y registro del spread
    motor.py        backtest de las reglas del bot (EMA+RSI del motor 13 y Keltner+RCI con stop/objetivo ATR):
                    dentro/fuera de muestra, walk-forward, ventaja estadística y detección de sobreoptimización
"""
from .. import config
from ..historico import AlmacenVelas

ETIQUETA = "RESULTADO HISTÓRICO CALCULADO · backtesting cTrader · no es una operación de cTrader"
PROVEEDOR = "ctrader-demo"

ESQUEMA_EXTRA = """
CREATE TABLE IF NOT EXISTS spreads(simbolo TEXT NOT NULL, ts INTEGER NOT NULL, bid REAL NOT NULL, ask REAL NOT NULL,
    spread REAL NOT NULL, fuente TEXT NOT NULL, PRIMARY KEY(simbolo, ts));
CREATE TABLE IF NOT EXISTS informes(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, etiqueta TEXT NOT NULL,
    simbolo TEXT NOT NULL, intervalo TEXT NOT NULL, proveedor TEXT NOT NULL, estrategia TEXT NOT NULL, desde INTEGER, hasta INTEGER,
    velas INTEGER, costo_por_lado REAL, costo_fuente TEXT, parametros TEXT, resultado TEXT NOT NULL)
"""


def ruta():
    return config.DATOS / "backtest_ctrader" / "historico.db"


_ALM = {}


def almacen():
    r = str(ruta())
    a = _ALM.get(r)
    if a is None:
        a = AlmacenVelas(ruta())
        a.asegurar(ESQUEMA_EXTRA)
        for viejo in _ALM.values():
            viejo.cerrar()
        _ALM.clear()
        _ALM[r] = a
    return a
