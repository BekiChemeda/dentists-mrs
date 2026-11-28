"""
Licences, phone activation and device-bound app sign-in. Synthetic accounts and keys only.

Phones are simulated with a real P-256 key and an attestation certificate chain under a test root that
replaces Google's roots for these tests, so the chain, challenge and key-description checks run for real.
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import json
import time

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import NameOID
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.devices import attestation, licence
from apps.devices.models import ActivationCode, Installation, MobileDevice
from conftest import PASSWORD

PACKAGE = "et.dentalmrs.dental_mrs"
APP_DIGEST = hashlib.sha256(b"supplier signing certificate").hexdigest()


# --- DER helpers for building key descriptions ---

def _len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def tlv(tag: bytes, content: bytes) -> bytes:
    return tag + _len(len(content)) + content


def integer(n: int) -> bytes:
    return tlv(b"\x02", n.to_bytes(max(1, (n.bit_length() + 8) // 8), "big", signed=True))


def enum(n: int) -> bytes:
    return tlv(b"\x0a", bytes([n]))


def octets(b: bytes) -> bytes:
    return tlv(b"\x04", b)


def seq(*parts: bytes) -> bytes:
    return tlv(b"\x30", b"".join(parts))


def set_of(*parts: bytes) -> bytes:
    return tlv(b"\x31", b"".join(parts))


def explicit(tag_number: int, content: bytes) -> bytes:
    # context-specific, constructed, high tag number form
    digits = []
    n = tag_number
    while True:
        digits.insert(0, n & 0x7F)
        n >>= 7
        if not n:
            break
    tag = bytes([0xBF] + [d | 0x80 for d in digits[:-1]] + [digits[-1]])
    return tlv(tag, content)


def key_description(challenge: bytes, *, level=1, boot=0, package=PACKAGE, digest=APP_DIGEST) -> bytes:
    app_id = seq(set_of(seq(octets(package.encode()), integer(1))), set_of(octets(bytes.fromhex(digest))))
    software = seq(explicit(709, octets(app_id)))
    hardware = seq(explicit(704, seq(octets(b"\x11" * 32), tlv(b"\x01", b"\xff"), enum(boot), octets(b"\x22" * 32))))
    return seq(integer(200), enum(level), integer(200), enum(level), octets(challenge), octets(b""), software, hardware)


def _cert(subject: str, public_key, issuer: str, issuer_key, extensions=()):
    now = datetime.datetime.now(datetime.timezone.utc)
    b = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject)]))
         .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, issuer)])).public_key(public_key)
         .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
         .not_valid_after(now + datetime.timedelta(days=3650)))
    for ext in extensions:
        b = b.add_extension(ext, critical=False)
    return b.sign(issuer_key, hashes.SHA256())


class Phone:
    """A simulated phone: hardware key plus its attestation chain."""

    def __init__(self, root_key, code: str, **kd):
        self.key = ec.generate_private_key(ec.SECP256R1())
        inter_key = ec.generate_private_key(ec.SECP256R1())
        challenge = kd.pop("challenge", None) or attestation.activation_challenge(code)
        ext = x509.UnrecognizedExtension(attestation.KEY_DESCRIPTION_OID, key_description(challenge, **kd))
        leaf = _cert("Android Keystore Key", self.key.public_key(), "Test intermediate", inter_key, [ext])
        inter = _cert("Test intermediate", inter_key.public_key(), "Test root", root_key)
        root = _cert("Test root", root_key.public_key(), "Test root", root_key)
        self.chain = [base64.b64encode(c.public_bytes(serialization.Encoding.DER)).decode() for c in (leaf, inter, root)]

    def sign(self, message: str) -> str:
        return base64.b64encode(self.key.sign(message.encode(), ec.ECDSA(hashes.SHA256()))).decode()


# --- Fixtures ---

@pytest.fixture
def vendor(settings, tmp_path, db):
    key = Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    settings.MRS_VENDOR_PUBLIC_KEYS = [base64.b64encode(pub).decode()]
    settings.MOBILE_ACTIVATION_REQUIRED = True
    settings.MOBILE_REQUIRE_HARDWARE_KEY = True
    settings.MOBILE_APP_SIGNATURE_SHA256 = []
    root_key = ec.generate_private_key(ec.SECP384R1())
    root = _cert("Test root", root_key.public_key(), "Test root", root_key)
    roots = tmp_path / "roots.json"
    roots.write_text(json.dumps({"roots": [root.public_bytes(serialization.Encoding.PEM).decode()]}))
    settings.MOBILE_ATTESTATION_ROOTS_FILE = str(roots)
    attestation._root_keys.cache_clear()
    cache.clear()
    yield {"key": key, "root_key": root_key}
    attestation._root_keys.cache_clear()
    cache.clear()


def issue(vendor, *, installation_id=None, mobile_app=True, max_devices=5, days=365, **extra) -> str:
    payload = {"v": 1, "licence_id": "L-TEST-1", "clinic_id": "test-clinic", "clinic_name": "Test Clinic",
               "installation_id": installation_id or str(Installation.get().installation_id),
               "addresses": {"clinic": "https://192.0.2.10"}, "mobile_app": mobile_app, "max_devices": max_devices,
               "issued_on": timezone.localdate().isoformat(),
               "expires_on": (timezone.localdate() + datetime.timedelta(days=days)).isoformat(), **extra}
    return licence.sign(payload, vendor["key"])


@pytest.fixture
def licensed(vendor, db):
    inst = Installation.get()
    inst.licence_text = issue(vendor)
    inst.save()
    cache.clear()
    return vendor


@pytest.fixture
def admin(make_user, login):
    return login(make_user("clinic_admin", username="phone.admin"), client=APIClient())


def new_code(admin, **body) -> dict:
    r = admin.post("/api/v1/devices/activation-codes/", body, format="json")
    assert r.status_code == 201, r.content
    return r.json()


def activate(code: str, phone: Phone):
    return APIClient().post("/api/v1/mobile/activate/", {"code": code, "attestation": phone.chain, "label": "Ward phone",
                                                         "model": "Tecno Spark", "os_version": "14"}, format="json")


def app_login(device_id: str, phone: Phone, username: str, password: str = PASSWORD):
    nonce = APIClient().post("/api/v1/auth/app/challenge/", {"device_id": device_id}, format="json").json()["nonce"]
    return APIClient().post("/api/v1/auth/app/login/", {
        "username": username, "password": password, "device": "Tecno", "device_id": device_id, "nonce": nonce,
        "signature": phone.sign(f"mrs-login:{nonce}")}, format="json")


def bearer(token):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return c


# --- Licence ---

def test_licence_signature_installation_and_contents_are_checked(vendor, db):
    inst = str(Installation.get().installation_id)
    lic = licence.parse(issue(vendor), installation_id=inst)
    assert lic.clinic_name == "Test Clinic" and lic.mobile_app and lic.max_devices == 5

    prefix, body, sig = issue(vendor).split(".")
    changed = json.loads(licence.b64u_decode(body))
    changed["max_devices"] = 500
    forged = f"{prefix}.{licence.b64u_encode(json.dumps(changed).encode())}.{sig}"
    with pytest.raises(licence.LicenceError, match="signature"):
        licence.parse(forged, installation_id=inst)
    with pytest.raises(licence.LicenceError, match="different server"):
        licence.parse(issue(vendor, installation_id="00000000-0000-0000-0000-000000000000"), installation_id=inst)
    other_supplier = licence.sign({"v": 1}, Ed25519PrivateKey.generate())
    with pytest.raises(licence.LicenceError, match="signature"):
        licence.parse(other_supplier, installation_id=inst)
    with pytest.raises(licence.LicenceError):
        licence.parse("not a licence")


def test_licence_is_installed_by_the_system_administrator_only(vendor, make_user, login, sysadmin, api):
    text = issue(vendor)
    clinic_admin = login(make_user("clinic_admin"), client=APIClient())
    assert clinic_admin.post("/api/v1/devices/licence/", {"licence": text}, format="json").status_code == 403
    sys_admin = login(sysadmin, client=api)
    bad = sys_admin.post("/api/v1/devices/licence/", {"licence": text[:-4] + "AAAA"}, format="json")
    assert bad.status_code == 400
    r = sys_admin.post("/api/v1/devices/licence/", {"licence": text}, format="json")
    assert r.status_code == 200 and r.json()["valid"] and r.json()["max_devices"] == 5
    assert clinic_admin.get("/api/v1/devices/licence/").json()["clinic_name"] == "Test Clinic"


def test_without_a_licence_including_the_app_no_phone_can_be_activated(vendor, admin):
    assert admin.post("/api/v1/devices/activation-codes/", {}, format="json").status_code == 403
    inst = Installation.get()
    inst.licence_text = issue(vendor, mobile_app=False)
    inst.save()
    cache.clear()
    r = admin.post("/api/v1/devices/activation-codes/", {}, format="json")
    assert r.status_code == 403 and r.json()["error"]["code"] == "app_not_licensed"


# --- Activation and sign-in ---

def test_activate_sign_in_and_switch_off(licensed, admin, make_user):
    make_user("nurse", username="ward.nurse")
    code = new_code(admin, label="Ward phone")
    qr = json.loads(licence.b64u_decode(code["qr"].removeprefix("MRSACT1.")))
    assert qr["code"] == code["code"] and qr["licence"].startswith("MRSL1.") and "<svg" in code["qr_svg"]
    assert ActivationCode.objects.get().code_hash != code["code"]  # only a hash is kept

    phone = Phone(licensed["root_key"], code["code"])
    r = activate(code["code"], phone)
    assert r.status_code == 201, r.content
    device_id = r.json()["device_id"]
    device = MobileDevice.objects.get(pk=device_id)
    assert device.key_storage == "tee" and device.boot_state == "verified" and device.label == "Ward phone"

    assert activate(code["code"], Phone(licensed["root_key"], code["code"])).status_code == 400  # used once only

    signed_in = app_login(device_id, phone, "ward.nurse")
    assert signed_in.status_code == 200, signed_in.content
    app = bearer(signed_in.json()["token"])
    assert app.get("/api/v1/auth/me/").json()["username"] == "ward.nurse"

    listed = admin.get("/api/v1/devices/").json()["results"]
    assert listed[0]["last_user"]["username"] == "ward.nurse"
    assert admin.post(f"/api/v1/devices/{device_id}/revoke/", {}, format="json").status_code == 400  # reason needed
    assert admin.post(f"/api/v1/devices/{device_id}/revoke/", {"reason": "Phone lost"}, format="json").status_code == 200
    assert app.get("/api/v1/auth/me/").status_code == 401
    assert app_login(device_id, phone, "ward.nurse").status_code == 401


def test_sign_in_needs_the_phone_key_and_a_fresh_challenge(licensed, admin, make_user):
    make_user("doctor", username="dr.phone")
    code = new_code(admin)["code"]
    phone = Phone(licensed["root_key"], code)
    device_id = activate(code, phone).json()["device_id"]

    plain = APIClient().post("/api/v1/auth/app/login/", {"username": "dr.phone", "password": PASSWORD}, format="json")
    assert plain.status_code == 401 and plain.json()["error"]["code"] == "device_not_activated"

    copied_app = Phone(licensed["root_key"], code)  # same device ID, different key: a cloned install
    assert app_login(device_id, copied_app, "dr.phone").status_code == 401

    nonce = APIClient().post("/api/v1/auth/app/challenge/", {"device_id": device_id}, format="json").json()["nonce"]
    body = {"username": "dr.phone", "password": PASSWORD, "device_id": device_id, "nonce": nonce,
            "signature": phone.sign(f"mrs-login:{nonce}")}
    assert APIClient().post("/api/v1/auth/app/login/", body, format="json").status_code == 200
    assert APIClient().post("/api/v1/auth/app/login/", body, format="json").status_code == 401  # nonce used


def test_password_is_not_tried_from_a_phone_that_is_not_activated(licensed, make_user):
    from apps.accounts.models import User

    make_user("doctor", username="dr.locked")
    for _ in range(8):
        APIClient().post("/api/v1/auth/app/login/", {"username": "dr.locked", "password": "wrong"}, format="json")
    assert User.objects.get(username="dr.locked").failed_login_count == 0


@pytest.mark.parametrize("problem,kwargs,message", [
    ("another activation", {"challenge": b"\x00" * 32}, "different activation"),
    ("software key", {"level": 0}, "software"),
    ("modified system", {"boot": 2}, "modified"),
    ("other app", {"package": "com.example.copy"}, "Dental MRS app"),
])
def test_weak_or_foreign_phones_are_refused(licensed, admin, problem, kwargs, message):
    code = new_code(admin)["code"]
    r = activate(code, Phone(licensed["root_key"], code, **kwargs))
    assert r.status_code == 400 and message in r.json()["error"]["message"], problem
    assert not MobileDevice.objects.exists()


def test_proof_under_an_unknown_root_is_refused(licensed, admin):
    code = new_code(admin)["code"]
    r = activate(code, Phone(ec.generate_private_key(ec.SECP384R1()), code))
    assert r.status_code == 400 and "Google" in r.json()["error"]["message"]


def test_re_signed_app_is_refused_when_the_supplier_certificate_is_pinned(licensed, admin, settings):
    settings.MOBILE_APP_SIGNATURE_SHA256 = ["AA:" * 31 + "AA"]
    code = new_code(admin)["code"]
    assert "official app" in activate(code, Phone(licensed["root_key"], code)).json()["error"]["message"]
    settings.MOBILE_APP_SIGNATURE_SHA256 = [APP_DIGEST.upper()]
    code = new_code(admin)["code"]
    assert activate(code, Phone(licensed["root_key"], code)).status_code == 201


def test_phone_limit_from_the_licence(vendor, admin):
    inst = Installation.get()
    inst.licence_text = issue(vendor, max_devices=1)
    inst.save()
    cache.clear()
    code = new_code(admin)["code"]
    assert activate(code, Phone(vendor["root_key"], code)).status_code == 201
    full = admin.post("/api/v1/devices/activation-codes/", {}, format="json")
    assert full.status_code == 409 and full.json()["error"]["max_devices"] == 1


def test_expired_code_is_refused(licensed, admin):
    code = new_code(admin)["code"]
    ActivationCode.objects.update(expires_at=timezone.now() - datetime.timedelta(seconds=1))
    assert activate(code, Phone(licensed["root_key"], code)).status_code == 400


def test_phone_for_one_person_cannot_be_used_by_another(licensed, admin, make_user):
    owner = make_user("nurse", username="owner.nurse")
    make_user("nurse", username="other.nurse")
    code = new_code(admin, for_user=str(owner.pk))["code"]
    phone = Phone(licensed["root_key"], code)
    device_id = activate(code, phone).json()["device_id"]
    assert app_login(device_id, phone, "other.nurse").status_code == 403
    assert app_login(device_id, phone, "owner.nurse").status_code == 200


def test_licence_ending_stops_signed_in_phones(licensed, admin, make_user):
    make_user("nurse", username="late.nurse")
    code = new_code(admin)["code"]
    phone = Phone(licensed["root_key"], code)
    device_id = activate(code, phone).json()["device_id"]
    app = bearer(app_login(device_id, phone, "late.nurse").json()["token"])
    assert app.get("/api/v1/auth/me/").status_code == 200
    inst = Installation.get()
    inst.licence_text = issue(licensed, days=-1)
    inst.save()
    cache.clear()
    assert app.get("/api/v1/auth/me/").status_code == 401
    assert app_login(device_id, phone, "late.nurse").status_code == 403


def test_two_step_sign_in_from_an_activated_phone(licensed, admin, make_user):
    from apps.accounts import mfa

    user = make_user("doctor", username="dr.mfa.phone")
    secret = mfa.new_secret()
    user.mfa_secret_encrypted = mfa.encrypt_secret(secret)
    user.mfa_enabled_at = timezone.now()
    user.save()
    code = new_code(admin)["code"]
    phone = Phone(licensed["root_key"], code)
    device_id = activate(code, phone).json()["device_id"]
    first = app_login(device_id, phone, "dr.mfa.phone").json()
    assert first["mfa_required"]
    done = APIClient().post("/api/v1/auth/app/login/mfa/", {"mfa_token": first["mfa_token"],
                                                             "code": mfa.hotp(secret, int(time.time()) // 30)},
                            format="json")
    assert done.status_code == 200
    from apps.accounts.models import UserSession

    assert str(UserSession.objects.get(user=user).device_id) == device_id


def test_public_licence_endpoint_lets_the_app_check_the_server(licensed):
    r = APIClient().get("/api/v1/mobile/licence/").json()
    assert r["licence"].startswith("MRSL1.") and r["installation_id"] == str(Installation.get().installation_id)
