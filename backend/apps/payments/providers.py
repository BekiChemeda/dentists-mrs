"""
Payment providers. Each one can send a payment prompt to a patient's phone, and say what became of it.
Billing only talks to these through `Provider`, so another gateway can be added without changing it.

The API container has no internet (docker-compose.yml). Requests leave through the `egress` relay, which
only connects to the providers' hosts; TLS is end to end and certificates are checked here.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from decimal import Decimal
from xml.etree import ElementTree
from xml.sax.saxutils import escape

from django.conf import settings
from django.utils import timezone

from apps.core.secretbox import unseal

CHAPA_API = "https://api.chapa.co/v1"
TIMEOUT = 25


class ProviderError(Exception):
    """The provider refused or could not be reached. The message is safe to show to staff."""


@dataclass
class CheckResult:
    status: str  # "pending", "succeeded", "failed"
    provider_reference: str = ""
    message: str = ""


# ---------------------------------------------------------------- transport

def _http(method: str, url: str, *, body: bytes | None = None, headers: dict | None = None) -> tuple[int, bytes]:
    """One HTTPS request through the egress relay. Replaced in tests."""
    handlers = [urllib.request.HTTPSHandler(context=ssl.create_default_context())]
    proxy = getattr(settings, "PAYMENTS_EGRESS_PROXY", "")
    handlers.append(urllib.request.ProxyHandler({"https": proxy} if proxy else {}))
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        # https only, to the providers' fixed hosts
        with opener.open(req, timeout=TIMEOUT) as res:  # nosec B310
            return res.status, res.read(1_000_000)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(1_000_000)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProviderError("The payment service could not be reached. Check the server's internet connection, "
                            "or take the payment in cash.") from exc


def new_reference() -> str:
    return "MRS" + timezone.localtime().strftime("%y%m%d") + secrets.token_hex(10).upper()


# ---------------------------------------------------------------- phone numbers

def ethiopian_mobile(raw: str) -> str:
    """'0911 23 45 67', '+251911234567' or '911234567' -> '0911234567'. Raises ValueError."""
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("251") and len(digits) == 12:
        digits = "0" + digits[3:]
    elif len(digits) == 9 and digits[0] in "79":
        digits = "0" + digits
    if not re.fullmatch(r"0[79]\d{8}", digits):
        raise ValueError("Enter an Ethiopian mobile number, for example 0911 23 45 67.")
    return digits


# ---------------------------------------------------------------- the interface

class Provider:
    code = ""

    def start(self, payment) -> str:
        """Send the prompt. Returns the provider's conversation reference (may be empty)."""
        raise NotImplementedError

    def check(self, payment) -> CheckResult:
        """Ask the provider what happened. Providers that only call back return pending."""
        return CheckResult("pending")


# ---------------------------------------------------------------- Chapa

def _multipart(fields: dict[str, str]) -> tuple[bytes, str]:
    boundary = "mrs" + secrets.token_hex(12)
    parts = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n')
    parts.append(f"--{boundary}--\r\n")
    return "".join(parts).encode(), f"multipart/form-data; boundary={boundary}"


def _json(raw: bytes) -> dict:
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def _message(data: dict, fallback: str) -> str:
    msg = data.get("message")
    if isinstance(msg, dict):  # Chapa sometimes returns field errors as a dict
        msg = "; ".join(f"{k}: {', '.join(v) if isinstance(v, list) else v}" for k, v in msg.items())
    return (str(msg) if msg else fallback)[:250]


class Chapa(Provider):
    """Chapa direct charge (USSD prompt) for telebirr, M-Pesa, CBE Birr and E-birr."""

    code = "chapa"

    def __init__(self, cfg):
        self.secret = unseal(cfg.chapa_secret_key, "chapa-secret") or ""
        if not self.secret:
            raise ProviderError("Chapa is not set up: the secret key is missing.")

    def _auth(self) -> dict:
        return {"Authorization": f"Bearer {self.secret}"}

    def start(self, payment) -> str:
        body, ctype = _multipart({"amount": f"{payment.amount:.2f}", "currency": "ETB", "tx_ref": payment.reference,
                                  "mobile": payment.phone})
        status, raw = _http("POST", f"{CHAPA_API}/charges?type={payment.method}", body=body,
                            headers={**self._auth(), "Content-Type": ctype})
        data = _json(raw)
        if status >= 400 or str(data.get("status", "")).lower() != "success":
            raise ProviderError(f"Chapa refused the request: {_message(data, f'error {status}')}")
        meta = (data.get("data") or {}).get("meta") or {}
        return str(meta.get("ref_id") or meta.get("reference") or "")[:80]

    def check(self, payment) -> CheckResult:
        status, raw = _http("GET", f"{CHAPA_API}/transaction/verify/{payment.reference}", headers=self._auth())
        data = _json(raw)
        tx = data.get("data") if isinstance(data.get("data"), dict) else {}
        if status == 404 or not tx:
            return CheckResult("pending", message=_message(data, "Not confirmed yet."))
        state = str(tx.get("status", "")).lower()
        ref = str(tx.get("reference") or tx.get("ref_id") or "")[:80]
        if state == "success":
            # Count it only if it is exactly what we asked for.
            try:
                amount = Decimal(str(tx.get("amount")))
            except Exception:  # noqa: BLE001
                amount = Decimal("-1")
            if (str(tx.get("tx_ref", payment.reference)) != payment.reference or str(tx.get("currency", "ETB")) != "ETB"
                    or amount != payment.amount):
                return CheckResult("failed", ref, "Chapa reported a different amount or reference. Not recorded; "
                                                  "check the Chapa dashboard.")
            return CheckResult("succeeded", ref, "Paid")
        if state in ("failed", "failure", "cancelled", "canceled", "declined", "reversed"):
            return CheckResult("failed", ref, _message(data, "The payment was not completed."))
        return CheckResult("pending", ref)


def chapa_webhook_valid(cfg, raw_body: bytes, headers) -> bool:
    secret = unseal(cfg.chapa_webhook_secret, "chapa-webhook") or ""
    if not secret:
        return False
    body_sig = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    key_sig = hmac.new(secret.encode(), secret.encode(), hashlib.sha256).hexdigest()
    given_body = headers.get("x-chapa-signature", "")
    given_key = headers.get("chapa-signature", "")
    return ((given_body and hmac.compare_digest(given_body, body_sig))
            or (given_key and hmac.compare_digest(given_key, key_sig)))


# ---------------------------------------------------------------- telebirr (merchant, USSD push)

API_NS = "http://cps.huawei.com/cpsinterface/api_requestmgr"
REQ_NS = "http://cps.huawei.com/cpsinterface/request"


class Telebirr(Provider):
    """telebirr "Buy Goods for Customer" USSD push (Ethio Telecom merchant SOAP API). The result arrives later
    at the clinic's public callback address; there is no status query."""

    code = "telebirr"

    def __init__(self, cfg):
        self.cfg = cfg
        self.password = unseal(cfg.telebirr_password, "telebirr-password") or ""
        self.credential = unseal(cfg.telebirr_security_credential, "telebirr-credential") or ""
        missing = [n for n, v in (("endpoint", cfg.telebirr_endpoint), ("third-party ID", cfg.telebirr_third_party_id),
                                  ("password", self.password), ("identifier", cfg.telebirr_identifier),
                                  ("security credential", self.credential), ("short code", cfg.telebirr_short_code),
                                  ("public address", cfg.telebirr_public_base_url)) if not v]
        if missing:
            raise ProviderError(f"telebirr is not set up: {', '.join(missing)} missing.")

    def result_url(self) -> str:
        base = self.cfg.telebirr_public_base_url.rstrip("/")
        return f"{base}/api/v1/payments/telebirr/result/{self.cfg.telebirr_callback_token}/"

    def envelope(self, payment) -> str:
        c = self.cfg
        x = escape
        msisdn = "251" + payment.phone[1:]
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:api="{API_NS}" '
            f'xmlns:req="{REQ_NS}"><soapenv:Body><api:Request>'
            "<req:Header><req:Version>1.0</req:Version><req:CommandID>InitTrans_BuyGoodsForCustomer</req:CommandID>"
            f"<req:OriginatorConversationID>{x(payment.reference)}</req:OriginatorConversationID>"
            f"<req:Caller><req:CallerType>2</req:CallerType><req:ThirdPartyID>{x(c.telebirr_third_party_id)}</req:ThirdPartyID>"
            f"<req:Password>{x(self.password)}</req:Password><req:ResultURL>{x(self.result_url())}</req:ResultURL></req:Caller>"
            f"<req:KeyOwner>1</req:KeyOwner><req:Timestamp>{timezone.localtime().strftime('%Y%m%d%H%M%S')}</req:Timestamp>"
            "</req:Header><req:Body><req:Identity>"
            f"<req:Initiator><req:IdentifierType>{x(c.telebirr_identifier_type)}</req:IdentifierType>"
            f"<req:Identifier>{x(c.telebirr_identifier)}</req:Identifier>"
            f"<req:SecurityCredential>{x(self.credential)}</req:SecurityCredential>"
            f"<req:ShortCode>{x(c.telebirr_short_code)}</req:ShortCode></req:Initiator>"
            f"<req:PrimaryParty><req:IdentifierType>1</req:IdentifierType><req:Identifier>{x(msisdn)}</req:Identifier>"
            "</req:PrimaryParty>"
            f"<req:ReceiverParty><req:IdentifierType>4</req:IdentifierType><req:Identifier>{x(c.telebirr_short_code)}"
            "</req:Identifier></req:ReceiverParty></req:Identity>"
            f"<req:TransactionRequest><req:Parameters><req:Amount>{payment.amount:.2f}</req:Amount>"
            "<req:Currency>ETB</req:Currency></req:Parameters></req:TransactionRequest>"
            "</req:Body></api:Request></soapenv:Body></soapenv:Envelope>"
        )

    def start(self, payment) -> str:
        if not payment.phone.startswith("09"):
            raise ProviderError("telebirr needs an Ethio Telecom number starting with 09.")
        status, raw = _http("POST", self.cfg.telebirr_endpoint, body=self.envelope(payment).encode(),
                            headers={"Content-Type": "text/xml; charset=utf-8",
                                     "SOAPAction": "InitTrans_BuyGoodsForCustomer"})
        values = soap_values(raw)
        if status >= 400 or values.get("ResponseCode") != "0":
            raise ProviderError(f"telebirr refused the request: {values.get('ResponseDesc') or f'error {status}'}"[:250])
        return values.get("ConversationID", "")[:80]


def soap_values(raw: bytes) -> dict[str, str]:
    """Leaf element texts by local name. Documents with a DOCTYPE are refused (entity expansion attacks)."""
    if b"<!DOCTYPE" in raw[:2000].upper() or b"<!ENTITY" in raw.upper():
        return {}
    try:
        root = ElementTree.fromstring(raw)  # nosec B314
    except ElementTree.ParseError:
        return {}
    out = {}
    for el in root.iter():
        if len(el) == 0 and el.text is not None:
            out.setdefault(el.tag.rsplit("}", 1)[-1], el.text.strip())
    return out


def for_settings(provider: str, cfg) -> Provider:
    if provider == "chapa":
        return Chapa(cfg)
    if provider == "telebirr":
        return Telebirr(cfg)
    raise ProviderError("Unknown payment provider.")
