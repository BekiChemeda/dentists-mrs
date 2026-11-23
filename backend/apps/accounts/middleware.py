from datetime import timedelta

from django.contrib.auth import logout
from django.utils import timezone

from apps.core.policy import session_idle_minutes

from .models import UserSession
from .services import touch_session


class SessionTrackingMiddleware:
    """
    Enforces session revocation, the idle timeout and the absolute session lifetime.

    It ends a session after the idle time set in the security policy, when an administrator
    revoked it, when the account was deactivated, or when it is older than
    SESSION_ABSOLUTE_TIMEOUT_HOURS, even if it was used continuously.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            key = request.session.session_key
            tracked = UserSession.objects.filter(session_key=key).first() if key else None
            now = timezone.now()
            if tracked is None or not tracked.is_active:
                logout(request)
            elif now >= tracked.absolute_expiry() or (
                now - tracked.last_seen_at > timedelta(minutes=session_idle_minutes())
            ):
                UserSession.objects.filter(pk=tracked.pk).update(
                    ended_at=now, end_reason=UserSession.EndReason.EXPIRED
                )
                logout(request)
            else:
                touch_session(tracked)
                request.user_session = tracked
        return self.get_response(request)
