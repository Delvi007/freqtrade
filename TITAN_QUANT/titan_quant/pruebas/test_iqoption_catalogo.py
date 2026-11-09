"""Catálogo IQ Option: resolución de pares OTC, grupos independientes y caché de fallos.
Sin red: el WebSocket de IQ Option se sustituye por un canal falso."""
import time
import unittest
from unittest import mock

import iqoption_data as iq


class Canal:
    """Imita api.api de iqoptionapi: get_instruments(mercado) rellena .instruments de forma asíncrona."""

    def __init__(self, respuestas):
        self.respuestas = respuestas   # mercado -> dict de respuesta, o None para no responder
        self.instruments = None
        self.llamadas = []

    def get_instruments(self, mercado):
        self.llamadas.append(mercado)
        self.instruments = self.respuestas.get(mercado)


class Api:
    def __init__(self, respuestas):
        self.api = Canal(respuestas)


def _lista(*nombres, abierto=True):
    ahora = time.time()
    sched = [{"open": ahora - 3600, "close": ahora + 3600}] if abierto else []
    return {"instruments": [{"name": n, "schedule": sched} for n in nombres]}


class CatalogoTests(unittest.TestCase):

    def setUp(self):
        iq._CAT.clear()
        iq._FALLOS.clear()
        self._t = mock.patch.object(iq, "TIMEOUT_CATALOGO_S", 0.2)
        self._t.start()

    def tearDown(self):
        self._t.stop()
        iq._CAT.clear()
        iq._FALLOS.clear()

    def _con(self, api):
        return mock.patch.object(iq, "_api", return_value=api)

    def test_par_otc_se_encuentra_en_el_grupo_turbo(self):
        api = Api({"turbo": _lista("EURGBP-OTC", "EURUSD-OTC")})
        with self._con(api):
            nombre, grupo, abierto = iq.resolve("EURGBP-OTC")
        self.assertEqual((nombre, grupo, abierto), ("EURGBP-OTC", "turbo", True))

    def test_grupo_cfd_caido_no_bloquea_el_otc(self):
        api = Api({"cfd": None, "turbo": _lista("EURGBP-OTC")})   # cfd no responde
        with self._con(api):
            nombre, grupo, _ = iq.resolve("EURGBP-OTC")
        self.assertEqual(grupo, "turbo")
        self.assertEqual(api.api.llamadas[0:1], ["turbo"])   # el OTC no espera por cfd

    def test_fallo_se_guarda_y_no_se_reintenta_en_cada_ciclo(self):
        api = Api({"turbo": None, "binary": None})   # ningún grupo OTC responde
        with self._con(api), mock.patch.object(iq, "_activos_estaticos", return_value={}):
            with self.assertRaises(RuntimeError):
                iq.resolve("ZZZZ-OTC")
            llamadas_1 = len(api.api.llamadas)
            t0 = time.time()
            with self.assertRaises(RuntimeError):
                iq.resolve("ZZZZ-OTC")
            self.assertLess(time.time() - t0, 0.1, "el segundo intento debe salir de la caché de fallos")
        self.assertEqual(len(api.api.llamadas), llamadas_1, "no debe volver a pedir el catálogo")

    def test_par_inexistente_se_rechaza_sin_sustituirlo(self):
        api = Api({"turbo": _lista("EURGBP-OTC"), "binary": _lista("EURGBP-OTC")})
        with self._con(api):
            with self.assertRaises(LookupError):
                iq.resolve("AUDNZD-OTC")

    def test_otc_no_se_busca_en_forex_ni_cfd(self):
        api = Api({"turbo": _lista("EURGBP-OTC")})
        with self._con(api):
            iq.resolve("EURGBP-OTC")
        self.assertNotIn("forex", api.api.llamadas)
        self.assertNotIn("cfd", api.api.llamadas)

    def test_exito_se_cachea(self):
        api = Api({"turbo": _lista("EURGBP-OTC")})
        with self._con(api):
            iq.resolve("EURGBP-OTC")
            iq.resolve("EURGBP-OTC")
        self.assertEqual(api.api.llamadas.count("turbo"), 1)

    def test_catalogo_caido_usa_tabla_estatica_para_otc_conocido(self):
        api = Api({"turbo": None, "binary": None})   # catálogo sin respuesta
        with self._con(api), mock.patch.object(iq, "_activos_estaticos", return_value={"EURGBP-OTC": 77}):
            nombre, grupo, abierto = iq.resolve("EURGBP-OTC")
        self.assertEqual((nombre, grupo, abierto), ("EURGBP-OTC", "estatico", None))

    def test_catalogo_caido_sin_tabla_estatica_sigue_fallando(self):
        api = Api({"turbo": None, "binary": None})
        with self._con(api), mock.patch.object(iq, "_activos_estaticos", return_value={"EURGBP-OTC": 77}):
            with self.assertRaises(RuntimeError):
                iq.resolve("AUDNZD-OTC")


if __name__ == "__main__":
    unittest.main()
