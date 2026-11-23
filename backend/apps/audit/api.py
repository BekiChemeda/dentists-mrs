from datetime import datetime, time

from django.utils import timezone
from rest_framework import serializers
from rest_framework.generics import ListAPIView

from apps.core.permissions import AnyOf, HasRequiredPermissions

from .models import AuditEvent


SECURITY_ACTION_PREFIXES = ("auth.", "user.", "role.", "access.", "session", "system.", "backup")


class AuditEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditEvent
        fields = [
            "id",
            "occurred_at",
            "actor",
            "actor_username",
            "action",
            "object_type",
            "object_id",
            "outcome",
            "ip_address",
            "user_agent",
            "request_id",
            "details",
        ]


class AuditFilterSerializer(serializers.Serializer):
    actor = serializers.UUIDField(required=False)
    action = serializers.CharField(required=False, max_length=100)
    object_type = serializers.CharField(required=False, max_length=100)
    object_id = serializers.CharField(required=False, max_length=64)
    outcome = serializers.ChoiceField(choices=AuditEvent.Outcome.choices, required=False)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)

    def validate(self, attrs):
        if attrs.get("date_from") and attrs.get("date_to") and attrs["date_from"] > attrs["date_to"]:
            raise serializers.ValidationError({"date_to": ["Must be on or after date_from."]})
        return attrs


class AuditEventListView(ListAPIView):
    """Read-only. There is deliberately no endpoint that modifies audit events."""

    permission_classes = [HasRequiredPermissions]
    required_permissions = {"GET": AnyOf(("audit.view", "audit.operational"))}
    serializer_class = AuditEventSerializer

    def get_queryset(self):
        filters = AuditFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        f = filters.validated_data
        qs = AuditEvent.objects.all()
        if not self.request.user.has_permissions(["audit.view"]):
            # audit.operational: clinic work only. Sign-ins, account, role, security and system events
            # stay with the system administrator.
            for prefix in SECURITY_ACTION_PREFIXES:
                qs = qs.exclude(action__startswith=prefix)
        if "actor" in f:
            qs = qs.filter(actor_id=f["actor"])
        if "action" in f:
            qs = qs.filter(action__startswith=f["action"])
        if "object_type" in f:
            qs = qs.filter(object_type=f["object_type"])
        if "object_id" in f:
            qs = qs.filter(object_id=f["object_id"])
        if "outcome" in f:
            qs = qs.filter(outcome=f["outcome"])
        tz = timezone.get_current_timezone()
        if "date_from" in f:
            qs = qs.filter(occurred_at__gte=datetime.combine(f["date_from"], time.min, tzinfo=tz))
        if "date_to" in f:
            qs = qs.filter(occurred_at__lte=datetime.combine(f["date_to"], time.max, tzinfo=tz))
        return qs.order_by("-occurred_at")
