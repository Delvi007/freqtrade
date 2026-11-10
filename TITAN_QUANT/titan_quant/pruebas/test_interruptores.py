"""C10 · Seguridad: PARADA TOTAL, interruptores por broker, protecciones que un proceso automático no puede desactivar."""
import time
from unittest import mock

from titan_quant import db
from titan_quant.pruebas.base_prueba import Base
from titan_quant.pruebas.ctrader_falso import CTraderFalso
from titan_quant.pruebas.test_evidencia import analisis, velas
from titan_quant.seguridad import boveda, interruptores
from titan_quant.trader import almacen, autotrader


class TestInterruptores(Base):
    def setUp(self):
        super().setUp()
        self.f = CTraderFalso().iniciar()
        self.W = self.f.mundo
        self.u = self.usuario()["id"]
        boveda.guardar(self.u, "ctrader", {"client_id": self.W.client_id, "client_secret": self.W.client_secret, "redirect_uri": "http://x/cb",
                                           "access_token": "tok-trading", "refresh_token": "ref-1"})
        autotrader.guardar_ajustes(self.u, "demo", {"estrategia": "multiactivo", "cuenta_ctid": 9001, "temporalidades": "1h", "lote_escaner": 1})
        autotrader.cambiar_estado(self.u, "demo", "activo")

    def tearDown(self):
        self.f.detener()
        super().tearDown()

    def cand(self):
        return [{"simbolo": "XAUUSD", "id": 41, "descripcion": "Gold", "estrategia": "cruce_ema", "params": {}, "direccion": "alcista",
                 "precio_ref": 2000.20, "atr": 2.0, "intervalo": "1h", "vela_ts": int(time.time()) - 3600 - 5, "exp_fuera": 0.2, "n_fuera": 30,
                 "tendencia": 0, "intervalo": "1h", "velas": velas(), "proveedor": "ctrader-demo"}]

    def ciclo(self):
        with mock.patch("titan_quant.backtest_ctrader.escaner.senales_vivas", return_value=self.cand()), \
             mock.patch("titan_quant.backtest_ctrader.escaner.actualizar_ranking", return_value=[]), \
             mock.patch("titan_quant.motores.nucleo.analizar", analisis(0.3)):
            return autotrader.ciclo(self.u, "demo")

    def test_parada_total_bloquea_todo_y_detiene_bots(self):
        r = interruptores.parada_total(self.u, "prueba")
        self.assertTrue(r["parada_global"])
        self.assertEqual(autotrader.estado(self.u, "demo")["estado"], "detenido")
        self.assertFalse(interruptores.permitido("ctrader")[0])
        with self.assertRaises(PermissionError):                       # no se puede arrancar un bot con la parada activa
            autotrader.cambiar_estado(self.u, "demo", "activo")
        self.assertEqual(self.W.ordenes, [])
        acciones = [a["accion"] for a in db.q("SELECT accion FROM auditoria")]
        self.assertIn("parada_total_activada", acciones)

    def test_reanudar_solo_usuario_con_clave_y_local(self):
        interruptores.parada_total(self.u, "prueba")
        for origen in ("ia", "sistema", "bot", "automatico"):
            with self.assertRaises(PermissionError):
                interruptores.reanudar(self.u, True, True, origen=origen)
        with self.assertRaises(PermissionError):
            interruptores.reanudar(self.u, False, True)
        with self.assertRaises(PermissionError):
            interruptores.reanudar(self.u, True, False)
        self.assertTrue(interruptores.estado()["parada_global"])
        interruptores.reanudar(self.u, True, True)
        self.assertFalse(interruptores.estado()["parada_global"])
        self.assertEqual(autotrader.estado(self.u, "demo")["estado"], "detenido")    # los bots no se reinician solos

    def test_broker_bloqueado_ninguna_orden_llega(self):
        interruptores.bloquear_broker(self.u, "ctrader", "revisión")
        self.assertEqual(self.ciclo()["accion"], "bloqueado_seguridad")
        self.assertEqual(self.W.ordenes, [])
        self.assertTrue(interruptores.permitido("iqoption")[0])                    # el otro broker sigue habilitado
        with self.assertRaises(PermissionError):
            interruptores.desbloquear_broker(self.u, "ctrader", True, True, origen="ia")
        interruptores.desbloquear_broker(self.u, "ctrader", True, True)
        self.assertEqual(self.ciclo()["resultados"][0]["accion"], "abrir")

    def test_defensa_en_profundidad_en_el_envio(self):
        """Aunque el bloqueo llegue entre los controles y el envío, la orden no sale al broker."""
        real = interruptores.permitido
        llamadas = {"n": 0}

        def permitido(b=None):
            llamadas["n"] += 1
            return (True, "") if llamadas["n"] <= 2 else (False, "bloqueado justo antes del envío")
        with mock.patch.object(interruptores, "permitido", permitido):
            r = self.ciclo()
        self.assertEqual(r["resultados"][0]["accion"], "bloqueado_seguridad", r)
        self.assertEqual(self.W.ordenes, [])
        self.assertIs(interruptores.permitido, real)

    def test_proteccion_automatica_por_ordenes_sin_confirmar(self):
        ahora = int(time.time())
        with almacen.tx("demo") as c:
            for i in range(3):
                c.execute("""INSERT INTO operaciones(usuario_id,modalidad,broker,instrumento,mercado,tipo,direccion,monto,estado,fase,abierta_ts)
                             VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (self.u, "demo", "ctrader", f"X{i}", "x", "margen", "alcista", 1, "error", "error_broker", ahora))
        autotrader._vigilar_errores_broker(self.u, "demo", {"broker": "ctrader"})
        e = interruptores.estado()
        self.assertTrue(e["brokers"]["ctrader"]["bloqueado"])
        self.assertEqual(e["brokers"]["ctrader"]["por"], "sistema")
        with self.assertRaises(PermissionError):                                  # el sistema bloquea, pero no puede desbloquear
            interruptores.desbloquear_broker(self.u, "ctrader", True, True, origen="sistema")

    def test_ajustes_protegidos_solo_usuario(self):
        autotrader.cambiar_estado(self.u, "demo", "detenido")
        with self.assertRaises(PermissionError):
            autotrader.guardar_ajustes(self.u, "demo", {"riesgo_pct": 3.0}, origen="ia")
        with self.assertRaises(PermissionError):
            autotrader.guardar_ajustes(self.u, "demo", {"sin_limites_perdida": True}, origen="optimizador")
        autotrader.guardar_ajustes(self.u, "demo", {"lote_escaner": 2}, origen="ia")             # no protegido: permitido
        autotrader.guardar_ajustes(self.u, "demo", {"riesgo_pct": 0.4})                           # el usuario sí puede
        self.assertEqual(autotrader.estado(self.u, "demo")["ajustes"]["riesgo_pct"], 0.4)

    def test_live_no_se_enciende_automaticamente(self):
        with self.assertRaises(PermissionError):
            autotrader.interruptor_live(self.u, "real", True, clave_ok=True, local=True, origen="ia")
        interruptores.parada_total(self.u, "prueba")
        with self.assertRaises(PermissionError):                       # ni el usuario enciende LIVE con la parada activa
            autotrader.interruptor_live(self.u, "binaria_real", True, clave_ok=True, local=True)
        self.assertFalse(autotrader.estado(self.u, "binaria_real")["real_habilitado"])
