from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.response import Response

from apps.core.api import PermissionedView
from apps.core.permissions import IsAuthenticatedWithCurrentPassword
from apps.scheduling.api import UserBrief

from . import services
from .models import ApprovalRequest


class ApprovalSerializer(serializers.ModelSerializer):
    requested_by = UserBrief(read_only=True)
    decided_by = UserBrief(read_only=True)
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    can_decide = serializers.SerializerMethodField()
    problem = serializers.SerializerMethodField()

    class Meta:
        model = ApprovalRequest
        fields = ["id", "kind", "kind_label", "status", "object_type", "object_id", "summary", "amount", "quantity",
                  "reason", "requested_by", "decided_by", "decided_at", "decision_note", "used_at", "created_at",
                  "can_decide", "problem"]

    def get_problem(self, obj) -> str | None:
        """For open requests: why approving or applying it would now fail (e.g. the invoice was paid)."""
        if obj.status not in (ApprovalRequest.Status.PENDING, ApprovalRequest.Status.APPROVED):
            return None
        return services.blocking_problem(obj)

    def get_can_decide(self, obj) -> bool:
        user = self.context["request"].user
        return (obj.status == ApprovalRequest.Status.PENDING and obj.requested_by_id != user.pk
                and user.has_permissions([ApprovalRequest.PERMISSION_FOR_KIND[obj.kind]]))


class ApprovalListView(PermissionedView):
    """Everyone sees their own requests; approvers also see requests they may decide."""

    permission_classes = [IsAuthenticatedWithCurrentPassword]

    def get(self, request):
        kinds = [k for k, perm in ApprovalRequest.PERMISSION_FOR_KIND.items() if request.user.has_permissions([perm])]
        qs = ApprovalRequest.objects.select_related("requested_by", "decided_by").filter(
            Q(requested_by=request.user) | Q(kind__in=kinds))
        if st := request.query_params.get("status"):
            qs = qs.filter(status__in=st.split(","))
        if obj := request.query_params.get("object_id"):
            qs = qs.filter(object_id__in=[o.strip() for o in obj.split(",")[:50] if o.strip()])
        return self.paginate(qs.order_by("-created_at"), ApprovalSerializer)


class ApprovalDecideView(PermissionedView):
    permission_classes = [IsAuthenticatedWithCurrentPassword]

    def post(self, request, pk, action):
        req = get_object_or_404(ApprovalRequest, pk=pk)
        if action == "withdraw":
            req = services.cancel(self.ctx(), req)
        elif action in ("approve", "reject"):
            req = services.decide(self.ctx(), req, approve=action == "approve", note=str(request.data.get("note", "")))
        else:
            return Response({"error": {"code": "not_found", "message": "Unknown action."}}, status=404)
        return Response(ApprovalSerializer(req, context={"request": request}).data)
