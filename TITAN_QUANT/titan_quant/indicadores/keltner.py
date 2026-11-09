"""Canal de Keltner según el script de referencia del usuario.

Fórmulas (idénticas al script, con el multiplicador por defecto ajustado a 2):
    typical  = (high + low + close) / 3          (hlc3)
    middle   = media(typical, periodo)           (por defecto EMA; igual que averages[fn])
    offset   = RMA(True Range, periodo) * multiplicador
    upper    = middle + offset
    lower    = middle - offset
"""
from .suavizado import ema, rma, sma, true_range

MEDIAS = {"ema": ema, "sma": sma}


def keltner(high, low, close, periodo=20, multiplicador=2.0, media="ema"):
    if media not in MEDIAS:
        raise ValueError("Media no soportada: " + str(media) + " (use: " + ", ".join(MEDIAS) + ")")
    if multiplicador <= 0:
        raise ValueError("El multiplicador debe ser > 0")
    tipico = [(h + l + c) / 3.0 for h, l, c in zip(high, low, close)]
    middle = MEDIAS[media](tipico, periodo)
    offset_base = rma(true_range(high, low, close), periodo)
    upper, lower, offset = [], [], []
    for m, o in zip(middle, offset_base):
        if m is None or o is None:
            upper.append(None); lower.append(None); offset.append(None)
        else:
            d = o * multiplicador
            offset.append(d); upper.append(m + d); lower.append(m - d)
    return {"upper": upper, "middle": middle, "lower": lower, "offset": offset}
