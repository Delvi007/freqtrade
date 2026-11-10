"""Confirmación de señales con los 23 motores, paso automático de EXPLORACIÓN a EVIDENCIA y aprendizaje con resultados reales."""
import json
import random
import time
import unittest
from unittest import mock

from titan_quant import confirmacion
from titan_quant.pruebas.base_prueba import Base
from titan_quant.pruebas.ctrader_falso import CTraderFalso
from titan_quant.seguridad import boveda
from titan_quant.trader import almacen, autotrader


def analisis(puntuacion=0.0, regimen="tendencia_alcista", eventos=0, calidad="alta"):
    def fn(simbolo, horizonte, nivel, politica, **kw):
        assert kw.get("serie") and kw["serie"]["c"]               # se analizan las MISMAS velas del broker
        return {"fusion": {"puntuacion": puntuacion, "hay_oportunidad": False},
                "motores": [{"motor": "regime", "estado": "completado", "salida": {"regimen": regimen}},
                            {"motor": "macro", "estado": "completado", "salida": {"eventos_alto_impacto_6h": eventos}},
                            {"motor": "data", "estado": "completado", "salida": {"calidad": {"calidad": calidad, "obsoleto": False}}},
                            {"motor": "fusion", "estado": "completado", "salida": {}}]}
    return fn


def velas(n=300, semilla=1):
    rnd, px, out = random.Random(semilla), 100.0, []
    t0 = int(time.time()) // 3600 * 3600 - n * 3600
    for i in range(n):
        a = px
        px *= 1 + rnd.gauss(0, 0.003)
        out.append([t0 + i * 3600, a, max(a, px) * 1.001, min(a, px) * 0.999, px, 10])
    return out


class TestConfirmacion(unittest.TestCase):
    def serie(self):
        return confirmacion.serie_desde(velas(), "ctrader-demo", "AUSTRALIA 200", "1h")

    def test_veto_y_confirmacion(self):
        c = confirmacion.confirmar(1, "AUSTRALIA 200", "alcista", self.serie(), "1h", 0.15, analizar_fn=analisis(-0.4))
        self.assertFalse(c["ok"])
        self.assertIn("en contra", c["detalle"])
        self.assertTrue(confirmacion.confirmar(1, "X", "alcista", self.serie(), "1h", 0.15, analizar_fn=analisis(0.0))["ok"])    # neutral: no veta
        self.assertTrue(confirmacion.confirmar(1, "X", "bajista", self.serie(), "1h", 0.15, analizar_fn=analisis(-0.4))["ok"])   # a favor
        self.assertFalse(confirmacion.confirmar(1, "X", "alcista", self.serie(), "1h", 0.15, analizar_fn=analisis(0.3, "alta_volatilidad"))["ok"])
        self.assertFalse(confirmacion.confirmar(1, "X", "alcista", self.serie(), "1h", 0.15, analizar_fn=analisis(0.3, eventos=2))["ok"])
        self.assertTrue(confirmacion.confirmar(1, "USDMXN-OTC", "alcista", self.serie(), "1m", 0.15, analizar_fn=analisis(0.3, eventos=2))["ok"])
        self.assertTrue(confirmacion.confirmar(1, "X", "alcista", self.serie(), "1h", 0.15, analizar_fn=analisis(0.3, eventos=2), veto_macro=False)["ok"])
        self.assertFalse(confirmacion.confirmar(1, "X", "alcista", self.serie(), "1h", 0.15, analizar_fn=analisis(0.3, calidad="baja"))["ok"])

    def test_si_el_analisis_falla_no_se_confirma(self):
        def falla(*a, **k):
            raise RuntimeError("sin red")
        self.assertFalse(confirmacion.confirmar(1, "X", "alcista", self.serie(), "1h", analizar_fn=falla)["ok"])

    def test_nombres_de_ctrader_validos_para_los_motores(self):
        self.assertEqual(confirmacion._simbolo_motor("AUSTRALIA 200"), "AUSTRALIA200")
        self.assertEqual(confirmacion._simbolo_motor("EURUSD"), "EURUSD")


class TestEvidenciaYAprendizaje(Base):
    def setUp(self):
        super().setUp()
        self.f = CTraderFalso().iniciar()
        self.W = self.f.mundo
        self.u = self.usuario()["id"]
        boveda.guardar(self.u, "ctrader", {"client_id": self.W.client_id, "client_secret": self.W.client_secret, "redirect_uri": "http://x/cb",
                                           "access_token": "tok-trading", "refresh_token": "ref-1"})
        autotrader.guardar_ajustes(self.u, "demo", {"estrategia": "multiactivo", "cuenta_ctid": 9001, "temporalidades": "1h",
                                                    "lote_escaner": 1, "muestra_exploracion": 3})
        autotrader.cambiar_estado(self.u, "demo", "activo")

    def tearDown(self):
        self.f.detener()
        super().tearDown()

    def cand(self, **kw):
        return [{"simbolo": "XAUUSD", "id": 41, "descripcion": "Gold", "estrategia": "cruce_ema", "params": {}, "direccion": "alcista",
                 "precio_ref": 2000.20, "atr": 2.0, "intervalo": "1h", "vela_ts": int(time.time()) - 3600 - 5, "exp_fuera": 0.2, "n_fuera": 30,
                 "tendencia": 0, "intervalo": "1h", "velas": velas(), "proveedor": "ctrader-demo", **kw}]

    def ciclo(self, cand, analizar_fn):
        with mock.patch("titan_quant.backtest_ctrader.escaner.senales_vivas", return_value=cand), \
             mock.patch("titan_quant.backtest_ctrader.escaner.actualizar_ranking", return_value=[]), \
             mock.patch("titan_quant.motores.nucleo.analizar", analizar_fn):
            return autotrader.ciclo(self.u, "demo")

    def cerradas(self, n, resultado):
        ahora = int(time.time()) - 3 * 86400
        with almacen.tx("demo") as c:
            for i in range(n):
                c.execute("""INSERT INTO operaciones(usuario_id,modalidad,broker,instrumento,mercado,tipo,direccion,monto,estado,fase,fuente_resultado,
                             id_externo,abierta_ts,cerrada_ts,resultado) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                          (self.u, "demo", "ctrader", f"Z{i}", "x", "margen", "alcista", 100, "cerrada", "resultado_recibido", "broker", f"E{i}",
                           ahora, ahora + 60 + i, resultado))

    def test_los_23_motores_vetan_la_senal(self):
        r = self.ciclo(self.cand(), analisis(-0.5))
        self.assertEqual(r["resultados"][0]["accion"], "rechazar", r)
        op = almacen.q1("demo", "SELECT * FROM operaciones ORDER BY id DESC LIMIT 1")
        ctl = {c["control"]: c for c in json.loads(op["controles"])}
        self.assertFalse(ctl["confirmacion_23_motores"]["ok"])
        self.assertEqual(self.W.ordenes, [])                                  # nada llega al broker

    def test_confirmada_por_los_motores_se_envia(self):
        r = self.ciclo(self.cand(), analisis(0.3))
        self.assertEqual(r["resultados"][0]["accion"], "abrir", r)
        op = almacen.q1("demo", "SELECT * FROM operaciones ORDER BY id DESC LIMIT 1")
        self.assertIn("regime", json.loads(op["motores"]))                    # los motores quedan registrados en la orden

    def test_paso_automatico_a_modo_evidencia(self):
        self.assertIn("exploración", self.ciclo([], analisis())["fase"])
        self.cerradas(3, 1.0)                                                 # se alcanza la muestra (3)
        self.assertEqual(self.ciclo([], analisis())["fase"], "evidencia")

    def test_aprendizaje_con_resultados_reales_bloquea_lo_que_pierde(self):
        for i in range(8):
            almacen.aprender("demo", "cruce_ema", "XAUUSD", "1h", "alcista", -1.0)
        r = self.ciclo(self.cand(), analisis(0.3))
        self.assertEqual(r["resultados"][0]["accion"], "rechazar")
        op = almacen.q1("demo", "SELECT * FROM operaciones ORDER BY id DESC LIMIT 1")
        self.assertIn("aprendizaje_real", op["motivo_cierre"])
        almacen.aprender("binaria", "cruce_ema", "XAUUSD", "1h", "alcista", 5.0)     # otro broker: no influye
        self.assertFalse(autotrader._control_aprendizaje("demo", autotrader.estado(self.u, "demo")["ajustes"], "cruce_ema", "XAUUSD")["ok"])


class TestCriteriosEstrictos(unittest.TestCase):
    def test_ctrader_estricto_exige_ic_positivo(self):
        from titan_quant.backtest_ctrader import escaner as esc
        rnd, px, o, h, l, c = random.Random(4), 100.0, [], [], [], []
        for _ in range(2500):
            a = px
            px *= 1 + rnd.gauss(0, 0.003)
            o.append(a); c.append(px); h.append(max(a, px) * 1.001); l.append(min(a, px) * 0.999)
        s = {"t": list(range(len(c))), "o": o, "h": h, "l": l, "c": c}
        estricto = esc.evaluar(s, "cruce_ema", {"rapida": 9, "lenta": 21}, "1h", 0.0, 1.5, 3.0, 5, -0.5, False, True)
        laxo = esc.evaluar(s, "cruce_ema", {"rapida": 9, "lenta": 21}, "1h", 0.0, 1.5, 3.0, 5, -0.5, True, False)
        self.assertLessEqual(int(estricto["apto"]), int(laxo["apto"]))
        self.assertFalse(estricto["apto"])                                     # paseo aleatorio: sin ventaja demostrada

    def test_binaria_estricta_exige_wilson_sobre_el_equilibrio(self):
        from titan_quant.backtest_binaria import escaner as escb
        from titan_quant.binaria_bot.datos import Vela
        rnd, px, vs = random.Random(6), 1.0, []
        t0 = 1_793_000_000 - 1_793_000_000 % 60
        for i in range(3000):
            a = px
            px *= 1 + rnd.gauss(0, 0.0004)
            vs.append(Vela(ts=t0 + 60 * i, open=a, high=max(a, px) * 1.0002, low=min(a, px) * 0.9998, close=px))
        from titan_quant.estrategias import simples
        r = escb.evaluar(vs, 0.83, "cruce_ema", simples.validar_parametros("cruce_ema", {}), 5, -0.03, "1m", False, None, True)
        self.assertFalse(r["apto"])
