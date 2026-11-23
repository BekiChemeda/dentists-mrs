"""
Payments by phone. Chapa and telebirr are replaced by fakes at the HTTP layer, so the real request building,
parsing, settling and guards run. Synthetic data only; no real money or keys.
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.billing import services as billing
from apps.billing.models import Invoice, Payment
from apps.core.context import ActorContext
from apps.devices import licence
from apps.devices.models import Installation
from apps.payments import providers, services
from apps.payments.models import GatewaySettings, OnlinePayment

pytestmark = pytest.mark.django_db


class FakeNet:
    """Records requests and answers like Chapa / telebirr would."""

    def __init__(self):
        self.calls = []
        self.verify = {"status": "success", "data": {"status": "pending"}}
        self.verify_code = 200
        self.charge = {"status": "success", "message": "Charge initiated",
                       "data": {"auth_type": "ussd", "meta": {"ref_id": "CHref123", "status": "success"}}}
        self.charge_code = 200
        self.soap_code = "0"

    def __call__(self, method, url, *, body=None, headers=None):
        self.calls.append(SimpleNamespace(method=method, url=url, body=body or b"", headers=headers or {}))
        if "/charges" in url:
            return self.charge_code, json.dumps(self.charge).encode()
        if "/transaction/verify/" in url:
            return self.verify_code, json.dumps(self.verify).encode()
        if "telebirr" in url:
            return 200, (
                '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"><soapenv:Body>'
                '<api:Response xmlns:api="http://cps.huawei.com/cpsinterface/api_resultmgr" '
                'xmlns:res="http://cps.huawei.com/cpsinterface/response"><res:Header><res:Version>1.0</res:Version>'
                '<res:OriginatorConversationID>x</res:OriginatorConversationID><res:ConversationID>AG_123</res:ConversationID>'
                f'</res:Header><res:Body><res:ResponseCode>{self.soap_code}</res:ResponseCode>'
                '<res:ResponseDesc>Accept the service request successfully.</res:ResponseDesc></res:Body></api:Response>'
                '</soapenv:Body></soapenv:Envelope>').encode()
        raise AssertionError(url)


@pytest.fixture
def net(monkeypatch):
    fake = FakeNet()
    monkeypatch.setattr(providers, "_http", fake)
    return fake


def _licence(settings, *, online_payments=True):
    key = Ed25519PrivateKey.generate()
    settings.MRS_VENDOR_PUBLIC_KEYS = [base64.b64encode(key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()]
    inst = Installation.get()
    inst.licence_text = licence.sign({
        "v": 1, "licence_id": "L-PAY", "clinic_id": "pay-clinic", "clinic_name": "Pay Clinic",
        "installation_id": str(inst.installation_id), "addresses": {"clinic": "https://192.0.2.5"},
        "mobile_app": True, "max_devices": 5, "online_payments": online_payments,
        "issued_on": timezone.localdate().isoformat(),
        "expires_on": (timezone.localdate() + datetime.timedelta(days=365)).isoformat()}, key)
    inst.save()
    cache.clear()


@pytest.fixture
def licensed(settings, db):
    _licence(settings)


@pytest.fixture
def chapa(licensed):
    cfg = GatewaySettings.get()
    from apps.core.secretbox import seal

    cfg.chapa_enabled = True
    cfg.chapa_secret_key = seal("CHASECK_TEST-synthetic", "chapa-secret")
    cfg.chapa_webhook_secret = seal("webhook-synthetic-secret", "chapa-webhook")
    cfg.chapa_methods = ["telebirr", "mpesa", "cbebirr"]
    cfg.save()
    return cfg


@pytest.fixture
def telebirr(licensed):
    from apps.core.secretbox import seal

    cfg = GatewaySettings.get()
    cfg.telebirr_enabled = True
    cfg.telebirr_endpoint = "https://telebirr.example.test/payment/services/APIRequestMgrService"
    cfg.telebirr_third_party_id = "MRS-TP"
    cfg.telebirr_password = seal("tp-pass-synthetic", "telebirr-password")
    cfg.telebirr_identifier = "MRSOP"
    cfg.telebirr_security_credential = seal("cred-synthetic", "telebirr-credential")
    cfg.telebirr_short_code = "200880"
    cfg.telebirr_public_base_url = "https://mrs.example.test"
    cfg.save()
    return cfg


@pytest.fixture
def invoice(staff):
    from apps.billing.models import ServicePrice
    from apps.patients.models import Patient

    rc = staff.receptionist
    p = rc.post("/api/v1/patients/", {"first_name": "Pay", "last_name": "Byphone", "sex": "female", "age_years": 30,
                                      "phone": "0911223344", "confirm_not_duplicate": True}, format="json").json()
    ctx = ActorContext(user=staff.users.cashier)
    inv = billing.create_invoice(ctx, patient=Patient.objects.get(pk=p["id"]))
    billing.add_service_line(ctx, inv, description="Consultation", unit_price=Decimal("350.00"))
    return billing.issue_invoice(ctx, inv)


def pay(staff, inv, **body):
    return staff.cashier.post(f"/api/v1/billing/invoices/{inv.pk}/pay-by-phone/",
                              {"method": "telebirr", "phone": "0911 22 33 44", **body}, format="json")


def chapa_success(net, op, amount=None, ref="APchapa77"):
    net.verify = {"status": "success", "message": "Payment details", "data": {
        "status": "success", "amount": str(amount or op.amount), "currency": "ETB", "tx_ref": op.reference,
        "reference": ref}}


# ---------------------------------------------------------------- availability

def test_nothing_is_offered_without_the_licence_or_set_up(settings, staff, net):
    _licence(settings, online_payments=False)
    assert staff.cashier.get("/api/v1/payments/options/").json() == {"options": [], "licensed": False}
    _licence(settings, online_payments=True)
    assert staff.cashier.get("/api/v1/payments/options/").json()["options"] == []  # licensed but not set up


def test_options_list_the_set_up_methods(chapa, staff):
    labels = [o["label"] for o in staff.cashier.get("/api/v1/payments/options/").json()["options"]]
    assert labels == ["telebirr", "M-Pesa", "CBE Birr"]


def test_settings_are_for_the_system_administrator_and_keys_never_come_back(licensed, sysadmin, login, api, staff):
    admin = login(sysadmin, client=api)
    assert staff.clinic_admin.get("/api/v1/settings/payments/").status_code == 403
    r = admin.patch("/api/v1/settings/payments/", {"chapa_enabled": True, "chapa_secret_key": "CHASECK_TEST-abc",
                                                   "chapa_methods": ["telebirr", "bogus"]}, format="json")
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["chapa_secret_key_set"] is True and "CHASECK" not in json.dumps(body)
    assert body["chapa_methods"] == ["telebirr"]
    assert "CHASECK" not in GatewaySettings.get().chapa_secret_key  # sealed at rest
    from apps.audit.models import AuditEvent

    assert "CHASECK" not in json.dumps(list(AuditEvent.objects.values_list("details", flat=True)))


def test_settings_need_the_licence(settings, sysadmin, login, api):
    _licence(settings, online_payments=False)
    r = login(sysadmin, client=api).patch("/api/v1/settings/payments/", {"chapa_enabled": True}, format="json")
    assert r.status_code == 403 and r.json()["error"]["code"] == "payments_not_licensed"


# ---------------------------------------------------------------- Chapa

def test_chapa_prompt_then_confirmation_records_the_payment_once(chapa, staff, invoice, net):
    r = pay(staff, invoice)
    assert r.status_code == 201, r.content
    op = OnlinePayment.objects.get(pk=r.json()["id"])
    call = net.calls[0]
    assert call.url == "https://api.chapa.co/v1/charges?type=telebirr"
    assert call.headers["Authorization"] == "Bearer CHASECK_TEST-synthetic"
    assert b'name="mobile"\r\n\r\n0911223344' in call.body and b'name="amount"\r\n\r\n350.00' in call.body
    assert op.status == "pending" and r.json()["phone"] == "0911••••44"

    # Cash cannot be taken while the phone request waits, and no second request either.
    cash = staff.cashier.post(f"/api/v1/billing/invoices/{invoice.pk}/payments/", {"amount": "350", "method": "cash"},
                              format="json")
    assert cash.status_code == 409
    assert pay(staff, invoice).status_code == 409

    assert staff.cashier.get(f"/api/v1/payments/online/{op.pk}/").json()["status"] == "pending"
    chapa_success(net, op)
    OnlinePayment.objects.filter(pk=op.pk).update(last_checked_at=None)
    done = staff.cashier.get(f"/api/v1/payments/online/{op.pk}/").json()
    assert done["status"] == "succeeded" and done["receipt_number"].startswith("RCT-")
    invoice.refresh_from_db()
    assert invoice.status == Invoice.Status.PAID
    payment = Payment.objects.get(invoice=invoice)
    assert payment.method == "telebirr" and payment.reference == "Chapa APchapa77"
    assert payment.received_by == staff.users.cashier

    services.refresh(OnlinePayment.objects.get(pk=op.pk), force=True)
    services.settle(OnlinePayment.objects.get(pk=op.pk), "APchapa77")
    assert Payment.objects.filter(invoice=invoice).count() == 1


def test_a_different_amount_from_chapa_is_not_recorded(chapa, staff, invoice, net):
    op = OnlinePayment.objects.get(pk=pay(staff, invoice).json()["id"])
    chapa_success(net, op, amount="1.00")
    op = services.refresh(op, force=True)
    assert op.status == "failed" and "different amount" in op.message
    assert not Payment.objects.filter(invoice=invoice).exists()


def test_failed_and_refused_requests(chapa, staff, invoice, net):
    net.charge_code, net.charge = 400, {"status": "failed", "message": "Invalid mobile number"}
    r = pay(staff, invoice)
    assert r.status_code == 409 and "Invalid mobile number" in r.json()["error"]["message"]
    assert OnlinePayment.objects.get().status == "failed"

    net.charge_code, net.charge = 200, FakeNet().charge
    op = OnlinePayment.objects.get(pk=pay(staff, invoice).json()["id"])
    net.verify = {"status": "success", "data": {"status": "failed", "tx_ref": op.reference}, "message": "Insufficient"}
    assert services.refresh(op, force=True).status == "failed"


def test_phone_numbers_and_amounts_are_checked(chapa, staff, invoice, net):
    assert pay(staff, invoice, phone="12345").status_code == 400
    assert pay(staff, invoice, method="mpesa", phone="0911223344").status_code == 400  # M-Pesa is 07
    assert pay(staff, invoice, amount="351.00").status_code == 400
    assert pay(staff, invoice, method="ebirr").status_code == 400  # not set up
    r = pay(staff, invoice, method="mpesa", phone="+251 711 223 344", amount="100.00")
    assert r.status_code == 201 and net.calls[-1].url.endswith("type=mpesa")
    assert b"0711223344" in net.calls[-1].body


def test_stopped_request_paid_late_is_still_recorded(chapa, staff, invoice, net):
    op = OnlinePayment.objects.get(pk=pay(staff, invoice).json()["id"])
    r = staff.cashier.post(f"/api/v1/payments/online/{op.pk}/cancel/")
    assert r.json()["status"] == "cancelled"
    chapa_success(net, op)
    services.sweep()
    assert OnlinePayment.objects.get(pk=op.pk).status == "succeeded"
    invoice.refresh_from_db()
    assert invoice.status == Invoice.Status.PAID


def test_paid_twice_is_flagged_for_refund(chapa, staff, invoice, net):
    from apps.notifications.models import Notification

    op = OnlinePayment.objects.get(pk=pay(staff, invoice).json()["id"])
    staff.cashier.post(f"/api/v1/payments/online/{op.pk}/cancel/")
    cash = staff.cashier.post(f"/api/v1/billing/invoices/{invoice.pk}/payments/", {"amount": "350", "method": "cash"},
                              format="json")
    assert cash.status_code in (200, 201), cash.content
    chapa_success(net, op)
    services.sweep()
    op.refresh_from_db()
    assert op.status == "unapplied" and "Refund" in op.message
    assert Payment.objects.filter(invoice=invoice).count() == 1
    assert Notification.objects.filter(kind="payment.refund_needed").exists()


def test_chapa_webhook_needs_the_signature_and_is_only_a_nudge(chapa, staff, invoice, net):
    op = OnlinePayment.objects.get(pk=pay(staff, invoice).json()["id"])
    body = json.dumps({"tx_ref": op.reference, "status": "success"}).encode()
    anon = APIClient()
    assert anon.post("/api/v1/payments/chapa/webhook/", body, content_type="application/json").status_code == 401
    forged = anon.post("/api/v1/payments/chapa/webhook/", body, content_type="application/json",
                       HTTP_X_CHAPA_SIGNATURE="00" * 32)
    assert forged.status_code == 401
    sig = hmac.new(b"webhook-synthetic-secret", body, hashlib.sha256).hexdigest()
    # Signed but Chapa's verify still says pending: nothing is recorded on the webhook's word.
    assert anon.post("/api/v1/payments/chapa/webhook/", body, content_type="application/json",
                     HTTP_X_CHAPA_SIGNATURE=sig).status_code == 200
    assert OnlinePayment.objects.get(pk=op.pk).status == "pending"
    chapa_success(net, op)
    anon.post("/api/v1/payments/chapa/webhook/", body, content_type="application/json", HTTP_X_CHAPA_SIGNATURE=sig)
    assert OnlinePayment.objects.get(pk=op.pk).status == "succeeded"


# ---------------------------------------------------------------- telebirr direct

def test_telebirr_push_and_result(telebirr, staff, invoice, net):
    op = OnlinePayment.objects.get(pk=pay(staff, invoice).json()["id"])
    assert op.provider == "telebirr" and op.conversation_id == "AG_123"
    soap = net.calls[0].body.decode()
    assert "<req:Identifier>251911223344</req:Identifier>" in soap
    assert f"<req:OriginatorConversationID>{op.reference}</req:OriginatorConversationID>" in soap
    assert "<req:Amount>350.00</req:Amount>" in soap and "tp-pass-synthetic" in soap
    assert f"/api/v1/payments/telebirr/result/{telebirr.telebirr_callback_token}/" in soap
    assert net.calls[0].headers["SOAPAction"] == "InitTrans_BuyGoodsForCustomer"

    def result(code, token=None, ref=op.reference):
        xml = ('<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"><soapenv:Body>'
               '<api:Result xmlns:api="http://cps.huawei.com/cpsinterface/api_resultmgr" '
               'xmlns:res="http://cps.huawei.com/cpsinterface/result"><res:Header>'
               f'<res:OriginatorConversationID>{ref}</res:OriginatorConversationID></res:Header><res:Body>'
               f'<res:ResultType>0</res:ResultType><res:ResultCode>{code}</res:ResultCode>'
               '<res:ResultDesc>Process service request successfully.</res:ResultDesc>'
               '<res:TransactionID>TBX9988</res:TransactionID></res:Body></api:Result></soapenv:Body></soapenv:Envelope>')
        return APIClient().post(f"/api/v1/payments/telebirr/result/{token or telebirr.telebirr_callback_token}/",
                                xml, content_type="text/xml")

    assert result("0", token="wrong-token").status_code == 404
    assert OnlinePayment.objects.get(pk=op.pk).status == "pending"
    assert result("0").status_code == 200
    op.refresh_from_db()
    assert op.status == "succeeded" and op.provider_reference == "TBX9988"
    assert Payment.objects.get(invoice=invoice).reference == "telebirr TBX9988"
    result("0")  # repeated result: still one payment
    assert Payment.objects.filter(invoice=invoice).count() == 1


def test_telebirr_refusal_and_failure(telebirr, staff, invoice, net):
    net.soap_code = "2001"
    assert pay(staff, invoice).status_code == 409
    net.soap_code = "0"
    op = OnlinePayment.objects.get(pk=pay(staff, invoice).json()["id"])
    services.telebirr_result(telebirr.telebirr_callback_token, (
        f'<x><OriginatorConversationID>{op.reference}</OriginatorConversationID><ResultCode>2001</ResultCode>'
        '<ResultDesc>Insufficient balance</ResultDesc></x>').encode())
    op.refresh_from_db()
    assert op.status == "failed" and op.message == "Insufficient balance"


def test_hostile_xml_is_ignored(telebirr):
    bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>'
    assert providers.soap_values(bomb) == {}


def test_phone_number_forms():
    assert providers.ethiopian_mobile("+251 911 22 33 44") == "0911223344"
    assert providers.ethiopian_mobile("911223344") == "0911223344"
    assert providers.ethiopian_mobile("0711223344") == "0711223344"
    with pytest.raises(ValueError):
        providers.ethiopian_mobile("0811223344")
