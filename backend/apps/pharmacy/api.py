from decimal import Decimal

from django.shortcuts import get_object_or_404
from django.urls import path
from rest_framework import serializers, status
from rest_framework.response import Response

from apps.approvals.api import ApprovalSerializer
from apps.clinical.models import PrescriptionItem
from apps.core.api import PermissionedView, validated
from apps.core.permissions import AnyOf
from apps.scheduling.api import PatientBrief, UserBrief

from . import services
from .models import Dispensation


class DispensationSerializer(serializers.ModelSerializer):
    dispensed_by = UserBrief(read_only=True)
    patient = PatientBrief(read_only=True)
    item_name = serializers.CharField(source="item.__str__", read_only=True)
    unit = serializers.CharField(source="item.unit", read_only=True)
    prescription_id = serializers.UUIDField(source="prescription_item.prescription_id", read_only=True)

    class Meta:
        model = Dispensation
        fields = ["id", "prescription_id", "prescription_item", "patient", "item", "item_name", "unit", "quantity",
                  "unit_price", "override_approval", "notes", "batch_choice_reason", "special_form_checked",
                  "counselling_given", "dispensed_by", "dispensed_at"]


class DispenseInput(serializers.Serializer):
    quantity = serializers.DecimalField(max_digits=10, decimal_places=3, min_value=Decimal("0.001"))
    item_id = serializers.UUIDField(required=False, allow_null=True)
    override_approval_id = serializers.UUIDField(required=False, allow_null=True)
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    batch_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    batch_reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    special_form_checked = serializers.BooleanField(default=False)
    counselling_given = serializers.BooleanField(default=False)


class DispenseView(PermissionedView):
    required_permissions = {"POST": ("pharmacy.dispense",)}

    def post(self, request, pk):
        data = validated(DispenseInput, request.data)
        d = services.dispense(self.ctx(), get_object_or_404(PrescriptionItem, pk=pk), **data)
        d = Dispensation.objects.select_related("dispensed_by", "patient", "item", "prescription_item").get(pk=d.pk)
        return Response(DispensationSerializer(d).data, status=status.HTTP_201_CREATED)


class OverrideInput(serializers.Serializer):
    quantity = serializers.DecimalField(max_digits=10, decimal_places=3, min_value=Decimal("0.001"))
    reason = serializers.CharField(max_length=255)


class OverrideRequestView(PermissionedView):
    required_permissions = {"POST": ("pharmacy.dispense",)}

    def post(self, request, pk):
        data = validated(OverrideInput, request.data)
        rx_item = get_object_or_404(PrescriptionItem.objects.select_related("prescription__patient"), pk=pk)
        req = services.request_override(self.ctx(), rx_item, **data)
        return Response(ApprovalSerializer(req, context={"request": request}).data, status=status.HTTP_201_CREATED)


class DispensationListView(PermissionedView):
    required_permissions = {"GET": AnyOf(("pharmacy.view", "clinical.view"))}

    def get(self, request):
        qs = Dispensation.objects.select_related("dispensed_by", "patient", "item", "prescription_item")
        if patient := self.param_uuid("patient"):
            qs = qs.filter(patient_id=patient)
        if day := self.param_date("date"):
            qs = qs.filter(dispensed_at__date=day)
        return self.paginate(qs.order_by("-dispensed_at"), DispensationSerializer)


class ControlledRegisterView(PermissionedView):
    """
    Register of a controlled medicine: every receipt, dispensing and adjustment in date order with a
    running balance (EFDA Directive 1121/2025, Art. 29). Built from the stock ledger, which is never
    edited, so the register cannot drift from stock. Supports ?export=csv.
    """

    required_permissions = {"GET": AnyOf(("pharmacy.dispense", "inventory.manage", "reports.operational"))}

    def get(self, request):
        import csv
        import io

        from django.http import HttpResponse

        from apps.audit.services import record_event
        from apps.clinical.models import Prescription
        from apps.inventory.models import Item, StockMovement

        controlled = Item.objects.exclude(controlled_class="").order_by("name")
        item_id = self.param_uuid("item")
        if item_id is None:
            return Response({"items": [{"id": str(i.pk), "name": str(i), "class": i.controlled_class}
                                       for i in controlled], "rows": []})
        item = get_object_or_404(controlled, pk=item_id)
        date_from, date_to = self.param_date("date_from"), self.param_date("date_to")
        moves = (StockMovement.objects.filter(item=item).select_related("batch", "created_by", "purchase__supplier")
                 .order_by("created_at", "id"))
        dispensations = {str(d.pk): d for d in Dispensation.objects.filter(item=item).select_related(
            "patient", "prescription_item__prescription__prescriber", "dispensed_by")}
        balance, rows = Decimal("0"), []
        for m in moves:
            balance += m.quantity
            day = m.created_at.date()
            if (date_from and day < date_from) or (date_to and day > date_to):
                continue
            row = {"date": m.created_at.isoformat(), "kind": m.get_kind_display(), "batch": m.batch.batch_number,
                   "expiry": m.batch.expiry_date.isoformat() if m.batch.expiry_date else "",
                   "received": str(m.quantity) if m.quantity > 0 else "", "issued": str(-m.quantity) if m.quantity < 0 else "",
                   "balance": str(balance), "by": m.created_by.full_name, "reference": m.reason,
                   "patient": "", "mrn": "", "prescriber": "", "prescriber_reg": "", "form_serial": ""}
            if m.purchase_id:
                row["reference"] = f"{m.purchase.supplier.name} {m.purchase.supplier_invoice_no}".strip()
            d = dispensations.get(m.reference_id) if m.reference_type == "dispensation" else None
            if d is not None:
                rx: Prescription = d.prescription_item.prescription
                row.update(patient=d.patient.full_name, mrn=d.patient.mrn, prescriber=rx.prescriber.full_name,
                           prescriber_reg=rx.prescriber.registration_number, form_serial=rx.special_form_serial,
                           reference=f"Dispensed by {d.dispensed_by.full_name} ({d.dispensed_by.registration_number})")
            rows.append(row)
        record_event(self.ctx(), action="pharmacy.register_view", object_type="item", object_id=item.pk,
                     details={"export": request.query_params.get("export") == "csv"})
        if request.query_params.get("export") == "csv":
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()) if rows else ["date"])
            w.writeheader()
            w.writerows(rows)
            resp = HttpResponse(buf.getvalue(), content_type="text/csv")
            resp["Content-Disposition"] = f'attachment; filename="register-{item.code}.csv"'
            return resp
        return Response({"item": {"id": str(item.pk), "name": str(item), "class": item.controlled_class,
                                  "unit": item.unit}, "rows": rows, "balance": str(balance)})


urlpatterns = [
    path("pharmacy/controlled-register/", ControlledRegisterView.as_view()),
    path("pharmacy/dispensations/", DispensationListView.as_view()),
    path("prescription-items/<uuid:pk>/dispense/", DispenseView.as_view()),
    path("prescription-items/<uuid:pk>/override-request/", OverrideRequestView.as_view()),
]
