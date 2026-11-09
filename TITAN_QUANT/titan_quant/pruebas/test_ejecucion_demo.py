"""Pruebas del ejecutor DEMO con una sesión FALSA. Demuestran la lógica de seguridad,
NO que cTrader haya aceptado una orden: esa prueba se hace contra el servidor DEMO real."""
from titan_quant import db
from titan_quant.pruebas.base_prueba import Base
from titan_quant.trader.base import ErrorAdaptador
from titan_quant.trader.ctrader_ws import ErrorCTrader
from titan_quant.trader import ejecucion_demo as ed


class SesionFalsa:
    def __init__(self, respuesta=None, error=None, bid=2000.0, ask=2000.2, edad=1):
        self.respuesta, self.error = respuesta, error
        self.cot = {"bid": bid, "ask": ask, "edad_s": edad}
        self.llamadas = 0

    def simbolo(self, sid):
        return {"vol_min": 100, "digitos": 2, "vol_paso": 100, "vol_max": None}

    def cotizacion(self, sid):
        return self.cot

    def orden_mercado(self, sid, lado, volumen, rel_stop, rel_obj, etiqueta, ref, comentario=""):
        self.llamadas += 1
        if self.error:
            raise self.error
        return self.respuesta

    def cerrar(self):
        pass


def decision(direccion="compra"):
    senal = {"direccion": direccion, "indice": 5, "rci": -70.0, "banda": 1999.0}
    return ed.crear_decision(senal, 2000.0, 2.0, timeframe="1h")


CONFIRMADA = {"posicion": 555, "precio": 2000.2, "volumen": 100, "comision": 0, "moneyDigits": 2}


class TestEjecucionDemo(Base):
    def test_stop_y_objetivo_en_atr(self):
        c = decision("compra")
        self.assertAlmostEqual(c["stop"], 2000.0 - 1.5 * 2.0)
        self.assertAlmostEqual(c["objetivo"], 2000.0 + 3.0 * 2.0)
        v = decision("venta")
        self.assertAlmostEqual(v["stop"], 2000.0 + 3.0)
        self.assertAlmostEqual(v["objetivo"], 2000.0 - 6.0)

    def test_requiere_temporalidad_y_atr_valido(self):
        with self.assertRaises(ValueError):
            ed.crear_decision({"direccion": "compra"}, 2000.0, 2.0)
        with self.assertRaises(ValueError):
            ed.crear_decision({"direccion": "compra"}, 2000.0, 0.0, timeframe="1h")

    def test_confirmada_y_no_se_reenvia(self):
        d = decision()
        s = SesionFalsa(respuesta=CONFIRMADA)
        r = ed.ejecutar_con_sesion(s, 41, "XAUUSD", d)
        self.assertEqual(r["estado"], "confirmada")
        self.assertEqual(r["posicion_id"], "555")
        self.assertEqual(s.llamadas, 1)
        r2 = ed.ejecutar_con_sesion(SesionFalsa(respuesta=CONFIRMADA), 41, "XAUUSD", d)
        self.assertEqual(r2["estado"], "confirmada")
        self.assertIn("no se reenvía", r2["nota"])

    def test_rechazo_se_registra(self):
        d = decision()
        with self.assertRaises(ErrorAdaptador):
            ed.ejecutar_con_sesion(SesionFalsa(error=ErrorCTrader("NOT_ENOUGH_MONEY", "saldo insuficiente")), 41, "XAUUSD", d)
        self.assertEqual(ed._estado(d["id"])["estado"], "rechazada")

    def test_timeout_deja_incierta_y_bloquea_reenvio(self):
        d = decision()
        s = SesionFalsa(error=ErrorCTrader("TIEMPO_AGOTADO", "no llegó la confirmación"))
        with self.assertRaises(ErrorAdaptador):
            ed.ejecutar_con_sesion(s, 41, "XAUUSD", d)
        self.assertEqual(ed._estado(d["id"])["estado"], "incierta")
        s2 = SesionFalsa(respuesta=CONFIRMADA)
        with self.assertRaises(ErrorAdaptador):
            ed.ejecutar_con_sesion(s2, 41, "XAUUSD", d)
        self.assertEqual(s2.llamadas, 0)                            # no reenvió a ciegas

    def test_confirmacion_sin_posicion_queda_incierta(self):
        d = decision()
        with self.assertRaises(ErrorAdaptador):
            ed.ejecutar_con_sesion(SesionFalsa(respuesta={"posicion": None, "precio": 2000.2}), 41, "XAUUSD", d)
        self.assertEqual(ed._estado(d["id"])["estado"], "incierta")

    def test_cotizacion_vieja_no_envia(self):
        d = decision()
        s = SesionFalsa(respuesta=CONFIRMADA, edad=120)
        with self.assertRaises(ErrorAdaptador):
            ed.ejecutar_con_sesion(s, 41, "XAUUSD", d)
        self.assertEqual(s.llamadas, 0)

    def test_precio_movido_cruza_stop_no_envia(self):
        d = decision()
        s = SesionFalsa(respuesta=CONFIRMADA, ask=1996.0, bid=1995.8)  # por debajo del stop 1997
        with self.assertRaises(ErrorAdaptador):
            ed.ejecutar_con_sesion(s, 41, "XAUUSD", d)
        self.assertEqual(s.llamadas, 0)

    def test_solo_demo(self):
        class Real:
            modalidad = "real"
        with self.assertRaises(ErrorAdaptador):
            ed.ejecutar(Real(), decision())
        d = decision(); d["modalidad"] = "real"
        with self.assertRaises(ErrorAdaptador):
            ed.ejecutar_con_sesion(SesionFalsa(respuesta=CONFIRMADA), 41, "XAUUSD", d)


if __name__ == "__main__":
    import unittest
    unittest.main()
