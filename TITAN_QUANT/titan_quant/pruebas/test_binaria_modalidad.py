"""Modalidad 'binaria': configuración estándar, validación, puente con el escáner, restablecer,
y ciclo del bot con tope de operaciones abiertas. Sin red ni broker real: adaptador falso."""
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from titan_quant.binaria_bot import escaner as es
from titan_quant.binaria_bot import puente_trader as pt
from titan_quant.binaria_bot.almacen import Almacen
from titan_quant.pruebas.base_prueba import Base
from titan_quant.trader import almacen, autotrader
from titan_quant.trader.base import Adaptador

B = "binaria"
BASE_TS = 1_700_000_040


def velas(n, base=BASE_TS, precio=1.1):
    out = []
    for i in range(n):
        p = precio + 0.0001 * ((i * 7) % 13)
        out.append({"ts": base + 60 * i, "open": p, "high": p + 0.0002, "low": p - 0.0002, "close": p})
    return out


def senal_en_ultima(n):
    """Sustituye al detector: fuerza una señal en la última vela."""
    def fn(high, low, close, **_):
        return [{"indice": n - 1, "direccion": "compra", "precio": close[-1], "rci": 0.0, "banda": 0.0}]
    return fn


def _ruta_escaner():
    d = tempfile.mkdtemp(prefix="tq_escaner_")
    return os.path.join(d, "escaner_vivo.db")


def _vencida(ruta, activo, ts_entrada, ts_vence, resultado):
    a = Almacen(ruta)
    try:
        es._asegurar_esquema(a.con)
        a.con.execute("INSERT INTO candidatas (activo, ts_senal, ts_entrada, vence_ts, direccion, entrada, resultado)"
                      " VALUES (?,?,?,?,?,?,?)", (activo, ts_entrada - 60, ts_entrada, ts_vence, "CALL", 1.0, resultado))
        a.con.commit()
    finally:
        a.cerrar()


class ConfiguracionTests(unittest.TestCase):

    def test_modalidad_registrada_y_estandar(self):
        self.assertIn(B, almacen.MODALIDADES)
        p = autotrader.POR_DEFECTO[B]
        self.assertEqual((p["broker"], p["tipo"], p["expiracion_min"]), ("iqoption", "binaria", 5))
        x = autotrader.PERFIL_EXPLORACION_BINARIA                     # PRACTICE: perfil de exploración
        self.assertEqual((p["riesgo_pct"], p["perdida_diaria_max_pct"], p["drawdown_max_pct"]),
                         (x["riesgo_pct"], x["perdida_diaria_max_pct"], x["drawdown_max_pct"]))
        r = autotrader.POR_DEFECTO["binaria_real"]                    # REAL: límites estrictos sin cambios
        self.assertEqual((r["riesgo_pct"], r["perdida_diaria_max_pct"], r["drawdown_max_pct"]), (1.0, 3.0, 5.0))
        self.assertEqual(p["estrategia"], "multiactivo")                 # por defecto: escáner de todos los pares
        self.assertIn("binaria_real", almacen.MODALIDADES)                   # cuenta REAL con interruptor LIVE
        self.assertEqual(autotrader.BROKERS_POR_MODALIDAD[B], ("iqoption",))

    def test_solo_pares_otc_de_divisas(self):
        for malo in ("AMAZON-OTC", "XAUUSD-OTC", "BCHUSD-OTC", "USOUSD-OTC", "EURUSD"):
            with self.assertRaises(ValueError, msg=malo):
                autotrader.validar_ajustes(B, {"instrumento": malo, "estrategia": "keltner_rci_m1"})
        aj = autotrader.validar_ajustes(B, {"instrumento": "eurgbp-otc", "estrategia": "keltner_rci_m1"})
        self.assertEqual(aj["instrumento"], "EURGBP-OTC")

    def test_fuerza_expiracion_mercado_y_fuente(self):
        aj = autotrader.validar_ajustes(B, {"instrumento": "EURGBP-OTC", "expiracion_min": 15,
                                            "mercado": "forex", "fuente_datos": "yahoo"})
        self.assertEqual((aj["expiracion_min"], aj["tipo"], aj["mercado"], aj["fuente_datos"]),
                         (5, "binaria", "binarias", "broker"))

    def test_tipo_margen_con_iqoption_se_rechaza(self):
        with self.assertRaises(ValueError):
            autotrader.validar_ajustes(B, {"instrumento": "EURGBP-OTC", "tipo": "margen"})

    def test_no_admite_otro_broker(self):
        with self.assertRaises(ValueError):
            autotrader.validar_ajustes(B, {"instrumento": "EURGBP-OTC", "broker": "ctrader"})


class PuenteTests(unittest.TestCase):

    def test_no_otc_se_abstiene(self):
        an = pt.analizar_binaria("XAUUSD-OTC", "scalping", serie=velas(40), ruta_escaner=_ruta_escaner(),
                                 ahora=BASE_TS + 40 * 60)
        self.assertFalse(an["hay_oportunidad"])
        self.assertIn("no es un par OTC", an["fusion"]["motivo_sin_oportunidad"][0])

    def test_pocas_velas_se_abstiene(self):
        an = pt.analizar_binaria("EURGBP-OTC", "scalping", serie=velas(10), ruta_escaner=_ruta_escaner(),
                                 ahora=BASE_TS + 10 * 60)
        self.assertIn("datos insuficientes", an["fusion"]["motivo_sin_oportunidad"][0])

    def test_huecos_se_abstiene(self):
        v = velas(40)
        del v[-10:-5]   # hueco de 5 minutos dentro de las últimas 30 velas
        an = pt.analizar_binaria("EURGBP-OTC", "scalping", serie=v, ruta_escaner=_ruta_escaner(), ahora=BASE_TS + 41 * 60)
        self.assertIn("huecos", an["fusion"]["motivo_sin_oportunidad"][0])

    def test_velas_viejas_se_abstiene(self):
        an = pt.analizar_binaria("EURGBP-OTC", "scalping", serie=velas(40), ruta_escaner=_ruta_escaner(),
                                 ahora=BASE_TS + 40 * 60 + 3600)
        self.assertIn("no frescos", an["fusion"]["motivo_sin_oportunidad"][0])

    def test_sin_payout_se_abstiene(self):
        n = 40
        with mock.patch.object(pt, "senales", senal_en_ultima(n)):
            an = pt.analizar_binaria("EURGBP-OTC", "scalping", serie=velas(n), payout=None,
                                     ruta_escaner=_ruta_escaner(), ahora=BASE_TS + n * 60)
        self.assertFalse(an["hay_oportunidad"])
        self.assertEqual(an["binaria"]["categoria"], "payout_desconocido")

    def test_sin_muestra_suficiente_se_abstiene(self):
        n = 40
        with mock.patch.object(pt, "senales", senal_en_ultima(n)):
            an = pt.analizar_binaria("EURGBP-OTC", "scalping", serie=velas(n), payout=0.86,
                                     ruta_escaner=_ruta_escaner(), ahora=BASE_TS + n * 60)
        self.assertFalse(an["hay_oportunidad"])
        self.assertEqual(an["binaria"]["categoria"], "muestra_insuficiente")

    def test_con_historia_ganadora_previa_opera(self):
        n = 40
        ruta = _ruta_escaner()
        entrada = BASE_TS + (n - 1) * 60 + 60
        for i in range(30):   # 30 ganadas, todas VENCIDAS antes de la entrada
            _vencida(ruta, "EURGBP-OTC", entrada - 3600 - i * 600, entrada - 3600 - i * 600 + 300, "ganada")
        with mock.patch.object(pt, "senales", senal_en_ultima(n)):
            an = pt.analizar_binaria("EURGBP-OTC", "scalping", serie=velas(n), payout=0.80,
                                     ruta_escaner=ruta, ahora=BASE_TS + n * 60)
        self.assertTrue(an["hay_oportunidad"], an["binaria"])
        self.assertEqual(an["escenario"]["direccion"], "alcista")

    def test_causal_resultados_no_vencidos_no_cuentan(self):
        n = 40
        ruta = _ruta_escaner()
        entrada = BASE_TS + (n - 1) * 60 + 60
        for i in range(30):   # ganadas pero que vencen DESPUÉS de la entrada: no deben usarse
            ts = entrada + 3600 + 60 * i
            _vencida(ruta, "EURGBP-OTC", ts, ts + 300, "ganada")
        with mock.patch.object(pt, "senales", senal_en_ultima(n)):
            an = pt.analizar_binaria("EURGBP-OTC", "scalping", serie=velas(n), payout=0.80,
                                     ruta_escaner=ruta, ahora=BASE_TS + n * 60)
        self.assertFalse(an["hay_oportunidad"])
        self.assertEqual(an["binaria"]["categoria"], "muestra_insuficiente")


class FijoBin(Adaptador):
    """Adaptador falso de la modalidad binaria: sin red."""
    id, nombre = "iqoption", "IQ Option (prueba)"

    def __init__(self, abre=True):
        self.abre, self.abiertas = abre, 0

    def conectado(self):
        return True

    def saldo(self):
        return {"balance": 1000.0, "moneda": "PRACTICE"}

    def velas_m1(self, simbolo, n=120):
        return velas(40)

    def payout(self, simbolo):
        return 0.86

    def cotizacion(self, simbolo):
        return {"precio": 1.1, "bid": None, "ask": None, "spread": None, "edad_s": 5, "proveedor": "prueba", "instrumento": simbolo}

    def abrir(self, sol):
        self.abiertas += 1
        return {"id_externo": f"B{self.abiertas}", "precio_entrada": 1.1, "costo": 0.0, "fuente_precio": "prueba"}

    def verificar(self, op):
        return True

    def actualizar(self, op, ahora=None):
        return None


def analisis_binario(contador):
    def fn(instrumento, horizonte, nivel, politica, **kw):
        contador.append(1)
        return {"ts": 1_700_000_000, "activo": {"simbolo": instrumento, "nombre": instrumento, "clase": "binaria"},
                "horizonte": horizonte, "hay_oportunidad": True,
                "escenario": {"direccion": "alcista", "precio_referencia": 1.1, "stop_loss": None,
                              "take_profit": [None], "vigencia_hasta_ts": 1_700_000_000 + 300},
                "fusion": {"justificacion": ["escáner"], "motivo_sin_oportunidad": []},
                "fuente_datos": {"tipo": "IQ Option PRACTICE"}, "motores": [],
                "binaria": {"ok": True, "detalle": "Wilson superior al equilibrio (prueba)", "payout": 0.86,
                            "categoria": "ventaja"}}
    return fn


class CicloBinariaTests(Base):

    def setUp(self):
        super().setUp()
        self.u = self.usuario()["id"]
        autotrader.guardar_ajustes(self.u, B, {"estrategia": "keltner_rci_m1", "instrumento": "EURGBP-OTC"})   # modo de un par

    def _ciclo(self, contador, adaptador=None):
        return autotrader.ciclo(self.u, B, analizar_fn=analisis_binario(contador), adaptador=adaptador or FijoBin())

    def test_tope_de_abiertas_solo_bloquea_abrir_y_el_analisis_sigue(self):
        autotrader.guardar_ajustes(self.u, B, {"max_abiertas": 1})
        autotrader.cambiar_estado(self.u, B, "activo")
        # Una operación ya abierta: el tope (1) está lleno.
        with almacen.tx(B) as c:
            c.execute("INSERT INTO operaciones(usuario_id,modalidad,broker,cuenta,instrumento,simbolo_broker,mercado,tipo,direccion,"
                      "monto,estado,abierta_ts,estrategia,horizonte) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (self.u, B, "iqoption", B, "EURGBP-OTC", "EURGBP-OTC", "binarias", "binaria", "alcista", 10.0,
                       "abierta", 1_700_000_000, "keltner_rci_m1", "scalping"))
        llamadas = []
        ad = FijoBin()
        r = self._ciclo(llamadas, ad)
        self.assertEqual(len(llamadas), 1, "el análisis debe ejecutarse aunque el tope esté lleno")
        self.assertEqual(r["accion"], "rechazar")
        self.assertEqual(ad.abiertas, 0)
        ctl = {c["control"]: c["ok"] for c in r["controles"]}
        self.assertFalse(ctl["max_operaciones_abiertas"])
        self.assertTrue(ctl["ventaja_escaner"])

    def test_con_cupo_libre_abre(self):
        autotrader.guardar_ajustes(self.u, B, {"max_abiertas": 3})
        autotrader.cambiar_estado(self.u, B, "activo")
        ad = FijoBin()
        r = self._ciclo([], ad)
        self.assertEqual(r["accion"], "abrir")
        self.assertEqual(ad.abiertas, 1)

    def test_sin_ventaja_del_escaner_no_abre(self):
        autotrader.cambiar_estado(self.u, B, "activo")

        def sin_ventaja(instrumento, horizonte, nivel, politica, **kw):
            an = analisis_binario([])(instrumento, horizonte, nivel, politica, **kw)
            an["hay_oportunidad"] = False
            an["binaria"] = {"ok": False, "detalle": "Wilson inferior no supera equilibrio", "payout": 0.86, "categoria": "sin_ventaja"}
            an["fusion"]["motivo_sin_oportunidad"] = ["Wilson inferior no supera equilibrio"]
            return an
        ad = FijoBin()
        r = autotrader.ciclo(self.u, B, analizar_fn=sin_ventaja, adaptador=ad)
        self.assertEqual(r["accion"], "omitir")
        self.assertEqual(ad.abiertas, 0)

    def test_drawdown_de_dias_anteriores_no_bloquea(self):
        autotrader.guardar_ajustes(self.u, B, {"max_abiertas": 3, "capital_desde_broker": False})
        autotrader.cambiar_estado(self.u, B, "activo")
        ayer = 1_700_000_000
        with almacen.tx(B) as c:                                 # pérdida grande AYER: el drawdown del día empieza en cero
            c.execute("INSERT INTO operaciones(usuario_id,modalidad,broker,cuenta,instrumento,simbolo_broker,mercado,tipo,direccion,"
                      "monto,estado,fase,fuente_resultado,id_externo,abierta_ts,cerrada_ts,resultado,estrategia,horizonte) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (self.u, B, "iqoption", B, "EURGBP-OTC", "EURGBP-OTC", "binarias", "binaria", "alcista", 900.0, "cerrada",
                       "resultado_recibido", "broker", "X1", ayer, ayer + 300, -900.0, "keltner_rci_m1", "scalping"))
        r = self._ciclo([], FijoBin())
        self.assertEqual(r["accion"], "abrir", r)

    def test_restablecer_vuelve_al_estandar_sin_borrar_historial(self):
        autotrader.guardar_ajustes(self.u, B, {"max_abiertas": 7, "riesgo_pct": 2.0})
        with almacen.tx(B) as c:
            c.execute("INSERT INTO operaciones(usuario_id,modalidad,broker,cuenta,instrumento,simbolo_broker,mercado,tipo,direccion,"
                      "monto,estado,abierta_ts,estrategia,horizonte) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (self.u, B, "iqoption", B, "EURGBP-OTC", "EURGBP-OTC", "binarias", "binaria", "alcista", 10.0,
                       "cerrada", 1_700_000_000, "keltner_rci_m1", "scalping"))
        e = autotrader.restablecer(self.u, B)
        self.assertEqual(e["ajustes"]["max_abiertas"], autotrader.POR_DEFECTO[B]["max_abiertas"])
        self.assertEqual(e["ajustes"]["riesgo_pct"], autotrader.POR_DEFECTO[B]["riesgo_pct"])
        n = almacen.q1(B, "SELECT COUNT(*) n FROM operaciones")["n"]
        self.assertEqual(n, 1)

    def test_no_restablece_con_bot_activo(self):
        autotrader.cambiar_estado(self.u, B, "activo")
        with self.assertRaises(ValueError):
            autotrader.restablecer(self.u, B)


if __name__ == "__main__":
    unittest.main()


class SinLimitesTests(unittest.TestCase):
    def test_practica_no_se_detiene_y_real_conserva_los_limites(self):
        p = autotrader.POR_DEFECTO["binaria"]
        self.assertTrue(p["sin_limites_perdida"])
        self.assertEqual((p["riesgo_pct"], p["max_abiertas"]), (1.0, 10))
        self.assertGreaterEqual(p["exposicion_max_pct"], p["riesgo_pct"] * p["max_abiertas"])   # caben las 10 a la vez
        r = autotrader.validar_ajustes("binaria_real", {**autotrader.POR_DEFECTO["binaria_real"], "sin_limites_perdida": True})
        self.assertFalse(r["sin_limites_perdida"])                                              # REAL: siempre con límites
        self.assertFalse(autotrader.POR_DEFECTO["binaria_real"]["sin_limites_perdida"])
