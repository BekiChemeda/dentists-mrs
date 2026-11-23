"""HTTP layer: parse and validate input, call a service, serialise the result. No business rules here."""

from django.contrib.auth import login, logout
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from apps.core.throttling import ClientScopedRateThrottle as ScopedRateThrottle
from rest_framework.views import APIView

from apps.audit.services import record_event
from apps.core.concurrency import bump_version, guarded_edit
from apps.core.context import ActorContext
from apps.core.permissions import AnyOf, HasRequiredPermissions, IsAuthenticatedWithCurrentPassword

from . import services
from .models import Department, Permission, Role, Room, User, UserSession
from .serializers import (
    DepartmentSerializer,
    CurrentUserSerializer,
    LoginSerializer,
    PasswordChangeSerializer,
    PermissionSerializer,
    RoleCreateSerializer,
    RoleSerializer,
    RoleUpdateSerializer,
    UserCreateSerializer,
    UserSerializer,
    UserSessionSerializer,
    UserUpdateSerializer,
)


def _ctx(request) -> ActorContext:
    return ActorContext.from_request(request)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        # DRF skips CSRF for anonymous requests; enforce it here to prevent login CSRF.
        SessionAuthentication().enforce_csrf(request)
        data = LoginSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        ctx = _ctx(request)
        user = services.verify_credentials(ctx, data.validated_data["username"], data.validated_data["password"])
        if user.mfa_enabled:
            # Password accepted; the sign-in is finished by LoginMfaView with a code from the phone.
            return Response({"mfa_required": True, "mfa_token": services.mfa_login_token(user)})
        return self._sign_in(request, ctx, user)

    @staticmethod
    def _sign_in(request, ctx, user):
        if request.user.is_authenticated:
            services.end_session(ctx, request.session.session_key, UserSession.EndReason.LOGOUT)
        login(request._request, user, backend="django.contrib.auth.backends.ModelBackend")
        if not request.session.session_key:
            request.session.save()
        services.start_session(ctx, user, request.session.session_key)
        return Response(CurrentUserSerializer(user).data)


class LogoutView(APIView):
    permission_classes = [IsAuthenticatedWithCurrentPassword]
    allow_pending_password_change = True

    def post(self, request):
        services.end_session(_ctx(request), request.session.session_key, UserSession.EndReason.LOGOUT)
        logout(request._request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = [IsAuthenticatedWithCurrentPassword]
    allow_pending_password_change = True

    def get(self, request):
        return Response(CurrentUserSerializer(request.user).data)


class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticatedWithCurrentPassword]
    allow_pending_password_change = True

    def post(self, request):
        data = PasswordChangeSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        old_key = request.session.session_key
        services.change_own_password(
            _ctx(request), request.user,
            data.validated_data["current_password"], data.validated_data["new_password"],
            current_session_key=old_key,
        )
        # Keep this session signed in with a fresh key; other sessions were ended.
        from django.contrib.auth import update_session_auth_hash

        update_session_auth_hash(request._request, request.user)
        services.rekey_session(old_key, request.session.session_key)
        return Response(CurrentUserSerializer(request.user).data)


class LoginMfaView(APIView):
    """Second step of sign-in: the code from the authenticator app, or a recovery code."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        SessionAuthentication().enforce_csrf(request)
        token = str(request.data.get("mfa_token", ""))[:500]
        code = str(request.data.get("code", ""))[:40]
        ctx = _ctx(request)
        user = services.complete_mfa_login(ctx, token, code)
        return LoginView._sign_in(request, ctx, user)


class MfaStatusView(APIView):
    permission_classes = [IsAuthenticatedWithCurrentPassword]
    allow_pending_mfa_setup = True

    def get(self, request):
        u = request.user
        return Response({"enabled": u.mfa_enabled, "enabled_at": u.mfa_enabled_at,
                         "required": services.mfa_required_for(u),
                         "recovery_codes_left": u.recovery_codes.filter(used_at__isnull=True).count()})


class MfaSetupView(APIView):
    permission_classes = [IsAuthenticatedWithCurrentPassword]
    allow_pending_mfa_setup = True
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "sensitive"

    def post(self, request):
        if request.user.mfa_enabled:
            return Response({"error": {"code": "conflict", "message": "Two-step sign-in is already on."}}, status=409)
        return Response(services.start_mfa_enrolment(request.user, request.session))


class MfaConfirmView(APIView):
    permission_classes = [IsAuthenticatedWithCurrentPassword]
    allow_pending_mfa_setup = True
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "sensitive"

    def post(self, request):
        codes = services.confirm_mfa_enrolment(_ctx(request), request.user, request.session,
                                               str(request.data.get("code", ""))[:20])
        return Response({"recovery_codes": codes})


class MfaRecoveryCodesView(APIView):
    permission_classes = [IsAuthenticatedWithCurrentPassword]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "sensitive"

    def post(self, request):
        codes = services.regenerate_recovery_codes(_ctx(request), request.user, str(request.data.get("code", ""))[:40])
        return Response({"recovery_codes": codes})


class MfaDisableView(APIView):
    permission_classes = [IsAuthenticatedWithCurrentPassword]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "sensitive"

    def post(self, request):
        services.disable_own_mfa(_ctx(request), request.user, str(request.data.get("password", ""))[:256],
                                 str(request.data.get("code", ""))[:40])
        return Response(status=status.HTTP_204_NO_CONTENT)


class MyEmailAlertsView(APIView):
    """Which notifications the signed-in person also gets by email."""

    permission_classes = [IsAuthenticatedWithCurrentPassword]

    def patch(self, request):
        choice = str(request.data.get("email_alerts", ""))
        if choice not in dict(User.EmailAlerts.choices):
            return Response({"error": {"code": "validation_error", "message": "Choose off, important or all.",
                                       "fields": {"email_alerts": ["Invalid choice."]}}}, status=400)
        User.objects.filter(pk=request.user.pk).update(email_alerts=choice)
        return Response({"email_alerts": choice})


class MyRoomView(APIView):
    """The room the signed-in person works in now (shown when they call a patient). null = none."""

    permission_classes = [IsAuthenticatedWithCurrentPassword]

    def patch(self, request):
        from .models import Room

        room_id = request.data.get("room_id")
        room = None
        if room_id:
            room = Room.objects.filter(pk=room_id, is_active=True).first() if _is_uuid(room_id) else None
            if room is None:
                return Response({"error": {"code": "validation_error", "message": "Choose an active room.",
                                           "fields": {"room_id": ["Not an active room."]}}}, status=400)
        User.objects.filter(pk=request.user.pk).update(room=room)
        return Response({"room": {"id": str(room.pk), "name": room.name} if room else None})


def _is_uuid(value) -> bool:
    import uuid

    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False


class RoomSerializer(serializers.ModelSerializer):
    department_id = serializers.PrimaryKeyRelatedField(source="department", queryset=Department.objects.all(),
                                                       allow_null=True, required=False)
    department_name = serializers.CharField(source="department.name", read_only=True, default="")

    class Meta:
        model = Room
        fields = ["id", "name", "department_id", "department_name", "is_active", "sort_order", "row_version"]
        read_only_fields = ["row_version"]


class RoomListCreateView(APIView):
    """Everyone signed in can list rooms (doctors pick theirs); departments.manage edits them."""

    permission_classes = [HasRequiredPermissions]
    required_permissions = {"GET": (), "POST": ("departments.manage",)}

    def get(self, request):
        from .models import Room

        qs = Room.objects.select_related("department")
        if request.query_params.get("active") == "true":
            qs = qs.filter(is_active=True)
        return Response(RoomSerializer(qs, many=True).data)

    def post(self, request):
        s = RoomSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        room = s.save()
        record_event(_ctx(request), action="room.create", object_type="room", object_id=room.pk,
                     details={"name": room.name})
        return Response(RoomSerializer(room).data, status=status.HTTP_201_CREATED)


class RoomDetailView(APIView):
    permission_classes = [HasRequiredPermissions]
    required_permissions = {"PATCH": ("departments.manage",)}

    def patch(self, request, pk):
        from .models import Room

        with guarded_edit(Room, pk, request, object_type="room", label="room") as room:
            s = RoomSerializer(room, data=request.data, partial=True)
            s.is_valid(raise_exception=True)
            changes = {k: str(v) for k, v in s.validated_data.items()}
            room = s.save()
            record_event(_ctx(request), action="room.update", object_type="room", object_id=room.pk, details=changes)
        return Response(RoomSerializer(Room.objects.select_related("department").get(pk=pk)).data)


class MySessionsView(ListAPIView):
    permission_classes = [IsAuthenticatedWithCurrentPassword]
    serializer_class = UserSessionSerializer
    pagination_class = None

    def get_queryset(self):
        return UserSession.objects.filter(user=self.request.user, ended_at__isnull=True).order_by("-last_seen_at")


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
def _user_queryset():
    return User.objects.select_related("department").prefetch_related(
        Prefetch("roles", queryset=Role.objects.prefetch_related("permissions").order_by("name")))


class UserListCreateView(APIView):
    permission_classes = [HasRequiredPermissions]
    required_permissions = {"GET": ("users.view",), "POST": AnyOf(("users.manage", "staff.manage"))}

    def get(self, request):
        qs = _user_queryset()
        search = request.query_params.get("search", "").strip()
        if search:
            qs = qs.filter(
                Q(username__icontains=search) | Q(first_name__icontains=search)
                | Q(last_name__icontains=search) | Q(phone__icontains=search)
            )
        active = request.query_params.get("is_active")
        if active in ("true", "false"):
            qs = qs.filter(is_active=(active == "true"))
        role = request.query_params.get("role")
        if role:
            qs = qs.filter(roles__code=role)
        if request.query_params.get("locked") == "true":
            qs = qs.filter(locked_until__gt=timezone.now())
        department = request.query_params.get("department")
        if department:
            qs = qs.filter(department__code=department)
        if request.query_params.get("pending_password") == "true":
            qs = qs.filter(must_change_password=True)
        from apps.core.pagination import StandardPagination

        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs.distinct().order_by("last_name", "first_name"), request, view=self)
        return paginator.get_paginated_response(UserSerializer(page, many=True).data)

    def post(self, request):
        data = UserCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user, temporary = services.create_user(_ctx(request), **data.validated_data)
        body = UserSerializer(_user_queryset().get(pk=user.pk)).data
        body["temporary_password"] = temporary  # shown once; never stored in plain text or logged
        return Response(body, status=status.HTTP_201_CREATED)


class UserDetailView(APIView):
    permission_classes = [HasRequiredPermissions]
    required_permissions = {"GET": ("users.view",), "PATCH": AnyOf(("users.manage", "staff.manage"))}

    def get(self, request, pk):
        return Response(UserSerializer(get_object_or_404(_user_queryset(), pk=pk)).data)

    def patch(self, request, pk):
        data = UserUpdateSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        with guarded_edit(User, pk, request, object_type="user", label="staff account") as user:
            roles_before = set(user.roles.values_list("pk", flat=True))
            services.update_user(_ctx(request), user, **data.validated_data)
            if set(user.roles.values_list("pk", flat=True)) != roles_before:
                bump_version(user)  # roles live in a link table the trigger cannot see
        return Response(UserSerializer(_user_queryset().get(pk=pk)).data)


class _UserActionView(APIView):
    """staff.manage holders reach these too; services.update_user & co. limit them to ordinary accounts."""

    permission_classes = [HasRequiredPermissions]
    required_permissions = {"POST": AnyOf(("users.manage", "staff.manage"))}

    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        extra = self.perform(_ctx(request), user) or {}
        body = UserSerializer(_user_queryset().get(pk=pk)).data
        body.update(extra)
        return Response(body)

    def perform(self, ctx, user):  # pragma: no cover - abstract
        raise NotImplementedError


class UserActivateView(_UserActionView):
    def perform(self, ctx, user):
        services.set_user_active(ctx, user, True)


class UserDeactivateView(_UserActionView):
    def perform(self, ctx, user):
        services.set_user_active(ctx, user, False)


class UserUnlockView(_UserActionView):
    def perform(self, ctx, user):
        services.unlock_user(ctx, user)


class UserResetPasswordView(_UserActionView):
    def perform(self, ctx, user):
        return {"temporary_password": services.admin_reset_password(ctx, user)}


class UserResetMfaView(_UserActionView):
    def perform(self, ctx, user):
        return {"sessions_ended": services.admin_reset_mfa(ctx, user)}


class UserRevokeSessionsView(_UserActionView):
    required_permissions = {"POST": ("sessions.manage",)}

    def perform(self, ctx, user):
        return {"sessions_ended": services.revoke_sessions(ctx, user)}


# ---------------------------------------------------------------------------
# Roles and permissions
# ---------------------------------------------------------------------------
def _role_queryset():
    return Role.objects.prefetch_related("permissions", "users")


class RoleListCreateView(APIView):
    permission_classes = [HasRequiredPermissions]
    required_permissions = {"GET": ("users.view",), "POST": ("roles.manage",)}

    def get(self, request):
        return Response(RoleSerializer(_role_queryset().order_by("name"), many=True).data)

    def post(self, request):
        data = RoleCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        role = services.create_role(_ctx(request), **data.validated_data)
        return Response(RoleSerializer(_role_queryset().get(pk=role.pk)).data, status=status.HTTP_201_CREATED)


class RoleDetailView(APIView):
    permission_classes = [HasRequiredPermissions]
    required_permissions = {"GET": ("users.view",), "PATCH": ("roles.manage",)}

    def get(self, request, pk):
        return Response(RoleSerializer(get_object_or_404(_role_queryset(), pk=pk)).data)

    def patch(self, request, pk):
        data = RoleUpdateSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        with guarded_edit(Role, pk, request, object_type="role", label="role") as role:
            perms_before = set(role.permissions.values_list("pk", flat=True))
            services.update_role(_ctx(request), role, **data.validated_data)
            if set(role.permissions.values_list("pk", flat=True)) != perms_before:
                bump_version(role)  # permissions live in a link table the trigger cannot see
        return Response(RoleSerializer(_role_queryset().get(pk=pk)).data)


class PermissionListView(ListAPIView):
    permission_classes = [HasRequiredPermissions]
    required_permissions = {"GET": ("users.view",)}
    serializer_class = PermissionSerializer
    pagination_class = None
    queryset = Permission.objects.order_by("module", "code")


# ---------------------------------------------------------------------------
# Departments
# ---------------------------------------------------------------------------
class DepartmentWriteSerializer(DepartmentSerializer):
    class Meta(DepartmentSerializer.Meta):
        fields = ["code", "name", "receives_triage", "is_active", "sort_order"]


class DepartmentListCreateView(APIView):
    """Everyone signed in can list departments (the triage form needs them); departments.manage edits them."""

    permission_classes = [HasRequiredPermissions]
    required_permissions = {"GET": (), "POST": ("departments.manage",)}

    def get(self, request):
        from django.db.models import Count

        qs = Department.objects.annotate(staff_count=Count("staff", filter=Q(staff__is_active=True)))
        if request.query_params.get("active") == "true":
            qs = qs.filter(is_active=True)
        if request.query_params.get("triage") == "true":
            qs = qs.filter(receives_triage=True, is_active=True)
        return Response(DepartmentSerializer(qs.order_by("sort_order", "name"), many=True).data)

    def post(self, request):
        data = DepartmentWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        dept = services.save_department(_ctx(request), None, data.validated_data)
        return Response(DepartmentSerializer(dept).data, status=status.HTTP_201_CREATED)


class DepartmentDetailView(APIView):
    permission_classes = [HasRequiredPermissions]
    required_permissions = {"PATCH": ("departments.manage",)}

    def patch(self, request, pk):
        with guarded_edit(Department, pk, request, object_type="department", label="department") as dept:
            data = DepartmentWriteSerializer(dept, data=request.data, partial=True)
            data.is_valid(raise_exception=True)
            dept = services.save_department(_ctx(request), dept, data.validated_data)
        return Response(DepartmentSerializer(dept).data)
