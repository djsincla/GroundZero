"""SHA-512 crypt ("$6$"), the password hash format ESXi kickstart `rootpw --iscrypted` accepts.

Pure-Python implementation of Ulrich Drepper's SHA-crypt specification; the stdlib `crypt` module
is deprecated and removed in Python 3.13.
"""

from __future__ import annotations

import hashlib
import secrets

_ALPHABET = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_ROUNDS_DEFAULT = 5000
# Byte permutation used when encoding the final digest (from the specification).
_ORDER = (
    (0, 21, 42), (22, 43, 1), (44, 2, 23), (3, 24, 45), (25, 46, 4), (47, 5, 26), (6, 27, 48),
    (28, 49, 7), (50, 8, 29), (9, 30, 51), (31, 52, 10), (53, 11, 32), (12, 33, 54), (34, 55, 13),
    (56, 14, 35), (15, 36, 57), (37, 58, 16), (59, 17, 38), (18, 39, 60), (40, 61, 19), (62, 20, 41),
)  # fmt: skip


def _b64_from_24bit(b2: int, b1: int, b0: int, n: int) -> str:
    w = (b2 << 16) | (b1 << 8) | b0
    out = []
    for _ in range(n):
        out.append(_ALPHABET[w & 0x3F])
        w >>= 6
    return "".join(out)


def _repeat(digest: bytes, length: int) -> bytes:
    return (digest * (length // 64 + 1))[:length]


def sha512_crypt(password: str, salt: str | None = None, rounds: int = _ROUNDS_DEFAULT) -> str:
    key = password.encode()
    salt = (salt if salt is not None else "".join(secrets.choice(_ALPHABET) for _ in range(16)))[:16]
    s = salt.encode()

    b = hashlib.sha512(key + s + key).digest()
    a = hashlib.sha512(key + s + _repeat(b, len(key)))
    n = len(key)
    while n > 0:
        a.update(b if n & 1 else key)
        n >>= 1
    a_digest = a.digest()

    p = _repeat(hashlib.sha512(key * len(key)).digest(), len(key))
    s_bytes = _repeat(hashlib.sha512(s * (16 + a_digest[0])).digest(), len(s))

    c = a_digest
    for i in range(rounds):
        h = hashlib.sha512()
        h.update(p if i & 1 else c)
        if i % 3:
            h.update(s_bytes)
        if i % 7:
            h.update(p)
        h.update(c if i & 1 else p)
        c = h.digest()

    encoded = "".join(_b64_from_24bit(c[x], c[y], c[z], 4) for x, y, z in _ORDER)
    encoded += _b64_from_24bit(0, 0, c[63], 2)
    prefix = "$6$" if rounds == _ROUNDS_DEFAULT else f"$6$rounds={rounds}$"
    return f"{prefix}{salt}${encoded}"
