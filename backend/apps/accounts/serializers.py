from rest_framework import serializers

from .models import Department, Permission, Role, User, UserSession, username_validator


class RoleSummarySerializer(serializers.ModelSerializer):
    privileged = serializers.SerializerMethodField()

    class Meta:
        model = Role
        fields = ["id", "code", "name", "privileged"]

    def get_privileged(self, role) -> bool:
        from .catalog import role_is_privileged

        return role_is_privileged(role.code, [p.code for p in role.permissions.all()])


class DepartmentSerializer(serializers.ModelSerializer):
    staff_count = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = Department
        fields = ["id", "code", "name", "receives_triage", "is_active", "sort_order", "staff_count", "row_version"]


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ["code", "module", "description"]


class RoleSerializer(serializers.ModelSerializer):
    permission_codes = serializers.SerializerMethodField()
    user_count = serializers.SerializerMethodField()
    privileged = serializers.SerializerMethodField()

    class Meta:
        model = Role
        fields = ["id", "code", "name", "description", "is_system", "permission_codes", "user_count", "privileged",
                  "row_version"]

    def get_privileged(self, role) -> bool:
        from .catalog import role_is_privileged

        return role_is_privileged(role.code, [p.code for p in role.permissions.all()])

    def get_permission_codes(self, role) -> list[str]:
        return sorted(p.code for p in role.permissions.all())

    def get_user_count(self, role) -> int:
        return sum(1 for u in role.users.all() if u.is_active)


class RoleCreateSerializer(serializers.Serializer):
    code = serializers.SlugField(max_length=50)
    name = serializers.CharField(max_length=100)
    description = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    permission_codes = serializers.ListField(child=serializers.CharField(max_length=100), default=list)


class RoleUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100, required=False)
    description = serializers.CharField(max_length=255, required=False, allow_blank=True)
    permission_codes = serializers.ListField(child=serializers.CharField(max_length=100), required=False)


class UserSerializer(serializers.ModelSerializer):
    roles = RoleSummarySerializer(many=True, read_only=True)
    full_name = serializers.CharField(read_only=True)
    is_locked = serializers.SerializerMethodField()
    department = serializers.SerializerMethodField()
    mfa_enabled = serializers.BooleanField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id", "row_version", "username", "first_name", "last_name", "full_name", "email", "phone", "job_title",
            "registration_number",
            "department", "start_date", "is_active", "is_locked", "must_change_password", "mfa_enabled", "roles",
            "last_login", "created_at",
        ]

    def get_department(self, user):
        d = user.department
        return {"id": str(d.id), "code": d.code, "name": d.name} if d else None

    def get_is_locked(self, user) -> bool:
        return user.is_locked()


class CurrentUserSerializer(UserSerializer):
    permissions = serializers.SerializerMethodField()
    mfa_setup_required = serializers.SerializerMethodField()

    class Meta(UserSerializer.Meta):
        fields = UserSerializer.Meta.fields + ["permissions", "mfa_setup_required", "email_alerts", "room",
                                               "modules_off"]

    modules_off = serializers.SerializerMethodField()

    def get_modules_off(self, user) -> list[str]:
        from apps.core.modules import disabled_modules

        return sorted(disabled_modules())

    room = serializers.SerializerMethodField()

    def get_room(self, user):
        r = user.room
        return {"id": str(r.pk), "name": r.name} if r and r.is_active else None

    def get_mfa_setup_required(self, user) -> bool:
        from .services import mfa_setup_required

        return mfa_setup_required(user)

    def get_permissions(self, user) -> list[str]:
        return sorted(user.permission_codes)


_PHONE_HELP = "Use digits, optionally starting with +, e.g. 0911234567 or +251911234567."


def _validate_phone(value: str) -> str:
    value = value.strip().replace(" ", "")
    if value and not (value.lstrip("+").isdigit() and 9 <= len(value.lstrip("+")) <= 15):
        raise serializers.ValidationError(_PHONE_HELP)
    return value


class UserCreateSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=50)
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100)
    email = serializers.EmailField(required=False, allow_blank=True, default="")
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    job_title = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    registration_number = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    role_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False)
    department_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    start_date = serializers.DateField(required=False, allow_null=True, default=None)

    def validate_username(self, value):
        value = value.strip().lower()
        username_validator(value)
        return value

    def validate_phone(self, value):
        return _validate_phone(value)


class UserUpdateSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=100, required=False)
    last_name = serializers.CharField(max_length=100, required=False)
    email = serializers.EmailField(required=False, allow_blank=True)
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    job_title = serializers.CharField(max_length=100, required=False, allow_blank=True)
    registration_number = serializers.CharField(max_length=50, required=False, allow_blank=True)
    role_ids = serializers.ListField(child=serializers.UUIDField(), required=False)
    department_id = serializers.UUIDField(required=False, allow_null=True)
    start_date = serializers.DateField(required=False, allow_null=True)

    def validate_phone(self, value):
        return _validate_phone(value)


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150, trim_whitespace=True)
    password = serializers.CharField(max_length=256, trim_whitespace=False)


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(max_length=256, trim_whitespace=False)
    new_password = serializers.CharField(max_length=256, trim_whitespace=False)


class UserSessionSerializer(serializers.ModelSerializer):
    is_current = serializers.SerializerMethodField()

    class Meta:
        model = UserSession
        fields = ["id", "created_at", "last_seen_at", "ip_address", "user_agent", "is_current"]

    def get_is_current(self, obj) -> bool:
        request = self.context.get("request")
        return bool(request and request.session.session_key == obj.session_key)
