"""
Security policy values, read from SystemSettings with the environment as the fallback and floor.

Kept small and dependency-free so accounts, middleware and validators can all use it.
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import DatabaseError

# Allowed ranges for values a system administrator can set.
LIMITS = {
    "password_min_length": (8, 64),
    "login_max_failures": (3, 20),
    "login_lockout_minutes": (1, 1440),
    "session_idle_minutes": (5, 720),
}


def current():
    from .models import SystemSettings

    try:
        return SystemSettings.get()
    except DatabaseError:  # e.g. before migrations have run
        return None


def password_min_length() -> int:
    obj = current()
    value = obj.password_min_length if obj else settings.PASSWORD_MIN_LENGTH
    return max(value, settings.PASSWORD_MIN_LENGTH)


def login_max_failures() -> int:
    obj = current()
    return obj.login_max_failures if obj else settings.LOGIN_MAX_FAILURES


def login_lockout_minutes() -> int:
    obj = current()
    return obj.login_lockout_minutes if obj else settings.LOGIN_LOCKOUT_MINUTES


def session_idle_minutes() -> int:
    obj = current()
    return obj.session_idle_minutes if obj else settings.SESSION_IDLE_TIMEOUT_MINUTES


class PolicyMinimumLengthValidator:
    """Applies the administrator's password length when it is stricter than PASSWORD_MIN_LENGTH."""

    def validate(self, password, user=None):
        minimum = password_min_length()
        if len(password) < minimum:
            raise ValidationError(f"This password is too short. It must contain at least {minimum} characters.",
                                  code="password_too_short")

    def get_help_text(self):
        return f"Your password must contain at least {password_min_length()} characters."
