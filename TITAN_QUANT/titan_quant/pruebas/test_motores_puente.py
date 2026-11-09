import random
import sqlite3
import unittest

from titan_quant.binaria_bot.datos import Vela
from titan_quant.binaria_bot import motores_puente as mp
from titan_quant.motores import base


def _velas(n, seed=4, inicio=1_700_000_040):
    rnd = random.Random(seed)
    out, p, ts = [], 1.30, inicio
    for _ in range(n):
        o = p
        c = o + rnd.gauss(0, 0.0004)
        out.append(Vela(ts, o, max(o, c) + 0.0002, min(o, c) - 0.0002, c))
        p, ts = c, ts + 60
    return out


class PuenteTests(unittest.TestCase):

    def test_todos_los_motores_offline_estan_registrados(self):
        for m in mp.MOTORES_OFFLINE:
            self.assertIn(m, base.REGISTRO)

    def test_excluidos_no_se_pueden_pedir(self):
        with self.assertRaises(ValueError):
            mp.ejecutar(_velas(200), "GBPUSD-OTC", motores=("cross_asset",))

    def test_motores_offline_no_fallan_con_serie_suficiente(self):
        res = mp.ejecutar(_velas(600), "GBPUSD-OTC", nivel="basico")
        self.assertEqual(set(res), set(mp.MOTORES_OFFLINE))
        errores = {k: v["error"] for k, v in res.items() if v["estado"] == "error"}
        self.assertEqual(errores, {}, "ningún motor offline debe fallar")

    def test_orden_respeta_dependencias(self):
        orden = mp._orden(set(mp.MOTORES_OFFLINE))
        self.assertLess(orden.index("data"), orden.index("features"))
        self.assertLess(orden.index("features"), orden.index("technical"))
        self.assertLess(orden.index("backtesting"), orden.index("montecarlo"))

    def test_serie_corta_da_sin_datos_no_error(self):
        res = mp.ejecutar(_velas(30), "GBPUSD-OTC", motores=("data",))
        self.assertEqual(res["data"]["estado"], "sin_datos")

    def test_velas_no_contiguas_se_rechazan(self):
        v = _velas(100)
        del v[50]
        with self.assertRaises(ValueError):
            mp.serie_desde_m1(v, "GBPUSD-OTC")

    def test_no_escribe_en_la_base_de_titan(self):
        """El puente no debe llamar a Motor.ejecutar (que persiste estado en db.tx)."""
        import titan_quant.motores.base as b
        llamadas = []
        original = b.registrar_estado
        b.registrar_estado = lambda *a, **k: llamadas.append(a)
        try:
            mp.ejecutar(_velas(200), "GBPUSD-OTC", motores=("data", "features"))
        finally:
            b.registrar_estado = original
        self.assertEqual(llamadas, [])


if __name__ == "__main__":
    unittest.main()
