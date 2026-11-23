"""
Django settings for the Clinic Medical Records System.

All deployment-specific values come from environment variables (see ../../.env.example).
Nothing secret is hard-coded. Production mode is the default: DEBUG must be enabled
explicitly for development.
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name: str, default: str | None = None, *, required: bool = False) -> str:
    value = os.environ.get(name, default)
    if required and not value:
        raise ImproperlyConfigured(f"Environment variable {name} is required.")
    return value or ""


def env_bool(name: str, default: bool = False) -> bool:
    return env(name, "true" if default else "false").strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    try:
        return int(env(name, str(default)))
    except ValueError as exc:
        raise ImproperlyConfigured(f"Environment variable {name} must be an integer.") from exc


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = env("DJANGO_SECRET_KEY", required=not DEBUG)
if DEBUG and not SECRET_KEY:
    SECRET_KEY = "dev-only-insecure-key-do-not-use-in-production"
if not DEBUG and len(SECRET_KEY) < 50:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be at least 50 characters in production.")

# Loopback is always allowed so the container health check works.
ALLOWED_HOSTS = sorted(set(env_list("DJANGO_ALLOWED_HOSTS", "")) | {"localhost", "127.0.0.1"})
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.postgres",
    "rest_framework",
    "apps.core",
    "apps.audit",
    "apps.accounts",
    "apps.notifications",
    "apps.approvals",
    "apps.patients",
    "apps.scheduling",
    "apps.inventory",
    "apps.clinical",
    "apps.laboratory",
    "apps.pharmacy",
    "apps.billing",
    "apps.reports",
    "apps.devices",
    "apps.payments",
    "apps.dental",
]

MIDDLEWARE = [
    "apps.core.middleware.RequestIdMiddleware",
    "apps.core.middleware.ApiErrorMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.accounts.middleware.SessionTrackingMiddleware",
    "apps.core.middleware.MaintenanceModeMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
    }
]

# ---------------------------------------------------------------------------
# Database (PostgreSQL only: the schema relies on PostgreSQL triggers and constraints)
# ---------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "mrs"),
        "USER": env("POSTGRES_USER", "mrs"),
        "PASSWORD": env("POSTGRES_PASSWORD", required=not DEBUG),
        "HOST": env("POSTGRES_HOST", "localhost"),
        "PORT": env("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": env_int("POSTGRES_CONN_MAX_AGE", 60),
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {"connect_timeout": 5},
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": env_int("PASSWORD_MIN_LENGTH", 10)},
    },
    {"NAME": "apps.core.policy.PolicyMinimumLengthValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Account lockout: LOGIN_MAX_FAILURES consecutive failures lock the account for LOGIN_LOCKOUT_MINUTES.
PASSWORD_MIN_LENGTH = env_int("PASSWORD_MIN_LENGTH", 10)
# Two-step sign-in. The policy is changed in the System page; this is only the value for a new install.
MFA_DEFAULT_POLICY = env("MFA_DEFAULT_POLICY", "admins")
# Optional separate key for encrypting authenticator secrets (default: derived from DJANGO_SECRET_KEY).
MFA_ENCRYPTION_KEY = env("MFA_ENCRYPTION_KEY", "")
LOGIN_MAX_FAILURES = env_int("LOGIN_MAX_FAILURES", 5)
LOGIN_LOCKOUT_MINUTES = env_int("LOGIN_LOCKOUT_MINUTES", 15)

# ---------------------------------------------------------------------------
# Sessions and cookies
# ---------------------------------------------------------------------------
HTTPS_ENABLED = env_bool("MRS_HTTPS", not DEBUG)

SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_NAME = "mrs_session"
SESSION_IDLE_TIMEOUT_MINUTES = env_int("SESSION_IDLE_TIMEOUT_MINUTES", 30)
SESSION_ABSOLUTE_TIMEOUT_HOURS = env_int("SESSION_ABSOLUTE_TIMEOUT_HOURS", 12)
# The idle timeout is enforced by SessionTrackingMiddleware from the security policy (System
# settings), so the cookie itself only needs to outlive the absolute limit.
SESSION_COOKIE_AGE = SESSION_ABSOLUTE_TIMEOUT_HOURS * 3600
SESSION_SAVE_EVERY_REQUEST = True  # sliding idle timeout
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = HTTPS_ENABLED

CSRF_COOKIE_NAME = "mrs_csrftoken"
CSRF_COOKIE_HTTPONLY = False  # the SPA must read it to send X-CSRFToken
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = HTTPS_ENABLED
CSRF_FAILURE_VIEW = "apps.core.views.csrf_failure"

# ---------------------------------------------------------------------------
# Security headers (Nginx adds CSP; see deploy/nginx)
# ---------------------------------------------------------------------------
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
if HTTPS_ENABLED:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 31536000)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
# Redirects are handled by Nginx, not Django, so health checks over HTTP keep working.
SECURE_SSL_REDIRECT = False

# ---------------------------------------------------------------------------
# REST framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication",
                                       "apps.accounts.app_token.AppTokenAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["apps.core.permissions.IsAuthenticatedWithCurrentPassword"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.StandardPagination",
    "PAGE_SIZE": 25,
    "EXCEPTION_HANDLER": "apps.core.exceptions.api_exception_handler",
    # A generous per-user ceiling that stops scripted bulk downloading with a stolen session.
    "DEFAULT_THROTTLE_CLASSES": ["apps.core.throttling.ClientUserRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {
        "login": env("LOGIN_THROTTLE_RATE", "20/min"),
        "sensitive": env("SENSITIVE_THROTTLE_RATE", "10/min"),
        "user": env("USER_THROTTLE_RATE", "600/min"),
    },
    "UNAUTHENTICATED_USER": "django.contrib.auth.models.AnonymousUser",
}

# --- Android app: clinic licence and phone activation (apps/devices) ---
# Supplier public keys (base64 Ed25519) that sign clinic licences. Public, not secret.
MRS_VENDOR_PUBLIC_KEYS = env_list("MRS_VENDOR_PUBLIC_KEYS")
# Every app sign-in must come from a phone activated with a one-time code. Off only for old test set-ups.
MOBILE_ACTIVATION_REQUIRED = env_bool("MOBILE_ACTIVATION_REQUIRED", True)
# Phones must prove their key is in security hardware. Turn off only on development servers (emulators).
MOBILE_REQUIRE_HARDWARE_KEY = env_bool("MOBILE_REQUIRE_HARDWARE_KEY", True)
MOBILE_APP_PACKAGE = env("MOBILE_APP_PACKAGE", "et.clinicmrs.clinic_mrs")
# SHA-256 of the supplier's app signing certificate(s); when set, re-signed copies of the app are refused.
MOBILE_APP_SIGNATURE_SHA256 = env_list("MOBILE_APP_SIGNATURE_SHA256")
# Payments by phone (apps/payments): requests to Chapa/telebirr go through the egress relay container.
PAYMENTS_EGRESS_PROXY = env("PAYMENTS_EGRESS_PROXY", "")
# SHA-256 of this server's HTTPS certificate, put in the activation QR so phones trust it without asking.
MOBILE_TLS_CERT_SHA256 = env("MOBILE_TLS_CERT_SHA256", "")

# Shared by every Gunicorn worker and kept across restarts, so request limits (sign-in attempts per
# minute and so on) count all of a person's requests, not only those that reached one worker.
# The table is created by migration core 0012.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.db.DatabaseCache", "LOCATION": "core_cache"}}

# ---------------------------------------------------------------------------
# Internationalisation: English now; Amharic and Afaan Oromo planned.
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en"
LANGUAGES = [("en", "English"), ("am", "Amharic"), ("om", "Afaan Oromo")]
TIME_ZONE = "Africa/Addis_Ababa"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Where deploy/scripts/backup.sh writes dumps; read by the system health page.
BACKUP_DIR = env("BACKUP_DIR", "")

# Dental image files (ADR 0007). Production: a host directory mounted into the api container only.
DENTAL_IMAGE_ROOT = Path(env("DENTAL_IMAGE_ROOT", str(BASE_DIR / "var" / "dental-images")))
DENTAL_IMAGE_MAX_BYTES = env_int("DENTAL_IMAGE_MAX_BYTES", 25 * 1024 * 1024)
MRS_VERSION = env("MRS_VERSION", "")

MRS_FACILITY_CODE = env("MRS_FACILITY_CODE", "CLN")
MRS_CLINIC_NAME = env("MRS_CLINIC_NAME", "Clinic")
# When true, a lab result must be verified by a different technician from the one who entered it.
LAB_REQUIRE_SECOND_VERIFIER = env_bool("LAB_REQUIRE_SECOND_VERIFIER", False)

# ---------------------------------------------------------------------------
# Logging: structured single-line logs to stdout, collected by Docker.
# ---------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"request_id": {"()": "apps.core.logging.RequestIdFilter"}},
    "formatters": {
        "default": {
            "format": "%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s %(message)s",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "filters": ["request_id"],
        }
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}
