"""
Two-step sign-in: time-based one-time codes (RFC 6238, the scheme used by Google Authenticator,
Microsoft Authenticator, Aegis and similar apps) plus single-use recovery codes.

- The authenticator secret is stored encrypted (Fernet, key derived from DJANGO_SECRET_KEY or
  MFA_ENCRYPTION_KEY). Changing that key disables everyone's authenticator: they re-enrol.
- Recovery codes are stored only as password hashes and can each be used once.
- A code is accepted for the current 30-second step and one step either side (clock drift), and the
  same step can never be used twice, so an observed code cannot be replayed.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password

STEP_SECONDS = 30
DIGITS = 6
DRIFT_STEPS = 1
RECOVERY_CODE_COUNT = 10
ISSUER = "Clinic MRS"


# ---------------------------------------------------------------------------
# TOTP (RFC 4226 / 6238)
# ---------------------------------------------------------------------------
def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret_b32: str) -> bytes:
    padded = secret_b32.upper() + "=" * (-len(secret_b32) % 8)
    return base64.b32decode(padded)


def hotp(secret_b32: str, counter: int, digits: int = DIGITS) -> str:
    mac = hmac.new(_key(secret_b32), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    value = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10 ** digits)).zfill(digits)


def current_step(now: float | None = None) -> int:
    return int((now if now is not None else time.time()) // STEP_SECONDS)


def verify_totp(secret_b32: str, code: str, *, last_step: int | None, now: float | None = None) -> int | None:
    """Return the matched step (to store as last used) or None. Constant-time comparison."""
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(code) != DIGITS:
        return None
    step = current_step(now)
    matched = None
    for candidate in range(step - DRIFT_STEPS, step + DRIFT_STEPS + 1):
        if hmac.compare_digest(hotp(secret_b32, candidate), code):
            matched = candidate
    if matched is None or (last_step is not None and matched <= last_step):
        return None
    return matched


def provisioning_uri(secret_b32: str, username: str, facility: str) -> str:
    label = quote(f"{ISSUER} ({facility}):{username}")
    return (f"otpauth://totp/{label}?secret={secret_b32}&issuer={quote(ISSUER)}"
            f"&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}")


def qr_svg(uri: str) -> str:
    import segno

    return segno.make(uri, error="m").svg_inline(scale=5, border=2, dark="#252c43")


# ---------------------------------------------------------------------------
# Secret encryption at rest
# ---------------------------------------------------------------------------
def _fernet():
    from cryptography.fernet import Fernet

    material = (getattr(settings, "MFA_ENCRYPTION_KEY", "") or settings.SECRET_KEY).encode()
    key = hashlib.sha256(b"mrs-mfa-v1:" + material).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(secret_b32: str) -> str:
    return _fernet().encrypt(secret_b32.encode()).decode()


def decrypt_secret(token: str) -> str | None:
    from cryptography.fernet import InvalidToken

    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None


# ---------------------------------------------------------------------------
# Recovery codes
# ---------------------------------------------------------------------------
_RC_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def new_recovery_codes() -> list[str]:
    def one():
        raw = "".join(secrets.choice(_RC_ALPHABET) for _ in range(10))
        return f"{raw[:5]}-{raw[5:]}"
    return [one() for _ in range(RECOVERY_CODE_COUNT)]


def normalise_recovery(code: str) -> str:
    raw = "".join(ch for ch in (code or "").lower() if ch.isalnum())
    return f"{raw[:5]}-{raw[5:]}" if len(raw) == 10 else ""


def hash_recovery(code: str) -> str:
    return make_password(code)


def matches_recovery(code: str, hashed: str) -> bool:
    return check_password(code, hashed)
