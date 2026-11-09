import unittest

from titan_quant.binaria_bot.leer_payouts import payouts_desde_perfil, tabla_comparativa


class _Perfil(dict):
    pass


DATOS = {
    "EURUSD-OTC": {"binary": 0.85, "turbo": 0.86},
    "AUDCAD-OTC": {"binary": 0.85, "turbo": 0.85},
    "SPY": {"binary": 0.86, "turbo": 0.86},          # ETF: fuera
    "GBPUSD-OTC": {"binary": None, "turbo": 0.86},   # sin valor en esta clave
    "USDJPY-OTC": {"binary": 86.0, "turbo": 0.86},   # escala incorrecta: fuera
}


class LectorPayoutsTests(unittest.TestCase):

    def test_filtra_otc_de_divisas_y_clave(self):
        self.assertEqual(payouts_desde_perfil(DATOS, "binary"), {"EURUSD-OTC": 0.85, "AUDCAD-OTC": 0.85})

    def test_clave_turbo(self):
        self.assertEqual(payouts_desde_perfil(DATOS, "turbo"),
                         {"EURUSD-OTC": 0.86, "AUDCAD-OTC": 0.85, "GBPUSD-OTC": 0.86, "USDJPY-OTC": 0.86})

    def test_clave_desconocida_falla(self):
        with self.assertRaises(ValueError):
            payouts_desde_perfil(DATOS, "digital")

    def test_tabla_muestra_ambas_claves(self):
        t = tabla_comparativa(DATOS)
        self.assertIn("EURUSD-OTC", t)
        self.assertIn("0.85", t)
        self.assertNotIn("SPY", t)


if __name__ == "__main__":
    unittest.main()
