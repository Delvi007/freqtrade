"""Planificador de los bots y coherencia backtest/vivo.

Fallos que reproducen estas pruebas (todos en trader/autotrader.py):
  * Un ciclo que lanzaba una excepción abortaba la vuelta entera del bucle: los bots siguientes (p. ej. IQ Option tras
    cTrader) no se ejecutaban. Ahora cada bot corre en su propio hilo y su fallo queda registrado solo para él.
  * Bots en serie: el de binarias (ciclo 60 s) esperaba al de cTrader (hasta 300 s de presupuesto).
  * Una candidata que fallaba abortaba las demás del mismo ciclo.
  * Señales aceptadas con hasta 2 velas de retraso (2 min en una binaria de 5 min); el backtest entra en el cierre exacto.
  * cTrader: el ranking validaba un objetivo de atr_obj·ATR y el bot operaba a atr_stop·rr_base·ATR.
"""
import threading
import time
from unittest import mock

from titan_quant.pruebas.base_prueba import Base
from titan_quant.trader import autotrader


class TestTocaCiclo(Base):
    BIN = {"estrategia": "multiactivo", "ciclo_s": 60}
    CT = {"estrategia": "multiactivo", "ciclo_s": 300}

    def test_binarias_alineadas_al_cierre_de_la_vela_m1(self):
        base = 1_800_000_000 - 1_800_000_000 % 300
        self.assertTrue(autotrader.toca_ciclo("binaria", self.BIN, 0, base + 2))
        self.assertTrue(autotrader.toca_ciclo("binaria", self.BIN, 0, base + 10))
        self.assertFalse(autotrader.toca_ciclo("binaria", self.BIN, 0, base + 30))       # a mitad de minuto: espera
        self.assertFalse(autotrader.toca_ciclo("binaria", self.BIN, 0, base + 1))
        # una vez por minuto como mucho
        self.assertFalse(autotrader.toca_ciclo("binaria", self.BIN, base + 2, base + 5))
        self.assertTrue(autotrader.toca_ciclo("binaria", self.BIN, base + 2, base + 62))

    def test_ctrader_alineado_al_cierre_de_las_velas_de_5m(self):
        base = 1_800_000_000 - 1_800_000_000 % 300
        self.assertTrue(autotrader.toca_ciclo("demo", self.CT, 0, base + 3))
        self.assertFalse(autotrader.toca_ciclo("demo", self.CT, 0, base + 120))
        self.assertFalse(autotrader.toca_ciclo("demo", self.CT, base + 3, base + 63))     # no repite antes de 5 min
        self.assertTrue(autotrader.toca_ciclo("demo", self.CT, base + 3, base + 303))

    def test_estrategia_de_un_solo_simbolo_usa_intervalo_simple(self):
        aj = {"estrategia": "fusion", "ciclo_s": 300}
        self.assertFalse(autotrader.toca_ciclo("demo", aj, 1000, 1200))
        self.assertTrue(autotrader.toca_ciclo("demo", aj, 1000, 1300))


class TestAislamiento(Base):
    def test_fallo_de_un_bot_no_afecta_a_otro(self):
        hecho = threading.Event()

        def roto(*a):
            raise RuntimeError("cTrader caído")
        autotrader._HILO["errores"].clear()
        self.assertTrue(autotrader._lanzar(("demo", 1), roto, 1, "demo"))
        self.assertTrue(autotrader._lanzar(("binaria", 1), lambda *a: hecho.set(), 1, "binaria"))
        self.assertTrue(hecho.wait(5), "el bot de binarias no se ejecutó tras el fallo del de cTrader")
        autotrader._HILO["trabajos"][("demo", 1)].join(5)
        self.assertIn("cTrader caído", autotrader._HILO["errores"][("demo", 1)])
        self.assertNotIn(("binaria", 1), autotrader._HILO["errores"])

    def test_un_bot_no_solapa_dos_ciclos(self):
        suelta = threading.Event()
        k = ("binaria", 99)
        self.assertTrue(autotrader._lanzar(k, lambda: suelta.wait(5)))
        self.assertFalse(autotrader._lanzar(k, lambda: None))          # sigue ocupado: no se lanza otro
        suelta.set()
        autotrader._HILO["trabajos"][k].join(5)
        self.assertTrue(autotrader._lanzar(k, lambda: None))

    def test_candidata_que_falla_no_aborta_las_demas(self):
        u = self.usuario()["id"]
        aj = dict(autotrader.estado(u, "binaria")["ajustes"])
        cands = [{"activo": "EURUSD-OTC", "estrategia": "x"}, {"activo": "GBPUSD-OTC", "estrategia": "x"}]
        ok = {"activo": "GBPUSD-OTC", "estrategia": "x", "accion": "abrir", "operacion_id": 7}
        with mock.patch.object(autotrader, "_senales_multiactivo", return_value=cands), \
                mock.patch.object(autotrader, "_ranking_multiactivo", return_value=[]), \
                mock.patch.object(autotrader, "_procesar_candidata", side_effect=[KeyError("edad_s"), ok]):
            out = autotrader._ciclo_multiactivo(u, "binaria", aj, object(), {"modalidad": "binaria"})
        self.assertEqual([r["accion"] for r in out["resultados"]], ["rechazar", "abrir"])
        self.assertEqual(out["accion"], "abrir")

    def test_senales_antes_que_el_re_backtest(self):
        u = self.usuario()["id"]
        aj = dict(autotrader.estado(u, "binaria")["ajustes"])
        orden = []
        with mock.patch.object(autotrader, "_senales_multiactivo", side_effect=lambda *a: orden.append("senales") or []), \
                mock.patch.object(autotrader, "_ranking_multiactivo", side_effect=lambda *a: orden.append("ranking") or []):
            autotrader._ciclo_multiactivo(u, "binaria", aj, object(), {"modalidad": "binaria"})
        self.assertEqual(orden, ["senales", "ranking"])


class TestVigencia(Base):
    def test_binaria(self):
        ahora = 1_800_000_000
        cand = {"vela_ts": ahora - 60 - 10}                         # vela M1 cerrada hace 10 s
        self.assertTrue(autotrader._control_vigencia({"broker": "iqoption"}, cand, "1m", ahora)["ok"])
        cand = {"vela_ts": ahora - 60 - 45}                         # 45 s: el 15 % de la binaria ya pasó
        self.assertFalse(autotrader._control_vigencia({"broker": "iqoption"}, cand, "1m", ahora)["ok"])

    def test_ctrader_proporcional_a_la_vela(self):
        ahora = 1_800_000_000
        self.assertTrue(autotrader._control_vigencia({"broker": "ctrader"}, {"vela_ts": ahora - 3600 - 600}, "1h", ahora)["ok"])
        self.assertFalse(autotrader._control_vigencia({"broker": "ctrader"}, {"vela_ts": ahora - 3600 - 1000}, "1h", ahora)["ok"])
        self.assertFalse(autotrader._control_vigencia({"broker": "ctrader"}, {"vela_ts": ahora - 300 - 90}, "5m", ahora)["ok"])


class TestObjetivoCoherente(Base):
    def test_backtest_mide_el_objetivo_que_se_opera(self):
        for m in ("demo", "real"):
            aj = autotrader.validar_ajustes(m, dict(autotrader.POR_DEFECTO[m]))
            self.assertAlmostEqual(aj["atr_obj"], aj["atr_stop"] * aj["rr_base"], msg=m)
            self.assertAlmostEqual(autotrader.config_escaner(aj)["atr_obj"], aj["atr_stop"] * aj["rr_base"])

    def test_configuracion_antigua_guardada_tambien_se_corrige(self):
        aj = {**autotrader.POR_DEFECTO["real"], "modalidad": "real", "atr_stop": 1.5, "atr_obj": 2.0, "rr_base": 2.0}
        self.assertEqual(autotrader.config_escaner(aj)["atr_obj"], 3.0)

    def test_binarias_no_cambian(self):
        aj = autotrader.validar_ajustes("binaria", dict(autotrader.POR_DEFECTO["binaria"]))
        self.assertEqual(autotrader.config_escaner(aj)["atr_obj"], aj["atr_obj"])



class TestRankingPorCriterio(Base):
    """PRACTICE (exploración) y REAL (evidencia) escanean los mismos pares de IQ Option: sus rankings no se pisan."""

    def _ranking(self, estricto, apto):
        from titan_quant.backtest_binaria import escaner as escb
        r = {"n_total": 50, "ev_total": 0.05, "n_fuera": 20, "acierto_fuera": 0.6, "equilibrio": 0.5376, "ev_fuera": 0.1,
             "apto": apto, "motivo": "estricto" if estricto else "exploración"}
        cfg = {"estrategias": {"cruce_ema": {}}, "intervalos_binaria": ["1m"], "min_ops": 12, "margen": 0.02, "lote": 5,
               "exploracion": not estricto, "estricto": estricto}
        with mock.patch.object(escb, "pares_abiertos", return_value=["EURUSD-OTC"]), \
                mock.patch("titan_quant.backtest_binaria.recolector.recopilar_iqoption"), \
                mock.patch("titan_quant.backtest_binaria.recolector.registrar_payout"), \
                mock.patch("titan_quant.backtest_binaria.motor._velas", return_value=[object()] * 400), \
                mock.patch.object(escb, "evaluar", return_value=r):
            escb.actualizar_ranking(object(), cfg, pagos={"EURUSD-OTC": 0.86})

    def test_exploracion_y_evidencia_no_se_sobrescriben(self):
        from titan_quant.backtest_binaria import escaner as escb
        self._ranking(estricto=True, apto=True)       # el bot REAL demuestra ventaja
        self._ranking(estricto=False, apto=False)     # después, el de PRACTICE recalcula el mismo par con su criterio
        self.assertEqual([f["activo"] for f in escb.mejores(estricto=True)], ["EURUSD-OTC"])
        self.assertEqual(escb.mejores(estricto=False), [])
        self._ranking(estricto=False, apto=True)
        self._ranking(estricto=True, apto=False)
        self.assertEqual([f["activo"] for f in escb.mejores(estricto=False)], ["EURUSD-OTC"])
        self.assertEqual(escb.mejores(estricto=True), [])

if __name__ == "__main__":
    import unittest
    unittest.main()
