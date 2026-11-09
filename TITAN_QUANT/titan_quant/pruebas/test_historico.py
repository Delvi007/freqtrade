"""Pruebas del almacén histórico (fase 1). Son pruebas UNITARIAS con un adaptador falso:
no demuestran conexión con cTrader. La verificación real queda pendiente (autorización DEMO)."""
import datetime as dt
import math

from titan_quant import db, historico
from titan_quant.pruebas.base_prueba import Base

H1 = 3600
T0 = int(dt.datetime(2026, 11, 2, 0, 0, tzinfo=dt.timezone.utc).timestamp())  # lunes


class AdaptadorFalso:
    """Simula velas por hora. Omite [saltar_desde, saltar_hasta) para crear un hueco real."""
    def __init__(self, saltar_desde=None, saltar_hasta=None):
        self.llamadas = []
        self.saltar = (saltar_desde, saltar_hasta)

    def velas(self, sid, intervalo, desde_ms, hasta_ms, cuenta=None):
        self.llamadas.append((desde_ms, hasta_ms))
        out = []
        for ts in range(int(desde_ms // 1000), int(hasta_ms // 1000), H1):
            if self.saltar[0] is not None and self.saltar[0] <= ts < self.saltar[1]:
                continue
            p = 100 + math.sin(ts / 9000)
            out.append([ts, p, p + 0.5, p - 0.5, p + 0.1, 10.0])
        return out


class TestHistorico(Base):
    def test_valida_y_rechaza_ohlc_incoherente(self):
        r = historico.guardar("ctrader", "XAUUSD", "1h", [
            [T0, 1.0, 2.0, 0.5, 1.5, 3],        # válida
            [T0 + H1, 1.0, 0.9, 0.5, 1.5, 3],    # h < c  → inválida
            [T0 + 2 * H1, -1, 2, 0.5, 1.5, 3],   # precio negativo
            [T0 + 3 * H1, float("nan"), 2, 0.5, 1.5, 3],
        ])
        self.assertEqual(r["guardadas"], 1)
        self.assertEqual(r["rechazadas"], 3)
        self.assertEqual(r["motivos_rechazo"]["ohlc"], 1)
        self.assertEqual(r["motivos_rechazo"]["precio"], 2)

    def test_idempotente_y_deduplica_en_lote(self):
        velas = [[T0, 1, 2, 0.5, 1.5, 3], [T0, 1, 2.1, 0.5, 1.6, 4]]
        r = historico.guardar("ctrader", "XAUUSD", "1h", velas)
        self.assertEqual(r["guardadas"], 1)
        self.assertEqual(r["duplicadas_en_lote"], 1)
        historico.guardar("ctrader", "XAUUSD", "1h", velas)
        self.assertEqual(len(historico.leer("ctrader", "XAUUSD", "1h")), 1)

    def test_no_mezcla_proveedores(self):
        historico.guardar("ctrader", "EURUSD", "1h", [[T0, 1, 2, 0.5, 1.5, 3]])
        historico.guardar("otro", "EURUSD", "1h", [[T0, 9, 10, 8, 9.5, 1]])
        self.assertEqual(historico.leer("ctrader", "EURUSD", "1h")[0][1], 1)
        self.assertEqual(historico.leer("otro", "EURUSD", "1h")[0][1], 9)

    def test_detecta_huecos_y_marca_fin_de_semana(self):
        # Series contiguas por horas. Único hueco de mercado real: 8 barras el martes; el cierre
        # viernes 21:00 UTC → domingo 22:00 UTC se marca como fin de semana, no como hueco.
        viernes = int(dt.datetime(2026, 11, 6, 21, 0, tzinfo=dt.timezone.utc).timestamp())
        contiguas = list(range(T0, viernes + 1, H1))                   # lunes 00:00 → viernes 21:00, sin huecos
        hueco = set(range(T0 + 30 * H1, T0 + 38 * H1, H1))             # 8 barras perdidas (hueco real)
        reapertura = [viernes + 49 * H1 + i * H1 for i in range(0, 3)] # domingo 22:00 UTC en adelante
        todas = sorted([t for t in contiguas if t not in hueco] + reapertura)
        historico.guardar("ctrader", "EURUSD", "1h", [[t, 1, 2, 0.5, 1.5, 1] for t in todas])
        hs = historico.huecos("ctrader", "EURUSD", "1h")
        reales = [h for h in hs if not h["fin_de_semana"]]
        finde = [h for h in hs if h["fin_de_semana"]]
        self.assertEqual(len(reales), 1)
        self.assertEqual(reales[0]["faltantes"], 8)
        self.assertEqual(len(finde), 1)

    def test_descarga_incremental_y_sin_repetir(self):
        ad = AdaptadorFalso()
        r1 = historico.descargar_incremental(ad, "ctrader", "XAUUSD", 41, "1h", T0, T0 + 48 * H1, lote=10)
        self.assertEqual(r1["guardadas"], 48)
        self.assertEqual(len(historico.leer("ctrader", "XAUUSD", "1h")), 48)
        n_llamadas = len(ad.llamadas)
        r2 = historico.descargar_incremental(ad, "ctrader", "XAUUSD", 41, "1h", T0, T0 + 48 * H1, lote=10)
        self.assertEqual(r2["guardadas"], 0)
        self.assertEqual(len(ad.llamadas), n_llamadas)            # no vuelve a pedir lo ya guardado
        self.assertEqual(len(historico.leer("ctrader", "XAUUSD", "1h")), 48)

    def test_descarga_reporta_hueco_del_proveedor(self):
        ad = AdaptadorFalso(saltar_desde=T0 + 5 * H1, saltar_hasta=T0 + 9 * H1)
        historico.descargar_incremental(ad, "ctrader", "XAUUSD", 41, "1h", T0, T0 + 24 * H1, lote=24)
        hs = historico.huecos("ctrader", "XAUUSD", "1h")
        self.assertEqual(len(hs), 1)
        self.assertEqual(hs[0]["faltantes"], 4)

    def test_intervalo_no_soportado(self):
        with self.assertRaises(ValueError):
            historico.guardar("ctrader", "X", "7m", [])


if __name__ == "__main__":
    import unittest
    unittest.main()
