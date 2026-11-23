import logging

from django.db import connection
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .context import current_request_id

logger = logging.getLogger(__name__)


class HealthView(APIView):
    """Liveness and database check, used by Docker health checks and monitoring."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except Exception:
            logger.exception("Health check: database unavailable")
            return Response({"status": "error", "database": "unavailable"}, status=503)
        return Response({"status": "ok", "database": "ok"})


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfView(APIView):
    """Sets the CSRF cookie so the single-page app can send X-CSRFToken on writes."""

    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"detail": "CSRF cookie set."})


def csrf_failure(request, reason=""):
    """Django-level CSRF failures (outside DRF) use the same error format."""
    return JsonResponse(
        {
            "error": {
                "code": "csrf_failed",
                "message": "Security token missing or invalid. Reload the page and try again.",
                "request_id": current_request_id.get(),
            }
        },
        status=403,
    )
