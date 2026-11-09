"""Contrato de los adaptadores de broker. Cada mercado/broker tiene el suyo; no se asume que todos hagan lo mismo.

Regla de integridad: un adaptador SOLO devuelve datos que proceden del broker. Si el broker no confirma algo,
el adaptador lo dice (None / confirmada=False / OrdenNoConfirmada); nunca lo deduce ni lo inventa.
"""


class ErrorAdaptador(Exception):
    """El broker (o el adaptador antes de enviar) rechazó la orden: con certeza NO se ejecutó."""


class OrdenNoConfirmada(Exception):
    """La orden se envió pero el broker no dio una respuesta clara: PUDO ejecutarse. Hay que conciliarla."""


class Adaptador:
    id = ""
    nombre = ""
    mercados = ()                   # forex, cripto, acciones, etf, indices, futuros, commodities, binarias
    tipos_orden = ()                # binaria, mercado, limite...
    modalidades = ()                # demo, binaria (practice)
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
        """Envía la orden. Devuelve {'id_externo', 'precio_entrada' (del broker o None), 'costo', 'evidencia', ...}.
        Lanza ErrorAdaptador si el broker la rechazó y OrdenNoConfirmada si el estado es dudoso."""
        raise NotImplementedError

    def verificar_apertura(self, op):
        """{'confirmada': bool, 'precio_entrada'?, 'evidencia'?}: el broker confirma que la operación está abierta."""
        return {"confirmada": False, "detalle": "este adaptador no sabe verificar aperturas"}

    def actualizar(self, op):
        """None si sigue abierta o sin resultado del broker; {'precio_salida','resultado','motivo','evidencia'?} con el
        resultado QUE DA EL BROKER cuando se cerró."""
        raise NotImplementedError

    def cerrar(self, op, motivo):
        raise NotImplementedError

    def verificar(self, op):
        return bool(self.verificar_apertura(op).get("confirmada"))
