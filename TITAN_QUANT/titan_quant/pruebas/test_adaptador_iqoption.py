"""El adaptador IQ Option del bot debe recibir el correo guardado en la configuración
y la clave de la bóveda. Sin red: no se conecta a IQ Option."""
import unittest
from unittest import mock

from titan_quant.trader import autotrader


class AdaptadorIQOptionTests(unittest.TestCase):

    def test_correo_de_configuracion_llega_al_adaptador(self):
        cfg = {"correo": "cuenta@ejemplo.com", "clave": "clave-de-prueba"}
        with mock.patch("titan_quant.integraciones._config", return_value=cfg) as cfg_mock:
            ad = autotrader.adaptador_para(1, {"broker": "iqoption", "modalidad": "binaria"})
        cfg_mock.assert_called_once_with(1, "iqoption")
        self.assertEqual(ad.cred, cfg)


if __name__ == "__main__":
    unittest.main()
