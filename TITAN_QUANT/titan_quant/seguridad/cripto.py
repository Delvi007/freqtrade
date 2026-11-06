"""Cifrado de secretos y hash de contraseñas (solo biblioteca estándar; AES-GCM si `cryptography` existe).

Secretos (bóveda):
  * v2 = AES-256-GCM (si el paquete `cryptography` está instalado).
  * v1 = HMAC-SHA256 en modo contador como flujo + HMAC-SHA256 de autenticación (cifrar-luego-MAC).
    Es una construcción estándar basada en una PRF; detecta cualquier manipulación del texto cifrado.
  Las claves se derivan con HKDF-SHA256 de una clave maestra de 32 bytes (archivo 600 o variable
  TITAN_CLAVE_MAESTRA). Cada secreto se liga a (usuario, proveedor, campo): no se puede mover a otra fila.

Contraseñas: scrypt (N=2^14, r=8, p=1, sal de 16 bytes); si scrypt no existe, PBKDF2-SHA256 600 000 iteraciones.
"""
import base64
import hashlib
import hmac
import os
import secrets

from .. import config

try:  # opcional
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # type: ignore
except Exception:  # pragma: no cover - depende del entorno
    AESGCM = None


class ErrorCifrado(Exception):
    pass


# ----------------------------------------------------------------- clave maestra
_CACHE = {}


def clave_maestra():
    ruta = str(config.CLAVE_MAESTRA)
    if ruta in _CACHE:
        return _CACHE[ruta]
    env = os.environ.get("TITAN_CLAVE_MAESTRA", "").strip()
    if env:
        k = bytes.fromhex(env) if all(ch in "0123456789abcdefABCDEF" for ch in env) and len(env) == 64 else base64.urlsafe_b64decode(env + "==")
        if len(k) != 32:
            raise ErrorCifrado("TITAN_CLAVE_MAESTRA debe tener 32 bytes (64 hex).")
    else:
        config.asegurar_directorios()
        if not os.path.exists(ruta):
            fd = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(secrets.token_bytes(32))
        os.chmod(ruta, 0o600)
        with open(ruta, "rb") as f:
            k = f.read()
        if len(k) != 32:
            raise ErrorCifrado("La clave maestra está dañada (no tiene 32 bytes).")
    _CACHE[ruta] = k
    return k


def _hkdf(clave, info, largo=32):
    prk = hmac.new(b"titan-quant-v1", clave, hashlib.sha256).digest()
    out, t, i = b"", b"", 1
    while len(out) < largo:
        t = hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        out += t
        i += 1
    return out[:largo]


def _flujo(k, nonce, n):
    out = bytearray()
    ctr = 0
    while len(out) < n:
        out += hmac.new(k, nonce + ctr.to_bytes(8, "big"), hashlib.sha256).digest()
        ctr += 1
    return bytes(out[:n])


def cifrar(texto, contexto):
    datos = texto.encode("utf-8")
    ad = contexto.encode("utf-8")
    km = clave_maestra()
    if AESGCM is not None:
        nonce = secrets.token_bytes(12)
        ct = AESGCM(_hkdf(km, b"aesgcm")).encrypt(nonce, datos, ad)
        return b"TQ2" + nonce + ct
    nonce = secrets.token_bytes(16)
    ke, ka = _hkdf(km, b"enc"), _hkdf(km, b"mac")
    ct = bytes(a ^ b for a, b in zip(datos, _flujo(ke, nonce, len(datos))))
    tag = hmac.new(ka, b"TQ1" + nonce + len(ad).to_bytes(4, "big") + ad + ct, hashlib.sha256).digest()
    return b"TQ1" + nonce + ct + tag


def descifrar(blob, contexto):
    blob = bytes(blob)
    ad = contexto.encode("utf-8")
    km = clave_maestra()
    if blob[:3] == b"TQ2":
        if AESGCM is None:
            raise ErrorCifrado("Este secreto se cifró con AES-GCM y falta el paquete cryptography.")
        try:
            return AESGCM(_hkdf(km, b"aesgcm")).decrypt(blob[3:15], blob[15:], ad).decode("utf-8")
        except Exception:
            raise ErrorCifrado("No se pudo descifrar (clave distinta o datos alterados).") from None
    if blob[:3] != b"TQ1" or len(blob) < 3 + 16 + 32:
        raise ErrorCifrado("Formato de secreto desconocido.")
    nonce, ct, tag = blob[3:19], blob[19:-32], blob[-32:]
    ke, ka = _hkdf(km, b"enc"), _hkdf(km, b"mac")
    esperado = hmac.new(ka, b"TQ1" + nonce + len(ad).to_bytes(4, "big") + ad + ct, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, esperado):
        raise ErrorCifrado("No se pudo descifrar (clave distinta o datos alterados).")
    return bytes(a ^ b for a, b in zip(ct, _flujo(ke, nonce, len(ct)))).decode("utf-8")


def algoritmo():
    return "AES-256-GCM" if AESGCM is not None else "HMAC-SHA256-CTR + HMAC-SHA256 (encrypt-then-MAC)"


def enmascarar(valor):
    v = str(valor or "")
    if not v:
        return ""
    if "@" in v and len(v) > 5:
        u, d = v.split("@", 1)
        return (u[:2] + "•••@" + d)
    if len(v) <= 6:
        return "••••"
    return "••••" + v[-4:]


# ----------------------------------------------------------------- contraseñas
def hash_clave(clave):
    sal = secrets.token_bytes(16)
    if hasattr(hashlib, "scrypt"):
        try:
            h = hashlib.scrypt(clave.encode("utf-8"), salt=sal, n=2 ** 14, r=8, p=1, dklen=32)
            return "scrypt$16384$8$1$%s$%s" % (base64.b64encode(sal).decode(), base64.b64encode(h).decode())
        except (ValueError, MemoryError):
            pass
    h = hashlib.pbkdf2_hmac("sha256", clave.encode("utf-8"), sal, 600000)
    return "pbkdf2$600000$%s$%s" % (base64.b64encode(sal).decode(), base64.b64encode(h).decode())


def verificar_clave(clave, guardado):
    try:
        partes = guardado.split("$")
        if partes[0] == "scrypt":
            n, r, p = int(partes[1]), int(partes[2]), int(partes[3])
            sal, h = base64.b64decode(partes[4]), base64.b64decode(partes[5])
            calc = hashlib.scrypt(clave.encode("utf-8"), salt=sal, n=n, r=r, p=p, dklen=len(h))
        elif partes[0] == "pbkdf2":
            it, sal, h = int(partes[1]), base64.b64decode(partes[2]), base64.b64decode(partes[3])
            calc = hashlib.pbkdf2_hmac("sha256", clave.encode("utf-8"), sal, it)
        else:
            return False
        return hmac.compare_digest(calc, h)
    except Exception:
        return False


# Hash ficticio para igualar el tiempo de respuesta cuando el correo no existe (no revela cuentas).
_HASH_FALSO = None


def verificar_falso(clave):
    global _HASH_FALSO
    if _HASH_FALSO is None:
        _HASH_FALSO = hash_clave(secrets.token_hex(8))
    verificar_clave(clave, _HASH_FALSO)
    return False


def token():
    return secrets.token_urlsafe(32)


def h_token(t):
    return hashlib.sha256(t.encode("utf-8")).hexdigest()
