"""
Payments by phone: start a prompt on the patient's phone, follow it, and record the payment in billing once
the provider confirms it. Nothing is recorded on a request alone, only on the provider's confirmation.

Rules:
- the clinic's licence must include online payments, and a system administrator must have set up a provider;
- one request at a time per invoice (database constraint), for at most the invoice balance;
- while a request waits, cash cannot be recorded on that invoice (billing checks), so nobody pays twice;
- a confirmation that arrives after the invoice was settled another way is kept as "paid twice: refund needed"
  and the billing approvers are told.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.core.context import ActorContext
from apps.core.exceptions import BusinessValidationError, ConflictError, DomainError
from apps.core.secretbox import seal

from . import providers
from .models import GatewaySettings, OnlinePayment

WAIT_MINUTES = 10  # how long a patient has to answer the prompt before we stop asking the provider often
GIVE_UP_HOURS = 24  # after this, a request with no answer is closed

METHOD_LABELS = {"telebirr": "telebirr", "mpesa": "M-Pesa", "cbebirr": "CBE Birr", "ebirr": "E-birr"}
# OnlinePayment.method -> billing Payment.Method
BILLING_METHOD = {"telebirr": "telebirr", "mpesa": "mpesa", "cbebirr": "cbe_birr", "ebirr": "ebirr"}


class PaymentsNotLicensed(DomainError):
    status_code = 403
    code = "payments_not_licensed"


def licensed() -> bool:
    from apps.devices.services import current_licence
    from apps.devices.licence import LicenceError

    try:
        lic = current_licence()
    except LicenceError:
        return False
    return lic.online_payments and not lic.expired()


def options() -> list[dict]:
    """What the cashier can offer, in order. Empty when not licensed or nothing is set up."""
    if not licensed():
        return []
    cfg = GatewaySettings.get()
    out = []
    if cfg.telebirr_enabled:
        out.append({"provider": "telebirr", "method": "telebirr", "label": "telebirr"})
    if cfg.chapa_enabled:
        for m in cfg.chapa_methods:
            if m in METHOD_LABELS and not (m == "telebirr" and cfg.telebirr_enabled):
                out.append({"provider": "chapa", "method": m, "label": METHOD_LABELS[m]})
    return out


def pending_for(invoice) -> OnlinePayment | None:
    return OnlinePayment.objects.filter(invoice=invoice, status=OnlinePayment.Status.PENDING).first()


def start(ctx: ActorContext, invoice, *, method: str, phone: str, amount=None, provider: str = "",
          started_from: str = "web") -> OnlinePayment:
    from apps.billing.models import Invoice
    from apps.billing.services import money

    if not licensed():
        raise PaymentsNotLicensed("Payments by phone are not part of this clinic's licence.")
    choice = next((o for o in options() if o["method"] == method and (not provider or o["provider"] == provider)), None)
    if choice is None:
        raise BusinessValidationError("This payment method is not set up.", fields={"method": ["Not available."]})
    try:
        mobile = providers.ethiopian_mobile(phone)
    except ValueError as exc:
        raise BusinessValidationError(str(exc), fields={"phone": [str(exc)]}) from exc
    if method == "telebirr" and not mobile.startswith("09"):
        raise BusinessValidationError("telebirr needs a number starting with 09.", fields={"phone": ["Starts with 09."]})
    if method == "mpesa" and not mobile.startswith("07"):
        raise BusinessValidationError("M-Pesa needs a Safaricom number starting with 07.",
                                      fields={"phone": ["Starts with 07."]})

    with transaction.atomic():
        invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
        if invoice.status not in (Invoice.Status.ISSUED, Invoice.Status.PARTIAL):
            raise ConflictError("Payments can only be taken on issued, unpaid invoices.")
        value = money(amount) if amount not in (None, "") else invoice.balance
        if value <= 0 or value > invoice.balance:
            raise BusinessValidationError(f"Enter an amount up to the balance, {invoice.balance} ETB.",
                                          fields={"amount": [f"Maximum {invoice.balance}."]})
        if pending_for(invoice):
            raise ConflictError("A payment request is already waiting on a phone for this invoice.")
        try:
            with transaction.atomic():
                op = OnlinePayment.objects.create(invoice=invoice, provider=choice["provider"], method=method,
                                                  phone=mobile, amount=value, reference=providers.new_reference(),
                                                  started_by=ctx.user, started_from=started_from[:10])
        except IntegrityError as exc:
            raise ConflictError("A payment request is already waiting on a phone for this invoice.") from exc

    gateway = providers.for_settings(op.provider, GatewaySettings.get())
    try:
        op.conversation_id = gateway.start(op)
    except providers.ProviderError as exc:
        OnlinePayment.objects.filter(pk=op.pk).update(status=OnlinePayment.Status.FAILED, message=str(exc)[:255],
                                                      completed_at=timezone.now())
        record_event(ctx, action="payments.start", object_type="invoice", object_id=invoice.pk, outcome="failure",
                     details={"provider": op.provider, "method": method, "amount": str(value), "reason": str(exc)})
        raise ConflictError(str(exc)) from exc
    op.save(update_fields=["conversation_id"])
    record_event(ctx, action="payments.start", object_type="invoice", object_id=invoice.pk,
                 details={"provider": op.provider, "method": method, "amount": str(value), "reference": op.reference,
                          "phone_last_digits": mobile[-3:]})
    return op


def refresh(op: OnlinePayment, *, force: bool = False) -> OnlinePayment:
    """Ask the provider about a waiting request (at most every 4 seconds unless forced)."""
    if op.status != OnlinePayment.Status.PENDING:
        return op
    now = timezone.now()
    if not force and op.last_checked_at and now - op.last_checked_at < timedelta(seconds=4):
        return op
    OnlinePayment.objects.filter(pk=op.pk).update(last_checked_at=now)
    try:
        result = providers.for_settings(op.provider, GatewaySettings.get()).check(op)
    except providers.ProviderError:
        result = providers.CheckResult("pending")
    if result.status == "succeeded":
        settle(op, result.provider_reference)
    elif result.status == "failed":
        _close(op, OnlinePayment.Status.FAILED, result.message, result.provider_reference)
    elif now - op.created_at > timedelta(minutes=WAIT_MINUTES * 2):
        # Stop waiting; sweep() keeps checking for an hour in case the answer comes late.
        _close(op, OnlinePayment.Status.EXPIRED, "No answer from the patient's phone.")
    op.refresh_from_db()
    return op


def _close(op: OnlinePayment, status: str, message: str, provider_reference: str = "") -> None:
    OnlinePayment.objects.filter(pk=op.pk, status=OnlinePayment.Status.PENDING).update(
        status=status, message=message[:255], completed_at=timezone.now(),
        **({"provider_reference": provider_reference[:80]} if provider_reference else {}))


def settle(op: OnlinePayment, provider_reference: str = "") -> OnlinePayment:
    """The provider confirmed the money. Record it in billing, once."""
    from apps.billing.models import Invoice
    from apps.billing.services import record_payment

    with transaction.atomic():
        op = OnlinePayment.objects.select_for_update().get(pk=op.pk)
        if op.status not in (OnlinePayment.Status.PENDING, OnlinePayment.Status.EXPIRED,
                             OnlinePayment.Status.CANCELLED):
            return op  # already settled, or refused for a mismatch: never twice
        op.provider_reference = (provider_reference or op.provider_reference)[:80]
        op.completed_at = timezone.now()
        # Free the invoice for the billing check below; the row stays locked until we finish.
        op.status = OnlinePayment.Status.SUCCEEDED
        op.save(update_fields=["status", "provider_reference", "completed_at"])
        ctx = ActorContext(user=op.started_by, user_agent=f"payment confirmation from {op.provider}")
        label = "Chapa" if op.provider == "chapa" else "telebirr"
        reference = f"{label} {op.provider_reference or op.reference}"[:80]
        try:
            with transaction.atomic():
                invoice = Invoice.objects.select_for_update().get(pk=op.invoice_id)
                if invoice.status not in (Invoice.Status.ISSUED, Invoice.Status.PARTIAL) or op.amount > invoice.balance:
                    raise ConflictError("already settled")
                payment = record_payment(ctx, invoice, amount=op.amount, method=BILLING_METHOD[op.method],
                                         reference=reference)
            op.payment = payment
            op.message = f"Paid. Receipt {payment.receipt_number}."
            op.save(update_fields=["payment", "message"])
        except ConflictError:
            op.status = OnlinePayment.Status.UNAPPLIED
            op.message = "The invoice was already paid another way. Refund this payment to the patient."
            op.save(update_fields=["status", "message"])
            record_event(ctx, action="payments.unapplied", object_type="invoice", object_id=op.invoice_id,
                         details={"reference": op.reference, "amount": str(op.amount), "provider": op.provider})
            from apps.notifications.services import notify_permission_holders

            notify_permission_holders("billing.void.approve", kind="payment.refund_needed",
                                      title=f"Paid twice: refund {op.amount} ETB",
                                      body=f"A {METHOD_LABELS.get(op.method, op.method)} payment ({reference}) for "
                                           f"invoice {op.invoice.number} arrived after the invoice was settled another "
                                           f"way. Refund it to the patient.",
                                      link="/billing")
    return op


def cancel(ctx: ActorContext, op: OnlinePayment) -> OnlinePayment:
    """Stop waiting (the patient will pay another way). If the money still arrives, it is handled by settle()."""
    if op.status != OnlinePayment.Status.PENDING:
        raise ConflictError("This request is no longer waiting.")
    refresh(op, force=True)  # the patient may have just paid
    op.refresh_from_db()
    if op.status == OnlinePayment.Status.PENDING:
        _close(op, OnlinePayment.Status.CANCELLED, "Stopped by staff.")
        record_event(ctx, action="payments.cancel", object_type="invoice", object_id=op.invoice_id,
                     details={"reference": op.reference})
        op.refresh_from_db()
    return op


def sweep() -> int:
    """Run every minute: follow waiting requests, and keep looking for late answers for a day."""
    now = timezone.now()
    n = 0
    candidates = OnlinePayment.objects.filter(
        status__in=[OnlinePayment.Status.PENDING, OnlinePayment.Status.CANCELLED, OnlinePayment.Status.EXPIRED],
        provider="chapa", created_at__gte=now - timedelta(hours=GIVE_UP_HOURS))
    for op in candidates:
        if op.status == OnlinePayment.Status.PENDING:
            refresh(op, force=True)
        elif op.completed_at and now - op.completed_at < timedelta(hours=1):
            # Stopped or timed out recently: a late confirmation is still possible.
            try:
                result = providers.for_settings("chapa", GatewaySettings.get()).check(op)
            except providers.ProviderError:
                continue
            if result.status == "succeeded":
                settle(op, result.provider_reference)
        n += 1
    OnlinePayment.objects.filter(status=OnlinePayment.Status.PENDING, provider="telebirr",
                                 created_at__lt=now - timedelta(minutes=WAIT_MINUTES * 3)).update(
        status=OnlinePayment.Status.EXPIRED, message="No answer from telebirr.", completed_at=now)
    return n


# ---------------------------------------------------------------- callbacks

def chapa_webhook(raw_body: bytes, headers) -> bool:
    import json

    cfg = GatewaySettings.get()
    if not providers.chapa_webhook_valid(cfg, raw_body, headers):
        return False
    try:
        tx_ref = str(json.loads(raw_body).get("tx_ref", ""))[:40]
    except ValueError:
        return False
    op = OnlinePayment.objects.filter(reference=tx_ref).first()
    if op is not None:
        # The webhook is only a nudge: the result is always taken from Chapa's verify call.
        if op.status == OnlinePayment.Status.PENDING:
            refresh(op, force=True)
        elif op.status in (OnlinePayment.Status.CANCELLED, OnlinePayment.Status.EXPIRED):
            result = providers.for_settings("chapa", cfg).check(op)
            if result.status == "succeeded":
                settle(op, result.provider_reference)
    return True


def telebirr_result(token: str, raw_body: bytes) -> bool:
    import hmac

    cfg = GatewaySettings.get()
    if not cfg.telebirr_enabled or not hmac.compare_digest(token, cfg.telebirr_callback_token):
        return False
    v = providers.soap_values(raw_body)
    op = OnlinePayment.objects.filter(reference=v.get("OriginatorConversationID", "")[:40], provider="telebirr").first()
    if op is None:
        return True  # acknowledged, nothing to do
    if v.get("ResultCode") == "0":
        if not v.get("TransactionID"):
            return True
        settle(op, v.get("TransactionID", ""))
    else:
        _close(op, OnlinePayment.Status.FAILED, v.get("ResultDesc") or "telebirr did not complete the payment.",
               v.get("TransactionID", ""))
    return True


# ---------------------------------------------------------------- settings

SECRET_FIELDS = {"chapa_secret_key": "chapa-secret", "chapa_webhook_secret": "chapa-webhook",
                 "telebirr_password": "telebirr-password", "telebirr_security_credential": "telebirr-credential"}
PLAIN_FIELDS = ("chapa_enabled", "chapa_methods", "telebirr_enabled", "telebirr_endpoint", "telebirr_third_party_id",
                "telebirr_identifier", "telebirr_identifier_type", "telebirr_short_code", "telebirr_public_base_url")


def settings_view(cfg: GatewaySettings | None = None) -> dict:
    cfg = cfg or GatewaySettings.get()
    data = {f: getattr(cfg, f) for f in PLAIN_FIELDS}
    data.update({f"{f}_set": bool(getattr(cfg, f)) for f in SECRET_FIELDS})
    data["licensed"] = licensed()
    data["telebirr_result_url"] = (
        f"{cfg.telebirr_public_base_url.rstrip('/')}/api/v1/payments/telebirr/result/{cfg.telebirr_callback_token}/"
        if cfg.telebirr_public_base_url else "")
    data["chapa_webhook_path"] = "/api/v1/payments/chapa/webhook/"
    data["updated_at"] = cfg.updated_at
    return data


def update_settings(ctx: ActorContext, data: dict) -> dict:
    if not licensed():
        raise PaymentsNotLicensed("Payments by phone are not part of this clinic's licence. Contact your supplier.")
    cfg = GatewaySettings.get()
    changed = []
    for f in PLAIN_FIELDS:
        if f in data:
            value = data[f]
            if f == "chapa_methods":
                value = [m for m in (value or []) if m in METHOD_LABELS]
            if f in ("telebirr_endpoint", "telebirr_public_base_url") and value and not str(value).startswith("https://"):
                raise BusinessValidationError("Use an https:// address.", fields={f: ["Must start with https://."]})
            setattr(cfg, f, value)
            changed.append(f)
    for f, purpose in SECRET_FIELDS.items():
        if data.get(f):  # empty = keep the stored one
            setattr(cfg, f, seal(str(data[f]).strip(), purpose))
            changed.append(f)
    if cfg.chapa_enabled and not (cfg.chapa_secret_key and cfg.chapa_methods):
        raise BusinessValidationError("Enter the Chapa secret key and choose at least one method.")
    if cfg.telebirr_enabled:
        try:
            providers.Telebirr(cfg)
        except providers.ProviderError as exc:
            raise BusinessValidationError(str(exc)) from exc
    cfg.updated_by = ctx.user
    cfg.save()
    record_event(ctx, action="payments.settings", details={"changed": sorted(changed)})  # never the secret values
    return settings_view(cfg)


def test_connection(provider: str) -> str:
    """A harmless call with the stored keys: Chapa answers a verify for an unknown reference."""
    cfg = GatewaySettings.get()
    gateway = providers.for_settings(provider, cfg)
    if provider == "chapa":
        status, raw = providers._http("GET", f"{providers.CHAPA_API}/transaction/verify/MRS-CONNECTION-TEST",
                                      headers=gateway._auth())
        if status in (401, 403):
            raise ConflictError("Chapa refused the secret key. Copy it again from the Chapa dashboard.")
        return "Chapa accepted the secret key."
    return ("telebirr settings are complete. telebirr has no test call: send a small real payment to check, and "
            "make sure the result address is reachable from the internet.")


def money_str(d: Decimal) -> str:
    return f"{d:.2f}"
