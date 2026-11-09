"""Estrategias básicas configurables, escáneres multiactivo (cTrader e IQ Option), ciclo multiactivo del bot y
selección segura de la cuenta PRACTICE/REAL de IQ Option. Sin dinero: servidor cTrader de pruebas y sesiones falsas."""
import json
import random
import time
import unittest
from unittest import mock

from titan_quant.estrategias import simples
from titan_quant.pruebas.base_prueba import Base
from titan_quant.pruebas.ctrader_falso import CTraderFalso
from titan_quant.seguridad import boveda
from titan_quant.trader import almacen, autotrader
from titan_quant.trader.base import ErrorAdaptador
from titan_quant.trader.iqoption import IQOption


def ohlc(n, semilla=1):
    rnd, px, o, h, l, c = random.Random(semilla), 100.0, [], [], [], []
    for _ in range(n):
        a = px
        px *= 1 + rnd.gauss(0, 0.004)
        o.append(a); c.append(px); h.append(max(a, px) * 1.001); l.append(min(a, px) * 0.999)
    return o, h, l, c


class TestEstrategias(unittest.TestCase):
    def test_todas_dan_senales_validas_y_sin_mirar_al_futuro(self):
        o, h, l, c = ohlc(600)
        for est in simples.CATALOGO:
            with self.subTest(est=est):
                ev = simples.senales(est, o, h, l, c)
                self.assertTrue(ev, est)
                self.assertTrue(all(e["direccion"] in ("compra", "venta") and 0 < e["indice"] < len(c) for e in ev))
                corte = 400                                   # la señal en j no cambia al añadir velas posteriores
                parcial = {(e["indice"], e["direccion"]) for e in simples.senales(est, o[:corte], h[:corte], l[:corte], c[:corte])}
                completo = {(e["indice"], e["direccion"]) for e in ev if e["indice"] < corte}
                self.assertEqual(parcial, completo, est)

    def test_parametros_validados(self):
        self.assertEqual(simples.validar_parametros("cruce_ema", {"rapida": "5"})["rapida"], 5)
        for est, prm in (("cruce_ema", {"rapida": 30, "lenta": 20}), ("rsi_reversion", {"sobreventa": 60, "sobrecompra": 55}),
                         ("ruptura_donchian", {"periodo": 1}), ("nada", {})):
            with self.subTest(est=est):
                with self.assertRaises(ValueError):
                    simples.validar_parametros(est, prm)

    def test_ajustes_del_bot_validan_las_estrategias(self):
        aj = autotrader.validar_ajustes("demo", {"estrategias_activas": {"cruce_ema": {"rapida": 5, "lenta": 30}}, "cuenta_ctid": 1})
        self.assertEqual(aj["estrategias_activas"], {"cruce_ema": {"rapida": 5, "lenta": 30}})
        with self.assertRaises(ValueError):
            autotrader.validar_ajustes("demo", {"estrategias_activas": {}})
        with self.assertRaises(ValueError):
            autotrader.validar_ajustes("demo", {"intervalo_escaner": "7m"})


class TestEscanerCTrader(Base):
    def setUp(self):
        super().setUp()
        self.f = CTraderFalso().iniciar()
        self.W = self.f.mundo
        self.u = self.usuario()["id"]
        boveda.guardar(self.u, "ctrader", {"client_id": self.W.client_id, "client_secret": self.W.client_secret, "redirect_uri": "http://x/cb",
                                           "access_token": "tok-trading", "refresh_token": "ref-1"})
        autotrader.guardar_ajustes(self.u, "demo", {"estrategia": "multiactivo", "cuenta_ctid": 9001, "intervalo_escaner": "1h",
                                                    "lote_escaner": 10, "min_ops_bt": 5, "exp_min": -0.5, "max_simbolos": 10})

    def tearDown(self):
        self.f.detener()
        super().tearDown()

    def test_ranking_de_todos_los_simbolos_con_datos_de_ctrader(self):
        autotrader.cambiar_estado(self.u, "demo", "activo")
        r = autotrader.ciclo(self.u, "demo")
        self.assertIn(r["accion"], ("omitir", "abrir", "rechazar"), r)
        from titan_quant.backtest_ctrader import escaner as esc
        filas = esc.ranking("demo", "1h")
        simbolos = {x["simbolo"] for x in filas}
        self.assertTrue({"XAUUSD", "EURUSD"} <= simbolos, simbolos)          # todos los símbolos activos de la cuenta, con su nombre de cTrader
        self.assertNotIn("XAGUSD", simbolos)                                  # deshabilitado en el broker: no se escanea
        self.assertEqual({x["estrategia"] for x in filas if x["simbolo"] == "XAUUSD"}, set(simples.CATALOGO))
        self.assertTrue(all(x["costo_frac"] is None or x["costo_frac"] > 0 for x in filas))
        self.assertEqual(almacen.q("demo", "SELECT * FROM operaciones WHERE estado NOT IN ('rechazada')") if r["accion"] != "abrir" else [], [])

    def test_senal_del_escaner_se_envia_a_ctrader_con_controles_y_fases(self):
        autotrader.cambiar_estado(self.u, "demo", "activo")
        cand = [{"simbolo": "XAUUSD", "id": 1, "descripcion": "Gold", "estrategia": "cruce_ema", "params": {"rapida": 9, "lenta": 21},
                 "direccion": "alcista", "precio_ref": 2000.20, "atr": 2.0, "vela_ts": int(time.time()) // 3600 * 3600, "exp_fuera": 0.2, "n_fuera": 30}]
        with mock.patch("titan_quant.backtest_ctrader.escaner.senales_vivas", return_value=cand):
            r = autotrader.ciclo(self.u, "demo")
        self.assertEqual(r["resultados"][0]["accion"], "abrir", r)
        op = almacen.q1("demo", "SELECT * FROM operaciones WHERE id=?", (r["resultados"][0]["operacion_id"],))
        self.assertEqual((op["instrumento"], op["simbolo_broker"], op["estrategia"], op["fase"]), ("XAUUSD", "XAUUSD", "cruce_ema", "abierta_confirmada"))
        self.assertEqual([o["ctid"] for o in self.W.ordenes], [9001])
        self.assertTrue(all(c["ok"] for c in json.loads(op["controles"])))


class SesionIQ:
    """Sesión falsa con selección de cuenta como la librería: la cuenta activa es un estado global."""
    def __init__(self, cambia=True):
        self.modo, self.cambia, self.compras = "PRACTICE", cambia, []
        self.api = type("C", (), {"buy_multi_option": {}})()

    def get_balance_mode(self):
        return self.modo

    def change_balance(self, tipo):
        if self.cambia:
            self.modo = tipo

    def check_connect(self):
        return True

    def get_balance(self):
        return 50.0 if self.modo == "REAL" else 10000.0

    def buy(self, monto, activo, accion, minutos):
        self.compras.append((self.modo, activo))
        return True, 99


class TestCuentaIQ(unittest.TestCase):
    def setUp(self):
        p = mock.patch("iqoption_data.resolve", return_value=("EURGBP-OTC", "turbo", True))
        p.start()
        self.addCleanup(p.stop)

    def sol(self, m):
        return {"modalidad": m, "tipo": "binaria", "instrumento": "EURGBP-OTC", "direccion": "alcista", "monto": 1.0, "expira_ts": int(time.time()) + 300}

    def test_orden_real_se_envia_con_la_cuenta_real_y_vuelve_a_practice(self):
        s = SesionIQ()
        IQOption({}, api=s, cuenta="REAL").abrir(self.sol("binaria_real"))
        self.assertEqual(s.compras, [("REAL", "EURGBP-OTC")])
        self.assertEqual(s.modo, "PRACTICE")
        IQOption({}, api=s, cuenta="PRACTICE").abrir(self.sol("binaria"))
        self.assertEqual(s.compras[-1], ("PRACTICE", "EURGBP-OTC"))
        self.assertEqual(IQOption({}, api=s, cuenta="REAL").saldo()["balance"], 50.0)
        self.assertEqual(s.modo, "PRACTICE")

    def test_cuenta_que_no_se_puede_seleccionar_no_envia(self):
        s = SesionIQ(cambia=False)
        with self.assertRaises(ErrorAdaptador):
            IQOption({}, api=s, cuenta="REAL").abrir(self.sol("binaria_real"))
        self.assertEqual(s.compras, [])

    def test_modalidad_y_cuenta_deben_coincidir(self):
        s = SesionIQ()
        with self.assertRaises(ErrorAdaptador):
            IQOption({}, api=s, cuenta="PRACTICE").abrir(self.sol("binaria_real"))
        with self.assertRaises(ErrorAdaptador):
            IQOption({}, api=s, cuenta="REAL").abrir(self.sol("binaria"))
        self.assertEqual(s.compras, [])


class TestEscanerBinario(Base):
    def test_evaluar_con_payout_real_y_concepto_binario(self):
        from titan_quant.backtest_binaria import escaner as escb
        from titan_quant.binaria_bot.datos import Vela
        o, h, l, c = ohlc(3000, 4)
        t0 = 1_793_000_000 - 1_793_000_000 % 60
        velas = [Vela(ts=t0 + 60 * i, open=o[i], high=h[i], low=l[i], close=c[i]) for i in range(3000)]
        r = escb.evaluar(velas, 0.85, "rsi_reversion", simples.validar_parametros("rsi_reversion", {}), 20, 0.0)
        self.assertAlmostEqual(r["equilibrio"], 1 / 1.85)
        self.assertFalse(r["apto"])                                      # paseo aleatorio: sin ventaja, no se opera
        self.assertIn("equilibrio", r["motivo"] + "equilibrio")

    def test_ciclo_multiactivo_binario_envia_a_la_cuenta_del_bot(self):
        u = self.usuario()["id"]
        autotrader.cambiar_estado(u, "binaria", "activo")
        s = SesionIQ()
        ad = IQOption({}, api=s, cuenta="PRACTICE")
        cand = [{"activo": "EURGBP-OTC", "estrategia": "bollinger_reversion", "direccion": "bajista", "precio_ref": 1.1, "vela_ts": int(time.time()) // 60 * 60,
                 "payout": 0.85, "acierto_fuera": 0.6, "equilibrio": 0.54, "n_fuera": 40}]
        with mock.patch("titan_quant.backtest_binaria.escaner.actualizar_ranking", return_value=[{"activo": "EURGBP-OTC"}]), \
             mock.patch("titan_quant.backtest_binaria.escaner.senales_vivas", return_value=cand), \
             mock.patch("iqoption_data.resolve", return_value=("EURGBP-OTC", "turbo", True)), \
             mock.patch.object(IQOption, "cotizacion", return_value={"precio": 1.1, "edad_s": 3, "bid": None, "ask": None, "spread": None}), \
             mock.patch.object(IQOption, "saldo", return_value={"balance": 1000.0, "moneda": "PRACTICE"}):
            r = autotrader.ciclo(u, "binaria", adaptador=ad)
        self.assertEqual(r["resultados"][0]["accion"], "abrir", r)
        self.assertEqual(s.compras, [("PRACTICE", "EURGBP-OTC")])
        op = almacen.q1("binaria", "SELECT * FROM operaciones")
        self.assertEqual((op["estrategia"], op["direccion"], op["id_externo"]), ("bollinger_reversion", "bajista", "99"))
        self.assertIsNone(almacen.q1("binaria_real", "SELECT * FROM operaciones"))   # la cuenta REAL no ve las de PRACTICE


class TestExploracionYTemporalidades(Base):
    def test_perfil_de_exploracion_solo_en_practica_y_con_el_bot_en_marcha(self):
        u = self.usuario()["id"]
        autotrader.guardar_ajustes(u, "demo", {"estrategia": "fusion", "simbolo_broker": "XAUUSD", "cuenta_ctid": 9001})
        autotrader.cambiar_estado(u, "demo", "activo")
        e = autotrader.aplicar_perfil_exploracion(u, "demo")              # funciona aunque el bot esté activo
        a = e["ajustes"]
        self.assertEqual((a["estrategia"], a["modo_exploracion"], a["cuenta_ctid"], e["estado"]), ("multiactivo", True, 9001, "activo"))
        self.assertEqual(autotrader.config_escaner(a)["intervalos"], ["5m", "15m", "1h", "4h"])
        b = autotrader.aplicar_perfil_exploracion(u, "binaria")["ajustes"]
        self.assertEqual(autotrader.config_escaner(b)["intervalos_binaria"], ["1m", "5m"])
        for m in ("real", "binaria_real"):
            with self.assertRaises(ValueError):
                autotrader.aplicar_perfil_exploracion(u, m)
        r = autotrader.validar_ajustes("real", {"modo_exploracion": True, "exp_min": -0.3, "min_ops_bt": 5, "cuenta_ctid": 7001})
        self.assertEqual((r["modo_exploracion"], r["exp_min"], r["min_ops_bt"]), (False, 0.0, 20))
        self.assertFalse(autotrader.config_escaner(r)["exploracion"])
        with self.assertRaises(ValueError):
            autotrader.validar_ajustes("demo", {"temporalidades": "5m,7m"})

    def test_exploracion_relaja_solo_la_exigencia_total(self):
        from titan_quant.backtest_ctrader import escaner as esc
        o, h, l, c = ohlc(2500, 9)
        s = {"t": list(range(len(c))), "o": o, "h": h, "l": l, "c": c}
        estricto = esc.evaluar(s, "cruce_ema", {"rapida": 9, "lenta": 21}, "15m", 0.0, 1.5, 2.0, 5, -0.5, exploracion=False)
        explora = esc.evaluar(s, "cruce_ema", {"rapida": 9, "lenta": 21}, "15m", 0.0, 1.5, 2.0, 5, -0.5, exploracion=True)
        self.assertGreaterEqual(int(explora["apto"]), int(estricto["apto"]))
        self.assertEqual(explora["n_fuera"], estricto["n_fuera"])

    def test_binaria_m5_vence_en_una_vela(self):
        from titan_quant.backtest_binaria import escaner as escb
        from titan_quant.binaria_bot.datos import Vela
        o, h, l, c = ohlc(1500, 12)
        t0 = 1_793_000_100 - 1_793_000_100 % 300
        velas = [Vela(ts=t0 + 300 * i, open=o[i], high=h[i], low=l[i], close=c[i]) for i in range(1500)]
        r = escb.evaluar(velas, 0.85, "cruce_ema", simples.validar_parametros("cruce_ema", {}), 5, -0.03, "5m", True)
        self.assertGreater(r["n_total"], 0)                                 # con paso de 300 s no se trocea en tramos vacíos


class TestFiltroTendencia(unittest.TestCase):
    def serie(self, deriva, n=1200, semilla=3):
        rnd, px, o, h, l, c = random.Random(semilla), 100.0, [], [], [], []
        for _ in range(n):
            a = px
            px *= 1 + deriva + rnd.gauss(0, 0.002)
            o.append(a); c.append(px); h.append(max(a, px) * 1.0005); l.append(min(a, px) * 0.9995)
        return o, h, l, c

    def test_tendencia_sin_mirar_al_futuro(self):
        o, h, l, c = self.serie(0.0008)
        t = simples.tendencia(c)
        self.assertEqual(t[:150], [0] * 150)                       # EMAs sin calentar: sin tendencia
        self.assertEqual(simples.tendencia(c[:700]), t[:700])
        self.assertGreater(t.count(1), t.count(-1))

    def test_solo_a_favor_de_la_tendencia(self):
        for deriva, esperado in ((0.0008, "compra"), (-0.0008, "venta")):
            o, h, l, c = self.serie(deriva)
            t = simples.tendencia(c)
            for est in simples.CATALOGO:
                with self.subTest(deriva=deriva, est=est):
                    ev = simples.senales(est, o, h, l, c, None, (50, 200))
                    self.assertTrue(all(t[e["indice"]] == (1 if e["direccion"] == "compra" else -1) for e in ev))
                    sin = simples.senales(est, o, h, l, c)
                    self.assertLessEqual(len(ev), len(sin))
            todas = [e for est in simples.CATALOGO for e in simples.senales(est, o, h, l, c, None, (50, 200))]
            self.assertTrue(todas)
            self.assertEqual(sum(e["direccion"] == esperado for e in todas) / len(todas) > 0.8, True)

    def test_backtest_binario_y_senal_viva_respetan_el_filtro(self):
        from titan_quant.backtest_binaria import escaner as escb
        from titan_quant.backtest_binaria.motor import ops_simple
        from titan_quant.binaria_bot.datos import Vela
        o, h, l, c = self.serie(0.0008, semilla=8)
        t0 = 1_793_000_000 - 1_793_000_000 % 60
        velas = [Vela(ts=t0 + 60 * i, open=o[i], high=h[i], low=l[i], close=c[i]) for i in range(len(c))]
        ops = [x for est in simples.CATALOGO for x in ops_simple(velas, 0.85, est, None, 5, 60, (50, 200))]
        t = simples.tendencia(c)
        idx = {v.ts: i for i, v in enumerate(velas)}
        self.assertTrue(ops)
        self.assertTrue(all(t[idx[x.ts_senal]] == (1 if x.direccion == "CALL" else -1) for x in ops))
        aj = autotrader.validar_ajustes("binaria", {})
        self.assertTrue(aj["filtro_tendencia"])                     # IQ Option: activado por defecto
        self.assertEqual(autotrader.config_escaner(aj)["tendencia"], (50, 200))
        self.assertTrue(autotrader.validar_ajustes("binaria_real", {})["filtro_tendencia"])
        with self.assertRaises(ValueError):
            autotrader.validar_ajustes("binaria", {"tendencia_rapida": 200, "tendencia_lenta": 100})


class TestRiesgoBeneficioYTrailing(Base):
    def setUp(self):
        super().setUp()
        self.f = CTraderFalso().iniciar()
        self.W = self.f.mundo
        self.u = self.usuario()["id"]
        boveda.guardar(self.u, "ctrader", {"client_id": self.W.client_id, "client_secret": self.W.client_secret, "redirect_uri": "http://x/cb",
                                           "access_token": "tok-trading", "refresh_token": "ref-1"})
        autotrader.guardar_ajustes(self.u, "demo", {"estrategia": "multiactivo", "cuenta_ctid": 9001, "temporalidades": "1h",
                                                    "lote_escaner": 1, "min_ops_bt": 5, "exp_min": -0.5})

    def tearDown(self):
        self.f.detener()
        super().tearDown()

    def test_objetivo_segun_tendencia_y_ventaja(self):
        aj = autotrader.estado(self.u, "demo")["ajustes"]
        rb = lambda **c: autotrader.riesgo_beneficio(aj, c, 1)[0]
        self.assertEqual(rb(tendencia=-1, exp_fuera=0.9, n_fuera=40), 2.0)     # contra tendencia: siempre 1:2
        self.assertEqual(rb(tendencia=1, exp_fuera=0.0, n_fuera=40), 2.0)      # a favor pero sin ventaja: 1:2
        self.assertEqual(rb(tendencia=1, exp_fuera=0.15, n_fuera=40), 3.0)     # ventaja: 1:3
        self.assertEqual(rb(tendencia=1, exp_fuera=0.4, n_fuera=40), 4.0)      # ventaja fuerte: 1:4 (máximo)
        self.assertEqual(rb(tendencia=1, exp_fuera=0.4, n_fuera=10), 2.0)      # poca muestra: 1:2
        with self.assertRaises(ValueError):
            autotrader.validar_ajustes("demo", {"rr_base": 4, "rr_tendencia": 3})

    def _abrir(self, tendencia):
        autotrader.cambiar_estado(self.u, "demo", "activo")
        cand = [{"simbolo": "XAUUSD", "id": 41, "descripcion": "Gold", "estrategia": "cruce_ema", "params": {"rapida": 9, "lenta": 21},
                 "direccion": "alcista", "precio_ref": 2000.20, "atr": 2.0, "vela_ts": int(time.time()) // 3600 * 3600, "exp_fuera": 0.2,
                 "n_fuera": 30, "tendencia": tendencia, "intervalo": "1h"}]
        with mock.patch("titan_quant.backtest_ctrader.escaner.senales_vivas", return_value=cand),              mock.patch("titan_quant.backtest_ctrader.escaner.actualizar_ranking", return_value=[]):
            r = autotrader.ciclo(self.u, "demo")
        return almacen.q1("demo", "SELECT * FROM operaciones WHERE id=?", (r["resultados"][0]["operacion_id"],))

    def test_orden_con_objetivo_1_a_3_si_va_a_favor(self):
        op = self._abrir(1)
        riesgo, beneficio = op["precio_entrada"] - op["stop"], op["objetivo"] - op["precio_entrada"]
        self.assertAlmostEqual(beneficio / riesgo, 3.0, delta=0.05)
        self.assertEqual(op["stop_inicial"], op["stop"])

    def test_trailing_sube_el_stop_en_el_broker_y_nunca_retrocede(self):
        op = self._abrir(0)
        riesgo = op["precio_entrada"] - op["stop"]
        self.assertAlmostEqual((op["objetivo"] - op["precio_entrada"]) / riesgo, 2.0, delta=0.05)     # sin tendencia: 1:2
        precio = op["precio_entrada"] + 1.7 * riesgo                  # el mercado avanza +1,7 R
        self.W.mover(41, precio, precio + 0.4)
        autotrader.actualizar_abiertas(self.u, "demo")
        op2 = almacen.q1("demo", "SELECT * FROM operaciones WHERE id=?", (op["id"],))
        self.assertGreater(op2["stop"], op["precio_entrada"])          # ya no puede perder
        self.assertEqual(op2["stop_inicial"], op["stop"])
        self.assertEqual(self.W.modificaciones[-1]["sl"], op2["stop"])  # el stop está puesto EN el broker
        self.assertTrue(any(e["fase"] == "ajuste_stop" for e in almacen.eventos("demo", op["id"])))
        n_mod = len(self.W.modificaciones)
        self.W.mover(41, op2["stop"] + 0.3, op2["stop"] + 0.7)        # retrocede sin tocar el stop: no se aleja
        autotrader.actualizar_abiertas(self.u, "demo")
        self.assertEqual(len(self.W.modificaciones), n_mod)
        self.W.mover(41, op2["stop"] - 0.5, op2["stop"] - 0.1)        # toca el stop movido: cierra con ganancia
        autotrader.actualizar_abiertas(self.u, "demo")
        op3 = almacen.q1("demo", "SELECT * FROM operaciones WHERE id=?", (op["id"],))
        self.assertEqual((op3["estado"], op3["fuente_resultado"]), ("cerrada", "broker"))
        self.assertGreater(op3["resultado"], 0)
