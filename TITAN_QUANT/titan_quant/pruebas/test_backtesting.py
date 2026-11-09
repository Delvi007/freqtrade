"""Los DOS motores de backtesting (binarias y cTrader): bases separadas, resultados etiquetados como
históricos calculados, sin ventaja ficticia en datos aleatorios, sin payout/coste inventado y sin mirar al futuro."""
import json
import random
import sqlite3

from titan_quant import backtest_binaria as bb
from titan_quant import backtest_ctrader as bc
from titan_quant.backtest_binaria import motor as mb
from titan_quant.backtest_binaria import recolector as rb
from titan_quant.backtest_ctrader import motor as mc
from titan_quant.backtest_ctrader import recolector as rc
from titan_quant.pruebas.base_prueba import Base
from titan_quant.trader import almacen

T0 = 1_793_000_000 - 1_793_000_000 % 3600


def paseo(n, paso, semilla=1, deriva=0.0, vol=0.0004):
    rnd, px, out = random.Random(semilla), 1.0, []
    for i in range(n):
        o = px
        px *= 1 + deriva + rnd.gauss(0, vol)
        h, l = max(o, px) * (1 + abs(rnd.gauss(0, vol / 2))), min(o, px) * (1 - abs(rnd.gauss(0, vol / 2)))
        out.append([T0 + i * paso, o, h, l, px, 0.0])
    return out


class SesionVelas:
    """Imita stable_api.get_candles de IQ Option (lotes desde `end` hacia atrás)."""
    def __init__(self, filas):
        self.filas = filas

    def get_candles(self, activo, seg, n, end):
        sel = [f for f in self.filas if f[0] <= end][-n:]
        return [{"from": f[0], "open": f[1], "max": f[2], "min": f[3], "close": f[4], "volume": 0} for f in sel]


class TestBacktestBinaria(Base):
    def test_base_propia_y_etiqueta(self):
        bb.almacen().guardar("iqoption", "EURGBP-OTC", "1m", paseo(3000, 60))
        rb.registrar_payout("EURGBP-OTC", 0.86)
        r = mb.ejecutar("EURGBP-OTC")
        self.assertEqual(r["etiqueta"], bb.ETIQUETA)
        self.assertIn("no es una operación de IQ Option", r["etiqueta"])
        self.assertEqual(r["payout"], 0.86)
        self.assertTrue(r["payout_fuente"].startswith("mediana"))
        self.assertEqual(len(r["walk_forward"]), 4)
        self.assertIn("sobreoptimizacion_probable", r["sobreoptimizacion"])
        self.assertNotEqual(bb.ruta(), bc.ruta())
        tablas = {x[0] for x in sqlite3.connect(bb.ruta()).execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"velas_historicas", "payouts", "informes"} <= tablas)
        self.assertFalse({"operaciones", "usuarios", "credenciales"} & tablas)
        self.assertEqual(almacen.q("binaria", "SELECT * FROM operaciones"), [])            # nada pasa a la cuenta del broker
        self.assertEqual(len(mb.informes()), 1)

    def test_sin_ventaja_ficticia_en_paseo_aleatorio(self):
        bb.almacen().guardar("iqoption", "EURUSD-OTC", "1m", paseo(8000, 60, semilla=7))
        r = mb.ejecutar("EURUSD-OTC", payout=0.80, guardar=False)
        self.assertFalse(r["global"]["ventaja_significativa"])
        self.assertFalse(r["evidencia_fuera_de_muestra"]["suficiente"])

    def test_sin_payout_ni_datos_no_inventa(self):
        with self.assertRaises(mb.SinDatosBacktest):
            mb.ejecutar("EURGBP-OTC")                                                         # sin velas
        bb.almacen().guardar("iqoption", "EURGBP-OTC", "1m", paseo(500, 60))
        with self.assertRaises(mb.SinDatosBacktest):
            mb.ejecutar("EURGBP-OTC")                                                         # sin payout observado
        self.assertFalse(rb.registrar_payout("EURGBP-OTC", None))

    def test_recolector_iqoption_incremental_y_solo_velas_cerradas(self):
        filas = paseo(2500, 60)
        ahora = filas[-1][0] + 30                                                            # la última vela sigue en formación
        s = SesionVelas(filas)
        r = rb.recopilar_iqoption("EURGBP-OTC", 3000, sesion=s, resolver=lambda a: (a, "turbo", True), ahora=ahora)
        self.assertEqual(r["guardadas"], 2499)
        self.assertEqual(bb.almacen().ultimo_ts("iqoption", "EURGBP-OTC", "1m"), filas[-2][0])
        r2 = rb.recopilar_iqoption("EURGBP-OTC", 3000, sesion=s, resolver=lambda a: (a, "turbo", True), ahora=ahora)
        self.assertEqual(r2["guardadas"], 0)

    def test_sobreoptimizacion_detectada_cuando_la_mejor_falla_fuera(self):
        filas = [mb.Vela(ts=f[0], open=f[1], high=f[2], low=f[3], close=f[4]) for f in paseo(6000, 60, semilla=11)]
        s = mb.sobreoptimizacion(filas, 0.86)
        self.assertTrue(s["evaluable"])
        self.assertGreater(s["combinaciones"], 10)
        if s["mejor_dentro"]["ev_fuera"] is not None and s["mejor_dentro"]["ev_dentro"] > 0 >= s["mejor_dentro"]["ev_fuera"]:
            self.assertTrue(s["sobreoptimizacion_probable"])


class TestBacktestCTrader(Base):
    def test_base_propia_coste_medido_y_etiqueta(self):
        bc.almacen().guardar(bc.PROVEEDOR, "XAUUSD", "15m", paseo(2000, 900))
        with self.assertRaises(mc.SinDatosBacktest):
            mc.ejecutar("XAUUSD")                                                             # sin spread observado: no se inventa
        with bc.almacen().tx() as c:
            c.execute("INSERT INTO spreads(simbolo,ts,bid,ask,spread,fuente) VALUES('XAUUSD',1,0.9999,1.0001,0.0002,'prueba')")
        r = mc.ejecutar("XAUUSD")
        self.assertIn("no es una operación de cTrader", r["etiqueta"])
        self.assertIn("medido en cTrader", r["costo_fuente"])
        self.assertAlmostEqual(r["costo_por_lado_frac"] * 1.0, 0.0001, delta=0.00003)
        for k in ("dentro_de_muestra", "fuera_de_muestra", "walk_forward", "sobreoptimizacion", "ventaja_fuera_de_muestra"):
            self.assertIn(k, r)
        tablas = {x[0] for x in sqlite3.connect(bc.ruta()).execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"velas_historicas", "spreads", "informes"} <= tablas)
        self.assertEqual(almacen.q("demo", "SELECT * FROM operaciones"), [])
        # Los históricos no se mezclan: el binario no ve las velas de cTrader ni al revés.
        self.assertEqual(bb.almacen().inventario(), [])
        self.assertEqual([x["simbolo"] for x in bc.almacen().inventario()], ["XAUUSD"])

    def test_estrategias_y_sin_ventaja_ficticia(self):
        bc.almacen().guardar(bc.PROVEEDOR, "EURUSD", "15m", paseo(4000, 900, semilla=5))
        for est in mc.ESTRATEGIAS:
            with self.subTest(est=est):
                r = mc.ejecutar("EURUSD", estrategia=est, costo_por_lado_pct=0.005, guardar=False)
                self.assertEqual(r["costo_fuente"], "SUPUESTO indicado por el usuario")
                self.assertFalse(r["ventaja_fuera_de_muestra"]["significativa"])

    def test_sin_informacion_futura(self):
        filas = paseo(1500, 900, semilla=9)
        s = {"t": [f[0] for f in filas], "o": [f[1] for f in filas], "h": [f[2] for f in filas], "l": [f[3] for f in filas], "c": [f[4] for f in filas]}
        completo = mc.operaciones(s, "keltner_rci_atr", mc.ESTRATEGIAS["keltner_rci_atr"], 8, 0.0)
        corte = 1000
        parcial = mc.operaciones({k: v[:corte] for k, v in s.items()}, "keltner_rci_atr", mc.ESTRATEGIAS["keltner_rci_atr"], 8, 0.0)
        # Toda operación cerrada antes del corte con la serie parcial es idéntica con la serie completa.
        cerradas = [t for t in parcial if t["i"] + 1 + 16 < corte]
        self.assertTrue(cerradas)
        for t in cerradas:
            self.assertIn((t["i"], t["dir"], round(t["r"], 9)), {(x["i"], x["dir"], round(x["r"], 9)) for x in completo})

    def test_recolector_usa_la_cuenta_demo_y_guarda_spread(self):
        from titan_quant.pruebas.ctrader_falso import CTraderFalso
        from titan_quant.seguridad import boveda
        from titan_quant.trader.ctrader import CTrader
        u = self.usuario()["id"]
        with CTraderFalso() as f:
            boveda.guardar(u, "ctrader", {"client_id": f.mundo.client_id, "client_secret": f.mundo.client_secret,
                                          "redirect_uri": "http://x/cb", "access_token": "tok-trading", "refresh_token": "ref-1"})
            r = rc.recopilar(u, 9001, "XAUUSD", "1h", 3)
            self.assertEqual(r["proveedor"], "ctrader-demo")
            self.assertGreater(r["guardadas"], 0)
            self.assertIsNotNone(rc.spread_observado("XAUUSD")[0])
            with self.assertRaises(Exception):
                rc.recopilar(u, 7001, "XAUUSD", "1h", 3)                                     # cuenta REAL: no se usa
            self.assertEqual([o for o in f.mundo.ordenes], [])                               # recopilar nunca envía órdenes
        self.assertTrue(json.dumps(bc.almacen().inventario()))
        self.assertTrue(issubclass(CTrader, object))


class TestEscanerBinariaRobusto(Base):
    def test_un_par_que_falla_no_aborta_el_escaneo(self):
        from unittest import mock
        from titan_quant.backtest_binaria import escaner as escb
        filas = [{"activo": "COFFEE-OTC", "intervalo": "1m", "estrategia": "cruce_ema", "params": "{}", "payout": 0.8,
                  "acierto_fuera": 0.6, "equilibrio": 0.55, "n_fuera": 20},
                 {"activo": "EURUSD-OTC", "intervalo": "1m", "estrategia": "cruce_ema", "params": "{}", "payout": 0.8,
                  "acierto_fuera": 0.6, "equilibrio": 0.55, "n_fuera": 20}]
        pedidos = []

        class Ad:
            def velas(self, par, tf, n):
                pedidos.append(par)
                if par == "COFFEE-OTC":
                    raise RuntimeError("COFFEE-OTC: no se pudo consultar el catálogo IQ Option")
                return []
        with mock.patch.object(escb, "mejores", return_value=filas):
            self.assertEqual(escb.senales_vivas(Ad(), {"estrategias": ["cruce_ema"], "max_simbolos": 5}), [])
        self.assertEqual(pedidos, ["COFFEE-OTC", "EURUSD-OTC"])          # el segundo par se sigue analizando


class TestEscaneoCompleto(Base):
    def test_binaria_mira_todos_los_aptos_y_pide_velas_una_vez(self):
        from unittest import mock
        from titan_quant.backtest_binaria import escaner as escb
        fila = lambda par, est: {"activo": par, "intervalo": "1m", "estrategia": est, "params": "{}", "payout": 0.8,
                                 "acierto_fuera": 0.6, "equilibrio": 0.55, "n_fuera": 20}
        filas = [fila(f"P{i}-OTC", e) for i in range(40) for e in ("cruce_ema", "rsi_reversion")]
        pedidos = []

        class Ad:
            def velas(self, par, tf, n):
                pedidos.append(par)
                return []
        with mock.patch.object(escb, "mejores", return_value=filas):
            escb.senales_vivas(Ad(), {"estrategias": ["cruce_ema", "rsi_reversion"], "max_simbolos": 1000})
        self.assertEqual(len(pedidos), 40)                                 # los 40 pares, una sola petición cada uno

    def test_presupuesto_corta_el_barrido_por_los_peores(self):
        from unittest import mock
        from titan_quant.backtest_binaria import escaner as escb
        filas = [{"activo": f"P{i}-OTC", "intervalo": "1m", "estrategia": "cruce_ema", "params": "{}", "payout": 0.8,
                  "acierto_fuera": 0.6, "equilibrio": 0.55, "n_fuera": 20} for i in range(10)]
        pedidos = []

        class Ad:
            def velas(self, par, tf, n):
                pedidos.append(par)
                import time as t
                t.sleep(0.15)
                return []
        with mock.patch.object(escb, "mejores", return_value=filas):
            escb.senales_vivas(Ad(), {"estrategias": ["cruce_ema"], "max_simbolos": 1000, "presupuesto_senales_s": 0.3})
        self.assertLess(len(pedidos), 10)
        self.assertEqual(pedidos[0], "P0-OTC")                             # empieza siempre por el mejor clasificado

    def test_cursor_avanza_solo_lo_procesado(self):
        from titan_quant.backtest_binaria import escaner as escb
        escb._avanzar_cursor("binaria|turbo", 0, 2, 10)
        self.assertEqual(escb._posicion("binaria|turbo", 10), 2)
        escb._avanzar_cursor("binaria|turbo", 8, 3, 10)
        self.assertEqual(escb._posicion("binaria|turbo", 10), 1)          # da la vuelta
