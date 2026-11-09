import types
import unittest

from titan_quant.binaria_sim.captura_options import instalar_captura_options


class _Api:
    get_options_v2_data = None


def _modulo_falso():
    m = types.ModuleType("cliente_falso")
    m.llamadas = []

    def sold_options(api, message):
        m.llamadas.append(message)
        return "original"

    m.sold_options = sold_options
    return m


class CapturaOptionsTests(unittest.TestCase):

    def test_guarda_mensaje_options_y_sigue_al_original(self):
        m = _modulo_falso()
        instalar_captura_options(m)
        api = _Api()
        msg = {"name": "options", "msg": {"closed_options": []}}
        self.assertEqual(m.sold_options(api, msg), "original")
        self.assertEqual(api.get_options_v2_data, msg)
        self.assertEqual(m.llamadas, [msg])

    def test_otros_mensajes_no_se_guardan(self):
        m = _modulo_falso()
        instalar_captura_options(m)
        api = _Api()
        m.sold_options(api, {"name": "otro"})
        self.assertIsNone(api.get_options_v2_data)

    def test_instalacion_idempotente(self):
        m = _modulo_falso()
        instalar_captura_options(m)
        primera = m.sold_options
        instalar_captura_options(m)
        self.assertIs(m.sold_options, primera, "no debe envolver dos veces")


if __name__ == "__main__":
    unittest.main()
