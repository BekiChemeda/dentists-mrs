"""System › Email: set up sending (cPanel or Brevo), send a test, see the outbox."""

from datetime import timedelta

from django.urls import path
from django.utils import timezone
from rest_framework import serializers
from rest_framework.response import Response
from apps.core.throttling import ClientScopedRateThrottle as ScopedRateThrottle

from apps.audit.services import record_event
from apps.core.api import PermissionedView, validated
from apps.core.permissions import AnyOf

from . import email
from .models import EmailSettings, OutboundEmail
from apps.core.concurrency import guarded_edit

VIEW = AnyOf(("system.health.view", "system.security.manage"))
MANAGE = ("system.security.manage",)


class EmailSettingsSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(required=False)
    provider = serializers.ChoiceField(choices=EmailSettings.Provider.choices, required=False)
    host = serializers.CharField(max_length=255, allow_blank=True, required=False)
    port = serializers.IntegerField(min_value=1, max_value=65535, required=False)
    security = serializers.ChoiceField(choices=EmailSettings.Security.choices, required=False)
    username = serializers.CharField(max_length=255, allow_blank=True, required=False)
    password = serializers.CharField(max_length=500, allow_blank=True, required=False, write_only=True,
                                     trim_whitespace=False)
    from_email = serializers.EmailField(allow_blank=True, required=False)
    from_name = serializers.CharField(max_length=100, allow_blank=True, required=False)
    reply_to = serializers.EmailField(allow_blank=True, required=False)
    site_url = serializers.URLField(allow_blank=True, required=False)

    def validate_host(self, value):
        value = value.strip().lower()
        if value and ("/" in value or " " in value or ":" in value):
            raise serializers.ValidationError("Only the server name, e.g. mail.myclinic.et (no https://, no port).")
        return value


def _body(cfg: EmailSettings) -> dict:
    queued = OutboundEmail.objects.filter(status=OutboundEmail.Status.QUEUED)
    return {
        "row_version": cfg.row_version, "enabled": cfg.enabled, "provider": cfg.provider, "host": cfg.host, "port": cfg.port,
        "security": cfg.security, "username": cfg.username, "password_set": bool(cfg.password_sealed),
        "from_email": cfg.from_email, "from_name": cfg.from_name, "reply_to": cfg.reply_to, "site_url": cfg.site_url,
        "configured": cfg.configured, "last_test_at": cfg.last_test_at, "last_test_ok": cfg.last_test_ok,
        "presets": email.PRESETS,
        "outbox": {"queued": queued.count(),
                   "failed_7d": OutboundEmail.objects.filter(status=OutboundEmail.Status.FAILED,
                                                             created_at__gte=timezone.now() - timedelta(days=7)).count(),
                   "oldest_queued_at": queued.order_by("created_at").values_list("created_at", flat=True).first()},
    }


class EmailSettingsView(PermissionedView):
    required_permissions = {"GET": VIEW, "PATCH": MANAGE}

    def get(self, request):
        return Response(_body(EmailSettings.get()))

    def patch(self, request):
        data = validated(EmailSettingsSerializer, request.data, partial=True)
        EmailSettings.get()
        with guarded_edit(EmailSettings, 1, request, object_type="email_settings", label="email set-up"):
            cfg, changes = email.save_settings(dict(data))
        if not cfg.site_url:
            # Sensible default: the address this administrator is using right now.
            cfg.site_url = f"{request.scheme}://{request.get_host()}"
            cfg.save(update_fields=["site_url", "updated_at"])
        if cfg.enabled and not cfg.configured:
            cfg.enabled = False
            cfg.save(update_fields=["enabled", "updated_at"])
            return Response({"error": {"code": "validation_error",
                                       "message": "Fill in the server, username, password and From address first.",
                                       "fields": {"enabled": ["Not set up yet."]}}}, status=400)
        if changes:
            safe = {k: v for k, v in changes.items() if k != "password"}
            if "password" in changes:
                safe["secret_replaced"] = True  # never the value; the audit log refuses password fields
            action = "email.settings_update"
            if "enabled" in changes:
                action = "email.enabled" if cfg.enabled else "email.disabled"
            record_event(self.ctx(), action=action, object_type="email_settings", object_id=1,
                         details={k: (v if not isinstance(v, dict) else {kk: str(vv) for kk, vv in v.items()})
                                  for k, v in safe.items()})
        return Response(_body(cfg))


class EmailTestSerializer(EmailSettingsSerializer):
    to = serializers.EmailField()


class EmailTestView(PermissionedView):
    """Sends one message straight away, with the saved settings or with unsaved ones from the form."""

    required_permissions = {"POST": MANAGE}
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "sensitive"

    def post(self, request):
        data = validated(EmailTestSerializer, request.data, partial=True)
        if "to" not in data:
            return Response({"error": {"code": "validation_error", "message": "Enter an address to send to.",
                                       "fields": {"to": ["Required."]}}}, status=400)
        saved = EmailSettings.get()
        trial = EmailSettings(**{f.name: getattr(saved, f.name) for f in EmailSettings._meta.fields})
        for key in ("provider", "host", "port", "security", "username", "from_email", "from_name", "reply_to", "site_url"):
            if key in data:
                setattr(trial, key, data[key])
        if not (trial.host and trial.from_email and trial.username):
            return Response({"error": {"code": "validation_error",
                                       "message": "Fill in the server, username and From address first."}}, status=400)
        ok, message = email.send_test(trial, data["to"], password=data.get("password") or None)
        EmailSettings.objects.filter(pk=1).update(last_test_at=timezone.now(), last_test_ok=ok)
        record_event(self.ctx(), action="email.test", object_type="email_settings", object_id=1,
                     outcome="success" if ok else "failure", details={"to": data["to"], "result": message[:200]})
        return Response({"ok": ok, "message": message}, status=200)


class OutboxSerializer(serializers.ModelSerializer):
    class Meta:
        model = OutboundEmail
        fields = ["id", "to_email", "kind", "subject", "status", "attempts", "next_attempt_at", "last_error",
                  "created_at", "sent_at"]


class OutboxView(PermissionedView):
    required_permissions = {"GET": VIEW}

    def get(self, request):
        qs = OutboundEmail.objects.all()
        st = request.query_params.get("status")
        if st in {"queued", "sent", "failed"}:
            qs = qs.filter(status=st)
        return self.paginate(qs.order_by("-created_at"), OutboxSerializer)


class OutboxRetryView(PermissionedView):
    required_permissions = {"POST": MANAGE}

    def post(self, request, pk):
        n = OutboundEmail.objects.filter(pk=pk, status=OutboundEmail.Status.FAILED).update(
            status=OutboundEmail.Status.QUEUED, attempts=0, next_attempt_at=timezone.now(), last_error="")
        return Response({"requeued": n})


urlpatterns = [
    path("system/email/", EmailSettingsView.as_view(), name="email-settings"),
    path("system/email/test/", EmailTestView.as_view(), name="email-test"),
    path("system/email/outbox/", OutboxView.as_view(), name="email-outbox"),
    path("system/email/outbox/<int:pk>/retry/", OutboxRetryView.as_view(), name="email-outbox-retry"),
]
