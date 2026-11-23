"""
Sign-in for the Android app.

The web pages use a session cookie. The app talks to the server from outside the browser, so it signs
in once and then sends `Authorization: Bearer <token>` on every request. Each app sign-in is an ordinary
UserSession row (marked "App: <device>"), so everything that already applies to sessions applies to the
app too: the idle timeout and absolute lifetime, "Sign out everywhere", ending sessions on password
change or deactivation, and the list of a person's sessions. Only a hash of the token is stored; a
stolen database copy cannot be used to sign in. No cookie is involved, so CSRF does not apply.

When MOBILE_ACTIVATION_REQUIRED is on (the default), sign-in is only possible from a phone activated
for this clinic (apps/devices): the phone signs a one-time challenge with its hardware key, and the
clinic's licence must include the app. The token is then tied to that phone; switching the phone off
or the licence ending stops it at once.
"""
from __future__ import annotations

import hashlib

from django.conf import settings
from django.core.cache import cache

from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.context import ActorContext
from apps.core.throttling import ClientScopedRateThrottle

from . import services
from .models import UserSession
from .serializers import CurrentUserSerializer

from .app_token import AppTokenAuthentication, issue_token


class AppLoginInput(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=128, trim_whitespace=False)
    device = serializers.CharField(max_length=80, required=False, allow_blank=True)
    # Proof from an activated phone (apps/devices): its ID, a fresh challenge and the signature of it.
    device_id = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")
    nonce = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    signature = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


def _proven_device(data):
    """Checked before the password, so only activated phones of a licensed clinic can even try one."""
    if not settings.MOBILE_ACTIVATION_REQUIRED:
        return None
    from apps.devices import services as devices

    devices.require_app_licence()
    return devices.verify_sign_in(device_id=str(data.get("device_id", ""))[:40], nonce=str(data.get("nonce", ""))[:64],
                                  signature=str(data.get("signature", ""))[:200])


def _mfa_key(mfa_token: str) -> str:
    return "devices:mfa:" + hashlib.sha256(mfa_token.encode()).hexdigest()


def _signed_in(ctx, user, device: str, mobile_device=None) -> Response:
    if mobile_device is not None:
        from apps.devices.services import note_sign_in

        note_sign_in(mobile_device, user)
    token = issue_token(ctx, user, device, mobile_device)
    return Response({"token": token, "user": CurrentUserSerializer(user).data}, status=status.HTTP_200_OK)


class AppLoginView(APIView):
    """POST {username, password, device}: a token, or {mfa_required, mfa_token} for the second step."""

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [ClientScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        s = AppLoginInput(data=request.data)
        s.is_valid(raise_exception=True)
        ctx = ActorContext.from_request(request)
        mobile_device = _proven_device(s.validated_data)
        user = services.verify_credentials(ctx, s.validated_data["username"], s.validated_data["password"])
        if user.mfa_enabled:
            mfa_token = services.mfa_login_token(user)
            if mobile_device is not None:
                cache.set(_mfa_key(mfa_token), str(mobile_device.pk), 600)
            return Response({"mfa_required": True, "mfa_token": mfa_token})
        return _signed_in(ctx, user, s.validated_data.get("device", ""), mobile_device)


class AppLoginMfaView(APIView):
    """POST {mfa_token, code, device}: finish sign-in with the authenticator code or a recovery code."""

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [ClientScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        ctx = ActorContext.from_request(request)
        mfa_token = str(request.data.get("mfa_token", ""))[:500]
        mobile_device = None
        if settings.MOBILE_ACTIVATION_REQUIRED:
            from apps.devices.models import MobileDevice
            from apps.devices.services import DeviceNotActivated

            device_id = cache.get(_mfa_key(mfa_token))
            mobile_device = MobileDevice.objects.filter(pk=device_id, status="active").first() if device_id else None
            if mobile_device is None:
                raise DeviceNotActivated("Sign in again from an activated phone.")
        user = services.complete_mfa_login(ctx, mfa_token, str(request.data.get("code", ""))[:40])
        cache.delete(_mfa_key(mfa_token))
        return _signed_in(ctx, user, str(request.data.get("device", ""))[:80], mobile_device)


class AppLogoutView(APIView):
    """POST: end this app sign-in."""

    authentication_classes = [AppTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        session = getattr(request._request, "user_session", None)
        if session is not None:
            services.end_session(ActorContext.from_request(request), session.session_key, UserSession.EndReason.LOGOUT)
        return Response(status=status.HTTP_204_NO_CONTENT)
