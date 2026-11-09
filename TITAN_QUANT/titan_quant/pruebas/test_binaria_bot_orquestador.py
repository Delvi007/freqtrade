import os
import tempfile
import unittest

from titan_quant.binaria_bot.autonomia import Autonomia, decidir_accion, evidencia_suficiente
from titan_quant.binaria_bot.almacen import Almacen
from titan_quant.binaria_bot.orquestador import BotBinaria
from titan_quant.binaria_bot.riesgo import GestorRiesgo, LimitesRiesgo
from titan_quant.binaria_bot.backtest import ResumenTramo
from titan_quant.binaria_sim.adaptador_practica import Resultado


class FakeAdaptador:
    """Sustituye a AdaptadorPractica: registra llamadas y devuelve respuestas preparadas."""

    def __init__(self, respuestas=None, liquidacion=None):
        self.respuestas = list(respuestas or [])
        self.liquidacion = liquidacion
        self.envios = []
        self.apagado = False

    def enviar(self, activo, direccion, monto):
        self.envios.append((activo, direccion, monto))
        return self.respuestas.pop(0) if self.respuestas else Resultado("enviada", orden_id=str(900 + len(self.envios)))

    def liquidar(self, orden_id):
        return self.liquidacion

    def apagar_nuevas(self):
        self.apagado = True

    def reactivar(self):
        self.apagado = False


def _resumen(i, sig):
    return ResumenTramo(indice=i, n=100, ganadas=60, perdidas=40, empates=0, tasa_acierto=0.6,
                        wilson_bajo=0.5, wilson_alto=0.7, equilibrio=0.5376, ev_unitario=0.1,
                        ventaja_significativa=sig)


class AutonomiaTests(unittest.TestCase):

    def test_observar_y_sugerir_nunca_envian(self):
        self.assertEqual(decidir_accion(Autonomia.OBSERVAR, True, True), "observar")
        self.assertEqual(decidir_accion(Autonomia.SUGERIR, True, True), "sugerir")

    def test_confirmar_requiere_confirmacion(self):
        self.assertEqual(decidir_accion(Autonomia.CONFIRMAR, False, False), "esperar_confirmacion")
        self.assertEqual(decidir_accion(Autonomia.CONFIRMAR, False, True), "enviar")

    def test_automatico_sin_evidencia_solo_sugiere(self):
        self.assertEqual(decidir_accion(Autonomia.AUTOMATICO_PRACTICE, False, False), "sugerir")
        self.assertEqual(decidir_accion(Autonomia.AUTOMATICO_PRACTICE, True, False), "enviar")

    def test_evidencia_exige_todos_los_tramos(self):
        ok, _ = evidencia_suficiente([_resumen(i, True) for i in range(4)])
        self.assertTrue(ok)
        ok, motivo = evidencia_suficiente([_resumen(i, i != 2) for i in range(4)])
        self.assertFalse(ok)
        self.assertIn("[2]", motivo)

    def test_sin_datos_o_pocos_tramos_no_hay_evidencia(self):
        self.assertFalse(evidencia_suficiente([])[0])
        self.assertFalse(evidencia_suficiente([_resumen(0, True)])[0])


class OrquestadorTests(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.almacen = Almacen(os.path.join(self.dir, "binaria_bot_prueba.db"))

    def tearDown(self):
        self.almacen.cerrar()

    def _bot(self, adaptador, autonomia=Autonomia.AUTOMATICO_PRACTICE, evidencia=True, limites=None):
        gestor = GestorRiesgo(limites or LimitesRiesgo(perdida_diaria_max=100, racha_perdidas_max=100,
                                                       drawdown_max=100))
        return BotBinaria(adaptador, gestor, self.almacen, autonomia, evidencia)

    def test_observar_no_envia(self):
        ad = FakeAdaptador()
        r = self._bot(ad, Autonomia.OBSERVAR).procesar_senal(1, "GBPUSD-OTC", "CALL", 1.0)
        self.assertEqual(r["accion"], "observar")
        self.assertEqual(ad.envios, [])

    def test_automatico_envia_y_registra(self):
        ad = FakeAdaptador()
        r = self._bot(ad).procesar_senal(1, "GBPUSD-OTC", "CALL", 1.0)
        self.assertEqual(r["accion"], "enviada")
        self.assertEqual(len(ad.envios), 1)
        self.assertEqual(self.almacen.pendientes()[0]["orden_broker"], "901")

    def test_monto_mayor_al_limite_no_envia(self):
        ad = FakeAdaptador()
        r = self._bot(ad).procesar_senal(1, "GBPUSD-OTC", "CALL", 2.0)
        self.assertEqual(r["accion"], "bloqueada")
        self.assertEqual(ad.envios, [])

    def test_orden_desconocida_bloquea_y_no_reintenta(self):
        ad = FakeAdaptador([Resultado("desconocida", motivo="no confirmada")])
        bot = self._bot(ad)
        self.assertEqual(bot.procesar_senal(1, "GBPUSD-OTC", "CALL", 1.0)["accion"], "desconocida")
        self.assertEqual(len(ad.envios), 1, "no debe reintentarse")
        self.assertTrue(bot.gestor.kill_switch)
        r = bot.procesar_senal(2, "GBPUSD-OTC", "PUT", 1.0)
        self.assertEqual(r["accion"], "bloqueada")
        self.assertEqual(len(ad.envios), 1)

    def test_reanudar_exige_conciliacion_previa(self):
        ad = FakeAdaptador([Resultado("desconocida", motivo="x")])
        bot = self._bot(ad)
        bot.procesar_senal(1, "GBPUSD-OTC", "CALL", 1.0)
        self.assertTrue(bot.gestor.kill_switch)
        ok, _ = bot.reanudar()
        self.assertFalse(ok, "no debe reanudar sin conciliar")
        bot.confirmar_conciliacion_manual()
        ok, _ = bot.reanudar()
        self.assertTrue(ok)
        self.assertFalse(bot.gestor.kill_switch)
        self.assertFalse(ad.apagado)

    def test_parada_emergencia_bloquea_todo(self):
        ad = FakeAdaptador()
        bot = self._bot(ad)
        bot.parada_emergencia()
        self.assertTrue(ad.apagado)
        self.assertEqual(bot.procesar_senal(1, "GBPUSD-OTC", "CALL", 1.0)["accion"], "bloqueada")
        self.assertEqual(ad.envios, [])

    def test_sin_evidencia_automatico_solo_sugiere(self):
        ad = FakeAdaptador()
        r = self._bot(ad, evidencia=False).procesar_senal(1, "GBPUSD-OTC", "CALL", 1.0)
        self.assertEqual(r["accion"], "sugerir")
        self.assertEqual(ad.envios, [])

    def test_liquidacion_actualiza_riesgo_y_bd(self):
        ad = FakeAdaptador(liquidacion=("perdida", -1.0))
        bot = self._bot(ad)
        bot.procesar_senal(1, "GBPUSD-OTC", "CALL", 1.0)
        cerradas = bot.liquidar_pendientes()
        self.assertEqual(len(cerradas), 1)
        self.assertEqual(bot.gestor.pnl_dia, -1.0)
        self.assertEqual(self.almacen.pendientes(), [])

    def test_almacen_rechaza_ruta_sin_db(self):
        with self.assertRaises(ValueError):
            Almacen(os.path.join(self.dir, "x.txt"))


if __name__ == "__main__":
    unittest.main()
