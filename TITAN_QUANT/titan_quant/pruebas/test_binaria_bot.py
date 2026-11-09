import dataclasses
import random
import unittest

from titan_quant.binaria_bot.datos import Vela, agregar_m1, tramos_continuos
from titan_quant.binaria_bot.estadistica import (
    intervalo_wilson, punto_equilibrio, valor_esperado_unitario, ventaja_significativa,
)
from titan_quant.binaria_bot.riesgo import GestorRiesgo, LimitesRiesgo
from titan_quant.binaria_bot.backtest import evaluar_walk_forward, _operaciones_de_tramo
from titan_quant.estrategias.keltner_rci import senales


def _serie_m1(n, seed=7, inicio=1_700_000_000 // 60 * 60, p0=1.30):
    """Paseo aleatorio M1 contiguo, determinista."""
    rnd = random.Random(seed)
    velas, precio, ts = [], p0, inicio
    for _ in range(n):
        o = precio
        c = o + rnd.gauss(0, 0.0004)
        h = max(o, c) + abs(rnd.gauss(0, 0.0002))
        l = min(o, c) - abs(rnd.gauss(0, 0.0002))
        velas.append(Vela(ts, o, h, l, c))
        precio, ts = c, ts + 60
    return velas


class EstadisticaTests(unittest.TestCase):

    def test_wilson_valores_conocidos(self):
        bajo, alto = intervalo_wilson(0, 10)
        self.assertAlmostEqual(bajo, 0.0, places=6)
        self.assertAlmostEqual(alto, 0.2775, places=3)
        bajo, alto = intervalo_wilson(50, 100)
        self.assertAlmostEqual(bajo, 0.4038, places=3)
        self.assertAlmostEqual(alto, 0.5962, places=3)

    def test_wilson_entradas_invalidas(self):
        with self.assertRaises(ValueError):
            intervalo_wilson(11, 10)

    def test_equilibrio_y_ev_cero_en_frontera(self):
        eq = punto_equilibrio(0.86)
        self.assertAlmostEqual(eq, 1 / 1.86, places=9)
        self.assertAlmostEqual(valor_esperado_unitario(eq, 0.86), 0.0, places=9)

    def test_ventaja_no_se_declara_con_muestra_pequena(self):
        # 6/10 = 60 % supera el 53.8 %, pero el límite inferior de Wilson no.
        self.assertFalse(ventaja_significativa(6, 10, 0.86))
        self.assertTrue(ventaja_significativa(6000, 10000, 0.86))


class DatosTests(unittest.TestCase):

    def _cinco_s(self, inicio, segundos):
        return [{"from": inicio + s, "open": 1.0 + s, "max": 1.0 + s + 0.5,
                 "min": 1.0 + s - 0.5, "close": 1.0 + s + 0.1} for s in range(0, segundos, 5)]

    def test_agregacion_minuto_completo(self):
        m1 = agregar_m1(self._cinco_s(1_700_000_040, 120))
        # El primer minuto (…040 a …099) está incompleto (empieza en 40 s): se descarta.
        self.assertTrue(all(v.ts % 60 == 0 for v in m1))
        self.assertEqual(len(m1), len({v.ts for v in m1}))

    def test_minuto_parcial_descartado(self):
        # Inicio alineado a minuto (1700000040 % 60 == 0); se quitan los últimos 15 s del minuto.
        velas = self._cinco_s(1_700_000_040, 60)[:-3]
        self.assertEqual(agregar_m1(velas), [])

    def test_minuto_completo_con_inicio_desfasado_se_descarta(self):
        # Datos que empiezan 20 s después del inicio del minuto: no cubren el minuto.
        velas = self._cinco_s(1_700_000_060, 60)
        self.assertEqual(agregar_m1(velas), [])

    def test_huecos_cortan_tramos(self):
        s = _serie_m1(10)
        s2 = s[:5] + s[6:]
        self.assertEqual([len(t) for t in tramos_continuos(s2)], [5, 4])


class CausalidadTests(unittest.TestCase):

    def test_senales_no_usan_futuro(self):
        """Truncar la serie no debe cambiar las señales anteriores al corte."""
        v = _serie_m1(600, seed=3)
        high, low, close = [x.high for x in v], [x.low for x in v], [x.close for x in v]
        completo = senales(high, low, close)
        corte = 400
        parcial = senales(high[:corte], low[:corte], close[:corte])
        antes_completo = [e for e in completo if e["indice"] < corte]
        self.assertEqual(antes_completo, parcial)


class RiesgoTests(unittest.TestCase):

    def test_limites_inmutables(self):
        lim = LimitesRiesgo()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            lim.monto_max = 100.0

    def test_monto_base_no_supera_maximo(self):
        with self.assertRaises(ValueError):
            LimitesRiesgo(monto_base=2.0, monto_max=1.0)

    def test_kill_switch_bloquea_hasta_reactivar(self):
        g = GestorRiesgo(LimitesRiesgo())
        g.apagar("prueba")
        self.assertFalse(g.puede_operar()[0])
        g.reactivar()
        self.assertTrue(g.puede_operar()[0])

    def test_racha_detiene(self):
        g = GestorRiesgo(LimitesRiesgo(racha_perdidas_max=3, perdida_diaria_max=100, drawdown_max=100))
        for _ in range(3):
            g.registrar(-1.0)
        self.assertTrue(g.kill_switch)
        self.assertIn("racha", g.motivo_bloqueo)

    def test_perdida_diaria_detiene(self):
        g = GestorRiesgo(LimitesRiesgo(perdida_diaria_max=2.0, racha_perdidas_max=99, drawdown_max=100))
        g.registrar(-1.0)
        self.assertFalse(g.kill_switch)
        g.registrar(-1.0)
        self.assertTrue(g.kill_switch)

    def test_sin_martingala_monto_fijo_tras_perdida(self):
        g = GestorRiesgo(LimitesRiesgo(monto_base=1.0, monto_max=1.0))
        g.registrar(-1.0)
        # El monto que se puede pedir sigue siendo el base; nada escala la apuesta.
        self.assertTrue(g.puede_operar(1.0)[0])
        self.assertFalse(g.puede_operar(2.0)[0])

    def test_ganancia_resetea_racha(self):
        g = GestorRiesgo(LimitesRiesgo(racha_perdidas_max=3, perdida_diaria_max=100, drawdown_max=100))
        g.registrar(-1.0)
        g.registrar(-1.0)
        g.registrar(0.86)
        self.assertEqual(g.racha, 0)
        self.assertFalse(g.kill_switch)


class BacktestTests(unittest.TestCase):

    def test_operaciones_no_se_solapan_y_liquidan(self):
        v = _serie_m1(800, seed=11)
        ops = _operaciones_de_tramo(v, 0.86, {})
        self.assertGreater(len(ops), 0)
        for op in ops:
            self.assertIn(op.resultado, {"ganada", "perdida", "empate"})
            self.assertIn(op.neto, {0.86, -1.0, 0.0})

    def test_walk_forward_contabilidad_consistente(self):
        v = _serie_m1(3000, seed=5)
        res = evaluar_walk_forward(v, payout=0.86, k=4)
        self.assertEqual(len(res), 4)
        for r in res:
            self.assertEqual(r.n, r.ganadas + r.perdidas + r.empates)
            self.assertEqual(r.n, len(r.operaciones))

    def test_paseo_aleatorio_no_declara_ventaja(self):
        """Prueba nula: sin ventaja real, el laboratorio no debe declarar significancia en ningún tramo."""
        v = _serie_m1(20000, seed=2024)
        res = evaluar_walk_forward(v, payout=0.86, k=4, min_ops_tramo=30)
        self.assertFalse(any(r.ventaja_significativa for r in res))

    def test_entrada_y_salida_segun_definicion(self):
        # Verifica que la entrada es la apertura de j+1 y la salida el cierre de j+5.
        seg = _serie_m1(800, seed=9)
        ops = _operaciones_de_tramo(seg, 0.86, {})
        self.assertGreater(len(ops), 0)
        indice_de_ts = {v.ts: i for i, v in enumerate(seg)}
        for o in ops:
            j = indice_de_ts[o.ts_senal]
            self.assertEqual(o.entrada, seg[j + 1].open)
            self.assertEqual(o.salida, seg[j + 5].close)


if __name__ == "__main__":
    unittest.main()
