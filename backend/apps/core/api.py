"""Small helpers shared by module APIs."""

import datetime
import uuid

from rest_framework import serializers
from rest_framework.views import APIView

from .context import ActorContext
from .models import ClinicSettings
from .pagination import StandardPagination
from .permissions import HasRequiredPermissions


class PermissionedView(APIView):
    """Base view: every subclass must declare `required_permissions`."""

    permission_classes = [HasRequiredPermissions]
    required_permissions: dict = {}

    def ctx(self) -> ActorContext:
        return ActorContext.from_request(self.request)

    def paginate(self, queryset, serializer_class, **context):
        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, self.request, view=self)
        data = serializer_class(page, many=True, context={"request": self.request, **context}).data
        return paginator.get_paginated_response(data)

    def param_date(self, name: str) -> datetime.date | None:
        raw = self.request.query_params.get(name)
        if not raw:
            return None
        try:
            return datetime.date.fromisoformat(raw)
        except ValueError as exc:
            raise serializers.ValidationError({name: ["Use the format YYYY-MM-DD."]}) from exc

    def param_uuid(self, name: str) -> uuid.UUID | None:
        raw = self.request.query_params.get(name)
        if not raw:
            return None
        try:
            return uuid.UUID(raw)
        except ValueError as exc:
            raise serializers.ValidationError({name: ["Invalid identifier."]}) from exc

    def param_bool(self, name: str) -> bool | None:
        raw = self.request.query_params.get(name)
        if raw in ("true", "1"):
            return True
        if raw in ("false", "0"):
            return False
        return None


def validated(serializer_class, data, **kwargs) -> dict:
    s = serializer_class(data=data, **kwargs)
    s.is_valid(raise_exception=True)
    return s.validated_data


class ClinicSettingsSerializer(serializers.Serializer):
    facility_name = serializers.CharField(max_length=150)
    facility_level = serializers.ChoiceField(choices=ClinicSettings.FacilityLevel.choices)
    license_number = serializers.CharField(max_length=50, allow_blank=True, required=False)
    address = serializers.CharField(max_length=255, allow_blank=True, required=False)
    phone = serializers.CharField(max_length=30, allow_blank=True, required=False)
    tin = serializers.CharField(max_length=20, allow_blank=True, required=False)
    lab_billing_point = serializers.ChoiceField(choices=ClinicSettings.LabBillingPoint.choices)
    show_ethiopian_calendar = serializers.BooleanField(required=False)
    note_patient_card = serializers.CharField(max_length=300, allow_blank=True, required=False)
    note_prescription = serializers.CharField(max_length=300, allow_blank=True, required=False)
    note_consultation = serializers.CharField(max_length=300, allow_blank=True, required=False)
    note_referral = serializers.CharField(max_length=300, allow_blank=True, required=False)
    note_lab_report = serializers.CharField(max_length=300, allow_blank=True, required=False)
    note_certificate = serializers.CharField(max_length=300, allow_blank=True, required=False)
    opening_hours = serializers.JSONField(required=False)
    wait_alert_minutes = serializers.IntegerField(min_value=10, max_value=480, required=False)
    allow_skip_triage = serializers.BooleanField(required=False)
    auto_complete_minutes = serializers.IntegerField(min_value=0, max_value=480, required=False)
    bill_consultation_for_dental = serializers.BooleanField(required=False)
    setup_checklist_hidden = serializers.BooleanField(required=False)
    row_version = serializers.IntegerField(read_only=True)

    def validate_opening_hours(self, value):
        from .hours import clean_opening_hours

        return clean_opening_hours(value)
    has_logo = serializers.SerializerMethodField()
    logo_version = serializers.SerializerMethodField()

    def get_has_logo(self, obj) -> bool:
        return bool(obj.logo_png)

    def get_logo_version(self, obj) -> str | None:
        from .branding import logo_version

        return logo_version(obj)


class ClinicSettingsView(PermissionedView):
    """Facility details (printed on documents) and billing policy. Everyone signed in can read them."""

    required_permissions = {"GET": (), "PATCH": ("settings.manage",)}

    def get(self, request):
        from rest_framework.response import Response

        return Response(ClinicSettingsSerializer(ClinicSettings.get()).data)

    def patch(self, request):
        from django.db import transaction
        from rest_framework.response import Response

        from apps.audit.services import record_event

        data = validated(ClinicSettingsSerializer, request.data, partial=True)
        from .concurrency import check_version, expected_version

        with transaction.atomic():
            obj = ClinicSettings.objects.select_for_update().get_or_create(pk=1)[0]
            check_version(obj, expected_version(request), object_type="clinic_settings", label="clinic settings page")
            changes = {}
            for key, value in data.items():
                if getattr(obj, key) != value:
                    changes[key] = {"from": str(getattr(obj, key)), "to": str(value)}
                    setattr(obj, key, value)
            if changes:
                obj.save()
                record_event(self.ctx(), action="settings.update", object_type="clinic_settings", object_id=1,
                             details=changes)
        return Response(ClinicSettingsSerializer(obj).data)


class SetupChecklistView(PermissionedView):
    """First-run checklist for the clinic administrator: what still needs setting up before go-live."""

    required_permissions = {"GET": ("settings.manage",)}

    def get(self, request):
        from rest_framework.response import Response

        from apps.accounts.models import Department, Room, User
        from apps.billing.models import ServicePrice
        from apps.inventory.models import Item
        from apps.laboratory.models import LabTest

        cs = ClinicSettings.get()
        staff = (User.objects.filter(is_active=True)
                 .exclude(roles__code__in=["system_admin", "clinic_admin", "clinic_director"]).distinct().count())
        consult = ServicePrice.objects.filter(code="CONSULT", is_active=True).first()
        items = [
            ("clinic", "Clinic name, address, phone and licence number",
             cs.facility_name.strip() not in ("", "Clinic") and bool(cs.address and cs.phone and cs.license_number),
             "/admin/clinic"),
            ("logo", "Clinic logo (optional)", bool(cs.logo_png), "/admin/clinic"),
            ("hours", "Opening hours", bool(cs.opening_hours), "/admin/clinic"),
            ("departments", "Departments that see patients",
             Department.objects.filter(receives_triage=True, is_active=True).exists(), "/admin/departments"),
            ("rooms", "Consultation rooms", Room.objects.filter(is_active=True).exists(), "/admin/departments"),
            ("staff", "Accounts for the staff (at least 3)", staff >= 3, "/admin/users"),
            ("prices", "Consultation price", bool(consult and consult.price > 0), "/catalogue"),
            ("lab", "Laboratory tests and prices", LabTest.objects.filter(is_active=True, price__gt=0).exists(),
             "/catalogue"),
            ("medicines", "Medicines in the catalogue", Item.objects.filter(is_active=True, category="medicine").exists(),
             "/inventory"),
        ]
        rows = [{"key": k, "label": label, "done": bool(done), "link": link} for k, label, done, link in items]
        return Response({"hidden": cs.setup_checklist_hidden, "items": rows,
                         "done": sum(r["done"] for r in rows), "total": len(rows)})
