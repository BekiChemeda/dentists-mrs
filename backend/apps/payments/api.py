"""
  GET  payments/options/                         billing.payment: methods the cashier can offer now
  POST billing/invoices/<id>/pay-by-phone/       billing.payment: send a payment prompt to the patient's phone
  GET  payments/online/<id>/                     billing.view or billing.payment: follow a request (checks the provider)
  POST payments/online/<id>/cancel/              billing.payment: stop waiting
  GET  payments/online/?invoice=&status=         billing.view: requests, newest first
  POST payments/chapa/webhook/                   public: Chapa's notice, signature checked, result re-verified
  POST payments/telebirr/result/<token>/         public: telebirr's result, secret address
  GET/PATCH settings/payments/                   payments.gateway.manage: providers and keys (keys never returned)
  POST settings/payments/test/                   payments.gateway.manage
"""
from __future__ import annotations

from django.http import HttpResponse
from django.urls import path
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api import PermissionedView
from apps.core.permissions import AnyOf
from apps.core.throttling import ClientScopedRateThrottle

from . import services
from .models import OnlinePayment


class OnlinePaymentSerializer(serializers.ModelSerializer):
    invoice_number = serializers.CharField(source="invoice.number", read_only=True)
    receipt_number = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    method_label = serializers.SerializerMethodField()
    phone = serializers.SerializerMethodField()

    class Meta:
        model = OnlinePayment
        fields = ["id", "invoice", "invoice_number", "provider", "method", "method_label", "phone", "amount",
                  "reference", "provider_reference", "status", "status_label", "message", "created_at",
                  "completed_at", "receipt_number", "started_from"]

    def get_receipt_number(self, obj):
        return obj.payment.receipt_number if obj.payment_id else None

    def get_method_label(self, obj):
        return services.METHOD_LABELS.get(obj.method, obj.method)

    def get_phone(self, obj):
        return obj.phone[:4] + "••••" + obj.phone[-2:]  # enough to recognise, not to copy


class OptionsView(PermissionedView):
    required_permissions = {"GET": ("billing.payment",)}

    def get(self, request):
        return Response({"options": services.options(), "licensed": services.licensed()})


class PayByPhoneInput(serializers.Serializer):
    method = serializers.CharField(max_length=10)
    provider = serializers.CharField(max_length=10, required=False, allow_blank=True, default="")
    phone = serializers.CharField(max_length=20)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    started_from = serializers.ChoiceField(choices=["web", "app"], required=False, default="web")


class PayByPhoneView(PermissionedView):
    required_permissions = {"POST": ("billing.payment",)}
    throttle_classes = [ClientScopedRateThrottle]
    throttle_scope = "sensitive"

    def post(self, request, pk):
        from apps.billing.models import Invoice

        invoice = Invoice.objects.filter(pk=pk).first()
        if invoice is None:
            return Response({"error": {"code": "not_found", "message": "No such invoice."}}, status=404)
        s = PayByPhoneInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        op = services.start(self.ctx(), invoice, method=d["method"], provider=d["provider"], phone=d["phone"],
                            amount=d.get("amount"), started_from=d["started_from"])
        return Response(OnlinePaymentSerializer(op).data, status=201)


class OnlinePaymentDetailView(PermissionedView):
    required_permissions = {"GET": AnyOf(("billing.view", "billing.payment"))}

    def get(self, request, pk):
        op = OnlinePayment.objects.select_related("invoice", "payment").filter(pk=pk).first()
        if op is None:
            return Response({"error": {"code": "not_found", "message": "No such payment request."}}, status=404)
        return Response(OnlinePaymentSerializer(services.refresh(op)).data)


class OnlinePaymentCancelView(PermissionedView):
    required_permissions = {"POST": ("billing.payment",)}

    def post(self, request, pk):
        op = OnlinePayment.objects.filter(pk=pk).first()
        if op is None:
            return Response({"error": {"code": "not_found", "message": "No such payment request."}}, status=404)
        return Response(OnlinePaymentSerializer(services.cancel(self.ctx(), op)).data)


class OnlinePaymentListView(PermissionedView):
    required_permissions = {"GET": AnyOf(("billing.view", "billing.payment"))}

    def get(self, request):
        qs = OnlinePayment.objects.select_related("invoice", "payment")
        invoice = self.param_uuid("invoice")
        if invoice:
            qs = qs.filter(invoice_id=invoice)
        status = request.query_params.get("status")
        if status in OnlinePayment.Status.values:
            qs = qs.filter(status=status)
        return self.paginate(qs.order_by("-created_at"), OnlinePaymentSerializer)


class ChapaWebhookView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [ClientScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        raw = request.body[:100_000]
        headers = {k.lower(): v for k, v in request.headers.items()}
        if not services.chapa_webhook(raw, headers):
            return Response(status=401)
        return Response({"received": True})


class TelebirrResultView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [ClientScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request, token):
        if not services.telebirr_result(token[:100], request.body[:100_000]):
            return Response(status=404)
        return HttpResponse(
            '<?xml version="1.0" encoding="UTF-8"?><soapenv:Envelope '
            'xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"><soapenv:Body>'
            "<ResultMsg>Received</ResultMsg></soapenv:Body></soapenv:Envelope>",
            content_type="text/xml")


class SettingsView(PermissionedView):
    required_permissions = {"GET": ("payments.gateway.manage",), "PATCH": ("payments.gateway.manage",)}

    def get(self, request):
        return Response(services.settings_view())

    def patch(self, request):
        return Response(services.update_settings(self.ctx(), dict(request.data)))


class SettingsTestView(PermissionedView):
    required_permissions = {"POST": ("payments.gateway.manage",)}

    def post(self, request):
        from apps.core.exceptions import ConflictError

        from .providers import ProviderError

        try:
            return Response({"message": services.test_connection(str(request.data.get("provider", "")))})
        except ProviderError as exc:
            raise ConflictError(str(exc)) from exc


urlpatterns = [
    path("payments/options/", OptionsView.as_view(), name="payments-options"),
    path("billing/invoices/<uuid:pk>/pay-by-phone/", PayByPhoneView.as_view(), name="pay-by-phone"),
    path("payments/online/", OnlinePaymentListView.as_view(), name="online-payments"),
    path("payments/online/<uuid:pk>/", OnlinePaymentDetailView.as_view(), name="online-payment"),
    path("payments/online/<uuid:pk>/cancel/", OnlinePaymentCancelView.as_view(), name="online-payment-cancel"),
    path("payments/chapa/webhook/", ChapaWebhookView.as_view(), name="chapa-webhook"),
    path("payments/telebirr/result/<str:token>/", TelebirrResultView.as_view(), name="telebirr-result"),
    path("settings/payments/", SettingsView.as_view(), name="payment-settings"),
    path("settings/payments/test/", SettingsTestView.as_view(), name="payment-settings-test"),
]
