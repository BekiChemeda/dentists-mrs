from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404
from django.urls import path
from rest_framework import serializers, status
from rest_framework.response import Response

from apps.clinical.models import Encounter
from apps.core.api import PermissionedView, validated
from apps.core.permissions import AnyOf
from apps.scheduling.api import PatientBrief, UserBrief

from . import services
from .models import LabOrder, LabOrderItem, LabReferenceRange, LabResultAmendment, LabTest
from apps.core.concurrency import bump_version, guarded_edit


class RangeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LabReferenceRange
        fields = ["id", "sex", "age_min_days", "age_max_days", "ref_low", "ref_high", "ref_text", "critical_low",
                  "critical_high"]


class LabTestSerializer(serializers.ModelSerializer):
    ranges = RangeSerializer(many=True, read_only=True)
    answers = serializers.SerializerMethodField()

    class Meta:
        model = LabTest
        fields = ["id", "code", "name", "category", "specimen_type", "result_type", "unit", "ref_low", "ref_high",
                  "ref_text", "choices", "normal_choice", "critical_low", "critical_high", "critical_choices", "price",
                  "is_active", "ranges", "answers", "row_version"]

    def get_answers(self, obj) -> list[str]:
        return obj.choice_list()


class AmendmentSerializer(serializers.ModelSerializer):
    author = UserBrief(read_only=True)

    class Meta:
        model = LabResultAmendment
        fields = ["id", "previous_numeric", "previous_text", "previous_flag", "reason", "author", "created_at"]


class LabItemSerializer(serializers.ModelSerializer):
    test = LabTestSerializer(read_only=True)
    entered_by = UserBrief(read_only=True)
    verified_by = UserBrief(read_only=True)
    collected_by = UserBrief(read_only=True)
    critical_reported_by = UserBrief(read_only=True)
    critical_acknowledged_by = UserBrief(read_only=True)
    amendments = AmendmentSerializer(many=True, read_only=True)
    display_result = serializers.SerializerMethodField()
    is_critical = serializers.BooleanField(read_only=True)

    class Meta:
        model = LabOrderItem
        fields = ["id", "test", "status", "price", "is_chargeable", "repeat_of", "repeat_reason", "specimen_type",
                  "specimen_label", "collected_at", "collected_by", "result_numeric", "result_text", "display_result",
                  "unit", "ref_low", "ref_high", "ref_text", "critical_low", "critical_high", "flag", "is_critical",
                  "result_comment", "entered_by", "entered_at", "verified_by", "verified_at", "cancel_reason",
                  "critical_reported_to", "critical_reported_at", "critical_reported_by", "critical_acknowledged_at",
                  "critical_acknowledged_by", "amendments"]

    def get_display_result(self, obj) -> str:
        if obj.result_numeric is not None:
            return f"{obj.result_numeric.normalize():f}"
        return obj.result_text


class LabOrderSerializer(serializers.ModelSerializer):
    patient = PatientBrief(read_only=True)
    ordered_by = UserBrief(read_only=True)
    items = serializers.SerializerMethodField()

    class Meta:
        model = LabOrder
        fields = ["id", "accession_number", "patient", "visit", "encounter", "ordered_by", "priority", "status",
                  "clinical_notes", "external_requester", "external_facility", "created_at", "items"]

    def get_items(self, obj):
        # Unverified results are visible to the laboratory but not yet to clinicians.
        request = self.context.get("request")
        lab_user = request is not None and request.user.has_permissions(["lab.result.enter"])
        data = LabItemSerializer(obj.items.all(), many=True).data
        if not lab_user:
            for row in data:
                if row["status"] != LabOrderItem.Status.VERIFIED:
                    row.update(result_numeric=None, result_text="", display_result="", flag="", result_comment="",
                               is_critical=False)
        return data


def _order_qs():
    return LabOrder.objects.select_related("patient", "ordered_by").prefetch_related(
        Prefetch("items", queryset=LabOrderItem.objects.select_related(
            "test", "entered_by", "verified_by", "collected_by", "critical_reported_by", "critical_acknowledged_by")
            .prefetch_related("amendments__author", "test__ranges").order_by("test__name", "repeat_of_id")))


LAB_READ = AnyOf(("lab.view", "lab.result.enter", "clinical.view"))


class LabTestListCreateView(PermissionedView):
    required_permissions = {"GET": AnyOf(("lab.request", "lab.view", "lab.catalog.manage", "billing.invoice")),
                            "POST": ("lab.catalog.manage",)}

    def get(self, request):
        qs = LabTest.objects.prefetch_related("ranges")
        active = self.param_bool("active")
        if active is not None:
            qs = qs.filter(is_active=active)
        if q := request.query_params.get("q", "").strip():
            qs = qs.filter(Q(name__icontains=q) | Q(code__iexact=q) | Q(category__icontains=q))
        return Response(LabTestSerializer(qs.order_by("category", "name"), many=True).data)

    def post(self, request):
        s = LabTestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        test = services.save_test(self.ctx(), dict(s.validated_data))
        return Response(LabTestSerializer(test).data, status=status.HTTP_201_CREATED)


class LabTestDetailView(PermissionedView):
    required_permissions = {"PATCH": ("lab.catalog.manage",)}

    def patch(self, request, pk):
        with guarded_edit(LabTest, pk, request, object_type="lab_test", label="laboratory test") as test:
            s = LabTestSerializer(test, data=request.data, partial=True)
            s.is_valid(raise_exception=True)
            data = dict(s.validated_data)
            data.pop("code", None)
            saved = services.save_test(self.ctx(), data, test)
        return Response(LabTestSerializer(saved).data)


class OrderInput(serializers.Serializer):
    test_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False)
    priority = serializers.ChoiceField(choices=LabOrder.Priority.choices, default=LabOrder.Priority.ROUTINE)
    clinical_notes = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class EncounterLabOrderView(PermissionedView):
    required_permissions = {"POST": ("lab.request",)}

    def post(self, request, pk):
        data = validated(OrderInput, request.data)
        order = services.order_tests(self.ctx(), get_object_or_404(Encounter, pk=pk), **data)
        return Response(LabOrderSerializer(_order_qs().get(pk=order.pk), context={"request": request}).data,
                        status=status.HTTP_201_CREATED)


class LabOrderListView(PermissionedView):
    required_permissions = {"GET": LAB_READ}

    def get(self, request):
        qs = _order_qs()
        if patient := self.param_uuid("patient"):
            qs = qs.filter(patient_id=patient)
        if encounter := self.param_uuid("encounter"):
            qs = qs.filter(encounter_id=encounter)
        if visit := self.param_uuid("visit"):
            qs = qs.filter(visit_id=visit)
        if st := request.query_params.get("status"):
            qs = qs.filter(status__in=st.split(","))
        if q := request.query_params.get("q", "").strip():
            qs = qs.filter(Q(accession_number__iexact=q) | Q(patient__mrn__iexact=q)
                           | Q(patient__first_name__icontains=q))
        if day := self.param_date("date"):
            qs = qs.filter(created_at__date=day)
        order = ["-priority", "created_at"] if request.query_params.get("worklist") else ["-created_at"]
        return self.paginate(qs.order_by(*order), LabOrderSerializer)


class LabOrderDetailView(PermissionedView):
    required_permissions = {"GET": LAB_READ}

    def get(self, request, pk):
        return Response(LabOrderSerializer(get_object_or_404(_order_qs(), pk=pk), context={"request": request}).data)


class ResultInput(serializers.Serializer):
    value = serializers.CharField(max_length=500)
    comment = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    critical_reported_to = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")


class CollectInput(serializers.Serializer):
    label = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    specimen_type = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    collected_at = serializers.DateTimeField(required=False, allow_null=True, default=None)


class RepeatInput(serializers.Serializer):
    reason = serializers.CharField(max_length=255)
    chargeable = serializers.BooleanField(default=False)


class LabItemActionView(PermissionedView):
    PERMS = {"collect": ("lab.result.enter",), "result": ("lab.result.enter",), "verify": ("lab.result.verify",),
             "amend": ("lab.result.verify",), "cancel": AnyOf(("lab.result.enter", "lab.request")),
             "repeat": AnyOf(("lab.result.enter", "lab.request")), "acknowledge": ("clinical.write",)}

    @property
    def required_permissions(self):
        action = self.kwargs.get("action")
        return {"POST": self.PERMS[action]} if action in self.PERMS else {}

    def post(self, request, pk, action):
        item = get_object_or_404(LabOrderItem, pk=pk)
        ctx = self.ctx()
        if action == "collect":
            data = validated(CollectInput, request.data)
            services.collect_specimen(ctx, item, data["label"], specimen_type=data["specimen_type"],
                                      collected_at=data["collected_at"])
        elif action == "result":
            data = validated(ResultInput, request.data)
            services.enter_result(ctx, item, value=data["value"], comment=data["comment"])
        elif action == "verify":
            services.verify_result(ctx, item, critical_reported_to=str(request.data.get("critical_reported_to", "")))
        elif action == "amend":
            data = validated(ResultInput, request.data)
            services.amend_result(ctx, item, value=data["value"], reason=data["reason"], comment=data["comment"],
                                  critical_reported_to=data["critical_reported_to"])
        elif action == "repeat":
            data = validated(RepeatInput, request.data)
            # A clinician's repeat of a verified test can be charged; laboratory-caused repeats are not.
            chargeable = data["chargeable"] and request.user.has_permissions(["lab.request"])
            services.repeat_test(ctx, item, reason=data["reason"], chargeable=chargeable)
        elif action == "acknowledge":
            services.acknowledge_critical(ctx, item)
        elif action == "cancel":
            services.cancel_item(ctx, item, str(request.data.get("reason", "")))
        return Response(LabOrderSerializer(_order_qs().get(pk=item.order_id), context={"request": request}).data)


class LabTestRangesView(PermissionedView):
    """Replace a test's age- and sex-specific reference ranges in one go."""

    required_permissions = {"GET": AnyOf(("lab.view", "lab.catalog.manage")), "PUT": ("lab.catalog.manage",)}

    def get(self, request, pk):
        return Response(RangeSerializer(get_object_or_404(LabTest, pk=pk).ranges.all(), many=True).data)

    def put(self, request, pk):
        s = RangeSerializer(data=request.data, many=True)
        s.is_valid(raise_exception=True)
        # Guarded by the test's version (If-Match header); ranges count as a change to the test.
        with guarded_edit(LabTest, pk, request, object_type="lab_test", label="laboratory test") as test:
            rows = services.set_ranges(self.ctx(), test, [dict(r) for r in s.validated_data])
            bump_version(test)
        resp = Response(RangeSerializer(rows, many=True).data)
        resp["ETag"] = f'"{test.row_version}"'
        return resp


class CriticalResultsView(PermissionedView):
    """Critical results not yet acknowledged by a clinician (for dashboards)."""

    required_permissions = {"GET": AnyOf(("clinical.view", "lab.view"))}

    def get(self, request):
        qs = (LabOrderItem.objects.filter(status=LabOrderItem.Status.VERIFIED, flag__in=LabOrderItem.CRITICAL_FLAGS,
                                          critical_acknowledged_at__isnull=True)
              .select_related("test", "order__patient", "order__ordered_by").order_by("-verified_at")[:50])
        if self.param_bool("mine"):
            qs = [i for i in qs if i.order.ordered_by_id == request.user.pk]
        return Response([{"id": str(i.pk), "test": i.test.name, "result": i.display_value(), "unit": i.unit,
                          "flag": i.flag, "verified_at": i.verified_at, "patient": PatientBrief(i.order.patient).data,
                          "ordered_by": i.order.ordered_by.full_name, "reported_to": i.critical_reported_to}
                         for i in qs])


class LabOnlyInput(serializers.Serializer):
    patient_id = serializers.UUIDField()
    test_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=40)
    requested_by = serializers.CharField(max_length=120)
    requesting_facility = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    priority = serializers.ChoiceField(choices=LabOrder.Priority.choices, default=LabOrder.Priority.ROUTINE)
    clinical_notes = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class LabOnlyVisitView(PermissionedView):
    """POST lab/walk-in/: a patient who came only for tests requested elsewhere."""

    required_permissions = {"POST": AnyOf(("queue.manage", "lab.request"))}

    def post(self, request):
        from apps.patients.models import Patient
        from apps.scheduling.api import VisitSerializer

        data = validated(LabOnlyInput, request.data)
        patient = get_object_or_404(Patient, pk=data.pop("patient_id"), is_active=True)
        visit, order = services.register_lab_only_visit(self.ctx(), patient=patient, **data)
        return Response({"visit": VisitSerializer(visit).data,
                         "order": LabOrderSerializer(order, context={"request": request}).data},
                        status=status.HTTP_201_CREATED)


urlpatterns = [
    path("lab/walk-in/", LabOnlyVisitView.as_view()),
    path("lab/tests/<uuid:pk>/ranges/", LabTestRangesView.as_view()),
    path("lab/critical/", CriticalResultsView.as_view()),
    path("lab/tests/", LabTestListCreateView.as_view()),
    path("lab/tests/<uuid:pk>/", LabTestDetailView.as_view()),
    path("lab/orders/", LabOrderListView.as_view()),
    path("lab/orders/<uuid:pk>/", LabOrderDetailView.as_view()),
    path("lab/items/<uuid:pk>/<str:action>/", LabItemActionView.as_view()),
    path("encounters/<uuid:pk>/lab-orders/", EncounterLabOrderView.as_view()),
]
