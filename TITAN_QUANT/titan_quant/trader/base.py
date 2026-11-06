"""Contrato de los adaptadores de broker. Cada mercado/broker tiene el suyo; no se asume que todos hagan lo mismo."""


class ErrorAdaptador(Exception):
    pass


class Adaptador:
    id = ""
    nombre = ""
    mercados = ()                   # forex, cripto, acciones, etf, indices, futuros, commodities, binarias
    tipos_orden = ()                # binaria, mercado, limite...
    modalidades = ()                # simulacion, demo, real
    autenticacion = ""
    comisiones = ""
    spreads = ""
    limites_api = ""
    restricciones = ""
    compatibilidad = ""             # estado verificado por pruebas

    def ficha(self):
        return {k: getattr(self, k) for k in ("id", "nombre", "mercados", "tipos_orden", "modalidades", "autenticacion", "comisiones",
                                               "spreads", "limites_api", "restricciones", "compatibilidad")}

    def conectado(self):
        raise NotImplementedError

    def cotizacion(self, simbolo):
        """{'precio','bid','ask','spread','ts','edad_s','proveedor','instrumento'}"""
        raise NotImplementedError

    def abrir(self, solicitud):
        """Devuelve {'id_externo','precio_entrada','costo'} o lanza ErrorAdaptador."""
        raise NotImplementedError

    def actualizar(self, op):
        """Devuelve None si sigue abierta o {'precio_salida','resultado','motivo'} si se cerró."""
        raise NotImplementedError

    def cerrar(self, op, motivo):
        raise NotImplementedError

    def verificar(self, op):
        return True
