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


def blocking_problem(req: ApprovalRequest) -> str | None:
    """Why approving this request would have no effect (the thing it is for has moved on), or None."""
    if req.kind == ApprovalRequest.Kind.DISCOUNT and req.object_type == "invoice":
        from apps.billing.models import Invoice
        from apps.billing.services import discount_problem

        invoice = Invoice.objects.filter(pk=req.object_id).first()
        if invoice is None:
            return "The invoice for this discount no longer exists."
        return discount_problem(invoice, req.amount or 0)
    return None


def other_approvers_exist(req: ApprovalRequest, user) -> bool:
    """Another active account (not the requester) holds the permission to decide this request."""
    from apps.accounts.models import User

    permission = ApprovalRequest.PERMISSION_FOR_KIND[req.kind]
    others = (User.objects.filter(is_active=True, roles__permissions__code=permission)
              .exclude(pk=user.pk).distinct())
    return any(permission in u.permission_codes for u in others)


def may_self_approve(req: ApprovalRequest, user) -> bool:
    """One-person clinic: the requester may decide their own request when the clinic says one person runs it
    and nobody else could. In a clinic with an approver, the second person is always needed."""
    from apps.core.models import ClinicSettings

    return (req.requested_by_id == user.pk and ClinicSettings.get().solo_approvals
            and user.has_permissions([ApprovalRequest.PERMISSION_FOR_KIND[req.kind]])
            and not other_approvers_exist(req, user))


@transaction.atomic
def decide(ctx: ActorContext, req: ApprovalRequest, *, approve: bool, note: str = "") -> ApprovalRequest:
    req = ApprovalRequest.objects.select_for_update().get(pk=req.pk)
    if req.status != ApprovalRequest.Status.PENDING:
        raise ConflictError("This request has already been decided.")
    own = req.requested_by_id == ctx.user.pk
    if own and not may_self_approve(req, ctx.user):
        raise ConflictError("You cannot approve your own request.")
    if own and not note.strip():
        raise BusinessValidationError("Write why you are deciding your own request; it is kept in the audit log.",
                                      fields={"note": ["Required."]})
    if not ctx.user.has_permissions([ApprovalRequest.PERMISSION_FOR_KIND[req.kind]]):
        from rest_framework.exceptions import PermissionDenied

        raise PermissionDenied()
    if not approve and not note.strip():
        raise BusinessValidationError("Give a reason for rejecting.", fields={"note": ["Required."]})
    if approve and (problem := blocking_problem(req)):
        raise ConflictError(problem)
    req.status = ApprovalRequest.Status.APPROVED if approve else ApprovalRequest.Status.REJECTED
    req.decided_by = ctx.user
    req.decided_at = timezone.now()
    req.decision_note = note.strip()
    req.self_approved = own
    req.save()
    record_event(ctx, action="approval.approve" if approve else "approval.reject", object_type="approval",
                 object_id=req.pk, details={"kind": req.kind, "note": req.decision_note,
                                            **({"self_approved": True} if own else {})})
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
    # An approver may also close a request that can no longer take effect (e.g. a discount on a paid invoice),
    # so it does not sit on the invoice forever.
    stale_close = (req.requested_by_id != ctx.user.pk and blocking_problem(req) is not None
                   and ctx.user.has_permissions([ApprovalRequest.PERMISSION_FOR_KIND[req.kind]]))
    if req.requested_by_id != ctx.user.pk and not stale_close:
        raise ConflictError("Only the requester can withdraw this request.")
    if req.status not in (ApprovalRequest.Status.PENDING, ApprovalRequest.Status.APPROVED):
        raise ConflictError("This request can no longer be withdrawn.")
    req.status = ApprovalRequest.Status.CANCELLED
    req.save(update_fields=["status", "updated_at"])
    record_event(ctx, action="approval.cancel", object_type="approval", object_id=req.pk,
                 details={"kind": req.kind, **({"closed_as_stale": True} if stale_close else {})})
    return req
