"""
Android key attestation: proof that the phone's sign-in key was made inside its security hardware, for
this activation, by our app.

The phone sends the certificate chain Android gives for the new key (leaf first). We check:
  1. each certificate is signed by the next, and the last one is one of Google's attestation roots
     (attestation_roots.json, downloaded by .github/workflows/attestation-roots.yml);
  2. the attestation challenge equals the one derived from this activation code, so the chain was made
     for this activation and cannot be replayed;
  3. the key lives in the secure area (TEE) or a separate security chip (StrongBox), not software;
  4. the phone's verified boot state is not "unverified" or "failed" (a modified system);
  5. the key was made by our app's package and, when MOBILE_APP_SIGNATURE_SHA256 is set, by an app signed
     with our release certificate, so a re-signed or modified copy of the app is refused.
Revocation of attestation certificates is not checked: clinic servers often run without internet.
"""
from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from django.conf import settings

KEY_DESCRIPTION_OID = x509.ObjectIdentifier("1.3.6.1.4.1.11129.2.1.17")
TAG_ATTESTATION_APPLICATION_ID = 709
TAG_ROOT_OF_TRUST = 704
SECURITY_LEVELS = {0: "software", 1: "tee", 2: "strongbox"}
BOOT_STATES = {0: "verified", 1: "self_signed", 2: "unverified", 3: "failed"}


class AttestationError(ValueError):
    pass


@dataclass(frozen=True)
class Attested:
    public_key_der: bytes
    security_level: str
    boot_state: str
    device_locked: bool | None
    package_names: tuple[str, ...]
    signature_digests: tuple[str, ...]


def activation_challenge(code: str) -> bytes:
    """What the phone passes to setAttestationChallenge: tied to the one-time code."""
    return hashlib.sha256(b"mrs-activate:" + normalise_code(code).encode()).digest()


def normalise_code(code: str) -> str:
    return "".join(ch for ch in str(code).upper() if ch.isalnum())


# --- A small DER reader: enough for the KeyDescription structure, including high tag numbers. ---

def _read(data: bytes, i: int) -> tuple[int, bool, int, bytes, int]:
    """Returns (tag class, constructed, tag number, content, next index)."""
    if i >= len(data):
        raise AttestationError("Truncated attestation data.")
    first = data[i]
    cls, constructed, tag = first >> 6, bool(first & 0x20), first & 0x1F
    i += 1
    if tag == 0x1F:
        tag = 0
        while True:
            b = data[i]
            i += 1
            tag = (tag << 7) | (b & 0x7F)
            if not b & 0x80:
                break
    length = data[i]
    i += 1
    if length & 0x80:
        n = length & 0x7F
        if n == 0 or n > 4:
            raise AttestationError("Unsupported length in attestation data.")
        length = int.from_bytes(data[i:i + n], "big")
        i += n
    end = i + length
    if end > len(data):
        raise AttestationError("Truncated attestation data.")
    return cls, constructed, tag, data[i:end], end


def _children(content: bytes) -> list[tuple[int, bool, int, bytes]]:
    out, i = [], 0
    while i < len(content):
        cls, constructed, tag, value, i = _read(content, i)
        out.append((cls, constructed, tag, value))
    return out


def _int(value: bytes) -> int:
    return int.from_bytes(value, "big", signed=True) if value else 0


def _authorisations(content: bytes) -> dict[int, bytes]:
    """AuthorizationList: SEQUENCE of [tag] EXPLICIT values. Returns tag -> inner DER element."""
    found = {}
    for cls, _constructed, tag, value in _children(content):
        if cls == 2:  # context-specific
            found[tag] = value
    return found


def _parse_key_description(ext_value: bytes) -> dict:
    _cls, _c, _tag, seq, _ = _read(ext_value, 0)
    items = _children(seq)
    if len(items) < 8:
        raise AttestationError("Unexpected attestation format.")
    security_level = _int(items[1][3])
    challenge = items[4][3]
    software = _authorisations(items[6][3])
    hardware = _authorisations(items[7][3])

    packages: list[str] = []
    digests: list[str] = []
    app_id = software.get(TAG_ATTESTATION_APPLICATION_ID) or hardware.get(TAG_ATTESTATION_APPLICATION_ID)
    if app_id:
        _c1, _cc, _t, octets, _ = _read(app_id, 0)  # EXPLICIT wrapper holds an OCTET STRING
        _c2, _cc2, _t2, app_seq, _ = _read(octets, 0)  # AttestationApplicationId SEQUENCE
        parts = _children(app_seq)
        if parts:
            for _a, _b, _c3, info in _children(parts[0][3]):  # SET OF AttestationPackageInfo
                fields = _children(info)
                if fields:
                    packages.append(fields[0][3].decode("utf-8", "replace"))
        if len(parts) > 1:
            digests = [d[3].hex() for d in _children(parts[1][3])]

    boot_state, locked = "unknown", None
    rot = hardware.get(TAG_ROOT_OF_TRUST)
    if rot:
        _c4, _cc4, _t4, rot_seq, _ = _read(rot, 0)
        fields = _children(rot_seq)
        if len(fields) >= 3:
            locked = fields[1][3] not in (b"", b"\x00")
            boot_state = BOOT_STATES.get(_int(fields[2][3]), "unknown")

    return {"security_level": SECURITY_LEVELS.get(security_level, "software"), "challenge": challenge,
            "packages": tuple(packages), "digests": tuple(digests), "boot_state": boot_state, "locked": locked}


# --- Certificate chain ---

@lru_cache(maxsize=1)
def _root_keys() -> tuple[bytes, ...]:
    path = Path(getattr(settings, "MOBILE_ATTESTATION_ROOTS_FILE", "") or Path(__file__).with_name("attestation_roots.json"))
    roots = json.loads(path.read_text())["roots"]
    return tuple(_spki(x509.load_pem_x509_certificate(pem.encode())) for pem in roots)


def _spki(cert: x509.Certificate) -> bytes:
    return cert.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)


def _signed_by(cert: x509.Certificate, issuer_key) -> bool:
    try:
        if isinstance(issuer_key, rsa.RSAPublicKey):
            issuer_key.verify(cert.signature, cert.tbs_certificate_bytes, padding.PKCS1v15(), cert.signature_hash_algorithm)
        elif isinstance(issuer_key, ec.EllipticCurvePublicKey):
            issuer_key.verify(cert.signature, cert.tbs_certificate_bytes, ec.ECDSA(cert.signature_hash_algorithm))
        else:
            return False
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def verify(chain_b64: list[str], code: str) -> Attested:
    if not chain_b64 or len(chain_b64) > 10:
        raise AttestationError("The phone did not send proof of its security chip.")
    try:
        chain = [x509.load_der_x509_certificate(base64.b64decode(c, validate=True)) for c in chain_b64]
    except Exception as exc:  # noqa: BLE001 - any parse failure means unusable proof
        raise AttestationError("The phone's security proof could not be read.") from exc

    for child, parent in zip(chain, chain[1:]):
        if not _signed_by(child, parent.public_key()):
            raise AttestationError("The phone's security proof is broken.")
    if _spki(chain[-1]) not in _root_keys():
        raise AttestationError("The phone's security proof does not come from Google's hardware roots.")

    # The key description sits in the leaf, or in the first certificate that carries it.
    description = None
    for cert in chain:
        try:
            description = cert.extensions.get_extension_for_oid(KEY_DESCRIPTION_OID).value.value
            leaf = cert
            break
        except x509.ExtensionNotFound:
            continue
    if description is None:
        raise AttestationError("The phone's security proof has no key description.")
    info = _parse_key_description(description)

    if info["challenge"] != activation_challenge(code):
        raise AttestationError("The phone's security proof was made for a different activation.")
    if info["security_level"] == "software":
        raise AttestationError("This phone keeps keys in software only. Use a phone with a secure area.")
    if info["boot_state"] in ("unverified", "failed"):
        raise AttestationError("This phone's system software has been modified. It cannot be activated.")
    package = getattr(settings, "MOBILE_APP_PACKAGE", "et.clinicmrs.clinic_mrs")
    if info["packages"] and package not in info["packages"]:
        raise AttestationError("The key was not made by the Clinic MRS app.")
    allowed = [d.lower().replace(":", "") for d in getattr(settings, "MOBILE_APP_SIGNATURE_SHA256", []) if d]
    if allowed and not set(info["digests"]) & set(allowed):
        raise AttestationError("This copy of the app is not the one from your supplier. Install the official app.")

    return Attested(public_key_der=_spki(leaf), security_level=info["security_level"], boot_state=info["boot_state"],
                    device_locked=info["locked"], package_names=info["packages"], signature_digests=info["digests"])
