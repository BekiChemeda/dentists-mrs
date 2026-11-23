#!/usr/bin/env python3
"""
Clinic MRS supplier tool: make the signing key and issue clinic licences for the phone app.

Keep the private key on your own computer (and a backup on an encrypted USB stick). Never put it on a
clinic server, in the code repository, or in a message. Anyone with it can issue licences.

  1. Once:   python licence_tool.py keygen --out ~/mrs-supplier.key
             -> prints the PUBLIC key. Put it in each server's .env as MRS_VENDOR_PUBLIC_KEYS=<key>
                and in the app build (GitHub secret VENDOR_PUBLIC_KEY).
  2. Per clinic, after installing the server:
             ssh into it and run:  docker compose exec backend python manage.py show_installation_id
  3. Issue:  python licence_tool.py sign --key ~/mrs-supplier.key --clinic-id adama-family \
               --clinic-name "Adama Family Clinic" --installation-id <id> \
               --clinic-address https://192.168.1.10 --remote-address https://mrs.adamafamily.et \
               --phones 10 --until 2027-11-30 [--online-payments] --out adama-family.licence
  4. Install on the server:  web page Administration > Phones > Licence, or
             docker compose exec -T backend python manage.py install_licence /dev/stdin < adama-family.licence
  To renew or add phones, issue a new licence with the same installation ID and install it.

Requires: pip install cryptography
"""
from __future__ import annotations

import argparse
import base64
import datetime
import json
import os
import secrets
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def keygen(args):
    out = Path(args.out).expanduser()
    if out.exists():
        sys.exit(f"{out} already exists. Refusing to overwrite a signing key.")
    password = os.environ.get("MRS_KEY_PASSWORD") or input("Password to protect the key (remember it): ")
    if len(password) < 12:
        sys.exit("Use a password of at least 12 characters.")
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.BestAvailableEncryption(password.encode()))
    out.write_bytes(pem)
    out.chmod(0o600)
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    print(f"Private key written to {out}. Back it up somewhere safe and offline.")
    print("Public key (safe to share; goes in servers and the app build):")
    print(base64.b64encode(public).decode())


def _load(path: str) -> Ed25519PrivateKey:
    password = os.environ.get("MRS_KEY_PASSWORD") or input("Key password: ")
    return serialization.load_pem_private_key(Path(path).expanduser().read_bytes(), password.encode())


def sign(args):
    until = datetime.date.fromisoformat(args.until)
    if until <= datetime.date.today():
        sys.exit("--until must be in the future.")
    addresses = {k: v for k, v in (("clinic", args.clinic_address), ("remote", args.remote_address)) if v}
    for v in addresses.values():
        if not v.startswith("https://"):
            sys.exit(f"Addresses must start with https:// ({v})")
    payload = {
        "v": 1,
        "licence_id": args.licence_id or f"L-{datetime.date.today():%Y%m%d}-{secrets.token_hex(3)}",
        "clinic_id": args.clinic_id,
        "clinic_name": args.clinic_name,
        "installation_id": args.installation_id,
        "addresses": addresses,
        "mobile_app": not args.no_app,
        "max_devices": args.phones,
        "online_payments": args.online_payments,
        "issued_on": datetime.date.today().isoformat(),
        "expires_on": until.isoformat(),
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    text = f"MRSL1.{b64u(body)}.{b64u(_load(args.key).sign(body))}"
    Path(args.out).write_text(text + "\n")
    print(json.dumps(payload, indent=2))
    print(f"Licence written to {args.out}")


def show(args):
    text = Path(args.file).read_text().strip()
    body = text.split(".")[1]
    print(json.dumps(json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))), indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(required=True)
    k = sub.add_parser("keygen", help="create the supplier signing key (once)")
    k.add_argument("--out", required=True)
    k.set_defaults(fn=keygen)
    s = sub.add_parser("sign", help="issue a clinic licence")
    s.add_argument("--key", required=True)
    s.add_argument("--clinic-id", required=True)
    s.add_argument("--clinic-name", required=True)
    s.add_argument("--installation-id", required=True)
    s.add_argument("--clinic-address", required=True, help="address on the clinic Wi-Fi, https://...")
    s.add_argument("--remote-address", default="", help="address from outside, if the clinic set one up")
    s.add_argument("--phones", type=int, required=True)
    s.add_argument("--until", required=True, help="last day the app works, YYYY-MM-DD")
    s.add_argument("--licence-id", default="")
    s.add_argument("--no-app", action="store_true", help="licence without the phone app")
    s.add_argument("--online-payments", action="store_true",
                   help="include payments by phone (Chapa, telebirr): only when the clinic pays for it")
    s.add_argument("--out", required=True)
    s.set_defaults(fn=sign)
    v = sub.add_parser("show", help="print what a licence file contains")
    v.add_argument("file")
    v.set_defaults(fn=show)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
