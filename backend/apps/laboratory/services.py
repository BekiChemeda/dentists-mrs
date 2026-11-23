"""Lab requests, specimens, results, verification and doctor notification."""

from __future__ import annotations

import datetime
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.clinical.models import Encounter
from apps.core.context import ActorContext
from apps.core.exceptions import BusinessValidationError, ConflictError
from apps.core.numbering import next_number
from apps.notifications.services import notify_permission_holders, notify_user
from apps.scheduling.services import visit_event

from .models import LabOrder, LabOrderItem, LabReferenceRange, LabResultAmendment, LabTest


def range_for(test: LabTest, *, sex: str, birth_date, on) -> dict:
    """The reference and critical limits that apply to this patient: most specific matching range, else the test's."""
    age_days = (on - birth_date).days if birth_date else None
    best, best_key = None, None
    if age_days is not None:
        for r in test.ranges.all():
            if r.sex and r.sex != sex:
                continue
            if age_days < r.age_min_days or (r.age_max_days is not None and age_days >= r.age_max_days):
                continue
            span = (r.age_max_days or 10**9) - r.age_min_days
            key = (0 if r.sex else 1, span)  # sex-specific first, then the narrowest age band
            if best_key is None or key < best_key:
                best, best_key = r, key
    src = best or test
    return {"ref_low": src.ref_low, "ref_high": src.ref_high, "ref_text": src.ref_text or test.ref_text,
            "critical_low": src.critical_low if best is None or src.critical_low is not None else test.critical_low,
            "critical_high": src.critical_high if best is None or src.critical_high is not None else test.critical_high}


@transaction.atomic
def order_tests(ctx: ActorContext, encounter: Encounter, *, test_ids: list, priority: str = "routine",
                clinical_notes: str = "") -> LabOrder:
    from apps.clinical.services import orderable_encounter

    encounter = orderable_encounter(ctx, encounter)
    return _create_order(ctx, patient=encounter.patient, visit=encounter.visit, encounter=encounter,
                         test_ids=test_ids, priority=priority, clinical_notes=clinical_notes)


def _create_order(ctx: ActorContext, *, patient, visit, test_ids: list, priority: str, clinical_notes: str = "",
                  encounter: Encounter | None = None, external_requester: str = "",
                  external_facility: str = "") -> LabOrder:
    test_ids = list(dict.fromkeys(test_ids))
    tests = list(LabTest.objects.filter(pk__in=test_ids, is_active=True).prefetch_related("ranges"))
    if not tests or len(tests) != len(test_ids):
        raise BusinessValidationError("Choose valid laboratory tests.", fields={"test_ids": ["Unknown or inactive test."]})
    today = timezone.localdate()
    accession = f"L{today:%y%m%d}-{next_number('lab_accession', today.isoformat()):04d}"
    order = LabOrder.objects.create(accession_number=accession, patient=patient, visit=visit,
                                    encounter=encounter, ordered_by=ctx.user, priority=priority,
                                    clinical_notes=clinical_notes.strip(), external_requester=external_requester.strip(),
                                    external_facility=external_facility.strip())
    for t in tests:
        limits = range_for(t, sex=patient.sex, birth_date=patient.birth_date, on=today)
        LabOrderItem.objects.create(order=order, test=t, price=t.price, unit=t.unit, specimen_type=t.specimen_type,
                                    **limits)
    record_event(ctx, action="lab.order", object_type="lab_order", object_id=order.pk,
                 details={"accession": accession, "tests": [t.code for t in tests], "patient": str(order.patient_id)})
    visit_event(ctx, order.visit_id, "lab.order",
                f"Laboratory requested ({accession}, {priority}): {', '.join(t.name for t in tests)}")
    return order


@transaction.atomic
def register_lab_only_visit(ctx: ActorContext, *, patient, test_ids: list, requested_by: str,
                            requesting_facility: str = "", priority: str = "routine", clinical_notes: str = ""):
    """A patient who came only for tests another clinician requested (paper request in hand).

    The visit skips triage and the doctor: it starts in the 'after consultation' stage, where the
    laboratory, the cashier and visit completion already work."""
    from apps.core.modules import is_enabled
    from apps.scheduling.models import Visit

    if not is_enabled("laboratory"):
        raise ConflictError("The Laboratory module is switched off for this clinic.")
    from apps.scheduling.services import _create_visit

    if not requested_by.strip():
        raise BusinessValidationError("Enter the clinician who requested the tests, as written on the request.",
                                      fields={"requested_by": ["Required."]})
    visit = _create_visit(ctx, patient=patient, kind=Visit.Kind.LAB_ONLY,
                          priority=Visit.Priority.URGENT if priority == "urgent" else Visit.Priority.ROUTINE)
    Visit.objects.filter(pk=visit.pk).update(status=Visit.Status.AFTER_CONSULTATION)
    who = requested_by.strip() + (f", {requesting_facility.strip()}" if requesting_facility.strip() else "")
    visit_event(ctx, visit, "lab_only", f"Laboratory-only visit; request from {who}")
    order = _create_order(ctx, patient=patient, visit=visit, test_ids=test_ids, priority=priority,
                          clinical_notes=clinical_notes, external_requester=requested_by,
                          external_facility=requesting_facility)
    visit.refresh_from_db()
    return visit, order


def _refresh_order_status(order: LabOrder) -> None:
    statuses = set(order.items.values_list("status", flat=True))
    if statuses <= {LabOrderItem.Status.CANCELLED}:
        new = LabOrder.Status.CANCELLED
    elif statuses <= {LabOrderItem.Status.VERIFIED, LabOrderItem.Status.CANCELLED}:
        new = LabOrder.Status.COMPLETED
    elif statuses == {LabOrderItem.Status.ORDERED}:
        new = LabOrder.Status.ORDERED
    else:
        new = LabOrder.Status.IN_PROGRESS
    if new != order.status:
        order.status = new
        order.save(update_fields=["status", "updated_at"])
        if new == LabOrder.Status.COMPLETED:
            notify_user(order.ordered_by, kind="lab_result", title=f"Lab results ready: {order.patient.full_name}",
                        body=f"Order {order.accession_number} is complete.", link=f"/patients/{order.patient_id}?tab=labs")


def _lock_item(item: LabOrderItem) -> LabOrderItem:
    return LabOrderItem.objects.select_for_update(of=("self",)).select_related("order", "test", "order__patient").get(pk=item.pk)


@transaction.atomic
def collect_specimen(ctx: ActorContext, item: LabOrderItem, label: str = "", *, specimen_type: str = "",
                     collected_at=None) -> LabOrderItem:
    item = _lock_item(item)
    if item.status != LabOrderItem.Status.ORDERED:
        raise ConflictError("The specimen for this test has already been collected or the test was cancelled.")
    now = timezone.now()
    if collected_at is not None and (collected_at > now + datetime.timedelta(minutes=2)
                                     or collected_at < item.order.created_at - datetime.timedelta(minutes=5)):
        raise BusinessValidationError("The collection time must be between the request and now.",
                                      fields={"collected_at": ["Check the time."]})
    index = list(item.order.items.order_by("test__name", "pk").values_list("pk", flat=True)).index(item.pk) + 1
    item.specimen_label = label.strip() or f"{item.order.accession_number}-{index}"
    item.specimen_type = specimen_type.strip() or item.specimen_type or item.test.specimen_type
    item.status = LabOrderItem.Status.COLLECTED
    item.collected_at = collected_at or now
    item.collected_by = ctx.user
    item.save()
    _refresh_order_status(item.order)
    record_event(ctx, action="lab.collect", object_type="lab_item", object_id=item.pk,
                 details={"specimen": item.specimen_label})
    visit_event(ctx, item.order.visit_id, "lab.collect", f"Specimen collected for {item.test.name} ({item.specimen_label})")
    return item


def _parse_result(test: LabTest, value: str) -> tuple[Decimal | None, str]:
    value = (value or "").strip()
    if not value:
        raise BusinessValidationError("Enter a result.", fields={"value": ["Required."]})
    if test.result_type == LabTest.ResultType.NUMERIC:
        try:
            return Decimal(value.replace(",", ".")), ""
        except InvalidOperation as exc:
            raise BusinessValidationError("Enter a number.", fields={"value": ["Must be a number."]}) from exc
    if test.result_type in (LabTest.ResultType.CHOICE, LabTest.ResultType.QUALITATIVE) \
            and value not in test.choice_list():
        raise BusinessValidationError("Choose one of the listed results.",
                                      fields={"value": [f"One of: {', '.join(test.choice_list())}"]})
    return None, value


def _flag(item: LabOrderItem, numeric: Decimal | None, text: str) -> str:
    F = LabOrderItem.Flag
    if numeric is not None:
        if item.critical_low is not None and numeric <= item.critical_low:
            return F.CRITICAL_LOW
        if item.critical_high is not None and numeric >= item.critical_high:
            return F.CRITICAL_HIGH
        if item.ref_low is not None and numeric < item.ref_low:
            return F.LOW
        if item.ref_high is not None and numeric > item.ref_high:
            return F.HIGH
        return F.NORMAL if (item.ref_low is not None or item.ref_high is not None) else ""
    test = item.test
    if test.result_type in (LabTest.ResultType.CHOICE, LabTest.ResultType.QUALITATIVE):
        if text in test.critical_answers():
            return F.CRITICAL
        normal = test.normal_answer()
        if normal:
            return F.NORMAL if text == normal else F.ABNORMAL
    return ""


@transaction.atomic
def enter_result(ctx: ActorContext, item: LabOrderItem, *, value: str, comment: str = "") -> LabOrderItem:
    item = _lock_item(item)
    if item.status not in (LabOrderItem.Status.COLLECTED, LabOrderItem.Status.RESULTED):
        raise ConflictError("Results can be entered only after the specimen is collected and before verification.")
    numeric, text = _parse_result(item.test, value)
    item.result_numeric, item.result_text = numeric, text
    item.flag = _flag(item, numeric, text)
    item.result_comment = comment.strip()
    item.entered_by, item.entered_at = ctx.user, timezone.now()
    item.status = LabOrderItem.Status.RESULTED
    item.save()
    _refresh_order_status(item.order)
    record_event(ctx, action="lab.result_enter", object_type="lab_item", object_id=item.pk,
                 details={"test": item.test.code, "flag": item.flag})
    return item


def _record_critical_report(ctx, item: LabOrderItem, reported_to: str) -> None:
    """A critical result must be communicated directly to a clinician; the system records who and when."""
    if not reported_to.strip():
        raise BusinessValidationError(
            "This is a critical result. Inform the requesting clinician directly (in person or by phone), "
            "then record who you informed.", fields={"critical_reported_to": ["Required for critical results."]})
    item.critical_reported_to = reported_to.strip()[:150]
    item.critical_reported_at = timezone.now()
    item.critical_reported_by = ctx.user
    item.critical_acknowledged_at, item.critical_acknowledged_by = None, None


def _alert_critical(item: LabOrderItem) -> None:
    title = f"CRITICAL result: {item.test.name} for {item.order.patient.full_name}"
    body = f"{item.display_value()} {item.unit} ({item.get_flag_display()}). Acknowledge in the patient's chart."
    if item.order.ordered_by.is_active:
        notify_user(item.order.ordered_by, kind="critical_result", title=title, body=body,
                    link=f"/patients/{item.order.patient_id}?tab=labs")
    else:
        notify_permission_holders("clinical.write", kind="critical_result", title=title, body=body,
                                  link=f"/patients/{item.order.patient_id}?tab=labs")


@transaction.atomic
def verify_result(ctx: ActorContext, item: LabOrderItem, *, critical_reported_to: str = "") -> LabOrderItem:
    item = _lock_item(item)
    if item.status != LabOrderItem.Status.RESULTED:
        raise ConflictError("Only entered results can be verified.")
    if getattr(settings, "LAB_REQUIRE_SECOND_VERIFIER", False) and item.entered_by_id == ctx.user.pk:
        raise ConflictError("A different technician must verify this result.")
    if item.is_critical:
        _record_critical_report(ctx, item, critical_reported_to)
    item.status = LabOrderItem.Status.VERIFIED
    item.verified_by, item.verified_at = ctx.user, timezone.now()
    item.save()
    if item.is_critical:
        _alert_critical(item)
        visit_event(ctx, item.order.visit_id, "lab.critical",
                    f"CRITICAL result {item.test.name}: reported to {item.critical_reported_to}")
    _refresh_order_status(item.order)
    record_event(ctx, action="lab.result_verify", object_type="lab_item", object_id=item.pk,
                 details={"test": item.test.code, "flag": item.flag})
    visit_event(ctx, item.order.visit_id, "lab.verify", f"Result verified: {item.test.name}")
    if item.flag in (LabOrderItem.Flag.LOW, LabOrderItem.Flag.HIGH, LabOrderItem.Flag.ABNORMAL) \
            and item.order.status != LabOrder.Status.COMPLETED:
        notify_user(item.order.ordered_by, kind="lab_result",
                    title=f"Abnormal result: {item.test.name}", body=f"{item.order.patient.full_name} · "
                    f"{item.order.accession_number}", link=f"/patients/{item.order.patient_id}?tab=labs")
    return item


@transaction.atomic
def amend_result(ctx: ActorContext, item: LabOrderItem, *, value: str, reason: str, comment: str = "",
                 critical_reported_to: str = "") -> LabOrderItem:
    item = _lock_item(item)
    if item.status != LabOrderItem.Status.VERIFIED:
        raise ConflictError("Only verified results are amended; correct unverified results directly.")
    if not reason.strip():
        raise BusinessValidationError("A reason is required.", fields={"reason": ["Required."]})
    LabResultAmendment.objects.create(item=item, previous_numeric=item.result_numeric, previous_text=item.result_text,
                                      previous_flag=item.flag, reason=reason.strip(), author=ctx.user)
    numeric, text = _parse_result(item.test, value)
    item.result_numeric, item.result_text = numeric, text
    item.flag = _flag(item, numeric, text)
    if comment:
        item.result_comment = comment.strip()
    if item.is_critical:
        _record_critical_report(ctx, item, critical_reported_to)
    item.verified_by, item.verified_at = ctx.user, timezone.now()
    item.save()
    if item.is_critical:
        _alert_critical(item)
    record_event(ctx, action="lab.result_amend", object_type="lab_item", object_id=item.pk,
                 details={"test": item.test.code, "reason": reason.strip()})
    notify_user(item.order.ordered_by, kind="lab_result", title=f"Result corrected: {item.test.name}",
                body=f"{item.order.patient.full_name} · {item.order.accession_number}",
                link=f"/patients/{item.order.patient_id}?tab=labs")
    return item


@transaction.atomic
def cancel_item(ctx: ActorContext, item: LabOrderItem, reason: str) -> LabOrderItem:
    item = _lock_item(item)
    if item.status in (LabOrderItem.Status.VERIFIED, LabOrderItem.Status.CANCELLED):
        raise ConflictError("Verified or cancelled tests cannot be cancelled.")
    if not reason.strip():
        raise BusinessValidationError("A reason is required.", fields={"reason": ["Required."]})
    item.status = LabOrderItem.Status.CANCELLED
    item.cancel_reason = reason.strip()
    item.save()
    _refresh_order_status(item.order)
    record_event(ctx, action="lab.cancel", object_type="lab_item", object_id=item.pk,
                 details={"test": item.test.code, "reason": item.cancel_reason})
    visit_event(ctx, item.order.visit_id, "lab.cancel", f"Test cancelled: {item.test.name} ({item.cancel_reason})")
    return item


@transaction.atomic
def acknowledge_critical(ctx: ActorContext, item: LabOrderItem) -> LabOrderItem:
    item = _lock_item(item)
    if not item.is_critical or item.status != LabOrderItem.Status.VERIFIED:
        raise ConflictError("Only verified critical results are acknowledged.")
    if item.critical_acknowledged_at:
        return item
    item.critical_acknowledged_at, item.critical_acknowledged_by = timezone.now(), ctx.user
    item.save(update_fields=["critical_acknowledged_at", "critical_acknowledged_by"])
    record_event(ctx, action="lab.critical_ack", object_type="lab_item", object_id=item.pk,
                 details={"test": item.test.code})
    visit_event(ctx, item.order.visit_id, "lab.critical_ack", f"Critical result {item.test.name} acknowledged")
    return item


@transaction.atomic
def repeat_test(ctx: ActorContext, item: LabOrderItem, *, reason: str, chargeable: bool = False) -> LabOrderItem:
    """
    Request the same test again on the same order. If the original is not yet verified (e.g. the
    specimen was rejected) it is cancelled with the same reason. Repeats caused by the laboratory are
    not charged; a repeat the clinician asks for can be.
    """
    item = _lock_item(item)
    if not reason.strip():
        raise BusinessValidationError("A reason is required.", fields={"reason": ["Required."]})
    if item.status == LabOrderItem.Status.ORDERED:
        raise ConflictError("The test has not been done yet; nothing to repeat.")
    if item.status in (LabOrderItem.Status.COLLECTED, LabOrderItem.Status.RESULTED):
        item.status = LabOrderItem.Status.CANCELLED
        item.cancel_reason = f"Repeated: {reason.strip()}"[:255]
        item.save(update_fields=["status", "cancel_reason"])
    order = item.order
    patient = order.patient
    limits = range_for(item.test, sex=patient.sex, birth_date=patient.birth_date, on=timezone.localdate())
    repeat = LabOrderItem.objects.create(order=order, test=item.test, price=item.test.price, unit=item.test.unit,
                                         specimen_type=item.test.specimen_type, repeat_of=item,
                                         repeat_reason=reason.strip(), is_chargeable=chargeable, **limits)
    _refresh_order_status(order)
    record_event(ctx, action="lab.repeat", object_type="lab_item", object_id=repeat.pk,
                 details={"of": str(item.pk), "test": item.test.code, "reason": reason.strip(),
                          "chargeable": chargeable})
    visit_event(ctx, order.visit_id, "lab.repeat", f"Repeat requested: {item.test.name} ({reason.strip()})")
    return repeat


TEST_FIELDS = ("code", "name", "category", "specimen_type", "result_type", "unit", "ref_low", "ref_high", "ref_text",
               "choices", "normal_choice", "critical_low", "critical_high", "critical_choices", "price", "is_active")


@transaction.atomic
def save_test(ctx: ActorContext, data: dict, test: LabTest | None = None) -> LabTest:
    creating = test is None
    if creating and LabTest.objects.filter(code__iexact=data["code"]).exists():
        raise ConflictError("A test with this code already exists.", fields={"code": ["Already used."]})
    test = test or LabTest()
    changes = {}
    for key in TEST_FIELDS:
        if key in data and (creating or getattr(test, key) != data[key]):
            changes[key] = str(data[key])
            setattr(test, key, data[key])
    test.full_clean()
    test.save()
    record_event(ctx, action="lab.test_create" if creating else "lab.test_update", object_type="lab_test",
                 object_id=test.pk, details=changes)
    return test


@transaction.atomic
def set_ranges(ctx: ActorContext, test: LabTest, rows: list[dict]) -> list[LabReferenceRange]:
    for r in rows:
        if r.get("age_max_days") is not None and r["age_max_days"] <= r.get("age_min_days", 0):
            raise BusinessValidationError("Each age band must end after it starts.", fields={"ranges": ["Check ages."]})
        if r.get("ref_low") is not None and r.get("ref_high") is not None and r["ref_low"] > r["ref_high"]:
            raise BusinessValidationError("Low limit is above high limit.", fields={"ranges": ["Check limits."]})
    old = list(test.ranges.values("sex", "age_min_days", "age_max_days", "ref_low", "ref_high"))
    test.ranges.all().delete()  # catalogue configuration; results keep their own snapshot of the range
    created = [LabReferenceRange.objects.create(test=test, **r) for r in rows]
    record_event(ctx, action="lab.ranges_update", object_type="lab_test", object_id=test.pk,
                 details={"from": [{k: str(v) for k, v in o.items()} for o in old], "count": len(created)})
    return created
