"""Configuración sencilla del panel: umbral de puntuación, confirmaciones y modo fijo por modalidad."""
import unittest

from titan_quant.trader import autotrader as at


class ConfigSencillaTests(unittest.TestCase):

    def test_valores_por_defecto(self):
        out = at.validar_ajustes("binaria", {})
        self.assertEqual(out["umbral_puntuacion"], 50.0)
        self.assertEqual(out["confirmaciones_minimas"], 2)
        self.assertTrue(out["modo_exploracion"])                         # práctica: exploración encendida por defecto
        self.assertFalse(at.validar_ajustes("binaria_real", {"modo_exploracion": True})["modo_exploracion"])   # REAL: nunca
        self.assertEqual(out["modo"], "binaria")

    def test_umbral_y_confirmaciones_editables(self):
        out = at.validar_ajustes("binaria", {"umbral_puntuacion": 65, "confirmaciones_minimas": 3, "modo_exploracion": True})
        self.assertEqual(out["umbral_puntuacion"], 65.0)
        self.assertEqual(out["confirmaciones_minimas"], 3)
        self.assertTrue(out["modo_exploracion"])

    def test_umbral_fuera_de_rango_se_rechaza(self):
        with self.assertRaises(ValueError):
            at.validar_ajustes("binaria", {"umbral_puntuacion": 101})
        with self.assertRaises(ValueError):
            at.validar_ajustes("demo", {"confirmaciones_minimas": 9})

    def test_modo_fijo_no_se_puede_cambiar(self):
        self.assertEqual(at.validar_ajustes("demo", {"modo": "binaria"})["modo"], "trader")
        self.assertEqual(at.validar_ajustes("binaria", {"modo": "trader"})["modo"], "binaria")


if __name__ == "__main__":
    unittest.main()
