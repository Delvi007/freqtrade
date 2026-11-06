"""Bóveda de credenciales: guarda cada campo secreto cifrado y devuelve solo su versión enmascarada.

El navegador nunca recibe un secreto completo: `listar()` da máscaras; `leer()` solo lo usan
los adaptadores en el servidor. Nada de esto se escribe en registros.
"""
import time

from .. import db
from . import cripto


def _ctx(uid, proveedor, campo):
    return f"u{uid}|{proveedor}|{campo}"


def guardar(uid, proveedor, campos):
    """campos: {nombre: valor}. Un valor vacío o None NO borra lo guardado (permite editar sin reescribir todo)."""
    ahora = int(time.time())
    with db.tx() as c:
        for campo, valor in campos.items():
            if valor is None or str(valor) == "":
                continue
            blob = cripto.cifrar(str(valor), _ctx(uid, proveedor, campo))
            c.execute("INSERT INTO credenciales(usuario_id,proveedor,campo,cifrado,mascara,actualizado_ts) VALUES(?,?,?,?,?,?) "
                      "ON CONFLICT(usuario_id,proveedor,campo) DO UPDATE SET cifrado=excluded.cifrado, mascara=excluded.mascara, actualizado_ts=excluded.actualizado_ts",
                      (uid, proveedor, campo, blob, cripto.enmascarar(valor), ahora))
    db.auditar(uid, "credenciales_guardadas", "integracion", proveedor, {"campos": sorted(k for k, v in campos.items() if v)})


def leer(uid, proveedor):
    out = {}
    for r in db.q("SELECT campo, cifrado FROM credenciales WHERE usuario_id=? AND proveedor=?", (uid, proveedor)):
        out[r["campo"]] = cripto.descifrar(r["cifrado"], _ctx(uid, proveedor, r["campo"]))
    return out


def mascaras(uid, proveedor):
    return {r["campo"]: {"mascara": r["mascara"], "actualizado_ts": r["actualizado_ts"]}
            for r in db.q("SELECT campo, mascara, actualizado_ts FROM credenciales WHERE usuario_id=? AND proveedor=?", (uid, proveedor))}


def eliminar(uid, proveedor):
    """Borrado seguro: se sobrescribe el blob antes de eliminar la fila."""
    with db.tx() as c:
        c.execute("UPDATE credenciales SET cifrado=zeroblob(length(cifrado)), mascara='' WHERE usuario_id=? AND proveedor=?", (uid, proveedor))
        n = c.execute("DELETE FROM credenciales WHERE usuario_id=? AND proveedor=?", (uid, proveedor)).rowcount
    db.auditar(uid, "credenciales_eliminadas", "integracion", proveedor, {"campos": n})
    return n
