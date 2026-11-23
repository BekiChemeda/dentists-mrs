"""
Request limits keyed by the real client address.

The API sits behind nginx, so REMOTE_ADDR is always nginx's own container address. DRF's default
identification would then put every computer in the clinic into one bucket: twenty staff signing in at
the start of a shift would lock each other out. nginx sets X-Real-IP to the connecting computer's
address (overwriting any value a browser sends), and the API is not reachable except through nginx.
"""
from rest_framework.throttling import ScopedRateThrottle, UserRateThrottle

from .context import client_ip


class _ClientAddressMixin:
    def get_ident(self, request):
        return client_ip(request) or super().get_ident(request)


class ClientScopedRateThrottle(_ClientAddressMixin, ScopedRateThrottle):
    """Per-scope limit (sign-in, password changes) per signed-in user, or per computer before sign-in."""


class ClientUserRateThrottle(_ClientAddressMixin, UserRateThrottle):
    """Overall request limit per signed-in user, or per computer for anonymous requests."""
