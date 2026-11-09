"""Pruebas de las herramientas históricas de la señal binaria original: datos CSV, señal, backtest y métricas.
El bot de simulación (bot.py, almacen.py, riesgo.py, adaptador desactivado) se retiró: ver TestSimulacionRetirada.

Todas las series son construidas a mano o con datos sintéticos. Ninguna prueba rentabilidad real.
"""
import importlib
import os
import tempfile
import unittest

from titan_quant.binaria import datos_csv
from titan_quant.binaria.senal import (VENCIMIENTO_VELAS, generar, resultado, segmentos_continuos)
from titan_quant.binaria.backtest_csv import metricas, simular, validar_pago, wilson

T0 = 1_700_006_400  # múltiplo de 60 s


def serie_con_compra(cola=6):
    """Fixture de la prueba Keltner + RCI: caída de 10 barras y rebote de 6. Cola plana para cerrar ventanas."""
    base = [100.0 + 0.2 * i for i in range(60)]
    caida = [base[-1] - 0.5 * k for k in range(1, 11)]
    cierres = base + caida + [caida[-1] + 6.0]
    cierres += [cierres[-1] + 0.01 * (k + 1) for k in range(cola)]
    velas = []
    for i, c in enumerate(cierres):
        velas.append((T0 + 60 * i, c - 0.1, c + 0.3, c - 0.3, c))
    return velas


class TestDatosCSV(unittest.TestCase):
    def _csv(self, texto):
        f = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8")
        f.write(texto)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_lee_iso_utc_y_epoch_milisegundos_ordenado(self):
        ruta = self._csv("time,open,high,low,close\n"
                         "2026-11-07 15:02:00,1,1.2,0.9,1.1\n"
                         "2026-11-07 15:01:00,1,1.2,0.9,1.0\n")
        velas, meta = datos_csv.leer(ruta, "XAUUSD", "manual")
        self.assertEqual([v[0] for v in velas], sorted(v[0] for v in velas))
        self.assertEqual(meta["velas"], 2)
        ruta2 = self._csv("timestamp,open,high,low,close\n1700006400000,1,1.2,0.9,1.1\n")
        self.assertEqual(datos_csv.leer(ruta2, "X", "manual")[0][0][0], 1700006400)

    def test_rechaza_duplicados_ohlc_incoherente_y_columnas_faltantes(self):
        with self.assertRaises(datos_csv.ErrorCSV):
            datos_csv.leer(self._csv("time,open,high,low,close\n1700006400,1,1.2,0.9,1\n1700006400,1,1.2,0.9,1\n"), "X", "m")
        with self.assertRaises(datos_csv.ErrorCSV):
            datos_csv.leer(self._csv("time,open,high,low,close\n1700006400,1,0.5,0.9,1\n"), "X", "m")
        with self.assertRaises(datos_csv.ErrorCSV):
            datos_csv.leer(self._csv("time,open,high,low\n1700006400,1,1.2,0.9\n"), "X", "m")
        with self.assertRaises(datos_csv.ErrorCSV):
            datos_csv.leer(self._csv("time,open,high,low,close\n"), "X", "m")

    def test_exige_instrumento_y_proveedor(self):
        with self.assertRaises(datos_csv.ErrorCSV):
            datos_csv.leer(self._csv("time,open,high,low,close\n1700006400,1,1.2,0.9,1\n"), "", "m")


class TestSegmentosYSenal(unittest.TestCase):
    def test_hueco_corta_el_tramo(self):
        velas = [(T0 + 60 * i, 1, 1, 1, 1) for i in range(3)] + [(T0 + 60 * 10, 1, 1, 1, 1)]
        self.assertEqual([len(t) for t in segmentos_continuos(velas)], [3, 1])

    def test_senal_compra_con_vencimiento_y_entrada_correctos(self):
        velas = serie_con_compra(cola=0)
        ss = [s for s in generar(velas) if s["direccion"] == "CALL"]
        self.assertTrue(ss)
        s = ss[0]
        j = s["indice"]
        self.assertEqual(s["ts_entrada"], velas[j][0] + 60)
        self.assertEqual(s["vencimiento_ts"], velas[j][0] + 60 + VENCIMIENTO_VELAS * 60)

    def test_resultado_binario(self):
        self.assertEqual(resultado("CALL", 10, 11, 0.8), ("ganada", 0.8))
        self.assertEqual(resultado("CALL", 10, 9, 0.8), ("perdida", -1.0))
        self.assertEqual(resultado("PUT", 10, 9, 0.8), ("ganada", 0.8))
        self.assertEqual(resultado("PUT", 10, 11, 0.8), ("perdida", -1.0))
        self.assertEqual(resultado("CALL", 10, 10, 0.8), ("empate", 0.0))


class TestSimulacion(unittest.TestCase):
    def test_entrada_en_apertura_siguiente_y_salida_en_cierre_de_quinta_vela(self):
        velas = serie_con_compra(cola=6)
        ops, descartadas = simular(velas, pago=0.8)
        compra = [o for o in ops if o["direccion"] == "CALL"]
        self.assertTrue(compra)
        o = compra[0]
        j = next(i for i, v in enumerate(velas) if v[0] == o["ts_senal"])
        self.assertEqual(o["precio_entrada"], velas[j + 1][1])   # apertura de j+1
        self.assertEqual(o["precio_vencimiento"], velas[j + 5][4])  # cierre de j+5
        self.assertEqual(o["ts_entrada"], velas[j + 1][0])

    def test_señal_sin_ventana_completa_se_descarta(self):
        velas = serie_con_compra(cola=0)
        ops, descartadas = simular(velas, pago=0.8)
        self.assertGreaterEqual(descartadas, 1)
        self.assertFalse([o for o in ops if o["ts_senal"] == velas[-1][0]])

    def test_pago_obligatorio_y_validado(self):
        for malo in (None, 0, -0.5, 25, "0.8"):
            with self.assertRaises(ValueError):
                validar_pago(malo)


class TestMetricas(unittest.TestCase):
    def test_cifras_calculadas_a_mano(self):
        ops = [{"resultado": "ganada", "retorno": 0.8}, {"resultado": "perdida", "retorno": -1.0},
               {"resultado": "ganada", "retorno": 0.8}, {"resultado": "empate", "retorno": 0.0},
               {"resultado": "perdida", "retorno": -1.0}]
        m = metricas(ops, pago=0.8)
        self.assertEqual(m["decididas"], 4)
        self.assertEqual(m["tasa_aciertos"], 0.5)
        self.assertAlmostEqual(m["punto_equilibrio"], 1 / 1.8, places=9)
        self.assertAlmostEqual(m["retorno_esperado_por_unidad"], -0.1, places=9)
        self.assertAlmostEqual(m["retorno_acumulado"], -0.4, places=9)
        self.assertAlmostEqual(m["drawdown_maximo"], 1.2, places=9)
        self.assertEqual(m["racha_perdidas_max"], 1)
        self.assertEqual(m["empates"], 1)

    def test_wilson_2_de_4(self):
        lo, hi = wilson(2, 4)
        self.assertAlmostEqual(lo, 0.150, places=2)
        self.assertAlmostEqual(hi, 0.850, places=2)

    def test_sin_operaciones_no_inventa_tasa(self):
        m = metricas([], pago=0.8)
        self.assertIsNone(m["tasa_aciertos"])
        self.assertIsNone(m["retorno_esperado_por_unidad"])


class TestSimulacionRetirada(unittest.TestCase):
    def test_modulos_de_simulacion_retirados(self):
        for mod in ("bot", "almacen", "riesgo", "adaptador_iqoption", "simulador"):
            with self.subTest(mod=mod):
                with self.assertRaises(ModuleNotFoundError):
                    importlib.import_module("titan_quant.binaria." + mod)

    def test_backtest_csv_no_registra_operaciones(self):
        ops, _ = simular(serie_con_compra(cola=6), 0.8)
        self.assertTrue(ops)
        self.assertFalse(any("modalidad" in o or "id_externo" in o for o in ops))


if __name__ == "__main__":
    unittest.main()
