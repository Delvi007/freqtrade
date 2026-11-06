"""Pruebas de los 23 motores: registro, contratos, matemáticas, ausencia de sesgo de anticipación y análisis completo."""
import math
import random

from titan_quant import niveles, recursos
from titan_quant.motores import base, cuant, datos, mat, nucleo
from titan_quant.pruebas import sintetico
from titan_quant.pruebas.base_prueba import Base


class TestRegistro(Base):
    def test_23_motores_con_ficha_completa_y_sin_ciclos(self):
        self.assertEqual(sorted(m.numero for m in base.REGISTRO.values()), list(range(1, 24)))
        for m in base.REGISTRO.values():
            f = m.ficha()
            for k in ("nombre", "objetivo", "metodos"):
                self.assertTrue(f[k], f"{m.id} sin {k}")
            for d in m.dependencias:
                self.assertIn(d, base.REGISTRO, f"{m.id} depende de {d} inexistente")
        capas = nucleo.capas([m.id for m in base.REGISTRO.values() if m.en_analisis])
        self.assertGreaterEqual(len(capas), 3)

    def test_motor_que_falla_no_tumba_el_analisis(self):
        class Roto(base.Motor):
            numero, id, nombre, objetivo, metodos = 99, "roto", "ROTO", "x", "x"

            def calcular(self, ctx):
                raise ZeroDivisionError("a propósito")
        r = Roto().ejecutar({"res": {}})
        self.assertEqual(r["estado"], "error")
        self.assertIn("ZeroDivisionError", r["error"])


class TestMatematicas(Base):
    def test_indicadores_basicos(self):
        c = [float(i) for i in range(1, 60)]
        self.assertAlmostEqual(mat.rsi_serie(c)[-1], 100.0)
        self.assertAlmostEqual(mat.correlacion(c, [2 * x for x in c]), 1.0)
        lo, hi = mat.wilson(50, 100)
        self.assertTrue(0.40 < lo < 0.5 < hi < 0.60)
        self.assertEqual(mat.max_drawdown([0, 2, 1, 3, -1]), 4)
        self.assertAlmostEqual(mat.cuantil([1, 2, 3, 4, 5], 0.5), 3)

    def test_hurst_de_ruido_blanco_cerca_de_0_5(self):
        rnd = random.Random(1)
        r = [rnd.gauss(0, 1) for _ in range(2048)]
        self.assertTrue(0.35 < mat.hurst(r) < 0.65)
        vr = mat.ratio_varianza(r, 4)
        self.assertTrue(0.8 < vr < 1.2)

    def test_logistica_aprende_patron_separable(self):
        rnd = random.Random(2)
        X = [[rnd.gauss(0, 1), rnd.gauss(0, 1)] for _ in range(400)]
        y = [1 if a + 0.5 * b > 0 else 0 for a, b in X]
        Xs, ms = mat.estandarizar(X)
        w, b = mat.logistica_entrenar(Xs, y, 200, lr=0.5)
        acc = sum((mat.logistica_prob(w, b, x) > 0.5) == bool(t) for x, t in zip(Xs, y)) / len(y)
        self.assertGreater(acc, 0.9)


class TestSinAnticipacion(Base):
    """Cambiar el FUTURO no puede cambiar lo calculado en el pasado."""

    def _serie(self, n=800):
        v, _ = sintetico.velas("TEST", "6mo", "60m")
        v = v[:n]
        return {"simbolo": "TEST", "proveedor": "prueba", "simbolo_proveedor": "TEST", "tipo": "accion_o_etf", "intervalo": "60m",
                "t": [x[0] for x in v], "o": [x[1] for x in v], "h": [x[2] for x in v], "l": [x[3] for x in v], "c": [x[4] for x in v],
                "v": [x[5] for x in v], "meta": {}}

    def _feat(self, s):
        c = s["c"]
        return {"emas": {20: mat.ema(c, 20), 50: mat.ema(c, 50)}, "rsi": mat.rsi_serie(c), "atr": mat.atr_serie(s["h"], s["l"], c),
                "macd_hist": mat.macd(c)[2], "logret": mat.log_retornos(c)}

    def test_indicadores_y_variables_ml(self):
        s = self._serie()
        f = self._feat(s)
        corte = 500
        s2 = {k: (v[:corte + 1] if isinstance(v, list) else v) for k, v in s.items()}
        f2 = self._feat(s2)
        for i in (100, 300, corte):
            self.assertAlmostEqual(f["rsi"][i], f2["rsi"][i], places=9)
            self.assertAlmostEqual(f["atr"][i], f2["atr"][i], places=9)
            for a, b in zip(cuant._features_en(i, s["c"], f, s["v"]), cuant._features_en(i, s2["c"], f2, s2["v"])):
                self.assertAlmostEqual(a, b, places=9)

    def test_backtest_no_depende_del_futuro(self):
        s = self._serie()
        f = self._feat(s)
        t_full = cuant.simular_estrategia(s, f, 8, 0.02)
        corte = 600
        s2 = {k: (v[:corte] if isinstance(v, list) else v) for k, v in s.items()}
        t_cut = cuant.simular_estrategia(s2, self._feat(s2), 8, 0.02)
        cerradas = [t for t in t_cut if t["i"] + 1 + 2 * 8 < corte - 1 and t["motivo"] != "tiempo"]
        mapa = {t["i"]: t for t in t_full}
        for t in cerradas:
            self.assertIn(t["i"], mapa)
            self.assertAlmostEqual(t["r"], mapa[t["i"]]["r"], places=9)


class TestCalidadDatos(Base):
    def test_detecta_datos_obsoletos(self):
        v, m = sintetico.velas("X", "1mo", "60m", ahora=1_700_000_000)
        datos.PROVEEDOR_YAHOO = lambda s, r, i: (v, m)
        datos.limpiar_cache()
        cal = datos.calidad(datos.obtener("X", "1mo", "60m"))
        self.assertTrue(cal["obsoleto"])
        self.assertEqual(cal["calidad"], "media")
        sintetico.instalar()

    def test_tipo_instrumento(self):
        self.assertEqual(datos.tipo_instrumento("GC=F"), "futuro")
        self.assertEqual(datos.tipo_instrumento("EURUSD=X"), "divisa_spot")
        self.assertEqual(datos.tipo_instrumento("BTC-USD"), "cripto_spot")
        self.assertEqual(datos.tipo_instrumento("XAUUSD", "iqoption"), "cfd")


class TestAnalisisCompleto(Base):
    def test_cuatro_niveles_23_motores_sin_errores(self):
        for nivel in niveles.ORDEN:
            r = nucleo.analizar("GC=F", "corto", nivel, "maximo", cartera=["GC=F", "BTC-USD", "ES=F"], presupuesto_s=600)
            est = {m["motor"]: m["estado"] for m in r["motores"]}
            self.assertEqual(len(est), 23, nivel)
            self.assertFalse([k for k, v in est.items() if v == "error"], f"{nivel}: {est}")
            self.assertIn("informe_md", r)
            fu = r["fusion"]
            if r["hay_oportunidad"]:
                e = r["escenario"]
                for k in ("direccion", "zona_entrada", "precio_referencia", "stop_loss", "take_profit", "riesgo_beneficio",
                          "probabilidad", "metodo_probabilidad", "confirmacion", "invalidacion", "vigencia_hasta_ts"):
                    self.assertIn(k, e)
                self.assertGreaterEqual(round(e["riesgo_beneficio"], 2), 1.5)
            else:
                self.assertTrue(fu["motivo_sin_oportunidad"])
                self.assertIsNone(r["escenario"])
        sim = {m["motor"]: m["salida"] for m in r["motores"]}
        self.assertEqual(sim["montecarlo"]["simulaciones"], niveles.NIVELES["super"]["montecarlo_sim"])

    def test_ml_no_declara_calibrado_un_paseo_aleatorio(self):
        r = nucleo.analizar("ZZZ-TEST", "corto", "intermedio", "maximo", cartera=[])
        ml = next(m for m in r["motores"] if m["motor"] == "ml")
        if ml["estado"] == "completado":
            s = ml["salida"]
            if s["calibrada"]:
                self.assertLess(s["brier_oos"], s["brier_base"])

    def test_sin_datos_no_inventa_escenario(self):
        def caido(s, r, i):
            raise OSError("sin red")
        datos.PROVEEDOR_YAHOO = caido
        datos.limpiar_cache()
        r = nucleo.analizar("GC=F", "corto", "basico", "automatico", cartera=[])
        est = {m["motor"]: m["estado"] for m in r["motores"]}
        self.assertEqual(est["data"], "sin_datos")
        self.assertEqual(est["fusion"], "sin_datos")
        self.assertFalse(r["hay_oportunidad"])
        self.assertIsNone(r["escenario"])
        sintetico.instalar()

    def test_presupuesto_agotado_aplaza_y_lo_dice(self):
        r = nucleo.analizar("GC=F", "corto", "basico", "automatico", cartera=[], presupuesto_s=-1)
        self.assertTrue(any(m["estado"] == "aplazado" for m in r["motores"]))


class TestAdaptativo(Base):
    def test_memoria_baja_reduce_sin_cambiar_nivel(self):
        d = recursos.diagnostico(red=False)
        d["memoria"]["disponible_mb"] = 200
        p, aj = recursos.plan_ejecucion("super", "maximo", d)
        self.assertEqual(p["id"], "super")
        self.assertLessEqual(p["montecarlo_sim"], 300)
        self.assertTrue(aj)

    def test_diagnostico_no_inventa_gpu(self):
        d = recursos.diagnostico(red=False)
        self.assertFalse(d["gpu"]["detectada"])
        self.assertGreaterEqual(d["cpu"]["nucleos"], 1)
        self.assertIn(recursos.recomendar_nivel(d)["recomendado"], niveles.ORDEN)

    def test_politica_desconocida(self):
        with self.assertRaises(ValueError):
            recursos.plan_ejecucion("basico", "turbo")
        self.assertTrue(math.isfinite(1.0))
