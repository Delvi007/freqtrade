"""Pruebas de la señal Keltner + RCI con series construidas a mano (no prueban rentabilidad)."""
import unittest

from titan_quant.estrategias.keltner_rci import senales
from titan_quant.indicadores.keltner import keltner
from titan_quant.indicadores.rci import rci


class TestSenalKeltnerRCI(unittest.TestCase):
    def test_sin_datos_suficientes_no_hay_senal(self):
        self.assertEqual(senales([1.0] * 5, [0.9] * 5, [1.0] * 5), [])

    def test_serie_plana_no_genera_senal(self):
        n = 80
        self.assertEqual(senales([10.0] * n, [10.0] * n, [10.0] * n), [])

    def test_compra_cuando_se_cumplen_las_tres_condiciones(self):
        # Caída de 10 barras (0.5 por barra) y un rebote de 6 que vuelve sobre la banda inferior.
        base = [100.0 + 0.2 * i for i in range(60)]
        caida = [base[-1] - 0.5 * k for k in range(1, 11)]
        cierres = base + caida + [caida[-1] + 6.0]
        highs = [c + 0.3 for c in cierres]
        lows = [c - 0.3 for c in cierres]
        compras = [e for e in senales(highs, lows, cierres) if e["direccion"] == "compra"]
        self.assertTrue(compras, "debería existir una señal de compra en el rebote")
        j = compras[0]["indice"]
        k = keltner(highs, lows, cierres)
        r = rci(cierres, periodo=14)
        self.assertLess(cierres[j - 1], k["lower"][j - 1])          # venía por debajo de la banda
        self.assertGreaterEqual(cierres[j], k["lower"][j])          # volvió a entrar desde abajo
        self.assertGreater(r[j], r[j - 1])                          # RCI saliendo de la sobreventa
        self.assertLessEqual(min(x for x in r[j - 3:j] if x is not None), -80)

    def test_venta_es_la_imagen_especular_de_la_compra(self):
        # Reflejar precios (x -> 200 - x) convierte la compra en venta en la misma vela.
        base = [100.0 + 0.2 * i for i in range(60)]
        caida = [base[-1] - 0.5 * k for k in range(1, 11)]
        cierres = base + caida + [caida[-1] + 6.0]
        highs = [c + 0.3 for c in cierres]
        lows = [c - 0.3 for c in cierres]
        compras = [e["indice"] for e in senales(highs, lows, cierres) if e["direccion"] == "compra"]
        rc = [200 - c for c in cierres]
        rh = [200 - l for l in lows]
        rl = [200 - h for h in highs]
        ventas = [e["indice"] for e in senales(rh, rl, rc) if e["direccion"] == "venta"]
        self.assertTrue(compras)
        self.assertEqual(ventas, compras)

    def test_sin_sobreventa_previa_no_hay_compra(self):
        # Rebote de cierre sobre la banda pero RCI nunca llegó a -80: no debe disparar.
        base = [100.0 + 0.05 * i for i in range(80)]
        cierres = base[:-1] + [base[-1] - 1.0, base[-1] + 0.2]
        highs = [c + 0.5 for c in cierres]
        lows = [c - 0.5 for c in cierres]
        ev = [e for e in senales(highs, lows, cierres, umbral=99.9) if e["direccion"] == "compra"]
        self.assertEqual(ev, [])

    def test_parametros_invalidos(self):
        with self.assertRaises(ValueError):
            senales([1.0] * 30, [0.9] * 30, [1.0] * 30, ventana=0)


if __name__ == "__main__":
    unittest.main()
