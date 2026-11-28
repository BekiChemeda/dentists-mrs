from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404
from django.urls import path
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response

from apps.approvals.api import ApprovalSerializer
from apps.core.api import PermissionedView, validated
from apps.core.permissions import AnyOf
from apps.patients.models import Patient
from apps.scheduling.api import PatientBrief, UserBrief
from apps.scheduling.models import Visit

from . import services
from .models import Invoice, InvoiceLine, Payment, ServicePrice
from apps.core.concurrency import bump_version, guarded_edit


class ServicePriceSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServicePrice
        fields = ["id", "code", "name", "category", "price", "tax_rate", "is_active", "row_version"]


class LineSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceLine
        fields = ["id", "kind", "description", "quantity", "unit_price", "line_total", "tax_rate", "source_type", "is_void"]


class PaymentSerializer(serializers.ModelSerializer):
    received_by = UserBrief(read_only=True)
    invoice_number = serializers.CharField(source="invoice.number", read_only=True)
    patient_name = serializers.CharField(source="invoice.patient.full_name", read_only=True)

    class Meta:
        model = Payment
        fields = ["id", "receipt_number", "invoice", "invoice_number", "patient_name", "amount", "method", "reference",
                  "amount_tendered", "change_given", "balance_after", "received_by", "received_at", "refunded",
                  "refundable"]

    change_given = serializers.SerializerMethodField()

    def get_change_given(self, obj) -> str | None:
        return None if obj.amount_tendered is None else str(obj.amount_tendered - obj.amount)

    refunded = serializers.SerializerMethodField()
    refundable = serializers.SerializerMethodField()

    def get_refunded(self, obj) -> str:
        return str(sum((r.amount for r in obj.refunds.all()), Decimal("0")))

    def get_refundable(self, obj) -> str:
        return str(obj.amount - sum((r.amount for r in obj.refunds.all()), Decimal("0")))


class RefundSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    number = serializers.CharField()
    payment = serializers.UUIDField(source="payment_id")
    receipt_number = serializers.CharField(source="payment.receipt_number")
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    method = serializers.CharField()
    reference = serializers.CharField()
    reason = serializers.CharField()
    approved_by = serializers.CharField(source="approval.decided_by.full_name")
    refunded_by = serializers.CharField(source="refunded_by.full_name")
    refunded_at = serializers.DateTimeField()


class InvoiceSerializer(serializers.ModelSerializer):
    patient = PatientBrief(read_only=True)
    created_by = UserBrief(read_only=True)
    lines = serializers.SerializerMethodField()
    payments = PaymentSerializer(many=True, read_only=True)
    refunds = RefundSerializer(many=True, read_only=True)
    balance = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    visit_date = serializers.DateField(source="visit.visit_date", read_only=True, default=None)

    class Meta:
        model = Invoice
        fields = ["id", "number", "patient", "visit", "visit_date", "status", "subtotal", "discount_amount",
                  "tax_amount", "total", "amount_paid", "balance", "void_reason", "issued_at", "created_at",
                  "created_by", "lines", "payments", "refunds"]

    def get_lines(self, obj):
        return LineSerializer([l for l in obj.lines.all() if not l.is_void or obj.status == Invoice.Status.VOID],
                              many=True).data


class InvoiceListSerializer(serializers.ModelSerializer):
    patient = PatientBrief(read_only=True)
    balance = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Invoice
        fields = ["id", "number", "patient", "visit", "status", "total", "amount_paid", "balance", "issued_at",
                  "created_at"]


def _invoice_qs():
    return Invoice.objects.select_related("patient", "created_by", "visit").prefetch_related(
        "lines", "payments__received_by", "payments__invoice__patient", "payments__refunds",
        "refunds__payment", "refunds__approval__decided_by", "refunds__refunded_by")


def _invoice_response(pk, code=200):
    return Response(InvoiceSerializer(_invoice_qs().get(pk=pk)).data, status=code)


class ServicePriceListCreateView(PermissionedView):
    required_permissions = {"GET": AnyOf(("billing.view", "billing.invoice", "appointments.view")), "POST": ("settings.manage",)}

    def get(self, request):
        qs = ServicePrice.objects.all()
        active = self.param_bool("active")
        if active is not None:
            qs = qs.filter(is_active=active)
        return Response(ServicePriceSerializer(qs.order_by("category", "name"), many=True).data)

    def post(self, request):
        s = ServicePriceSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return Response(ServicePriceSerializer(services.save_service(self.ctx(), dict(s.validated_data))).data,
                        status=status.HTTP_201_CREATED)


class ServicePriceDetailView(PermissionedView):
    required_permissions = {"PATCH": ("settings.manage",)}

    def patch(self, request, pk):
        with guarded_edit(ServicePrice, pk, request, object_type="service_price", label="service") as service:
            s = ServicePriceSerializer(service, data=request.data, partial=True)
            s.is_valid(raise_exception=True)
            data = dict(s.validated_data)
            data.pop("code", None)
            saved = services.save_service(self.ctx(), data, service)
        return Response(ServicePriceSerializer(saved).data)


class InvoiceInput(serializers.Serializer):
    patient_id = serializers.UUIDField()
    visit_id = serializers.UUIDField(required=False, allow_null=True)
    pull_charges = serializers.BooleanField(default=True)


class InvoiceListCreateView(PermissionedView):
    required_permissions = {"GET": ("billing.view",), "POST": ("billing.invoice",)}

    def get(self, request):
        qs = Invoice.objects.select_related("patient")
        if patient := self.param_uuid("patient"):
            qs = qs.filter(patient_id=patient)
        if st := request.query_params.get("status"):
            qs = qs.filter(status__in=st.split(","))
        if q := request.query_params.get("q", "").strip():
            qs = qs.filter(Q(number__iexact=q) | Q(patient__mrn__iexact=q) | Q(patient__first_name__icontains=q)
                           | Q(patient__middle_name__icontains=q))
        if day := self.param_date("date"):
            qs = qs.filter(created_at__date=day)
        return self.paginate(qs.order_by("-created_at"), InvoiceListSerializer)

    def post(self, request):
        data = validated(InvoiceInput, request.data)
        patient = get_object_or_404(Patient, pk=data["patient_id"])
        visit = get_object_or_404(Visit, pk=data["visit_id"]) if data.get("visit_id") else None
        existing = Invoice.objects.filter(visit=visit, status=Invoice.Status.DRAFT).first() if visit else None
        invoice = existing or services.create_invoice(self.ctx(), patient=patient, visit=visit)
        if visit and data["pull_charges"]:
            services.add_pending_charges(self.ctx(), invoice)
        return _invoice_response(invoice.pk, 200 if existing else 201)


class InvoiceDetailView(PermissionedView):
    required_permissions = {"GET": ("billing.view",)}

    def get(self, request, pk):
        get_object_or_404(Invoice, pk=pk)
        return _invoice_response(pk)


class LineInput(serializers.Serializer):
    service_id = serializers.UUIDField(required=False, allow_null=True)
    description = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0, required=False)
    quantity = serializers.DecimalField(max_digits=10, decimal_places=3, min_value=Decimal("0.001"), default=1)


class PaymentInput(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    method = serializers.ChoiceField(choices=Payment.Method.choices)
    reference = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    amount_tendered = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"),
                                               required=False, allow_null=True, default=None)


class AmountReasonInput(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"), required=False)
    reason = serializers.CharField(max_length=255)


class InvoiceActionView(PermissionedView):
    PERMS = {"lines": ("billing.invoice",), "pull-charges": ("billing.invoice",), "issue": ("billing.invoice",),
             "payments": ("billing.payment",), "request-discount": AnyOf(("billing.invoice", "billing.payment")),
             "apply-discount": AnyOf(("billing.invoice", "billing.payment")),
             "request-void": AnyOf(("billing.invoice", "billing.payment")),
             "void": AnyOf(("billing.invoice", "billing.payment"))}

    @property
    def required_permissions(self):
        action = self.kwargs.get("action")
        return {"POST": self.PERMS[action]} if action in self.PERMS else {}

    def post(self, request, pk, action):
        invoice = get_object_or_404(Invoice.objects.select_related("patient"), pk=pk)
        ctx = self.ctx()
        if action == "lines":
            data = validated(LineInput, request.data)
            service = get_object_or_404(ServicePrice, pk=data["service_id"], is_active=True) \
                if data.get("service_id") else None
            services.add_service_line(ctx, invoice, service=service, description=data["description"],
                                      unit_price=data.get("unit_price"), quantity=data["quantity"])
        elif action == "pull-charges":
            services.add_pending_charges(ctx, invoice)
        elif action == "issue":
            services.issue_invoice(ctx, invoice)
        elif action == "payments":
            payment = services.record_payment(ctx, invoice, **validated(PaymentInput, request.data))
            body = _invoice_response(pk).data
            body["new_payment"] = PaymentSerializer(payment).data
            return Response(body, status=status.HTTP_201_CREATED)
        elif action in ("request-discount", "request-void"):
            data = validated(AmountReasonInput, request.data)
            if action == "request-discount":
                if "amount" not in data:
                    return Response({"error": {"code": "validation_error", "message": "Enter an amount.",
                                               "fields": {"amount": ["Required."]}}}, status=400)
                req = services.request_discount(ctx, invoice, amount=data["amount"], reason=data["reason"])
            else:
                req = services.request_void(ctx, invoice, reason=data["reason"])
            return Response(ApprovalSerializer(req, context={"request": request}).data, status=status.HTTP_201_CREATED)
        elif action in ("apply-discount", "void"):
            approval_id = request.data.get("approval_id")
            if not approval_id:
                return Response({"error": {"code": "validation_error", "message": "approval_id is required."}},
                                status=400)
            if action == "void":
                services.void_invoice(ctx, invoice, approval_id)
            else:
                services.apply_discount(ctx, invoice, approval_id)
        return _invoice_response(pk)


class InvoiceLineRemoveView(PermissionedView):
    required_permissions = {"POST": ("billing.invoice",)}

    def post(self, request, pk):
        line = get_object_or_404(InvoiceLine.objects.select_related("invoice"), pk=pk, is_void=False)
        services.remove_line(self.ctx(), line)
        return _invoice_response(line.invoice_id)


class PaymentListView(PermissionedView):
    required_permissions = {"GET": ("billing.view",)}

    def get(self, request):
        qs = Payment.objects.select_related("received_by", "invoice__patient")
        day = self.param_date("date")
        if day:
            qs = qs.filter(received_at__date=day)
        if self.param_bool("mine"):
            qs = qs.filter(received_by=request.user)
        if patient := self.param_uuid("patient"):
            qs = qs.filter(invoice__patient_id=patient)
        return self.paginate(qs.prefetch_related("refunds").order_by("-received_at"), PaymentSerializer)


class DailySummaryView(PermissionedView):
    required_permissions = {"GET": AnyOf(("billing.payment", "reports.financial"))}

    def get(self, request):
        day = self.param_date("date") or timezone.localdate()
        payments = Payment.objects.filter(received_at__date=day)
        from .models import Refund

        refunds = Refund.objects.filter(refunded_at__date=day)
        refunded = refunds.aggregate(t=Sum("amount"))["t"] or 0
        by_method = {row["method"]: row["total"] for row in payments.values("method").annotate(total=Sum("amount"))}
        by_cashier = [{"cashier": row["received_by__first_name"] + " " + row["received_by__last_name"],
                       "total": row["total"], "count": row["n"]}
                      for row in payments.values("received_by__first_name", "received_by__last_name")
                      .annotate(total=Sum("amount"), n=Count("id"))]
        issued = Invoice.objects.filter(issued_at__date=day).exclude(status=Invoice.Status.VOID)
        outstanding = Invoice.objects.filter(status__in=[Invoice.Status.ISSUED, Invoice.Status.PARTIAL])
        return Response({
            "date": day,
            "received_total": payments.aggregate(t=Sum("amount"))["t"] or 0,
            "refunded_total": refunded,
            "collected_total": (payments.aggregate(t=Sum("amount"))["t"] or 0) - refunded,
            "payment_count": payments.count(),
            "by_method": by_method,
            "by_cashier": by_cashier,
            "invoiced_total": issued.aggregate(t=Sum("total"))["t"] or 0,
            "discounts_total": issued.aggregate(t=Sum("discount_amount"))["t"] or 0,
            "outstanding_total": sum((i.balance for i in outstanding), 0),
            "outstanding_count": outstanding.count(),
        })


class RefundInput(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    reason = serializers.CharField(max_length=255)


class ApplyRefundInput(serializers.Serializer):
    approval_id = serializers.UUIDField()
    method = serializers.ChoiceField(choices=Payment.Method.choices)
    reference = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")


class PaymentRefundView(PermissionedView):
    """POST payments/<id>/request-refund/ (ask for approval) or /refund/ (pay out an approved refund)."""

    required_permissions = {"POST": ("billing.payment",)}

    def post(self, request, pk, action):
        payment = get_object_or_404(Payment.objects.select_related("invoice__patient"), pk=pk)
        if action == "request-refund":
            from apps.approvals.api import ApprovalSerializer

            data = validated(RefundInput, request.data)
            req = services.request_refund(self.ctx(), payment, amount=data["amount"], reason=data["reason"])
            return Response(ApprovalSerializer(req, context={"request": request}).data, status=status.HTTP_201_CREATED)
        data = validated(ApplyRefundInput, request.data)
        services.apply_refund(self.ctx(), payment, data["approval_id"], method=data["method"],
                              reference=data["reference"])
        return _invoice_response(payment.invoice_id, 201)


urlpatterns = [
    path("billing/payments/<uuid:pk>/<str:action>/", PaymentRefundView.as_view()),
    path("billing/services/", ServicePriceListCreateView.as_view()),
    path("billing/services/<uuid:pk>/", ServicePriceDetailView.as_view()),
    path("billing/invoices/", InvoiceListCreateView.as_view()),
    path("billing/invoices/<uuid:pk>/", InvoiceDetailView.as_view()),
    path("billing/invoices/<uuid:pk>/<str:action>/", InvoiceActionView.as_view()),
    path("billing/lines/<uuid:pk>/remove/", InvoiceLineRemoveView.as_view()),
    path("billing/payments/", PaymentListView.as_view()),
    path("billing/daily-summary/", DailySummaryView.as_view()),
]
