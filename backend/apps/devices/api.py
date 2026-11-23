"""
Endpoints:
  GET  mobile/licence/                 public: the signed licence, so the app can check this server
  POST mobile/activate/                public, rate-limited: activate a phone with a one-time code
  POST auth/app/challenge/             public, rate-limited: a one-time value for the phone to sign
  GET  devices/                        devices.manage: phones and their state
  POST devices/<id>/revoke/            devices.manage: switch a phone off and end its sign-ins
  POST devices/activation-codes/       devices.manage: a one-time code and QR for a new phone
  GET  devices/licence/                devices.manage or system.security.manage: licence state
  POST devices/licence/                system.security.manage: install a licence from the supplier
"""
from __future__ import annotations

import segno
from django.contrib.auth import get_user_model
from django.urls import path
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api import PermissionedView
from apps.core.context import ActorContext
from apps.core.permissions import AnyOf
from apps.core.throttling import ClientScopedRateThrottle

from . import services
from .models import MobileDevice


class PublicLicenceView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def get(self, request):
        from .models import Installation

        inst = Installation.get()
        return Response({"licence": inst.licence_text, "installation_id": str(inst.installation_id)})


class ActivateInput(serializers.Serializer):
    code = serializers.CharField(max_length=20)
    attestation = serializers.ListField(child=serializers.CharField(max_length=8000), max_length=10, required=False,
                                        default=list)
    public_key = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    label = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    model = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    os_version = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")


class ActivateView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [ClientScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        s = ActivateInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        lic = services.require_app_licence()
        device = services.activate(ActorContext.from_request(request), code=d["code"], chain=d["attestation"],
                                   public_key=d["public_key"], label=d["label"], model_name=d["model"],
                                   os_version=d["os_version"])
        return Response({"device_id": str(device.pk), "clinic_name": lic.clinic_name,
                         "key_storage": device.key_storage}, status=201)


class ChallengeView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [ClientScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        device_id = str(request.data.get("device_id", ""))[:40]
        if not device_id:
            return Response({"error": {"code": "validation_error", "message": "device_id is required."}}, status=400)
        return Response({"nonce": services.new_challenge(device_id), "expires_in": services.CHALLENGE_SECONDS})


class DeviceSerializer(serializers.ModelSerializer):
    for_user = serializers.SerializerMethodField()
    last_user = serializers.SerializerMethodField()
    revoked_by = serializers.SerializerMethodField()

    class Meta:
        model = MobileDevice
        fields = ["id", "label", "model_name", "os_version", "key_storage", "boot_state", "status", "activated_at",
                  "last_seen_at", "for_user", "last_user", "revoked_at", "revoked_by", "revoke_reason"]

    @staticmethod
    def _person(u):
        return None if u is None else {"id": str(u.pk), "username": u.username, "full_name": u.full_name}

    def get_for_user(self, obj):
        return self._person(obj.for_user)

    def get_last_user(self, obj):
        return self._person(obj.last_user)

    def get_revoked_by(self, obj):
        return self._person(obj.revoked_by)


class DeviceListView(PermissionedView):
    required_permissions = {"GET": ("devices.manage",)}

    def get(self, request):
        qs = MobileDevice.objects.select_related("for_user", "last_user", "revoked_by")
        status = request.query_params.get("status")
        if status in ("active", "revoked"):
            qs = qs.filter(status=status)
        return self.paginate(qs.order_by("status", "-activated_at"), DeviceSerializer)


class DeviceRevokeView(PermissionedView):
    required_permissions = {"POST": ("devices.manage",)}

    def post(self, request, pk):
        device = MobileDevice.objects.filter(pk=pk).first()
        if device is None:
            return Response({"error": {"code": "not_found", "message": "No such phone."}}, status=404)
        reason = str(request.data.get("reason", "")).strip()
        if not reason:
            return Response({"error": {"code": "validation_error", "message": "Give a reason.",
                                       "fields": {"reason": ["Give a reason."]}}}, status=400)
        services.revoke(self.ctx(), device, reason)
        return Response(DeviceSerializer(device).data)


class CodeInput(serializers.Serializer):
    label = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    for_user = serializers.UUIDField(required=False, allow_null=True, default=None)


class ActivationCodeView(PermissionedView):
    required_permissions = {"POST": ("devices.manage",)}

    def post(self, request):
        s = CodeInput(data=request.data)
        s.is_valid(raise_exception=True)
        user = None
        if s.validated_data["for_user"]:
            user = get_user_model().objects.filter(pk=s.validated_data["for_user"], is_active=True).first()
            if user is None:
                return Response({"error": {"code": "validation_error", "message": "Choose an active staff account.",
                                           "fields": {"for_user": ["Not an active account."]}}}, status=400)
        result = services.create_activation_code(self.ctx(), label=s.validated_data["label"], for_user=user)
        result["qr_svg"] = segno.make(result["qr"], error="m").svg_inline(scale=4, border=2, dark="#111", light="#fff")
        return Response(result, status=201)


class LicenceView(PermissionedView):
    required_permissions = {"GET": AnyOf(("devices.manage", "system.security.manage")),
                            "POST": ("system.security.manage",)}

    def get(self, request):
        return Response(services.licence_status())

    def post(self, request):
        return Response(services.install_licence(self.ctx(), str(request.data.get("licence", ""))))


urlpatterns = [
    path("mobile/licence/", PublicLicenceView.as_view(), name="mobile-licence"),
    path("mobile/activate/", ActivateView.as_view(), name="mobile-activate"),
    path("auth/app/challenge/", ChallengeView.as_view(), name="app-challenge"),
    path("devices/", DeviceListView.as_view(), name="devices"),
    path("devices/<uuid:pk>/revoke/", DeviceRevokeView.as_view(), name="device-revoke"),
    path("devices/activation-codes/", ActivationCodeView.as_view(), name="device-activation-codes"),
    path("devices/licence/", LicenceView.as_view(), name="devices-licence"),
]
