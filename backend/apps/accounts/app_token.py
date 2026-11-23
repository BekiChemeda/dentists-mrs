"""Bearer tokens for the Android app (see app_auth.py). Kept free of view imports: DRF loads this module
while building its settings, before its own views module has finished importing."""
from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.utils import timezone
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication

TOKEN_PREFIX = "mrsapp_"


def _key(token: str) -> str:
    # UserSession.session_key holds 40 characters: "app:" + 36 hex digits (144 bits) of the SHA-256.
    return "app:" + hashlib.sha256(token.encode()).hexdigest()[:36]


def issue_token(ctx: ActorContext, user, device: str, mobile_device=None) -> str:
    from .models import UserSession

    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    UserSession.objects.create(user=user, session_key=_key(token), ip_address=ctx.ip_address,
                               user_agent=f"App: {device or 'Android'}"[:255], device=mobile_device)
    return token


class AppTokenAuthentication(BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if not header.startswith(f"{self.keyword} "):
            return None
        token = header[len(self.keyword) + 1:].strip()
        if not token.startswith(TOKEN_PREFIX) or len(token) > 100:
            raise exceptions.AuthenticationFailed("Please sign in again.")
        from apps.core.policy import session_idle_minutes

        from .models import UserSession

        session = UserSession.objects.select_related("user", "device").filter(session_key=_key(token)).first()
        now = timezone.now()
        if session is None or not session.is_active or not session.user.is_active:
            raise exceptions.AuthenticationFailed("Please sign in again.")
        from django.conf import settings

        from apps.devices.services import app_licence_ok

        # The phone must still be activated and the clinic's app licence still valid.
        if session.device is not None:
            if not session.device.is_active:
                raise exceptions.AuthenticationFailed("This phone has been switched off for the app.")
            if not app_licence_ok():
                raise exceptions.AuthenticationFailed("The phone app licence for this clinic is not valid.")
        elif settings.MOBILE_ACTIVATION_REQUIRED:
            raise exceptions.AuthenticationFailed("Activate this phone before signing in.")
        if now >= session.absolute_expiry() or now - session.last_seen_at > timedelta(minutes=session_idle_minutes()):
            UserSession.objects.filter(pk=session.pk, ended_at__isnull=True).update(
                ended_at=now, end_reason=UserSession.EndReason.EXPIRED)
            raise exceptions.AuthenticationFailed("You were signed out after a period without use. Sign in again.")
        from .services import touch_session

        touch_session(session)
        request._request.user_session = session
        return session.user, session

    def authenticate_header(self, request):
        return self.keyword  # makes DRF answer 401, not 403, when the token is missing or ended


