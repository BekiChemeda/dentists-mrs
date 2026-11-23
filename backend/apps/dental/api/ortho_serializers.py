"""Response shapes for orthodontics. HTTP only: business rules live in services/ortho.py."""

from __future__ import annotations

from decimal import Decimal

from django.utils import timezone
from rest_framework import serializers

from apps.scheduling.api import UserBrief

from ..models import OrthoAssessment, OrthoCase, OrthoInstalment, OrthoVisit
from ..services.ortho import billed_total, instalment_lines, instalment_state
from .serializers import PatientMini

ZERO = Decimal("0.00")


def _m(value) -> str | None:
    """Money as the API always sends it: a string with two decimals."""
    return None if value is None else f"{Decimal(value):.2f}"


class OrthoAssessmentSerializer(serializers.ModelSerializer):
    recorded_by = UserBrief(read_only=True)
    version = serializers.IntegerField(source="row_version", read_only=True)
    encounter_status = serializers.CharField(source="encounter.status", read_only=True)

    class Meta:
        model = OrthoAssessment
        fields = ["id", "patient", "encounter", "encounter_status", "recorded_by", "created_at", "updated_at",
                  "version", *OrthoAssessment.CHOICE_FIELDS, "overjet_mm", "overbite_mm",
                  *OrthoAssessment.TEXT_FIELDS]


class OrthoVisitSerializer(serializers.ModelSerializer):
    performed_by = UserBrief(read_only=True)
    voided_by = UserBrief(read_only=True)
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    visit_date = serializers.DateField(source="visit.visit_date", read_only=True)

    class Meta:
        model = OrthoVisit
        fields = ["id", "case", "visit", "visit_date", "encounter", "kind", "kind_label", "upper_wire", "lower_wire",
                  "elastics", "aligner_number", "breakages", "oral_hygiene", "compliance", "notes",
                  "next_interval_weeks", "performed_by", "created_at", "charge", "no_charge_reason", "extra_charge",
                  "extra_charge_reason", "status", "voided_by", "voided_at", "void_reason"]


def _instalments(case: OrthoCase) -> tuple[list[dict], dict]:
    rows = list(case.instalments.all())
    lines = instalment_lines(rows)
    today = timezone.localdate()
    out, totals = [], {"scheduled": ZERO, "invoiced": ZERO, "paid": ZERO, "overdue": ZERO}
    for inst in rows:
        line = lines.get(str(inst.pk))
        state = instalment_state(inst, line, today)
        out.append({"id": str(inst.pk), "sequence": inst.sequence, "label": inst.label, "due_date": inst.due_date,
                    "amount": _m(inst.amount), "state": state, "status": inst.status,
                    "cancelled_reason": inst.cancelled_reason,
                    "invoice": ({"id": str(line.invoice_id), "number": line.invoice.number,
                                 "status": line.invoice.status} if line else None)})
        if inst.status == OrthoInstalment.Status.CANCELLED:
            continue
        if line is None:
            totals["scheduled"] += inst.amount
            if state == "overdue":
                totals["overdue"] += inst.amount
        else:
            totals["invoiced"] += inst.amount
            if state == "paid":
                totals["paid"] += inst.amount
    return out, {k: _m(v) for k, v in totals.items()}


class OrthoCaseBriefSerializer(serializers.ModelSerializer):
    patient = PatientMini(read_only=True)
    orthodontist = UserBrief(read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    appliance_label = serializers.CharField(source="get_appliance_display", read_only=True)
    billing_label = serializers.CharField(source="get_billing_mode_display", read_only=True)
    months_in_treatment = serializers.SerializerMethodField()
    last_visit = serializers.SerializerMethodField()

    class Meta:
        model = OrthoCase
        fields = ["id", "number", "patient", "orthodontist", "appliance", "appliance_label", "arches", "status",
                  "status_label", "started_on", "debonded_on", "closed_on", "expected_months", "months_in_treatment",
                  "billing_mode", "billing_label", "package_price", "per_visit_price", "last_visit", "created_at"]

    def get_months_in_treatment(self, obj):
        if not obj.started_on:
            return None
        end = obj.closed_on or obj.debonded_on or timezone.localdate()
        return max(0, (end.year - obj.started_on.year) * 12 + end.month - obj.started_on.month)

    def get_last_visit(self, obj):
        ov = next((v for v in obj.visits.all() if v.status == OrthoVisit.Status.RECORDED), None)
        return {"date": ov.visit.visit_date, "kind": ov.get_kind_display()} if ov else None


class OrthoCaseSerializer(OrthoCaseBriefSerializer):
    created_by = UserBrief(read_only=True)
    version = serializers.IntegerField(source="row_version", read_only=True)
    visits = OrthoVisitSerializer(many=True, read_only=True)
    instalments = serializers.SerializerMethodField()
    billing_summary = serializers.SerializerMethodField()
    events = serializers.SerializerMethodField()
    assessment = OrthoAssessmentSerializer(read_only=True)
    plan = serializers.SerializerMethodField()

    class Meta(OrthoCaseBriefSerializer.Meta):
        fields = [*OrthoCaseBriefSerializer.Meta.fields, "version", "objectives", "notes", "closed_reason",
                  "retainer_upper", "retainer_lower", "retention_review_months", "deposit", "created_by",
                  "assessment", "plan", "visits", "instalments", "billing_summary", "events"]

    def _inst(self, obj):
        key = f"_inst_{obj.pk}"
        if key not in self.context:
            self.context[key] = _instalments(obj)
        return self.context[key]

    def get_instalments(self, obj):
        return self._inst(obj)[0]

    def get_billing_summary(self, obj):
        if obj.billing_mode == OrthoCase.Billing.PACKAGE:
            totals = self._inst(obj)[1]
            return {"mode": obj.billing_mode, "package_price": _m(obj.package_price), **totals}
        visits = [v for v in obj.visits.all() if v.status == OrthoVisit.Status.RECORDED]
        charged = sum((v.charge or ZERO) + v.extra_charge for v in visits)
        return {"mode": obj.billing_mode, "per_visit_price": _m(obj.per_visit_price), "visits_charged": _m(charged),
                "invoiced_instalments": _m(billed_total(obj))}

    def get_events(self, obj):
        return [{"action": e.action, "note": e.note, "by": e.actor.full_name, "at": e.created_at}
                for e in obj.events.all()]

    def get_plan(self, obj):
        return {"id": str(obj.plan_id), "number": obj.plan.number, "title": obj.plan.title} if obj.plan_id else None
