from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.core.context import ActorContext
from apps.core.exceptions import BusinessValidationError, ConflictError
from apps.notifications.services import notify_permission_holders, notify_user

from .models import ApprovalRequest


@transaction.atomic
def request_approval(ctx: ActorContext, *, kind: str, object_type: str, object_id, summary: str, reason: str,
                     amount: Decimal | None = None, quantity: Decimal | None = None) -> ApprovalRequest:
    if not reason.strip():
        raise BusinessValidationError("Explain why this is needed.", fields={"reason": ["Required."]})
    if ApprovalRequest.objects.filter(kind=kind, object_type=object_type, object_id=str(object_id),
                                      status=ApprovalRequest.Status.PENDING).exists():
        raise ConflictError("A request for this is already waiting for approval.")
    req = ApprovalRequest.objects.create(kind=kind, object_type=object_type, object_id=str(object_id),
                                         summary=summary[:255], reason=reason.strip(), amount=amount,
                                         quantity=quantity, requested_by=ctx.user)
    record_event(ctx, action="approval.request", object_type="approval", object_id=req.pk,
                 details={"kind": kind, "object": f"{object_type}:{object_id}", "reason": req.reason,
                          **({"amount": str(amount)} if amount is not None else {}),
                          **({"quantity": str(quantity)} if quantity is not None else {})})
    notify_permission_holders(ApprovalRequest.PERMISSION_FOR_KIND[kind], kind="approval",
                              title=f"Approval needed: {req.get_kind_display()}", body=req.summary,
                              link="/approvals", exclude_user=ctx.user)
    return req


@transaction.atomic
def decide(ctx: ActorContext, req: ApprovalRequest, *, approve: bool, note: str = "") -> ApprovalRequest:
    req = ApprovalRequest.objects.select_for_update().get(pk=req.pk)
    if req.status != ApprovalRequest.Status.PENDING:
        raise ConflictError("This request has already been decided.")
    if req.requested_by_id == ctx.user.pk:
        raise ConflictError("You cannot approve your own request.")
    if not ctx.user.has_permissions([ApprovalRequest.PERMISSION_FOR_KIND[req.kind]]):
        from rest_framework.exceptions import PermissionDenied

        raise PermissionDenied()
    if not approve and not note.strip():
        raise BusinessValidationError("Give a reason for rejecting.", fields={"note": ["Required."]})
    req.status = ApprovalRequest.Status.APPROVED if approve else ApprovalRequest.Status.REJECTED
    req.decided_by = ctx.user
    req.decided_at = timezone.now()
    req.decision_note = note.strip()
    req.save()
    record_event(ctx, action="approval.approve" if approve else "approval.reject", object_type="approval",
                 object_id=req.pk, details={"kind": req.kind, "note": req.decision_note})
    notify_user(req.requested_by, kind="approval",
                title=f"{req.get_kind_display()} {'approved' if approve else 'rejected'}",
                body=req.summary + (f" — {req.decision_note}" if req.decision_note else ""), link="/approvals")
    return req


def consume(ctx: ActorContext, approval_id, *, kind: str, object_type: str, object_id) -> ApprovalRequest:
    """Mark an approval as used. Must run inside the caller's transaction."""
    req = ApprovalRequest.objects.select_for_update().filter(pk=approval_id).first()
    if (req is None or req.kind != kind or req.object_type != object_type or req.object_id != str(object_id)):
        raise ConflictError("That approval does not match this action.")
    if req.status != ApprovalRequest.Status.APPROVED:
        raise ConflictError("That approval is not available (pending, rejected or already used).")
    req.status = ApprovalRequest.Status.USED
    req.used_at = timezone.now()
    req.save(update_fields=["status", "used_at", "updated_at"])
    record_event(ctx, action="approval.use", object_type="approval", object_id=req.pk, details={"kind": kind})
    return req


@transaction.atomic
def cancel(ctx: ActorContext, req: ApprovalRequest) -> ApprovalRequest:
    req = ApprovalRequest.objects.select_for_update().get(pk=req.pk)
    if req.requested_by_id != ctx.user.pk:
        raise ConflictError("Only the requester can withdraw this request.")
    if req.status not in (ApprovalRequest.Status.PENDING, ApprovalRequest.Status.APPROVED):
        raise ConflictError("This request can no longer be withdrawn.")
    req.status = ApprovalRequest.Status.CANCELLED
    req.save(update_fields=["status", "updated_at"])
    record_event(ctx, action="approval.cancel", object_type="approval", object_id=req.pk)
    return req
