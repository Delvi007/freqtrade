"""Almacén de velas históricas validadas.

`AlmacenVelas(ruta)` guarda velas en SU PROPIO archivo SQLite. Cada motor de backtesting usa el suyo, de modo que
el histórico del mercado binario (IQ Option) y el de cTrader nunca comparten base ni tabla:
    datos/backtest_binaria/historico.db   (titan_quant.backtest_binaria)
    datos/backtest_ctrader/historico.db   (titan_quant.backtest_ctrader)
Las funciones de módulo (guardar, leer, huecos, descargar_incremental…) mantienen la API de la fase 1 sobre
titan_quant.db, por compatibilidad.

- Cada vela conserva su proveedor de origen; nunca se mezclan proveedores sin filtrar.
- Validación OHLC: precios finitos y > 0, h >= max(o,c), l <= min(o,c), h >= l. Las velas inválidas se rechazan y se cuentan.
- Duplicados: en la misma descarga se conserva la última; entre descargas, la fila se reemplaza (idempotente).
- Huecos: se reportan los intervalos con separación mayor a 1.5 veces el paso; los cierres de fin de semana
  del mercado de forex se marcan como esperados.
- Descarga incremental: parte desde la última vela guardada; no vuelve a pedir lo ya almacenado.

El adaptador de descarga expone `velas(sid, intervalo, desde_ms, hasta_ms, cuenta=None)` y devuelve filas
[ts_segundos, open, high, low, close, volumen], como `trader.ctrader_ws.SesionCTrader.velas`.
"""
import math
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from . import db

SEG = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "60m": 3600, "1h": 3600, "4h": 14400, "1d": 86400, "1wk": 604800}
MAX_LOTE = 5000
MAX_ITERACIONES = 10000

ESQUEMA = """CREATE TABLE IF NOT EXISTS velas_historicas(
    proveedor TEXT NOT NULL, simbolo TEXT NOT NULL, intervalo TEXT NOT NULL, ts INTEGER NOT NULL,
    o REAL NOT NULL, h REAL NOT NULL, l REAL NOT NULL, c REAL NOT NULL, volumen REAL,
    descargado_ts INTEGER NOT NULL,
    PRIMARY KEY(proveedor, simbolo, intervalo, ts))"""


def _paso(intervalo):
    if intervalo not in SEG:
        raise ValueError("Intervalo no soportado: " + str(intervalo))
    return SEG[intervalo]


def _valida(fila):
    try:
        ts, o, h, l, c, v = fila[0], fila[1], fila[2], fila[3], fila[4], (fila[5] if len(fila) > 5 else 0)
        ts = int(ts)
        o, h, l, c = float(o), float(h), float(l), float(c)
    except (TypeError, ValueError, IndexError):
        return None, "formato"
    if ts <= 0:
        return None, "ts"
    if not all(math.isfinite(x) and x > 0 for x in (o, h, l, c)):
        return None, "precio"
    if not (h >= l and h >= max(o, c) and l <= min(o, c)):
        return None, "ohlc"
    try:
        vol = float(v) if v is not None and math.isfinite(float(v)) and float(v) >= 0 else 0.0
    except (TypeError, ValueError):
        vol = 0.0
    return (ts, o, h, l, c, vol), None


def _fin_de_semana(ts_ini, ts_fin):
    """Cierre de forex: viernes ~21:00 UTC a domingo ~21:00 UTC."""
    import datetime as dt
    a = dt.datetime.fromtimestamp(ts_ini, dt.timezone.utc)
    return a.weekday() == 4 and a.hour >= 20 and (ts_fin - ts_ini) <= 60 * 60 * 56


class AlmacenVelas:
    """Velas validadas en un archivo SQLite propio. `tx` y `q` pueden inyectarse (compatibilidad con titan_quant.db)."""

    def __init__(self, ruta=None, tx=None, q=None):
        self.ruta = Path(ruta) if ruta else None
        self._tx_ext, self._q_ext = tx, q
        self._local = threading.local()
        self._listo = False

    # --- conexión propia
    def _con(self):
        c = getattr(self._local, "c", None)
        if c is None:
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
            c = sqlite3.connect(str(self.ruta), timeout=15, isolation_level=None, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA busy_timeout=15000")
            try:
                c.execute("PRAGMA journal_mode=WAL")
            except sqlite3.DatabaseError:
                pass
            try:
                os.chmod(self.ruta, 0o600)
            except OSError:
                pass
            self._local.c = c
        return c

    def cerrar(self):
        c = getattr(self._local, "c", None)
        if c is not None:
            c.close()
            self._local.c = None

    @contextmanager
    def tx(self):
        if self._tx_ext:
            with self._tx_ext() as c:
                yield c
            return
        c = self._con()
        c.execute("BEGIN IMMEDIATE")
        try:
            yield c
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise

    def q(self, sql, args=()):
        if self._q_ext:
            return self._q_ext(sql, args)
        return [dict(r) for r in self._con().execute(sql, args).fetchall()]

    def asegurar(self, extra=""):
        if self._listo and not extra:
            return
        with self.tx() as c:
            c.execute(ESQUEMA)
            for sent in [x for x in extra.split(";") if x.strip()]:
                c.execute(sent)
        self._listo = True

    # --- API
    def guardar(self, proveedor, simbolo, intervalo, velas):
        """Guarda velas validadas. Devuelve un resumen; nunca lanza por una vela mala."""
        self.asegurar()
        _paso(intervalo)
        limpias, rechazadas = {}, {"formato": 0, "ts": 0, "precio": 0, "ohlc": 0}
        for fila in velas:
            v, motivo = _valida(fila)
            if motivo:
                rechazadas[motivo] += 1
                continue
            limpias[v[0]] = v                       # dentro del lote, la última gana
        duplicadas_lote = len(velas) - sum(rechazadas.values()) - len(limpias)
        ahora = int(time.time())
        with self.tx() as c:
            c.executemany(
                "INSERT OR REPLACE INTO velas_historicas(proveedor,simbolo,intervalo,ts,o,h,l,c,volumen,descargado_ts) VALUES(?,?,?,?,?,?,?,?,?,?)",
                [(proveedor, simbolo, intervalo, v[0], v[1], v[2], v[3], v[4], v[5], ahora) for v in limpias.values()])
        return {"guardadas": len(limpias), "rechazadas": sum(rechazadas.values()), "motivos_rechazo": rechazadas,
                "duplicadas_en_lote": duplicadas_lote}

    def ultimo_ts(self, proveedor, simbolo, intervalo):
        self.asegurar()
        r = self.q("SELECT MAX(ts) AS t FROM velas_historicas WHERE proveedor=? AND simbolo=? AND intervalo=?",
                   (proveedor, simbolo, intervalo))
        return r[0]["t"] if r and r[0]["t"] is not None else None

    def leer(self, proveedor, simbolo, intervalo, desde=None, hasta=None):
        self.asegurar()
        sql = "SELECT ts,o,h,l,c,volumen FROM velas_historicas WHERE proveedor=? AND simbolo=? AND intervalo=?"
        args = [proveedor, simbolo, intervalo]
        if desde is not None:
            sql += " AND ts>=?"
            args.append(int(desde))
        if hasta is not None:
            sql += " AND ts<=?"
            args.append(int(hasta))
        return [[r["ts"], r["o"], r["h"], r["l"], r["c"], r["volumen"]] for r in self.q(sql + " ORDER BY ts", args)]

    def inventario(self):
        self.asegurar()
        return self.q("""SELECT proveedor, simbolo, intervalo, COUNT(*) n, MIN(ts) desde, MAX(ts) hasta
                         FROM velas_historicas GROUP BY proveedor, simbolo, intervalo ORDER BY simbolo, intervalo""")

    def huecos(self, proveedor, simbolo, intervalo, desde=None, hasta=None):
        paso = _paso(intervalo)
        filas = self.leer(proveedor, simbolo, intervalo, desde, hasta)
        out = []
        for (t1, *_), (t2, *_) in zip(filas, filas[1:]):
            if t2 - t1 > 1.5 * paso:
                out.append({"desde": t1, "hasta": t2, "faltantes": int((t2 - t1) // paso) - 1,
                            "fin_de_semana": _fin_de_semana(t1, t2)})
        return out

    def descargar_incremental(self, adaptador, proveedor, simbolo, sid, intervalo, desde_ts, hasta_ts, lote=1000):
        """Descarga y guarda velas desde la última almacenada (o desde `desde_ts`) hasta `hasta_ts`."""
        self.asegurar()
        paso = _paso(intervalo)
        lote = max(1, min(int(lote), MAX_LOTE))
        ult = self.ultimo_ts(proveedor, simbolo, intervalo)
        inicio = int(desde_ts) if ult is None else max(int(desde_ts), ult + paso)
        total = {"guardadas": 0, "rechazadas": 0, "duplicadas_en_lote": 0, "peticiones": 0}
        fin = int(hasta_ts)
        while inicio < fin:
            if total["peticiones"] >= MAX_ITERACIONES:
                raise RuntimeError("Se alcanzó el máximo de peticiones; repite la descarga para continuar.")
            tope = min(fin, inicio + lote * paso)
            filas = adaptador.velas(sid, intervalo, inicio * 1000, tope * 1000, cuenta=lote)
            total["peticiones"] += 1
            filas = [f for f in filas if inicio <= int(f[0]) < tope]
            if filas:
                r = self.guardar(proveedor, simbolo, intervalo, filas)
                for k in ("guardadas", "rechazadas", "duplicadas_en_lote"):
                    total[k] += r[k]
                inicio = max(int(f[0]) for f in filas) + paso
            else:
                inicio = tope
        return total


# ----------------------------------------------------------------- API de la fase 1 (titan_quant.db)
_PRINCIPAL = AlmacenVelas(tx=db.tx, q=lambda sql, args: db.q(sql, args))


def _asegurar():
    _PRINCIPAL._listo = False
    _PRINCIPAL.asegurar()


def guardar(proveedor, simbolo, intervalo, velas):
    _asegurar()
    return _PRINCIPAL.guardar(proveedor, simbolo, intervalo, velas)


def ultimo_ts(proveedor, simbolo, intervalo):
    _asegurar()
    return _PRINCIPAL.ultimo_ts(proveedor, simbolo, intervalo)


def leer(proveedor, simbolo, intervalo, desde=None, hasta=None):
    _asegurar()
    return _PRINCIPAL.leer(proveedor, simbolo, intervalo, desde, hasta)


def huecos(proveedor, simbolo, intervalo, desde=None, hasta=None):
    _asegurar()
    return _PRINCIPAL.huecos(proveedor, simbolo, intervalo, desde, hasta)


def descargar_incremental(adaptador, proveedor, simbolo, sid, intervalo, desde_ts, hasta_ts, lote=1000):
    _asegurar()
    return _PRINCIPAL.descargar_incremental(adaptador, proveedor, simbolo, sid, intervalo, desde_ts, hasta_ts, lote)
