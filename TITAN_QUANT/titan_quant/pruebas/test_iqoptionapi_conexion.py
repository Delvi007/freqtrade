"""Conector IQ Option: esperas acotadas, TLS verificado, errores de login y disponibilidad real.

Cada prueba reproduce un fallo encontrado en la librería no oficial `iqoptionapi`:
  * bucles `while X == None: pass` sin límite (hilo colgado para siempre, CPU al 100 %);
  * `get_candles` evaluaba `self.check_connect` sin llamarlo (siempre verdadero);
  * websocket con `CERT_NONE` (sin verificar certificado) por el que viaja el SSID de la cuenta;
  * `connect()` hacía `response.text` sobre una excepción de red (AttributeError que ocultaba el motivo);
  * `change_balance()` llamaba a `exit(1)` y terminaba el proceso entero;
  * `disponible()` devolvía True aunque faltaran websocket-client/requests.
Ninguna prueba usa la red."""
import ssl
import sys
import time
import unittest
from unittest import mock

from iqoptionapi import esperas

try:
    import iqoptionapi.stable_api as stable_api
    import iqoptionapi.api as iq_api
    import iqoptionapi.global_value as global_value
    DEPENDENCIAS = True
except Exception:  # websocket-client / requests no instalados
    DEPENDENCIAS = False

requiere_dependencias = unittest.skipUnless(DEPENDENCIAS, "faltan websocket-client/requests (pip install -r requirements.txt)")


class TestEsperar(unittest.TestCase):
    def test_devuelve_en_cuanto_se_cumple(self):
        estado = {"n": 0}

        def cond():
            estado["n"] += 1
            return estado["n"] >= 3
        esperas.esperar(cond, timeout=2)
        self.assertEqual(estado["n"], 3)

    def test_vence_el_plazo_con_timeouterror(self):
        t0 = time.monotonic()
        with self.assertRaises(TimeoutError) as cm:
            esperas.esperar(lambda: False, timeout=0.2, que="nada")
        self.assertLess(time.monotonic() - t0, 1.5)
        self.assertIn("nada", str(cm.exception))

    def test_no_consume_cpu_mientras_espera(self):
        llamadas = {"n": 0}

        def cond():
            llamadas["n"] += 1
            return False
        with self.assertRaises(esperas.EsperaAgotada):
            esperas.esperar(cond, timeout=0.3)
        # con pausa de 20 ms son ~15 comprobaciones; un bucle activo haría cientos de miles
        self.assertLess(llamadas["n"], 100)

    def test_excepciones_de_la_condicion_cuentan_como_todavia_no(self):
        datos = {}
        hilo_datos = {"listo": False}

        def cond():
            if not hilo_datos["listo"]:
                hilo_datos["listo"] = True
                return datos["clave"]["id"]  # KeyError: la respuesta aún no existe
            return True
        esperas.esperar(cond, timeout=1)


class _Velas:
    candles_data = None


class _ApiFalsa:
    def __init__(self, entrega=None):
        self.candles = _Velas()
        self.entrega = entrega
        self.peticiones = 0

    def getcandles(self, *a):
        self.peticiones += 1
        if self.entrega is not None:
            self.candles.candles_data = self.entrega


@requiere_dependencias
class TestGetCandles(unittest.TestCase):
    def _iq(self, api, conectado):
        iq = object.__new__(stable_api.IQ_Option)
        iq.api = api
        iq.check_connect = lambda: conectado
        iq.connect = mock.Mock(return_value=(False, "sin red"))
        return iq

    def test_desconectado_no_se_cuelga(self):
        """Antes: `while self.check_connect and ...` era siempre verdadero -> bucle infinito."""
        api = _ApiFalsa(entrega=None)
        iq = self._iq(api, conectado=False)
        t0 = time.monotonic()
        with mock.patch.object(esperas, "ESPERA_MAX_S", 0.3):
            with self.assertRaises(TimeoutError):
                iq.get_candles("EURUSD", 60, 10, 1_700_000_000)
        self.assertLess(time.monotonic() - t0, 5)
        self.assertEqual(api.peticiones, 3)          # reintentos limitados
        self.assertEqual(iq.connect.call_count, 2)   # reconecta entre intentos, no tras el último

    def test_sin_respuesta_estando_conectado_vence_el_plazo(self):
        api = _ApiFalsa(entrega=None)
        iq = self._iq(api, conectado=True)
        with mock.patch.object(esperas, "ESPERA_MAX_S", 0.2):
            with self.assertRaises(TimeoutError):
                iq.get_candles("EURUSD", 60, 10, 1_700_000_000, intentos=1)

    def test_devuelve_las_velas(self):
        velas = [{"from": 1, "open": 1.0, "close": 1.1, "min": 0.9, "max": 1.2}]
        iq = self._iq(_ApiFalsa(entrega=velas), conectado=True)
        self.assertEqual(iq.get_candles("EURUSD", 60, 1, 1_700_000_000), velas)

    def test_activo_desconocido_devuelve_none(self):
        iq = self._iq(_ApiFalsa(), conectado=True)
        self.assertIsNone(iq.get_candles("NO-EXISTE-XYZ", 60, 1, 1))


@requiere_dependencias
class TestConexion(unittest.TestCase):
    def setUp(self):
        self._ssid = global_value.SSID
        global_value.SSID = None

    def tearDown(self):
        global_value.SSID = self._ssid

    def test_tls_del_websocket_verificado(self):
        op = iq_api._sslopt_verificado()
        self.assertEqual(op["cert_reqs"], ssl.CERT_REQUIRED)
        self.assertTrue(op["check_hostname"])

    def test_websocket_se_lanza_con_tls_verificado(self):
        api = iq_api.IQOptionAPI("iqoption.com", "u@example.com", "x")
        lanzado = {}

        class HiloFalso:
            def __init__(self, target=None, kwargs=None):
                lanzado.update(kwargs or {})
                self.daemon = False

            def start(self):
                global_value.check_websocket_if_connect = 1
        with mock.patch.object(iq_api.threading, "Thread", HiloFalso), \
                mock.patch.object(iq_api, "WebsocketClient", mock.Mock()):
            self.assertEqual(api.start_websocket(), (True, None))
        self.assertEqual(lanzado["sslopt"]["cert_reqs"], ssl.CERT_REQUIRED)

    def test_websocket_que_nunca_abre_no_se_cuelga(self):
        api = iq_api.IQOptionAPI("iqoption.com", "u@example.com", "x")

        class HiloMudo:
            def __init__(self, target=None, kwargs=None):
                self.daemon = False

            def start(self):
                pass
        with mock.patch.object(iq_api.threading, "Thread", HiloMudo), \
                mock.patch.object(iq_api, "WebsocketClient", mock.Mock()), \
                mock.patch.object(esperas, "ESPERA_MAX_S", 0.2):
            ok, motivo = api.start_websocket()
        self.assertFalse(ok)
        self.assertIn("websocket", motivo)

    def test_error_de_red_en_login_da_motivo_legible(self):
        """Antes: get_ssid() devolvía la excepción y connect() hacía response.text -> AttributeError."""
        api = iq_api.IQOptionAPI("iqoption.com", "u@example.com", "x")
        api.start_websocket = lambda: (True, None)
        api.close = lambda: None
        api.get_ssid = lambda: ConnectionError("sin red")
        ok, motivo = api.connect()
        self.assertFalse(ok)
        self.assertIn("ConnectionError", motivo)

    def test_peticiones_http_con_timeout(self):
        api = iq_api.IQOptionAPI("iqoption.com", "u@example.com", "x")
        respuesta = mock.Mock()
        api.session.request = mock.Mock(return_value=respuesta)
        api.send_http_request_v2("https://iqoption.com/api/x", "POST")
        self.assertEqual(api.session.request.call_args.kwargs["timeout"], esperas.HTTP_TIMEOUT)

    def test_modo_de_saldo_desconocido_no_termina_el_proceso(self):
        iq = object.__new__(stable_api.IQ_Option)
        iq.get_profile_ansyc = lambda: {"balances": [{"type": 4, "id": 1}]}
        iq.position_change_all = lambda *a: None
        with self.assertRaises(ValueError):
            iq.change_balance("INVENTADO")


class TestDisponible(unittest.TestCase):
    def test_false_si_faltan_dependencias(self):
        from titan_quant.trader import iqoption
        with mock.patch.dict(sys.modules, {"iqoptionapi.stable_api": None}):
            self.assertFalse(iqoption.disponible())


if __name__ == "__main__":
    unittest.main()
