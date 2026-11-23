"""
Clinic licence for the Android app.

The supplier signs one licence per clinic server with a private key that never leaves the supplier
(vendor-tools/licence_tool.py). The server and the app both check the signature against the supplier's
public key, so a licence cannot be edited, invented, or copied to another clinic's server: it names this
server's installation ID.

Format: "MRSL1.<base64url JSON payload>.<base64url Ed25519 signature of the payload bytes>"

Payload:
  v               1
  licence_id      supplier's reference
  clinic_id       short stable name, e.g. "adama-family-clinic"
  clinic_name     shown on the phone during activation
  installation_id this server's ID (manage.py show_installation_id)
  addresses       {"clinic": "https://192.168.1.10", "remote": "https://..."}; the app only connects here
  mobile_app      true when the clinic has paid for the app
  online_payments true when the clinic has paid for payments by phone (Chapa, telebirr); optional, default false
  max_devices     how many phones may be active at once
  issued_on       YYYY-MM-DD
  expires_on      YYYY-MM-DD, last day the app works
"""
from __future__ import annotations

import base64
import binascii
import datetime
import json
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from django.conf import settings
from django.utils import timezone

PREFIX = "MRSL1"
MAX_LENGTH = 4000


def b64u_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def b64u_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class LicenceError(ValueError):
    """The licence text is not a valid, correctly signed licence for this server."""


@dataclass(frozen=True)
class Licence:
    text: str
    licence_id: str
    clinic_id: str
    clinic_name: str
    installation_id: str
    addresses: dict
    mobile_app: bool
    max_devices: int
    online_payments: bool
    issued_on: datetime.date
    expires_on: datetime.date

    def expired(self, today: datetime.date | None = None) -> bool:
        return (today or timezone.localdate()) > self.expires_on

    def days_left(self, today: datetime.date | None = None) -> int:
        return (self.expires_on - (today or timezone.localdate())).days


def vendor_keys() -> list[Ed25519PublicKey]:
    keys = []
    for raw in getattr(settings, "MRS_VENDOR_PUBLIC_KEYS", []):
        try:
            data = base64.b64decode(raw.strip(), validate=True)
            keys.append(Ed25519PublicKey.from_public_bytes(data))
        except (binascii.Error, ValueError):
            continue
    return keys


def parse(text: str, *, installation_id: str | None = None) -> Licence:
    """Check the signature and contents. Raises LicenceError with a sentence an administrator can act on."""
    text = (text or "").strip()
    if not text:
        raise LicenceError("No licence is installed.")
    if len(text) > MAX_LENGTH or text.count(".") != 2:
        raise LicenceError("This is not a Clinic MRS licence.")
    prefix, body, sig = text.split(".")
    if prefix != PREFIX:
        raise LicenceError("This is not a Clinic MRS licence.")
    try:
        payload_bytes, signature = b64u_decode(body), b64u_decode(sig)
    except (binascii.Error, ValueError) as exc:
        raise LicenceError("The licence text is damaged. Copy it again in full.") from exc
    keys = vendor_keys()
    if not keys:
        raise LicenceError("This server has no supplier key to check licences. Contact your supplier.")
    for key in keys:
        try:
            key.verify(signature, payload_bytes)
            break
        except InvalidSignature:
            continue
    else:
        raise LicenceError("The licence signature is not valid. It was changed or not issued by your supplier.")
    try:
        p = json.loads(payload_bytes)
        licence = Licence(
            text=text,
            licence_id=str(p["licence_id"]),
            clinic_id=str(p["clinic_id"]),
            clinic_name=str(p["clinic_name"]),
            installation_id=str(p["installation_id"]),
            addresses={k: str(v) for k, v in dict(p.get("addresses") or {}).items() if k in ("clinic", "remote") and v},
            mobile_app=bool(p.get("mobile_app")),
            max_devices=int(p.get("max_devices", 0)),
            online_payments=bool(p.get("online_payments")),
            issued_on=datetime.date.fromisoformat(p["issued_on"]),
            expires_on=datetime.date.fromisoformat(p["expires_on"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise LicenceError("The licence is signed but incomplete. Contact your supplier.") from exc
    if p.get("v") != 1:
        raise LicenceError("This licence is for a newer version of Clinic MRS. Update the server.")
    if installation_id is not None and licence.installation_id != str(installation_id):
        raise LicenceError("This licence was issued for a different server. Send this server's installation ID "
                           "to your supplier.")
    return licence


def sign(payload: dict, private_key) -> str:
    """Used by the supplier's tool and by tests. `private_key` is an Ed25519PrivateKey."""
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return f"{PREFIX}.{b64u_encode(body)}.{b64u_encode(private_key.sign(body))}"
