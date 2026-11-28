"""
Domain errors and the single JSON error format used by every endpoint:

    {"error": {"code": "...", "message": "...", "fields": {...}, "request_id": "..."}}
"""

import logging

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.db import InterfaceError, OperationalError, connection
from django.http import Http404
from rest_framework import exceptions as drf_exceptions
from rest_framework import status
from rest_framework.response import Response

from .context import current_request_id

logger = logging.getLogger(__name__)


class DomainError(Exception):
    """Base class for business-rule violations raised by services."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "domain_error"

    def __init__(self, message: str, *, fields: dict | None = None, extra: dict | None = None):
        super().__init__(message)
        self.message = message
        self.fields = fields or {}
        self.extra = extra or {}


class BusinessValidationError(DomainError):
    code = "validation_error"


class ConflictError(DomainError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class PermissionDeniedError(DomainError):
    """A rule that depends on the record, not only on the caller's permissions (e.g. staff scope)."""

    status_code = status.HTTP_403_FORBIDDEN
    code = "permission_denied"


class AccountLocked(DomainError):
    status_code = status.HTTP_423_LOCKED
    code = "account_locked"


class ModuleSwitchedOff(drf_exceptions.PermissionDenied):
    """The person's roles allow this, but the clinic has switched the module off."""


class PasswordChangeRequired(drf_exceptions.PermissionDenied):
    default_code = "password_change_required"
    default_detail = "You must change your temporary password before continuing."


class MfaSetupRequired(drf_exceptions.PermissionDenied):
    default_code = "mfa_setup_required"
    default_detail = "Set up two-step sign-in before continuing."


def _body(code: str, message: str, fields: dict | None = None, extra: dict | None = None) -> dict:
    error = {"code": code, "message": message, "request_id": current_request_id.get()}
    if fields:
        error["fields"] = fields
    if extra:
        error.update(extra)
    return {"error": error}


def _flatten_fields(detail) -> dict:
    if isinstance(detail, dict):
        return {key: _flatten_list(value) for key, value in detail.items()}
    return {"non_field_errors": _flatten_list(detail)}


def _flatten_list(value) -> list[str]:
    if isinstance(value, list):
        out: list[str] = []
        # A list of rows (e.g. prescription lines): say which row each message is about.
        rows = len(value) > 0 and all(isinstance(item, dict) for item in value)
        for i, item in enumerate(value):
            out.extend(f"line {i + 1}, {m}" if rows else m for m in _flatten_list(item))
        return out
    if isinstance(value, dict):
        return [f"{k}: {msg}" for k, v in value.items() for msg in _flatten_list(v)]
    return [str(value)]


DATABASE_DOWN_MESSAGE = ("The database is not responding, so this was not saved or loaded. "
                         "Wait a minute and try again; if it keeps happening, call the system administrator.")


def database_is_down(exc: BaseException | None) -> bool:
    """True when exc means PostgreSQL cannot be reached (stopped, crashed, restarting), as opposed to an
    ordinary database error such as a lock timeout. Checked by trying to reconnect once."""
    if not isinstance(exc, (OperationalError, InterfaceError)):
        return False
    text = str(exc).lower()
    if any(m in text for m in ("starting up", "shutting down", "in recovery mode", "connection refused",
                               "could not connect", "server closed the connection")):
        return True
    try:
        connection.close()
        connection.ensure_connection()
    except Exception:
        return True
    return False


def database_down_response() -> Response:
    return Response(_body("database_unavailable", DATABASE_DOWN_MESSAGE),
                    status=status.HTTP_503_SERVICE_UNAVAILABLE, headers={"Retry-After": "30"})


def api_exception_handler(exc, context):
    request = context.get("request")

    if database_is_down(exc):
        # Not recorded in the error log: that log lives in the database that is down.
        logger.error("Database unavailable: %s", exc)
        return database_down_response()

    if isinstance(exc, PermissionDeniedError):
        _record_denied_access(request, reason=exc.message)
    if isinstance(exc, DomainError):
        return Response(_body(exc.code, exc.message, exc.fields, exc.extra), status=exc.status_code)

    if isinstance(exc, Http404):
        exc = drf_exceptions.NotFound()
    elif isinstance(exc, DjangoPermissionDenied):
        exc = drf_exceptions.PermissionDenied()

    if isinstance(exc, drf_exceptions.ValidationError):
        return Response(
            _body("validation_error", "Invalid input.", _flatten_fields(exc.detail)),
            status=status.HTTP_400_BAD_REQUEST,
        )

    if isinstance(exc, (drf_exceptions.NotAuthenticated, drf_exceptions.AuthenticationFailed)):
        return Response(
            _body("not_authenticated", "Please sign in to continue."),
            status=status.HTTP_401_UNAUTHORIZED,
        )

    if isinstance(exc, MfaSetupRequired):
        return Response(_body("mfa_setup_required", str(exc.detail)), status=status.HTTP_403_FORBIDDEN)

    if isinstance(exc, PasswordChangeRequired):
        return Response(_body("password_change_required", str(exc.detail)), status=status.HTTP_403_FORBIDDEN)

    if isinstance(exc, ModuleSwitchedOff):
        return Response(_body("module_switched_off", str(exc.detail)), status=status.HTTP_403_FORBIDDEN)

    if isinstance(exc, drf_exceptions.PermissionDenied):
        detail = str(exc.detail)
        if detail.startswith("CSRF Failed"):
            return Response(
                _body("csrf_failed", "Security token missing or invalid. Reload the page and try again."),
                status=status.HTTP_403_FORBIDDEN,
            )
        _record_denied_access(request)
        return Response(
            _body("permission_denied", "You do not have permission to perform this action."),
            status=status.HTTP_403_FORBIDDEN,
        )

    if isinstance(exc, drf_exceptions.Throttled):
        return Response(
            _body("throttled", "Too many requests. Please wait and try again."),
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    if isinstance(exc, drf_exceptions.APIException):
        code = exc.get_codes() if isinstance(exc.get_codes(), str) else "error"
        return Response(_body(code, str(exc.detail)), status=exc.status_code)

    # Unexpected error: log full details server-side, return a generic message.
    logger.exception("Unhandled API error")
    record_error(request, exc)
    return Response(
        _body("server_error", "An unexpected error occurred. Quote the request ID when reporting it."),
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def _record_denied_access(request, reason: str = "") -> None:
    if request is None or not getattr(request, "user", None) or not request.user.is_authenticated:
        return
    from apps.audit.services import record_event
    from .context import ActorContext

    try:
        record_event(
            ActorContext.from_request(request),
            action="access.denied",
            outcome="denied",
            details={"method": request.method, "path": request.path[:255], **({"reason": reason} if reason else {})},
        )
    except Exception:  # never let audit failure mask the original 403
        logger.exception("Failed to record access.denied audit event")


def record_error(request, exc) -> None:
    """Keep a short record of an unexpected error for the system health page. Never raises."""
    try:
        from .models import ErrorEvent

        user = getattr(request, "user", None) if request is not None else None
        ErrorEvent.objects.create(
            request_id=current_request_id.get() or "",
            method=(getattr(request, "method", "") or "")[:10],
            path=(getattr(request, "path", "") or "")[:255],
            exception_type=f"{type(exc).__module__}.{type(exc).__qualname__}"[:150],
            # The message can contain data values, so only its first line, truncated, is kept.
            message=str(exc).splitlines()[0][:255] if str(exc) else "",
            user_id=user.pk if user is not None and user.is_authenticated else None,
        )
    except Exception:  # noqa: BLE001 - recording must never mask the original error
        logger.warning("Could not record error event", exc_info=True)
