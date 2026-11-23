"""
Request-independent description of *who* is acting and *from where*.

Services receive an ActorContext instead of an HTTP request, which keeps business logic
separate from HTTP handlers and lets the same services run from management commands.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apps.accounts.models import User

current_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


@dataclass(frozen=True)
class ActorContext:
    user: User | None
    ip_address: str | None = None
    user_agent: str = ""
    request_id: str = "-"

    @classmethod
    def system(cls, label: str = "system") -> ActorContext:
        return cls(user=None, user_agent=label, request_id=current_request_id.get())

    @classmethod
    def from_request(cls, request: Any) -> ActorContext:
        user = getattr(request, "user", None)
        if user is not None and not user.is_authenticated:
            user = None
        return cls(
            user=user,
            ip_address=client_ip(request),
            user_agent=(request.META.get("HTTP_USER_AGENT", "") or "")[:255],
            request_id=getattr(request, "request_id", current_request_id.get()),
        )


def client_ip(request: Any) -> str | None:
    """
    Nginx is the only entry point and sets X-Real-IP; the API container is not reachable
    from the LAN, so this header cannot be forged by clients.
    """
    meta = request.META
    return meta.get("HTTP_X_REAL_IP") or meta.get("REMOTE_ADDR") or None
