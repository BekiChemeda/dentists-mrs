"""
Encrypts small secrets kept in the database (e.g. the email server password), so a copy of the
database or a backup alone does not reveal them. Key derived from DJANGO_SECRET_KEY (or
SECRETBOX_KEY) and the purpose, so each kind of secret uses a different key.
If the key changes, stored secrets cannot be read and must be entered again.
"""

import base64
import hashlib

from django.conf import settings


def _fernet(purpose: str):
    from cryptography.fernet import Fernet

    material = (getattr(settings, "SECRETBOX_KEY", "") or settings.SECRET_KEY).encode()
    key = hashlib.sha256(f"mrs-secretbox-v1:{purpose}:".encode() + material).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def seal(plain: str, purpose: str) -> str:
    return _fernet(purpose).encrypt(plain.encode()).decode() if plain else ""


def unseal(token: str, purpose: str) -> str | None:
    from cryptography.fernet import InvalidToken

    if not token:
        return None
    try:
        return _fernet(purpose).decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None
