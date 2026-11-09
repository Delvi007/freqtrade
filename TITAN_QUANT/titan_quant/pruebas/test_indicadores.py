"""Pruebas de indicadores con valores calculados a mano."""
import math
import unittest

from titan_quant.indicadores.suavizado import ema, rma, sma, true_range
from titan_quant.indicadores.keltner import keltner
from titan_quant.indicadores.rci import rci


class TestSuavizado(unittest.TestCase):
    def test_sma_manual(self):
        self.assertEqual(sma([1, 2, 3, 4, 5], 3), [None, None, 2.0, 3.0, 4.0])

    def test_ema_semilla_y_alpha(self):
        # n=3, alpha=0.5, semilla=SMA(1,2,3)=2
        r = ema([1, 2, 3, 4, 5], 3)
        self.assertEqual(r[:2], [None, None])
        self.assertAlmostEqual(r[2], 2.0)
        self.assertAlmostEqual(r[3], 0.5 * 4 + 0.5 * 2.0)   # 3.0
        self.assertAlmostEqual(r[4], 0.5 * 5 + 0.5 * 3.0)   # 4.0

    def test_rma_alpha_1_sobre_n(self):
        # n=2, alpha=0.5; semilla SMA(1,3)=2
        r = rma([1, 3, 5, 7], 2)
        self.assertAlmostEqual(r[1], 2.0)
        self.assertAlmostEqual(r[2], 0.5 * 5 + 0.5 * 2.0)   # 3.5
        self.assertAlmostEqual(r[3], 0.5 * 7 + 0.5 * 3.5)   # 5.25

    def test_constante_no_cambia(self):
        for f in (ema, rma, sma):
            self.assertTrue(all(abs(x - 7.0) < 1e-12 for x in f([7.0] * 30, 5)[4:]))

    def test_true_range(self):
        h = [10, 12, 11]; l = [8, 9, 10]; c = [9, 11, 10.5]
        tr = true_range(h, l, c)
        self.assertEqual(tr[0], 2)                  # H-L
        self.assertEqual(tr[1], max(3, abs(12 - 9), abs(9 - 9)))  # 3
        self.assertEqual(tr[2], max(1, abs(11 - 11), abs(10 - 11)))  # 1

    def test_periodo_invalido(self):
        with self.assertRaises(ValueError):
            ema([1, 2], 0)


class TestKeltner(unittest.TestCase):
    def setUp(self):
        n = 60
        self.c = [100 + 5 * math.sin(i / 4) for i in range(n)]
        self.h = [x + 1 for x in self.c]
        self.l = [x - 1 for x in self.c]

    def test_multiplicador_por_defecto_es_2(self):
        k = keltner(self.h, self.l, self.c, periodo=20)
        k2 = keltner(self.h, self.l, self.c, periodo=20, multiplicador=2.0)
        self.assertEqual(k["upper"], k2["upper"])

    def test_bandas_simetricas_respecto_a_la_media(self):
        k = keltner(self.h, self.l, self.c, periodo=20)
        for i in range(len(self.c)):
            if k["middle"][i] is None:
                self.assertIsNone(k["upper"][i]); continue
            self.assertAlmostEqual(k["upper"][i] - k["middle"][i], k["middle"][i] - k["lower"][i], places=10)
            self.assertAlmostEqual(k["upper"][i] - k["middle"][i], k["offset"][i], places=10)

    def test_offset_es_rma_tr_por_multiplicador(self):
        k = keltner(self.h, self.l, self.c, periodo=20, multiplicador=2.0)
        base = rma(true_range(self.h, self.l, self.c), 20)
        for i in range(len(self.c)):
            if base[i] is not None:
                self.assertAlmostEqual(k["offset"][i], base[i] * 2.0, places=10)

    def test_media_ema_sobre_hlc3(self):
        k = keltner(self.h, self.l, self.c, periodo=20)
        tip = [(h + l + c) / 3 for h, l, c in zip(self.h, self.l, self.c)]
        self.assertAlmostEqual(k["middle"][30], ema(tip, 20)[30], places=10)

    def test_parametros_invalidos(self):
        with self.assertRaises(ValueError):
            keltner(self.h, self.l, self.c, media="wma")
        with self.assertRaises(ValueError):
            keltner(self.h, self.l, self.c, multiplicador=0)


class TestRCI(unittest.TestCase):
    def test_creciente_es_100(self):
        r = rci([1, 2, 3, 4, 5, 6, 7, 8, 9], 9)
        self.assertAlmostEqual(r[8], 100.0)

    def test_decreciente_es_menos_100(self):
        r = rci([9, 8, 7, 6, 5, 4, 3, 2, 1], 9)
        self.assertAlmostEqual(r[8], -100.0)

    def test_calentamiento(self):
        r = rci(list(range(20)), 9)
        self.assertTrue(all(x is None for x in r[:8]))
        self.assertIsNotNone(r[8])

    def test_empates_rango_medio(self):
        # ventana [1,1,1]: todos los rangos son 2; d = 2-1, 2-2, 2-3 = 1, 0, -1; sum d^2 = 2
        r = rci([1, 1, 1], 3)
        self.assertAlmostEqual(r[2], (1 - 6 * 2 / (3 * 8)) * 100)

    def test_rango_valido(self):
        import random
        random.seed(7)
        s = [random.random() for _ in range(200)]
        for x in rci(s, 26)[25:]:
            self.assertTrue(-100.0 - 1e-9 <= x <= 100.0 + 1e-9)

    def test_periodo_invalido(self):
        with self.assertRaises(ValueError):
            rci([1, 2, 3], 1)


if __name__ == "__main__":
    unittest.main()
