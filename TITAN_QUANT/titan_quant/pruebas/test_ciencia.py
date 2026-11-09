"""Biblioteca científica: cada algoritmo se valida contra valores conocidos o datos sintéticos con parámetros conocidos."""
import math
import unittest

import numpy as np

from titan_quant.ciencia import (aprendizaje, bayes, cartera, deterioro, especiales, estocastico, filtros, informacion, optimizacion, regimen,
                                 volatilidad)


class TestEspeciales(unittest.TestCase):
    def test_valores_conocidos(self):
        self.assertAlmostEqual(especiales.betainc(2, 3, 0.4), 0.5248, places=4)          # I_0.4(2,3) = 0.5248
        self.assertAlmostEqual(especiales.betainc(0.5, 0.5, 0.5), 0.5, places=10)
        self.assertAlmostEqual(especiales.t_cdf(2.0, 10), 0.963306, places=5)            # tabla t
        self.assertAlmostEqual(especiales.norm_ppf(0.975), 1.959964, places=5)
        self.assertAlmostEqual(especiales.norm_cdf(1.959964), 0.975, places=5)


class TestBayes(unittest.TestCase):
    def test_tasa_acierto(self):
        r = bayes.tasa_acierto(60, 40, umbral=0.5)
        self.assertAlmostEqual(r["media"], 60.5 / 101, places=6)
        self.assertGreater(r["p_sobre_umbral"], 0.97)
        self.assertLess(r["ic95"][0], 0.6)
        self.assertGreater(r["ic95"][1], 0.6)
        self.assertLess(bayes.tasa_acierto(5, 5, umbral=0.546)["p_sobre_umbral"], 0.5)   # 10 operaciones: sin evidencia

    def test_expectativa_r(self):
        rnd = np.random.default_rng(1)
        buena = bayes.expectativa_r(rnd.normal(0.3, 1.0, 400))
        self.assertGreater(buena["p_positiva"], 0.99)
        mala = bayes.expectativa_r(rnd.normal(-0.2, 1.0, 400))
        self.assertLess(mala["p_positiva"], 0.01)
        poca = bayes.expectativa_r([1.0, 2.0, -1.0])
        self.assertLess(poca["p_positiva"], 0.95)                                         # previa escéptica

    def test_kelly_binaria(self):
        self.assertEqual(bayes.kelly_binaria(0.5, 0.83), 0.0)
        self.assertAlmostEqual(bayes.kelly_binaria(0.6, 1.0), 0.2, places=6)


class TestOptimizacion(unittest.TestCase):
    def test_nelder_mead_rosenbrock(self):
        x, fx = optimizacion.nelder_mead(lambda p: (1 - p[0]) ** 2 + 100 * (p[1] - p[0] ** 2) ** 2, [-1.2, 1.0], max_iter=5000, tol=1e-14)
        self.assertAlmostEqual(x[0], 1.0, places=3)
        self.assertAlmostEqual(x[1], 1.0, places=3)


class TestVolatilidad(unittest.TestCase):
    def test_garch_recupera_parametros(self):
        rnd = np.random.default_rng(7)
        w, a, b, n = 2e-6, 0.08, 0.90, 4000
        r, v = np.empty(n), w / (1 - a - b)
        for t in range(n):
            r[t] = math.sqrt(v) * rnd.standard_normal()
            v = w + a * r[t] ** 2 + b * v
        m = volatilidad.garch11(r)
        self.assertAlmostEqual(m["persistencia"], a + b, delta=0.03)
        self.assertAlmostEqual(m["alfa"], a, delta=0.04)
        self.assertGreater(len(volatilidad.pronostico_garch(m, 5)), 4)

    def test_estimadores_rango(self):
        rnd = np.random.default_rng(3)
        c = 100 * np.exp(np.cumsum(rnd.normal(0, 0.01, 500)))
        o = np.r_[100, c[:-1]]
        h, l = np.maximum(o, c) * 1.002, np.minimum(o, c) * 0.998
        self.assertGreater(volatilidad.parkinson(h, l), 0)
        self.assertGreater(volatilidad.garman_klass(o, h, l, c), 0)
        self.assertEqual(len(volatilidad.ewma(np.diff(np.log(c)))), 499)


class TestRegimen(unittest.TestCase):
    def test_hmm_separa_calma_y_turbulencia(self):
        rnd = np.random.default_rng(11)
        x = np.r_[rnd.normal(0, 0.005, 400), rnd.normal(0, 0.03, 300), rnd.normal(0, 0.005, 300)]
        m = regimen.ajustar(x, 2)
        self.assertLess(m["var"][0], m["var"][1])
        self.assertAlmostEqual(math.sqrt(m["var"][1]), 0.03, delta=0.006)
        camino = regimen.viterbi(x, m)
        self.assertGreater((camino[420:680] == 1).mean(), 0.9)
        self.assertGreater((camino[:380] == 0).mean(), 0.9)
        self.assertEqual(regimen.describir(m)["regimen_actual"], "calma")


class TestFiltros(unittest.TestCase):
    def test_kalman_reduce_ruido_y_estima_pendiente(self):
        rnd = np.random.default_rng(5)
        t = np.arange(600)
        real = 100 + 0.05 * t
        y = real + rnd.normal(0, 0.5, 600)
        k = filtros.kalman_tendencia(y)
        self.assertLess(np.abs(k["nivel"][100:] - real[100:]).mean(), np.abs(y[100:] - real[100:]).mean())
        self.assertAlmostEqual(k["pendiente"][-1], 0.05, delta=0.03)

    def test_ou_vida_media(self):
        x = estocastico.ou(0.0, theta=0.1, mu=0.0, sigma=0.2, pasos=5000, trayectorias=1, semilla=2)[0]
        r = filtros.ornstein_uhlenbeck(x)
        self.assertTrue(r["reversion"])
        self.assertAlmostEqual(r["vida_media"], math.log(2) / 0.1, delta=2.5)


class TestInformacion(unittest.TestCase):
    def test_hurst_y_entropias(self):
        rnd = np.random.default_rng(9)
        ruido = rnd.standard_normal(4000)
        self.assertAlmostEqual(informacion.hurst(ruido), 0.5, delta=0.1)
        self.assertGreater(informacion.entropia_permutacion(ruido), 0.97)
        self.assertLess(informacion.entropia_permutacion(np.arange(200.0)), 0.01)     # serie monótona: totalmente predecible
        x = rnd.standard_normal(3000)
        self.assertGreater(informacion.informacion_mutua(x, x + 0.1 * rnd.standard_normal(3000)), 1.0)
        self.assertLess(informacion.informacion_mutua(x, rnd.standard_normal(3000)), 0.05)

    def test_razon_varianzas(self):
        rnd = np.random.default_rng(4)
        self.assertGreater(informacion.razon_varianzas(rnd.standard_normal(3000))["p_valor"], 0.01)
        e = rnd.standard_normal(3000)
        ar = np.empty(3000)
        ar[0] = 0
        for i in range(1, 3000):
            ar[i] = 0.4 * ar[i - 1] + e[i]
        self.assertGreater(informacion.razon_varianzas(ar)["vr"], 1.3)                  # autocorrelación positiva


class TestCartera(unittest.TestCase):
    def setUp(self):
        rnd = np.random.default_rng(12)
        self.R = rnd.multivariate_normal([0, 0, 0], [[0.04, 0.01, 0], [0.01, 0.09, 0.02], [0, 0.02, 0.01]], 500)

    def test_ledoit_wolf_y_minima_varianza(self):
        S, d = cartera.ledoit_wolf(self.R)
        self.assertTrue(0 <= d <= 1)
        self.assertTrue(np.all(np.linalg.eigvalsh(S) > 0))
        w = cartera.minima_varianza(S)
        self.assertAlmostEqual(w.sum(), 1.0, places=9)
        self.assertTrue((w >= -1e-12).all())
        self.assertEqual(int(np.argmax(w)), 2)                                            # el activo de menor varianza pesa más

    def test_paridad_riesgo(self):
        S, _ = cartera.ledoit_wolf(self.R)
        w = cartera.paridad_riesgo(S)
        rc = cartera.contribuciones_riesgo(w, S)
        self.assertLess(rc.max() - rc.min(), 1e-6)

    def test_cvar_y_kelly(self):
        c = cartera.cvar(np.random.default_rng(1).normal(0, 1, 20000), 0.95)
        self.assertAlmostEqual(c["var"], 1.645, delta=0.05)
        self.assertAlmostEqual(c["cvar"], 2.063, delta=0.06)
        self.assertEqual(cartera.kelly(-0.1, 0.04), 0.0)


class TestDeterioro(unittest.TestCase):
    def test_detecta_caida(self):
        rnd = np.random.default_rng(6)
        x = np.r_[rnd.normal(0.4, 1, 60), rnd.normal(-0.6, 1, 60)]
        self.assertTrue(deterioro.deterioro(x)["deterioro"])
        self.assertFalse(deterioro.deterioro(rnd.normal(0.4, 1, 120))["deterioro"])


class TestEstocastico(unittest.TestCase):
    def test_gbm_media_y_toque(self):
        tr = estocastico.gbm(100, 0.0005, 0.01, 250, 4000, semilla=1)
        self.assertAlmostEqual(tr[:, -1].mean(), 100 * math.exp(0.0005 * 250), delta=1.5)
        p = estocastico.prob_toque(estocastico.gbm(100, 0.0, 0.01, 2000, 3000, semilla=3), 100, 98, 102)
        self.assertAlmostEqual(p["p_objetivo"], 0.5, delta=0.05)                           # simétrico sin deriva
        m = estocastico.merton(100, 0, 0.01, 0.05, -0.02, 0.03, 100, 500, semilla=1)
        self.assertEqual(m.shape, (500, 100))


class TestAprendizaje(unittest.TestCase):
    def test_walk_forward_detecta_senal_y_rechaza_ruido(self):
        rnd = np.random.default_rng(8)
        X = rnd.standard_normal((2000, 3))
        y = (rnd.random(2000) < 1 / (1 + np.exp(-(1.5 * X[:, 0])))).astype(float)
        self.assertTrue(aprendizaje.walk_forward(X, y)["util"])
        ruido = (rnd.random(2000) < 0.5).astype(float)
        self.assertFalse(aprendizaje.walk_forward(X, ruido)["util"])


if __name__ == "__main__":
    unittest.main()
