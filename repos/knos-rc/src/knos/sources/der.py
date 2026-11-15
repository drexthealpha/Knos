"""Just enough DER (ITU-T X.690) and X.509 (RFC 5280) to read a Sigstore signing certificate, and ECDSA over P-256 and
P-384 (FIPS 186-4, 6.4) to check what it signs. No third-party library: Knos adds no runtime dependency.

Only what a Fulcio certificate uses is read. Anything else is refused, never guessed."""
from __future__ import annotations

import base64
import calendar
import hashlib
from dataclasses import dataclass, field


class DerError(ValueError):
    pass


def tlv(raw: bytes, at: int = 0) -> tuple[int, bytes, int, int]:
    """(tag, value, start of the element, end of the element) of the element at `at`. Definite lengths only (DER)."""
    if at + 2 > len(raw):
        raise DerError("the element is cut short")
    tag, n, start = raw[at], raw[at + 1], at
    at += 2
    if n & 0x80:
        size = n & 0x7F
        if not 1 <= size <= 4 or at + size > len(raw):
            raise DerError("a length DER does not allow")
        n, at = int.from_bytes(raw[at:at + size], "big"), at + size
    if at + n > len(raw):
        raise DerError("the element is longer than the bytes")
    return tag, raw[at:at + n], start, at + n


def children(value: bytes) -> list[tuple[int, bytes, bytes]]:
    """The elements inside a constructed value: (tag, value, the whole element's bytes)."""
    out, at = [], 0
    while at < len(value):
        tag, v, start, end = tlv(value, at)
        out.append((tag, v, value[start:end]))
        at = end
    return out


def oid(value: bytes) -> str:
    if not value:
        raise DerError("an empty object identifier")
    parts, n = [value[0] // 40, value[0] % 40], 0
    for b in value[1:]:
        n = (n << 7) | (b & 0x7F)
        if not b & 0x80:
            parts.append(n)
            n = 0
    return ".".join(map(str, parts))


def _time(tag: int, value: bytes) -> int:
    text = value.decode("ascii")
    if tag == 0x17 and len(text) == 13 and text.endswith("Z"):         # UTCTime YYMMDDHHMMSSZ (RFC 5280, 4.1.2.5.1)
        year = int(text[:2])
        text = str(year + (2000 if year < 50 else 1900)) + text[2:]
    elif not (tag == 0x18 and len(text) == 15 and text.endswith("Z")):  # GeneralizedTime YYYYMMDDHHMMSSZ
        raise DerError("a time RFC 5280 does not allow")
    return calendar.timegm((int(text[:4]), int(text[4:6]), int(text[6:8]), int(text[8:10]), int(text[10:12]), int(text[12:14]), 0, 0, 0))


ECDSA_SHA256, ECDSA_SHA384 = "1.2.840.10045.4.3.2", "1.2.840.10045.4.3.3"
EC_KEY, P256_OID, P384_OID = "1.2.840.10045.2.1", "1.2.840.10045.3.1.7", "1.3.132.0.34"


@dataclass(frozen=True)
class Cert:
    der: bytes
    tbs: bytes                  # the signed part
    sig_alg: str
    signature: bytes            # DER ECDSA-Sig-Value
    issuer: bytes               # the issuer Name, as bytes
    subject: bytes
    not_before: int             # seconds since 1970, UTC
    not_after: int
    key: "Key"
    extensions: dict = field(default_factory=dict)     # oid -> the extension's value (the OCTET STRING's bytes)


@dataclass(frozen=True)
class Key:
    curve: str                  # "P-256" or "P-384"
    x: int
    y: int


def spki(der: bytes) -> Key:
    """A SubjectPublicKeyInfo holding an uncompressed EC point on P-256 or P-384."""
    tag, value, _, _ = tlv(der)
    if tag != 0x30:
        raise DerError("a public key is a SEQUENCE")
    alg, bits = children(value)
    params = children(alg[1])
    if oid(params[0][1]) != EC_KEY or len(params) != 2:
        raise DerError("only elliptic-curve keys are read")
    curve = {P256_OID: "P-256", P384_OID: "P-384"}.get(oid(params[1][1]))
    point = bits[1][1:]
    size = {"P-256": 32, "P-384": 48}.get(curve or "", 0)
    if not size or bits[0] != 0x03 or bits[1][:1] != b"\x00" or len(point) != 1 + 2 * size or point[0] != 4:
        raise DerError("the key is not an uncompressed point on P-256 or P-384")
    return Key(curve or "", int.from_bytes(point[1:1 + size], "big"), int.from_bytes(point[1 + size:], "big"))


def cert(der: bytes) -> Cert:
    tag, value, _, end = tlv(der)
    if tag != 0x30 or end != len(der):
        raise DerError("a certificate is one SEQUENCE")
    tbs_el, alg_el, sig_el = children(value)
    if sig_el[0] != 0x03 or sig_el[1][:1] != b"\x00":
        raise DerError("the signature is a BIT STRING")
    parts = children(tbs_el[1])
    if parts[0][0] == 0xA0:                 # [0] version: present in v3
        parts = parts[1:]
    _serial, inner_alg, issuer, validity, subject, key = parts[:6]
    if inner_alg[2] != alg_el[2]:
        raise DerError("the two signature algorithms differ")
    (t1, v1, _), (t2, v2, _) = children(validity[1])
    exts: dict = {}
    for tag_, val, _ in parts[6:]:
        if tag_ != 0xA3:                    # [3] extensions; the unique ids [1] [2] are never used by Fulcio
            raise DerError("a certificate field this reader does not know")
        for _t, ext, _w in children(children(val)[0][1]):
            items = children(ext)
            name = oid(items[0][1])
            if name in exts:
                raise DerError(f"the extension {name} appears twice")
            exts[name] = items[-1][1]
    return Cert(der, tbs_el[2], oid(children(alg_el[1])[0][1]), sig_el[1][1:], issuer[2], subject[2],
                _time(t1, v1), _time(t2, v2), spki(key[2]), exts)


def pem_certs(text: str) -> list[bytes]:
    out = []
    for block in text.split("-----BEGIN CERTIFICATE-----")[1:]:
        out.append(base64.b64decode("".join(block.split("-----END CERTIFICATE-----")[0].split())))
    return out


def text_ext(c: Cert, name: str) -> str | None:
    """A Fulcio extension's text: DER UTF8String for the 1.3.6.1.4.1.57264.1.8 and later ones, the raw bytes for the
    first six (Fulcio's OID document, https://github.com/sigstore/fulcio/blob/main/docs/oid-info.md)."""
    raw = c.extensions.get(name)
    if raw is None:
        return None
    if int(name.rsplit(".", 1)[1]) >= 8 and name.startswith("1.3.6.1.4.1.57264.1."):
        tag, value, _, end = tlv(raw)
        if tag != 0x0C or end != len(raw):
            raise DerError(f"the extension {name} is not a UTF8String")
        raw = value
    return raw.decode("utf-8")


def san_uris(c: Cert) -> list[str]:
    """The URIs of the Subject Alternative Name (2.5.29.17), GeneralName [6]."""
    raw = c.extensions.get("2.5.29.17")
    if raw is None:
        return []
    return [v.decode("utf-8") for t, v, _ in children(tlv(raw)[1]) if t == 0x86]


# -- ECDSA ------------------------------------------------------------------------------------------------------------
CURVES = {      # p, n, b, G (FIPS 186-4, D.1.2.3 and D.1.2.4); a is -3 on both
    "P-256": (0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF,
              0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551,
              0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B,
              (0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296,
               0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5), hashlib.sha256),
    "P-384": (0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFFFF0000000000000000FFFFFFFF,
              0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFC7634D81F4372DDF581A0DB248B0A77AECEC196ACCC52973,
              0xB3312FA7E23EE7E4988E056BE3F82D19181D9C6EFE8141120314088F5013875AC656398D8A2ED19D2A85C8EDD3EC2AEF,
              (0xAA87CA22BE8B05378EB1C71EF320AD746E1D3B628BA79B9859F741E082542A385502F25DBF55296C3A545E3872760AB7,
               0x3617DE4A96262C6F5D9E98BF9292DC29F8F41DBD289A147CE9DA3113B5F0B8C00A60B1CE1D7E819D7A431D7C90EA0E5F), hashlib.sha384),
}


def _add(a, b, p):
    if a is None or b is None:
        return a or b
    if a[0] == b[0] and (a[1] + b[1]) % p == 0:
        return None
    m = (3 * a[0] * a[0] - 3) * pow(2 * a[1], -1, p) % p if a == b else (b[1] - a[1]) * pow(b[0] - a[0], -1, p) % p
    x = (m * m - a[0] - b[0]) % p
    return x, (m * (a[0] - x) - a[1]) % p


def _mul(k, point, p):
    out = None
    while k:
        if k & 1:
            out = _add(out, point, p)
        point, k = _add(point, point, p), k >> 1
    return out


def ecdsa(key: Key, message: bytes, der_sig: bytes, digest=None) -> bool:
    """ECDSA verification. The hash is the curve's own (SHA-256 on P-256, SHA-384 on P-384) unless `digest` names
    another; the signature is DER (SEQUENCE of two INTEGERs), as X.509 and Sigstore write it."""
    p, n, b, g, h = CURVES[key.curve]
    try:
        tag, value, _, end = tlv(der_sig)
        (t1, r_raw, _), (t2, s_raw, _) = children(value)
    except (DerError, ValueError):
        return False
    if tag != 0x30 or end != len(der_sig) or t1 != 0x02 or t2 != 0x02:
        return False
    r, s = int.from_bytes(r_raw, "big"), int.from_bytes(s_raw, "big")
    if not (0 < r < n and 0 < s < n) or (key.y * key.y - (key.x ** 3 - 3 * key.x + b)) % p:
        return False
    e = int.from_bytes((digest or h)(message).digest()[:(n.bit_length() + 7) // 8], "big")
    w = pow(s, -1, n)
    got = _add(_mul(e * w % n, g, p), _mul(r * w % n, (key.x, key.y), p), p)
    return got is not None and got[0] % n == r
