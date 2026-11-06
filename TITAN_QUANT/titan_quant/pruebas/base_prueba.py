"""Base común de las pruebas: datos temporales aislados y red sintética.
IMPORTANTE: las pruebas deben ejecutarse sobre una COPIA del proyecto (lo hace `python3 -m titan_quant.cli probar`)."""
import os
import shutil
import tempfile
import unittest

from titan_quant import config, db
from titan_quant.pruebas import sintetico
from titan_quant.seguridad import cripto, limites
from titan_quant.trader import almacen

sintetico.instalar()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="tq_prueba_")
        config.DATOS = config.Path(self.tmp)
        config.DB_PRINCIPAL = config.DATOS / "titan_quant.db"
        config.CLAVE_MAESTRA = config.DATOS / ".clave_maestra"
        config.SALIDA_CORREO = config.DATOS / "correo_saliente"
        config.RESPALDOS = config.DATOS / "respaldos"
        config.REGISTRO = config.DATOS / "titan.log"
        cripto._CACHE.clear()
        db.reiniciar_para_pruebas()
        almacen.reiniciar_para_pruebas()
        limites.reiniciar()
        os.environ.pop("TITAN_CLAVE_MAESTRA", None)

    def tearDown(self):
        almacen.reiniciar_para_pruebas()
        db.reiniciar_para_pruebas()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def usuario(self, correo="dueno@ejemplo.com", clave="Titan-Quant-2026!", nombre="Dueño"):
        from titan_quant.seguridad import cuentas
        u, tok = cuentas.registrar(nombre, correo, clave, clave, True)
        cuentas.verificar_correo(tok)
        with db.tx() as c:                     # en las pruebas generales, la cuenta queda aprobada
            c.execute("UPDATE usuarios SET aprobado=1 WHERE id=?", (u["id"],))
        return cuentas.usuario(u["id"])
