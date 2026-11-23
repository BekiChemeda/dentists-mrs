from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response

from apps.accounts.models import User
from apps.audit.services import record_event
from apps.core.api import PermissionedView, validated
from apps.core.exceptions import BusinessValidationError, ConflictError
from apps.core.permissions import AnyOf
from apps.patients.models import Patient

from . import completion, services
from .models import Appointment, AppointmentType, Holiday, Visit, VisitEvent
from apps.core.concurrency import bump_version, guarded_edit


class PatientBrief(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    age = serializers.SerializerMethodField()
    address = serializers.SerializerMethodField()

    class Meta:
        model = Patient
        fields = ["id", "mrn", "full_name", "sex", "birth_date", "age", "phone", "address"]

    def get_address(self, obj) -> str:
        return ", ".join(x for x in (obj.kebele and f"Kebele {obj.kebele}", obj.subcity_woreda, obj.city) if x)

    def get_age(self, obj) -> int:
        from apps.patients.api import age_of

        return age_of(obj.birth_date)


class UserBrief(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = ["id", "full_name", "username"]


class AppointmentSerializer(serializers.ModelSerializer):
    patient = PatientBrief(read_only=True)
    doctor = UserBrief(read_only=True)
    visit_id = serializers.SerializerMethodField()
    visit_status = serializers.SerializerMethodField()
    display_status = serializers.SerializerMethodField()
    service = serializers.SerializerMethodField()
    appointment_type = serializers.SerializerMethodField()
    room = serializers.SerializerMethodField()

    class Meta:
        model = Appointment
        fields = ["id", "patient", "doctor", "scheduled_at", "scheduled_date", "duration_minutes", "reason", "notes",
                  "service", "appointment_type", "room", "status", "display_status", "confirmed_at",
                  "reschedule_count", "cancel_reason", "visit_id", "visit_status", "source_encounter", "created_at"]

    def get_appointment_type(self, obj):
        t = obj.appointment_type
        return {"id": str(t.pk), "code": t.code, "name": t.name, "category": t.category} if t else None

    def get_room(self, obj):
        return {"id": str(obj.room_id), "name": obj.room.name} if obj.room_id else None

    def _visit(self, obj):
        try:
            return obj.visit
        except Visit.DoesNotExist:
            return None

    def get_visit_id(self, obj):
        visit = self._visit(obj)
        return str(visit.pk) if visit else None

    def get_visit_status(self, obj):
        visit = self._visit(obj)
        return visit.status if visit else None

    def get_display_status(self, obj) -> str:
        """The appointment's own status, refined by the visit once the patient has arrived."""
        visit = self._visit(obj)
        if obj.status == Appointment.Status.ARRIVED and visit and visit.status == Visit.Status.IN_CONSULTATION:
            return "in_consultation"
        return obj.status

    def get_service(self, obj):
        return {"id": str(obj.service_id), "name": obj.service.name} if obj.service_id else None


class VisitSerializer(serializers.ModelSerializer):
    patient = PatientBrief(read_only=True)
    assigned_doctor = UserBrief(read_only=True)
    called_by = UserBrief(read_only=True)
    completed_by = UserBrief(read_only=True)
    waiting_minutes = serializers.SerializerMethodField()
    has_vitals = serializers.SerializerMethodField()
    triage = serializers.SerializerMethodField()
    diagnoses = serializers.SerializerMethodField()
    encounters = serializers.SerializerMethodField()

    class Meta:
        model = Visit
        fields = ["id", "patient", "visit_date", "queue_number", "kind", "status", "priority", "assigned_doctor",
                  "arrived_at", "consultation_started_at", "completed_at", "completed_by", "outcome",
                  "completion_note", "cancel_reason", "called_at", "called_by", "called_room", "skipped_at", "skip_reason",
                  "waiting_minutes", "has_vitals", "triage", "diagnoses", "encounters", "dental_encounters",
                  "appointment", "department", "internal_referral"]

    internal_referral = serializers.SerializerMethodField()

    def get_internal_referral(self, obj):
        """The waiting internal referral, if any: shown on the receiving department's waiting list."""
        refs = [r for r in obj.internal_referrals.all() if r.status == "pending"]
        if not refs:
            return None
        r = refs[0]
        return {"id": str(r.pk), "from_department": r.from_department, "urgency": r.urgency, "reason": r.reason,
                "referred_by": r.referred_by.full_name, "created_at": r.created_at}

    def get_waiting_minutes(self, obj) -> int | None:
        if obj.status not in Visit.WAITING and obj.status != Visit.Status.IN_CONSULTATION:
            return None
        start = obj.consultation_started_at if obj.status == Visit.Status.IN_CONSULTATION else obj.arrived_at
        return int((timezone.now() - start).total_seconds() // 60)

    def get_has_vitals(self, obj) -> bool:
        annotated = getattr(obj, "vitals_count", None)
        return bool(annotated) if annotated is not None else obj.vital_signs.exists()

    def get_triage(self, obj):
        """The latest triage, for the waiting list: when it was done, the complaint and where the patient was sent."""
        latest = max(obj.vital_signs.all(), key=lambda v: v.recorded_at, default=None)
        if latest is None:
            return None
        return {"recorded_at": latest.recorded_at, "chief_complaint": latest.chief_complaint,
                "complaint_duration": latest.complaint_duration, "triage_to": latest.triage_to,
                "general_appearance": latest.general_appearance}

    def get_encounters(self, obj) -> list[dict]:
        return [{"id": str(e.pk), "doctor_id": str(e.doctor_id), "status": e.status}
                for e in sorted(obj.encounters.all(), key=lambda e: e.created_at)]

    dental_encounters = serializers.SerializerMethodField()

    def get_dental_encounters(self, obj) -> list[dict]:
        return [{"id": str(e.pk), "dentist_id": str(e.dentist_id), "status": e.status}
                for e in sorted(obj.dental_encounters.all(), key=lambda e: e.created_at)]

    def get_diagnoses(self, obj) -> list[dict]:
        return [{"code": d.icd_id or "", "description": d.description}
                for e in obj.encounters.all() for d in e.diagnoses.all() if not d.is_removed]


def _patient(pk) -> Patient:
    return get_object_or_404(Patient, pk=pk)  # services refuse inactive records with a clear message


def _doctor(pk):
    return get_object_or_404(User, pk=pk) if pk else None


class DoctorListView(PermissionedView):
    required_permissions = {"GET": ("appointments.view",)}

    def get(self, request):
        return Response(UserBrief(services.doctors(), many=True).data)


class AppointmentInput(serializers.Serializer):
    patient_id = serializers.UUIDField()
    doctor_id = serializers.UUIDField()
    scheduled_at = serializers.DateTimeField()
    duration_minutes = serializers.IntegerField(min_value=5, max_value=240, required=False, allow_null=True)
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    notes = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")
    service_id = serializers.UUIDField(required=False, allow_null=True)
    appointment_type_id = serializers.UUIDField(required=False, allow_null=True)
    room_id = serializers.UUIDField(required=False, allow_null=True)
    # Set when a doctor books a follow-up from a consultation.
    encounter_id = serializers.UUIDField(required=False, allow_null=True)


class RescheduleInput(serializers.Serializer):
    scheduled_at = serializers.DateTimeField()
    duration_minutes = serializers.IntegerField(min_value=5, max_value=240, required=False)
    doctor_id = serializers.UUIDField(required=False, allow_null=True)
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    room_id = serializers.UUIDField(required=False, allow_null=True)


def _room(pk):
    from apps.accounts.models import Room

    return get_object_or_404(Room, pk=pk) if pk else None


def _appointment_type(pk):
    return get_object_or_404(AppointmentType, pk=pk) if pk else None


def _service(pk):
    from apps.billing.models import ServicePrice

    return get_object_or_404(ServicePrice, pk=pk) if pk else None


class AppointmentListCreateView(PermissionedView):
    required_permissions = {"GET": ("appointments.view",), "POST": ("appointments.manage",)}

    def get(self, request):
        qs = Appointment.objects.select_related("patient", "doctor", "visit", "service", "appointment_type", "room")
        day = self.param_date("date")
        if day:
            qs = qs.filter(scheduled_date=day)
        date_from, date_to = self.param_date("date_from"), self.param_date("date_to")
        if date_from:
            qs = qs.filter(scheduled_date__gte=date_from)
        if date_to:
            qs = qs.filter(scheduled_date__lte=date_to)
        if doctor := self.param_uuid("doctor"):
            qs = qs.filter(doctor_id=doctor)
        if patient := self.param_uuid("patient"):
            qs = qs.filter(patient_id=patient)
        if room := self.param_uuid("room"):
            qs = qs.filter(room_id=room)
        if st := request.query_params.get("status"):
            qs = qs.filter(status=st)
        return self.paginate(qs.order_by("scheduled_at"), AppointmentSerializer)

    def post(self, request):
        data = validated(AppointmentInput, request.data)
        encounter = None
        if data.get("encounter_id"):
            from apps.clinical.models import Encounter

            encounter = get_object_or_404(Encounter, pk=data["encounter_id"])
            if encounter.patient_id != data["patient_id"]:
                return Response({"error": {"code": "validation_error",
                                           "message": "The consultation belongs to another patient."}}, status=400)
        appt = services.book_appointment(self.ctx(), patient=_patient(data["patient_id"]),
                                         doctor=_doctor(data["doctor_id"]), scheduled_at=data["scheduled_at"],
                                         duration_minutes=data.get("duration_minutes"), reason=data["reason"],
                                         notes=data["notes"], service=_service(data.get("service_id")),
                                         source_encounter=encounter,
                                         appointment_type=_appointment_type(data.get("appointment_type_id")),
                                         room=_room(data.get("room_id")))
        return Response(AppointmentSerializer(appt).data, status=status.HTTP_201_CREATED)


class AppointmentActionView(PermissionedView):
    required_permissions = {"POST": ("appointments.manage",)}

    def post(self, request, pk, action):
        appt = get_object_or_404(Appointment, pk=pk)
        reason = str(request.data.get("reason", ""))
        if action == "cancel":
            services.cancel_appointment(self.ctx(), appt, reason)
        elif action == "confirm":
            services.confirm_appointment(self.ctx(), appt)
        elif action == "reschedule":
            data = validated(RescheduleInput, request.data)
            extra = {"room": _room(data["room_id"])} if "room_id" in data else {}
            services.reschedule_appointment(self.ctx(), appt, scheduled_at=data["scheduled_at"],
                                            duration_minutes=data.get("duration_minutes"),
                                            doctor=_doctor(data.get("doctor_id")), reason=data["reason"], **extra)
        elif action == "no-show":
            services.cancel_appointment(self.ctx(), appt, reason, no_show=True)
        elif action == "check-in":
            if not request.user.has_permissions(["queue.manage"]):
                return Response({"error": {"code": "permission_denied", "message": "You cannot check patients in."}},
                                status=403)
            visit = services.check_in(self.ctx(), appt)
            return Response(VisitSerializer(visit).data, status=status.HTTP_201_CREATED)
        else:
            return Response({"error": {"code": "not_found", "message": "Unknown action."}}, status=404)
        appt.refresh_from_db()
        return Response(AppointmentSerializer(appt).data)


class WalkInInput(serializers.Serializer):
    patient_id = serializers.UUIDField()
    doctor_id = serializers.UUIDField(required=False, allow_null=True)
    priority = serializers.ChoiceField(choices=Visit.Priority.choices, default=Visit.Priority.ROUTINE)


def _visit_qs():
    from django.db.models import Count

    return (Visit.objects.select_related("patient", "assigned_doctor", "called_by", "completed_by")
            .prefetch_related("vital_signs", "encounters__diagnoses", "internal_referrals__referred_by",
                              "dental_encounters")
            .annotate(vitals_count=Count("vital_signs", distinct=True)))


class VisitListCreateView(PermissionedView):
    """GET is the queue (and visit history); POST registers a walk-in."""

    required_permissions = {"GET": ("patients.view",), "POST": ("queue.manage",)}

    def get(self, request):
        qs = _visit_qs()
        if patient := self.param_uuid("patient"):
            qs = qs.filter(patient_id=patient).order_by("-visit_date", "-queue_number")
        elif self.param_bool("stale"):
            # Visits from earlier days that were never closed: they need completing or cancelling.
            qs = qs.filter(visit_date__lt=timezone.localdate(), status__in=Visit.OPEN).order_by("visit_date", "queue_number")
            return Response(VisitSerializer(qs[:200], many=True).data)
        else:
            qs = qs.filter(visit_date=self.param_date("date") or timezone.localdate())
            qs = qs.order_by("queue_number")
            if statuses := request.query_params.get("status"):
                qs = qs.filter(status__in=statuses.split(","))
            if doctor := self.param_uuid("doctor"):
                qs = qs.filter(Q(assigned_doctor_id=doctor) | Q(assigned_doctor__isnull=True))
            if self.param_bool("open"):
                qs = qs.filter(status__in=Visit.OPEN)
            rows = sorted(qs[:500], key=services.queue_order)
            return Response(VisitSerializer(rows, many=True).data)
        return self.paginate(qs, VisitSerializer)

    def post(self, request):
        data = validated(WalkInInput, request.data)
        visit = services.register_walk_in(self.ctx(), patient=_patient(data["patient_id"]),
                                          doctor=_doctor(data.get("doctor_id")), priority=data["priority"])
        return Response(VisitSerializer(_visit_qs().get(pk=visit.pk)).data, status=status.HTTP_201_CREATED)


class VisitUpdateInput(serializers.Serializer):
    status = serializers.ChoiceField(choices=Visit.Status.choices, required=False)
    doctor_id = serializers.UUIDField(required=False, allow_null=True)
    priority = serializers.ChoiceField(choices=Visit.Priority.choices, required=False)
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class VisitDetailView(PermissionedView):
    required_permissions = {"GET": ("patients.view",), "PATCH": ("queue.manage",)}

    def get(self, request, pk):
        return Response(VisitSerializer(get_object_or_404(_visit_qs(), pk=pk)).data)

    def patch(self, request, pk):
        visit = get_object_or_404(Visit, pk=pk)
        data = validated(VisitUpdateInput, request.data)
        kwargs = {"status": data.get("status"), "priority": data.get("priority"), "reason": data["reason"]}
        if "doctor_id" in data:
            kwargs["doctor"] = _doctor(data["doctor_id"])
        services.update_queue_entry(self.ctx(), visit, **kwargs)
        return Response(VisitSerializer(_visit_qs().get(pk=pk)).data)


QUEUE_STAFF = AnyOf(("queue.manage", "triage.record", "clinical.write", "dental.write"))


class VisitActionInput(serializers.Serializer):
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class CompleteVisitInput(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=Visit.Outcome.choices)
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    acknowledge_outstanding = serializers.BooleanField(default=False)


class VisitActionView(PermissionedView):
    """POST visits/<id>/<action>/: call, skip, return, complete, reopen."""

    required_permissions = {"POST": QUEUE_STAFF}

    def post(self, request, pk, action):
        visit = get_object_or_404(Visit, pk=pk)
        ctx = self.ctx()
        if action == "call":
            services.call_patient(ctx, visit)
        elif action == "skip":
            services.skip_patient(ctx, visit, validated(VisitActionInput, request.data)["reason"])
        elif action == "return":
            services.return_to_queue(ctx, visit)
        elif action in ("complete", "reopen"):
            if not request.user.has_any_permission(["queue.manage", "clinical.write", "dental.write"]):
                return Response({"error": {"code": "permission_denied",
                                           "message": "You cannot complete or reopen visits."}}, status=403)
            if action == "complete":
                data = validated(CompleteVisitInput, request.data)
                completion.complete_visit(ctx, visit, outcome=data["outcome"], note=data["note"],
                                          acknowledge_outstanding=data["acknowledge_outstanding"])
            else:
                from django.db import transaction

                with transaction.atomic():
                    if visit.visit_date != timezone.localdate():
                        return Response({"error": {"code": "conflict",
                                                   "message": "Only today's visits can be reopened."}}, status=409)
                    services.transition_visit(ctx, visit, Visit.Status.AFTER_CONSULTATION,
                                              reason=validated(VisitActionInput, request.data)["reason"])
        else:
            return Response({"error": {"code": "not_found", "message": "Unknown action."}}, status=404)
        return Response(VisitSerializer(_visit_qs().get(pk=pk)).data)


class CallNextView(PermissionedView):
    required_permissions = {"POST": QUEUE_STAFF}

    def post(self, request):
        stage = str(request.data.get("stage", ""))
        visit = services.call_next(self.ctx(), stage=stage)
        if visit is None:
            return Response({"visit": None, "message": "Nobody is waiting."})
        return Response({"visit": VisitSerializer(_visit_qs().get(pk=visit.pk)).data})


class VisitEventSerializer(serializers.ModelSerializer):
    actor = UserBrief(read_only=True)

    class Meta:
        model = VisitEvent
        fields = ["id", "at", "actor", "kind", "summary"]


class VisitTimelineView(PermissionedView):
    required_permissions = {"GET": ("patients.view",)}

    def get(self, request, pk):
        visit = get_object_or_404(Visit, pk=pk)
        events = VisitEvent.objects.filter(visit=visit).select_related("actor")
        return Response(VisitEventSerializer(events, many=True).data)


class VisitOutstandingView(PermissionedView):
    required_permissions = {"GET": QUEUE_STAFF}

    def get(self, request, pk):
        visit = get_object_or_404(Visit, pk=pk)
        return Response(completion.outstanding_for(visit).as_dict())


# ---------------------------------------------------------------------------
# Calendar: appointment load per day and holidays
# ---------------------------------------------------------------------------
class HolidaySerializer(serializers.Serializer):
    row_version = serializers.IntegerField(read_only=True)
    date = serializers.DateField()
    name = serializers.CharField(max_length=120)
    kind = serializers.ChoiceField(choices=Holiday.Kind.choices)
    tentative = serializers.BooleanField(default=False)
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class CalendarView(PermissionedView):
    """GET calendar/?date_from=&date_to=[&doctor=]: appointments per day by status, plus holidays."""

    required_permissions = {"GET": ("appointments.view",)}

    def get(self, request):
        from django.db.models import Count

        from .holidays import holidays_between

        start, end = self.param_date("date_from"), self.param_date("date_to")
        if not start or not end or start > end or (end - start).days > 62:
            raise BusinessValidationError("Give a date range of at most 62 days.", fields={"date_from": ["Invalid."]})
        qs = Appointment.objects.filter(scheduled_date__range=(start, end))
        if doctor := self.param_uuid("doctor"):
            qs = qs.filter(doctor_id=doctor)
        days: dict = {}
        for row in qs.values("scheduled_date", "status").annotate(n=Count("id")):
            d = days.setdefault(row["scheduled_date"].isoformat(), {"total": 0, "by_status": {}})
            d["by_status"][row["status"]] = row["n"]
            if row["status"] in Appointment.ACTIVE or row["status"] == Appointment.Status.COMPLETED:
                d["total"] += row["n"]
        doctors = services.doctors().count()
        return Response({"days": days, "holidays": holidays_between(start, end), "doctors": doctors})


class HolidayListCreateView(PermissionedView):
    required_permissions = {"POST": ("settings.manage",)}

    def post(self, request):
        data = validated(HolidaySerializer, request.data)
        if Holiday.objects.filter(date=data["date"], name__iexact=data["name"]).exists():
            raise ConflictError("This holiday is already on that day.")
        h = Holiday.objects.create(created_by=request.user, **data)
        record_event(self.ctx(), action="holiday.create", object_type="holiday", object_id=h.pk,
                     details={k: str(v) for k, v in data.items()})
        return Response({"id": h.pk, **HolidaySerializer(h).data}, status=status.HTTP_201_CREATED)


class HolidayDetailView(PermissionedView):
    required_permissions = {"PATCH": ("settings.manage",), "DELETE": ("settings.manage",)}

    def patch(self, request, pk):
        data = validated(HolidaySerializer, request.data, partial=True)
        with guarded_edit(Holiday, pk, request, object_type="holiday", label="holiday") as h:
            before = HolidaySerializer(h).data
            for k, v in data.items():
                setattr(h, k, v)
            h.save()
            record_event(self.ctx(), action="holiday.update", object_type="holiday", object_id=h.pk,
                         details={"from": {k: str(v) for k, v in before.items() if k in data},
                                  "to": {k: str(v) for k, v in data.items()}})
        return Response({"id": h.pk, **HolidaySerializer(h).data})

    def delete(self, request, pk):
        h = get_object_or_404(Holiday, pk=pk)
        record_event(self.ctx(), action="holiday.delete", object_type="holiday", object_id=h.pk,
                     details={"date": str(h.date), "name": h.name})
        h.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AppointmentTypeSerializer(serializers.ModelSerializer):
    default_room = serializers.SerializerMethodField()
    default_room_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)
    code = serializers.SlugField(max_length=40)

    class Meta:
        model = AppointmentType
        fields = ["id", "code", "name", "category", "default_minutes", "default_room", "default_room_id", "is_active",
                  "sort_order", "row_version"]
        read_only_fields = ["row_version"]

    def get_default_room(self, obj):
        return {"id": str(obj.default_room_id), "name": obj.default_room.name} if obj.default_room_id else None

    def validate_default_minutes(self, value):
        if not 5 <= value <= 240:
            raise serializers.ValidationError("Between 5 and 240 minutes.")
        return value


APPT_TYPE_ADMIN = AnyOf(("dental.catalog.manage", "settings.manage"))


class AppointmentTypeListView(PermissionedView):
    """Appointment types: everyone who books sees the active ones; catalogue managers maintain them."""

    required_permissions = {"GET": AnyOf(("appointments.view", "dental.catalog.manage", "settings.manage")),
                            "POST": APPT_TYPE_ADMIN}

    def get(self, request):
        qs = AppointmentType.objects.select_related("default_room")
        if not self.param_bool("all"):
            qs = qs.filter(is_active=True)
        return Response(AppointmentTypeSerializer(qs, many=True).data)

    def post(self, request):
        data = validated(AppointmentTypeSerializer, request.data)
        appt_type = services.save_appointment_type(self.ctx(), data, room=_room(data.pop("default_room_id", None)))
        return Response(AppointmentTypeSerializer(appt_type).data, status=status.HTTP_201_CREATED)


class AppointmentTypeDetailView(PermissionedView):
    required_permissions = {"PATCH": APPT_TYPE_ADMIN}

    def patch(self, request, pk):
        data = validated(AppointmentTypeSerializer, request.data, partial=True)
        with guarded_edit(AppointmentType, pk, request, object_type="appointment_type",
                          label="appointment type") as appt_type:
            room = _room(data.pop("default_room_id")) if "default_room_id" in data else ...
            services.save_appointment_type(self.ctx(), data, appt_type=appt_type, room=room)
        return Response(AppointmentTypeSerializer(AppointmentType.objects.get(pk=pk)).data)
