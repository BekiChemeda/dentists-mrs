"""
Server-side authorisation.

Every API view either relies on the default (authenticated + no pending password change)
or declares `required_permissions`, a mapping of HTTP method -> permission codes.
A method missing from the mapping is denied: the check fails closed.
"""

from rest_framework.permissions import BasePermission

from .exceptions import MfaSetupRequired, ModuleSwitchedOff, PasswordChangeRequired


class AnyOf(tuple):
    """Use in `required_permissions` when holding any one of the codes is enough."""


class IsAuthenticatedWithCurrentPassword(BasePermission):
    def has_permission(self, request, view) -> bool:
        user = request.user
        if not (user and user.is_authenticated and user.is_active):
            return False
        pending_ok = getattr(view, "allow_pending_password_change", False)
        if user.must_change_password and not pending_ok:
            raise PasswordChangeRequired()
        if not (pending_ok or getattr(view, "allow_pending_mfa_setup", False)):
            from apps.accounts.services import mfa_setup_required

            if mfa_setup_required(user):
                raise MfaSetupRequired()
        return True


class HasRequiredPermissions(IsAuthenticatedWithCurrentPassword):
    def has_permission(self, request, view) -> bool:
        if not super().has_permission(request, view):
            return False
        required = getattr(view, "required_permissions", None)
        if not isinstance(required, dict):
            return False
        method = "GET" if request.method == "HEAD" else request.method
        if method == "OPTIONS":
            return True
        codes = required.get(method)
        if codes is None:
            return False
        allowed = (any(request.user.has_permissions([code]) for code in codes) if isinstance(codes, AnyOf)
                   else request.user.has_permissions(codes))
        if not allowed and codes:
            _explain_switched_off(request.user, codes)
        return allowed


def _explain_switched_off(user, codes) -> None:
    """If the person's roles would allow this and only a switched-off module stops it, say so."""
    from apps.core.modules import disabled_modules, module_for_permission

    off = disabled_modules()
    if not off:
        return
    granted = user.role_permission_codes
    ok_by_roles = (any(c in granted for c in codes) if isinstance(codes, AnyOf) else set(codes) <= granted)
    if not ok_by_roles:
        return
    for code in codes:
        module = module_for_permission(code, off)
        if module and code in granted:
            raise ModuleSwitchedOff(f"The {module.name} module is switched off for this clinic.")
