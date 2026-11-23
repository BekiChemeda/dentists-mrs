"""
System administration endpoints: health, error log, security policy and maintenance mode.

These are for the system administrator. They expose server facts only: no patient records,
money or clinic configuration. Backup *restore* is deliberately not offered here; it stays a
command-line procedure (docs/operations/restore.md) so it cannot be triggered from a browser.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import time
from datetime import timedelta
from pathlib import Path

import django
from django.conf import settings
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.urls import path
from django.utils import timezone
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.services import record_event

from . import policy
from .api import PermissionedView, validated
from . import offsite
from .models import ErrorEvent, OffsiteBackupRun, SystemSettings
from .permissions import AnyOf, IsAuthenticatedWithCurrentPassword
from .concurrency import check_version, expected_version

_PROCESS_STARTED = time.time()


# ---------------------------------------------------------------------------
# Readers (each returns None/"unknown" rather than failing the whole page)
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)

def _disk(path_str: str):
    try:
        usage = shutil.disk_usage(path_str)
    except OSError:
        return None
    return {"path": path_str, "total": usage.total, "used": usage.used, "free": usage.free,
            # total - free, not `used`: filesystems reserve blocks that are neither, and those are not available to us.
            "percent_used": round((usage.total - usage.free) * 100 / usage.total, 1) if usage.total else None}


def _memory():
    try:
        info = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            info[key] = int(rest.strip().split()[0]) * 1024
        total, available = info["MemTotal"], info.get("MemAvailable", info.get("MemFree", 0))
        return {"total": total, "available": available, "percent_used": round((total - available) * 100 / total, 1)}
    except (OSError, KeyError, ValueError, ZeroDivisionError):
        return None


def _load():
    try:
        one, five, fifteen = os.getloadavg()
        return {"1m": round(one, 2), "5m": round(five, 2), "15m": round(fifteen, 2), "cpus": os.cpu_count()}
    except OSError:
        return None


def _host_uptime_seconds():
    try:
        return int(float(Path("/proc/uptime").read_text().split()[0]))
    except (OSError, ValueError, IndexError):
        return None


def _database():
    started = time.perf_counter()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            latency_ms = round((time.perf_counter() - started) * 1000, 1)
            size = None
            if connection.vendor == "postgresql":
                cursor.execute("SELECT pg_database_size(current_database())")
                size = cursor.fetchone()[0]
        executor = MigrationExecutor(connection)
        pending = [f"{m.app_label}.{m.name}" for m, _ in executor.migration_plan(executor.loader.graph.leaf_nodes())]
        return {"status": "ok", "latency_ms": latency_ms, "vendor": connection.vendor,
                "server_version": getattr(connection, "pg_version", None), "size_bytes": size,
                "pending_migrations": pending}
    except Exception:  # noqa: BLE001 - reported as status, never raised
        return {"status": "error", "pending_migrations": []}


def _last_backup():
    root = settings.BACKUP_DIR
    if not root:
        return {"configured": False}
    base = Path(root)
    if not base.is_dir():
        return {"configured": True, "found": False, "directory": root}
    newest = None
    count = 0
    for file in base.rglob("*.dump"):
        count += 1
        mtime = file.stat().st_mtime
        if newest is None or mtime > newest[1]:
            newest = (file, mtime)
    if newest is None:
        return {"configured": True, "found": False, "directory": root}
    taken = timezone.datetime.fromtimestamp(newest[1], tz=timezone.get_current_timezone())
    age_hours = round((timezone.now() - taken).total_seconds() / 3600, 1)
    return {"configured": True, "found": True, "directory": root, "file": newest[0].name, "taken_at": taken,
            "size_bytes": newest[0].stat().st_size, "age_hours": age_hours, "count": count,
            "stale": age_hours > 26}


def health_snapshot() -> dict:
    from apps.accounts.models import LoginAttempt, User, UserSession

    now = timezone.now()
    since = now - timedelta(hours=24)
    db = _database()
    disk = _disk(str(settings.BASE_DIR))
    memory = _memory()
    backup = _last_backup()
    errors_24h = ErrorEvent.objects.filter(occurred_at__gte=since).count()
    warnings = []
    if db["status"] != "ok":
        warnings.append("The database is not responding.")
    if db.get("pending_migrations"):
        warnings.append("Database updates (migrations) are waiting to be applied.")
    if disk and disk["percent_used"] and disk["percent_used"] >= 90:
        warnings.append("The server disk is over 90% full.")
    if memory and memory["percent_used"] >= 90:
        warnings.append("Server memory is over 90% used.")
    if not backup.get("configured"):
        warnings.append("BACKUP_DIR is not set, so backups cannot be checked here.")
    elif not backup.get("found"):
        warnings.append("No backup file was found.")
    elif backup.get("stale"):
        warnings.append("The newest backup is more than a day old.")
    if errors_24h:
        warnings.append(f"{errors_24h} server error(s) in the last 24 hours.")
    off = offsite.status(now)
    if off["overdue"]:
        warnings.append("Off-site backup is overdue: no successful upload within the expected time.")
    settings_obj = SystemSettings.get()
    if settings_obj.maintenance_mode:
        warnings.append("Maintenance mode is on: only system administrators can use the system.")
    return {
        "checked_at": now,
        "status": "error" if db["status"] != "ok" else ("warning" if warnings else "ok"),
        "warnings": warnings,
        "version": settings.MRS_VERSION or None,
        "python": platform.python_version(),
        "django": django.get_version(),
        "debug": settings.DEBUG,
        "https": settings.HTTPS_ENABLED,
        "app_uptime_seconds": int(time.time() - _PROCESS_STARTED),
        "host_uptime_seconds": _host_uptime_seconds(),
        "load": _load(),
        "memory": memory,
        "disk": disk,
        "backup_disk": _disk(settings.BACKUP_DIR) if backup.get("found") else None,
        "database": db,
        "backup": backup,
        "errors_24h": errors_24h,
        "sessions_active": UserSession.objects.filter(ended_at__isnull=True,
                                                     last_seen_at__gte=now - timedelta(minutes=policy.session_idle_minutes())).count(),
        "failed_logins_24h": LoginAttempt.objects.filter(attempted_at__gte=since, succeeded=False).count(),
        "locked_accounts": User.objects.filter(locked_until__gt=now).count(),
        "maintenance_mode": settings_obj.maintenance_mode,
        "offsite": off,
    }


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------
def record_health_sample(snap: dict) -> None:
    """Keep one row per day (the latest reading of the day wins); 400 days are kept."""
    from datetime import timedelta

    from .models import HealthSample

    disk = snap.get("disk") or {}
    db = snap.get("database") or {}
    backup = snap.get("backup") or {}
    today = timezone.localdate()
    HealthSample.objects.update_or_create(day=today, defaults={
        "disk_percent_used": disk.get("percent_used"), "disk_free_bytes": disk.get("free"),
        "database_bytes": db.get("size_bytes"), "newest_backup_bytes": backup.get("size_bytes")})
    HealthSample.objects.filter(day__lt=today - timedelta(days=400)).delete()


class ModulesView(APIView):
    """GET: which modules are on (everyone signed in, so screens can adapt)."""

    permission_classes = [IsAuthenticatedWithCurrentPassword]

    def get(self, request):
        from .modules import describe

        return Response(describe())


class ModuleDetailView(PermissionedView):
    """PATCH system/modules/<key>/ {enabled}: system administrator only. Refused while work is unfinished."""

    required_permissions = {"PATCH": ("system.security.manage",)}

    def patch(self, request, key):
        from .modules import set_module

        enabled = request.data.get("enabled")
        if not isinstance(enabled, bool):
            raise serializers.ValidationError({"enabled": ["true or false."]})
        return Response(set_module(self.ctx(), key, enabled))


class PermissionLayoutView(PermissionedView):
    """The permission matrix: areas of work (rows) by kind of action (columns)."""

    required_permissions = {"GET": ("users.view",)}

    def get(self, request):
        from .modules import permission_layout

        return Response(permission_layout())


class SystemStatusView(APIView):
    """Public: lets the sign-in page show a maintenance notice. Reveals nothing else."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def get(self, request):
        obj = policy.current()
        on = bool(obj and obj.maintenance_mode)
        return Response({"maintenance_mode": on, "maintenance_message": obj.maintenance_message if on else ""})


class SystemHealthView(PermissionedView):
    required_permissions = {"GET": ("system.health.view",)}

    def get(self, request):
        snap = health_snapshot()
        try:
            record_health_sample(snap)
        except Exception:  # a trend reading must never break the health page
            logger.exception("could not record health sample")
        return Response(snap)


class SystemHealthHistoryView(PermissionedView):
    """Daily disk and storage readings for the trend charts (default 90 days, at most 400)."""

    required_permissions = {"GET": ("system.health.view",)}

    def get(self, request):
        from datetime import timedelta

        from .models import HealthSample

        try:
            days = min(max(int(request.query_params.get("days", 90)), 7), 400)
        except ValueError:
            days = 90
        since = timezone.localdate() - timedelta(days=days - 1)
        rows = HealthSample.objects.filter(day__gte=since).order_by("day")
        return Response([{"day": r.day, "disk_percent_used": r.disk_percent_used, "disk_free_bytes": r.disk_free_bytes,
                          "database_bytes": r.database_bytes, "newest_backup_bytes": r.newest_backup_bytes}
                         for r in rows])


class ErrorEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorEvent
        fields = ["id", "occurred_at", "request_id", "method", "path", "exception_type", "message", "user_id"]


class ErrorEventListView(PermissionedView):
    required_permissions = {"GET": ("system.health.view",)}

    def get(self, request):
        qs = ErrorEvent.objects.all()
        rid = request.query_params.get("request_id", "").strip()
        if rid:
            qs = qs.filter(request_id=rid)
        return self.paginate(qs.order_by("-occurred_at"), ErrorEventSerializer)


class SecuritySettingsSerializer(serializers.Serializer):
    password_min_length = serializers.IntegerField(min_value=policy.LIMITS["password_min_length"][0],
                                                   max_value=policy.LIMITS["password_min_length"][1])
    login_max_failures = serializers.IntegerField(min_value=policy.LIMITS["login_max_failures"][0],
                                                  max_value=policy.LIMITS["login_max_failures"][1])
    login_lockout_minutes = serializers.IntegerField(min_value=policy.LIMITS["login_lockout_minutes"][0],
                                                     max_value=policy.LIMITS["login_lockout_minutes"][1])
    session_idle_minutes = serializers.IntegerField(min_value=policy.LIMITS["session_idle_minutes"][0],
                                                    max_value=policy.LIMITS["session_idle_minutes"][1])
    maintenance_mode = serializers.BooleanField()
    maintenance_message = serializers.CharField(max_length=255, allow_blank=True)
    mfa_required_for = serializers.ChoiceField(choices=SystemSettings.MfaPolicy.choices)
    dormant_account_days = serializers.IntegerField(min_value=0, max_value=730)

    def validate_password_min_length(self, value):
        if value < settings.PASSWORD_MIN_LENGTH:
            raise serializers.ValidationError(
                f"The server requires at least {settings.PASSWORD_MIN_LENGTH} characters (PASSWORD_MIN_LENGTH).")
        return value

    def validate_session_idle_minutes(self, value):
        ceiling = settings.SESSION_ABSOLUTE_TIMEOUT_HOURS * 60
        if value > ceiling:
            raise serializers.ValidationError(f"Cannot exceed the absolute session limit ({ceiling} minutes).")
        return value


class SecuritySettingsView(PermissionedView):
    required_permissions = {"GET": AnyOf(("system.health.view", "system.security.manage")),
                            "PATCH": ("system.security.manage",)}

    def _body(self, obj):
        data = SecuritySettingsSerializer(obj).data
        data["row_version"] = obj.row_version
        data["floor"] = {"password_min_length": settings.PASSWORD_MIN_LENGTH}
        data["limits"] = policy.LIMITS
        data["session_absolute_hours"] = settings.SESSION_ABSOLUTE_TIMEOUT_HOURS
        return data

    def get(self, request):
        return Response(self._body(SystemSettings.get()))

    def patch(self, request):
        data = validated(SecuritySettingsSerializer, request.data, partial=True)
        SystemSettings.get()
        with transaction.atomic():
            obj = SystemSettings.objects.select_for_update().get(pk=1)
            check_version(obj, expected_version(request), object_type="system_settings", label="security policy")
            changes = {}
            for key, value in data.items():
                if getattr(obj, key) != value:
                    changes[key] = {"from": getattr(obj, key), "to": value}
                    setattr(obj, key, value)
            if changes:
                obj.save()
                action = "system.security_update"
                if "maintenance_mode" in changes:
                    action = "system.maintenance_on" if obj.maintenance_mode else "system.maintenance_off"
                record_event(self.ctx(), action=action, object_type="system_settings", object_id=1, details=changes)
        return Response(self._body(obj))


class OffsiteRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = OffsiteBackupRun
        fields = ["id", "started_at", "finished_at", "status", "snapshot_id", "bytes_added", "dump_file", "target",
                  "message"]


class OffsiteSettingsSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(required=False)
    interval_hours = serializers.ChoiceField(choices=offsite.INTERVAL_CHOICES, required=False)


class OffsiteBackupView(PermissionedView):
    """
    Switch off-site backup on or off and choose how often. The destination and the owner's secret
    phrase are set on the server (deploy/scripts/offsite-backup.sh init), never through the browser.
    """

    required_permissions = {"GET": AnyOf(("system.health.view", "backups.manage")), "PATCH": ("backups.manage",)}

    def _body(self):
        runs = OffsiteBackupRun.objects.order_by("-finished_at")[:20]
        return {**offsite.status(), "interval_choices": offsite.INTERVAL_CHOICES,
                "runs": OffsiteRunSerializer(runs, many=True).data}

    def get(self, request):
        return Response(self._body())

    def patch(self, request):
        data = validated(OffsiteSettingsSerializer, request.data)
        SystemSettings.get()
        with transaction.atomic():
            obj = SystemSettings.objects.select_for_update().get(pk=1)
            changes = {}
            if "enabled" in data and data["enabled"] != obj.offsite_enabled:
                changes["enabled"] = {"from": obj.offsite_enabled, "to": data["enabled"]}
                obj.offsite_enabled = data["enabled"]
            if "interval_hours" in data and data["interval_hours"] != obj.offsite_interval_hours:
                changes["interval_hours"] = {"from": obj.offsite_interval_hours, "to": data["interval_hours"]}
                obj.offsite_interval_hours = data["interval_hours"]
            if changes:
                obj.save()
                action = "backup.offsite_settings"
                if "enabled" in changes:
                    action = "backup.offsite_on" if obj.offsite_enabled else "backup.offsite_off"
                record_event(self.ctx(), action=action, object_type="system_settings", object_id=1, details=changes)
        return Response(self._body())


urlpatterns = [
    path("system/offsite/", OffsiteBackupView.as_view(), name="system-offsite"),
    path("system/status/", SystemStatusView.as_view(), name="system-status"),
    path("system/health/", SystemHealthView.as_view(), name="system-health"),
    path("system/modules/", ModulesView.as_view(), name="system-modules"),
    path("system/modules/<slug:key>/", ModuleDetailView.as_view(), name="system-module"),
    path("system/permission-layout/", PermissionLayoutView.as_view(), name="permission-layout"),
    path("system/health/history/", SystemHealthHistoryView.as_view(), name="system-health-history"),
    path("system/errors/", ErrorEventListView.as_view(), name="system-errors"),
    path("system/security/", SecuritySettingsView.as_view(), name="system-security"),
]
