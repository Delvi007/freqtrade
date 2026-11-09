"""Parche sobre iqoptionapi 7.1.1: captura el mensaje 'options' (historial de operaciones cerradas).

Defecto verificado en la librería: ws/client.py on_message no despacha el mensaje 'options' a su
handler, así que api.get_options_v2_data nunca se asigna. Este parche envuelve sold_options y
guarda el mensaje ANTES de seguir el flujo original.

Se aplica una sola vez por proceso. No cambia el comportamiento de ningún otro mensaje.
"""

_MARCA = "_titan_captura_options"


def instalar_captura_options(modulo_cliente=None):
    """modulo_cliente: módulo iqoptionapi.ws.client (inyectable para pruebas).
    Devuelve True si el parche quedó instalado en esta llamada o ya lo estaba."""
    if modulo_cliente is None:
        import iqoptionapi.ws.client as modulo_cliente  # importación diferida
    if getattr(modulo_cliente, _MARCA, False):
        return True
    original = modulo_cliente.sold_options

    def envoltorio(api, message):
        if isinstance(message, dict) and message.get("name") == "options":
            api.get_options_v2_data = message
        return original(api, message)

    modulo_cliente.sold_options = envoltorio
    setattr(modulo_cliente, _MARCA, True)
    return True
