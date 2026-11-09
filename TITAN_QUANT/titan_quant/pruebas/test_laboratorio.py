import json
import os
import random
import tempfile
import unittest

from titan_quant.binaria_bot.laboratorio import construir_informe, main


def _crudas_aleatorias(ruta, minutos=600, seed=1):
    rnd = random.Random(seed)
    velas, precio, t = [], 1.30, 1_700_000_040  # alineado a minuto
    for _ in range(minutos * 12):  # 12 velas de 5 s por minuto
        o = precio
        c = o + rnd.gauss(0, 0.0004)
        velas.append({"from": t, "open": o, "close": c, "max": max(o, c) + 0.0001,
                      "min": min(o, c) - 0.0001, "volume": 0})
        precio, t = c, t + 5
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump({"meta": {"prueba": True}, "velas": velas}, f)


class LaboratorioTests(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.ruta = os.path.join(self.dir, "sintetico_5s.json")
        _crudas_aleatorias(self.ruta)

    def test_informe_contiene_tramos_y_evidencia(self):
        texto, ok = construir_informe(self.ruta, 0.86, 4)
        self.assertIn("Evidencia para operar", texto)
        self.assertIn("equilibrio: 0.5376", texto)
        self.assertFalse(ok, "un paseo aleatorio no debe dar evidencia")

    def test_main_escribe_informe(self):
        salida = os.path.join(self.dir, "informe.txt")
        self.assertEqual(main([self.ruta, "--informe", salida]), 0)
        with open(salida, encoding="utf-8") as f:
            self.assertIn("tramo", f.read())

    def test_archivo_sin_velas_validas(self):
        vacio = os.path.join(self.dir, "vacio.json")
        with open(vacio, "w", encoding="utf-8") as f:
            json.dump({"meta": {}, "velas": []}, f)
        texto, ok = construir_informe(vacio, 0.86, 4)
        self.assertFalse(ok)
        self.assertIn("Sin velas", texto)

    def test_formato_invalido_levanta_error(self):
        malo = os.path.join(self.dir, "malo.json")
        with open(malo, "w", encoding="utf-8") as f:
            json.dump({"otro": 1}, f)
        with self.assertRaises(ValueError):
            construir_informe(malo, 0.86, 4)


if __name__ == "__main__":
    unittest.main()
