from django.urls import path
from rest_framework import serializers
from rest_framework.response import Response

from apps.core.api import PermissionedView
from apps.core.permissions import IsAuthenticatedWithCurrentPassword

from . import services
from .models import Announcement, Notification
from apps.core.concurrency import bump_version, guarded_edit


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "kind", "title", "body", "link", "created_at", "read_at"]


class NotificationListView(PermissionedView):
    permission_classes = [IsAuthenticatedWithCurrentPassword]

    def get(self, request):
        qs = Notification.objects.filter(user=request.user)
        if self.param_bool("unread"):
            qs = qs.filter(read_at__isnull=True)
        response = self.paginate(qs.order_by("-created_at"), NotificationSerializer)
        response.data["unread"] = Notification.objects.filter(user=request.user, read_at__isnull=True).count()
        return response


class NotificationReadView(PermissionedView):
    permission_classes = [IsAuthenticatedWithCurrentPassword]

    def post(self, request):
        ids = request.data.get("ids")
        if ids is not None and not isinstance(ids, list):
            return Response({"error": {"code": "validation_error", "message": "ids must be a list."}}, status=400)
        return Response({"marked": services.mark_read(request.user, ids)})


class AnnouncementSerializer(serializers.ModelSerializer):
    role_ids = serializers.PrimaryKeyRelatedField(source="roles", many=True, read_only=True)
    department_id = serializers.UUIDField(source="department.id", read_only=True, allow_null=True)
    department_name = serializers.CharField(source="department.name", read_only=True, allow_null=True)
    created_by_name = serializers.CharField(source="created_by.full_name", read_only=True)

    class Meta:
        model = Announcement
        fields = ["id", "title", "body", "level", "role_ids", "department_id", "department_name", "starts_on",
                  "ends_on", "is_active", "created_by_name", "created_at", "row_version"]


class AnnouncementWriteSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=150)
    body = serializers.CharField(max_length=2000, allow_blank=True, required=False, default="")
    level = serializers.ChoiceField(choices=Announcement.Level.choices, required=False, default="info")
    role_ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)
    department_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    starts_on = serializers.DateField()
    ends_on = serializers.DateField(required=False, allow_null=True, default=None)
    is_active = serializers.BooleanField(required=False, default=True)

    def validate(self, attrs):
        if attrs.get("ends_on") and attrs.get("starts_on") and attrs["ends_on"] < attrs["starts_on"]:
            raise serializers.ValidationError({"ends_on": ["Must be on or after the start date."]})
        return attrs


class CurrentAnnouncementsView(PermissionedView):
    """Announcements meant for the signed-in user today: everyone, their roles, or their department."""

    permission_classes = [IsAuthenticatedWithCurrentPassword]

    def get(self, request):
        return Response(AnnouncementSerializer(services.current_announcements(request.user), many=True).data)


class AnnouncementListCreateView(PermissionedView):
    required_permissions = {"GET": ("announcements.manage",), "POST": ("announcements.manage",)}

    def get(self, request):
        qs = Announcement.objects.select_related("department", "created_by").prefetch_related("roles")
        return self.paginate(qs.order_by("-starts_on", "-created_at"), AnnouncementSerializer)

    def post(self, request):
        s = AnnouncementWriteSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        obj = services.save_announcement(self.ctx(), None, s.validated_data)
        return Response(AnnouncementSerializer(obj).data, status=201)


class AnnouncementDetailView(PermissionedView):
    required_permissions = {"PATCH": ("announcements.manage",)}

    def patch(self, request, pk):
        from django.shortcuts import get_object_or_404

        s = AnnouncementWriteSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        with guarded_edit(Announcement, pk, request, object_type="announcement", label="announcement") as obj:
            obj = services.save_announcement(self.ctx(), obj, s.validated_data)
            if "role_ids" in s.validated_data:
                bump_version(obj)  # target roles live in a link table the trigger cannot see
        return Response(AnnouncementSerializer(obj).data)


urlpatterns = [
    path("announcements/", AnnouncementListCreateView.as_view()),
    path("announcements/current/", CurrentAnnouncementsView.as_view()),
    path("announcements/<uuid:pk>/", AnnouncementDetailView.as_view()),
    path("notifications/", NotificationListView.as_view()),
    path("notifications/read/", NotificationReadView.as_view()),
]
