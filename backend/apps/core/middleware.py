import re
import uuid

import sys

from django.core.signals import got_request_exception
from django.dispatch import receiver
from django.http import JsonResponse

from .context import current_request_id

_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")


class RequestIdMiddleware:
    """Tags every request with an ID that appears in logs, audit events, errors and the response."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.META.get("HTTP_X_REQUEST_ID", "")
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        request.request_id = request_id
        token = current_request_id.set(request_id)
        try:
            response = self.get_response(request)
        finally:
            current_request_id.reset(token)
        response["X-Request-ID"] = request_id
        return response


# Paths that keep working in maintenance mode, so people can sign in and out and the
# system administrator can switch maintenance off again.
_MAINTENANCE_OPEN = ("/api/v1/health/", "/api/v1/auth/", "/api/v1/system/")


class MaintenanceModeMiddleware:
    """While maintenance mode is on, only holders of system.security.manage can use the API."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if path.startswith("/api/") and not path.startswith(_MAINTENANCE_OPEN):
            from .policy import current

            obj = current()
            if obj is not None and obj.maintenance_mode:
                user = getattr(request, "user", None)
                allowed = user is not None and user.is_authenticated and user.has_permissions(["system.security.manage"])
                if not allowed:
                    return JsonResponse({"error": {
                        "code": "maintenance",
                        "message": obj.maintenance_message or "The system is under maintenance. Please try again later.",
                        "request_id": current_request_id.get(),
                    }}, status=503)
        return self.get_response(request)


@receiver(got_request_exception)
def _remember_exception(sender, request=None, **kwargs):
    """Keep the exception on the request so ApiErrorMiddleware can tell a database outage from a bug."""
    if request is not None:
        request._mrs_exception = sys.exc_info()[1]


class ApiErrorMiddleware:
    """
    Errors raised outside a view (for example in the session or sign-in middleware when the database is
    down) would otherwise come back as Django's HTML error page. For /api/ requests this turns them into
    the usual JSON error body, with 503 database_unavailable when PostgreSQL cannot be reached, so the
    screens can show a clear message instead of a blank page.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if (request.path.startswith("/api/") and response.status_code >= 500
                and "json" not in response.get("Content-Type", "")):
            from .exceptions import DATABASE_DOWN_MESSAGE, database_is_down

            request_id = getattr(request, "request_id", "")
            if database_is_down(getattr(request, "_mrs_exception", None)):
                out = JsonResponse({"error": {"code": "database_unavailable", "message": DATABASE_DOWN_MESSAGE,
                                              "request_id": request_id}}, status=503)
                out["Retry-After"] = "30"
                return out
            return JsonResponse({"error": {"code": "server_error", "request_id": request_id,
                                           "message": "An unexpected error occurred. Quote the request ID when reporting it."}},
                                status=500)
        return response
