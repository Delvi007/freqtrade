"""BACKTESTING DEL BOT DE BINARIAS (IQ Option) — sistema independiente.

Todo lo que produce este paquete es un RESULTADO HISTÓRICO CALCULADO sobre velas pasadas. Nunca es una operación
de IQ Option, nunca entra en las bases de cuenta (datos/cuentas/*.db) ni en saldos o informes del broker.

Datos propios, separados de cualquier otro mercado:
    datos/backtest_binaria/historico.db
        velas_historicas   velas M1 validadas (proveedor 'iqoption', 'sonda' o 'csv:<origen>')
        payouts            payouts observados en IQ Option (solo lectura del broker) por par y hora
        informes           resultados de cada backtest, con su etiqueta, parámetros y datos usados

Módulos:
    recolector.py   descarga incremental de velas M1 cerradas de IQ Option (PRACTICE, solo lectura) e importación
                    de archivos de la sonda (5 s → M1) y CSV
    motor.py        backtest de la estrategia del bot (Keltner + RCI, vencimiento 5 velas M1): walk-forward con
                    parámetros fijos, fuera de muestra, ventaja estadística (Wilson vs. equilibrio del payout) y
                    detección de sobreoptimización (optimización dentro de muestra → rango fuera de muestra)
"""
from .. import config
from ..historico import AlmacenVelas

ETIQUETA = "RESULTADO HISTÓRICO CALCULADO · backtesting binario · no es una operación de IQ Option"
INTERVALO = "1m"

ESQUEMA_EXTRA = """
CREATE TABLE IF NOT EXISTS payouts(activo TEXT NOT NULL, ts INTEGER NOT NULL, payout REAL NOT NULL, fuente TEXT NOT NULL,
    PRIMARY KEY(activo, ts));
CREATE TABLE IF NOT EXISTS informes(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, etiqueta TEXT NOT NULL,
    activo TEXT NOT NULL, proveedor TEXT NOT NULL, desde INTEGER, hasta INTEGER, velas INTEGER, payout REAL, payout_fuente TEXT,
    parametros TEXT, resultado TEXT NOT NULL)
"""


def ruta():
    return config.DATOS / "backtest_binaria" / "historico.db"


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
