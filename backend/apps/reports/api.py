import csv
import datetime
import io
from decimal import Decimal

from django.http import HttpResponse
from django.urls import path
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.audit.services import record_event
from apps.core.api import PermissionedView
from apps.core.exceptions import BusinessValidationError
from apps.core.permissions import IsAuthenticatedWithCurrentPassword

from .reports import REPORTS

MAX_RANGE_DAYS = 366


def _serialise(value):
    if isinstance(value, Decimal):
        return f"{value:.2f}" if value == value.quantize(Decimal("0.01")) else f"{value.normalize():f}"
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return value


class ReportCatalogView(PermissionedView):
    permission_classes = [IsAuthenticatedWithCurrentPassword]

    def get(self, request):
        return Response([
            {"key": r.key, "title": r.title, "description": r.description, "uses_dates": r.uses_dates,
             "by_department": r.by_department}
            for r in REPORTS.values() if request.user.has_permissions([r.permission])
        ])


class ReportRunView(PermissionedView):
    permission_classes = [IsAuthenticatedWithCurrentPassword]

    def get(self, request, key):
        report = REPORTS.get(key)
        if report is None:
            return Response({"error": {"code": "not_found", "message": "Unknown report."}}, status=404)
        if not request.user.has_permissions([report.permission]):
            raise PermissionDenied()
        today = timezone.localdate()
        date_to = self.param_date("date_to") or today
        date_from = self.param_date("date_from") or date_to.replace(day=1)
        if date_from > date_to:
            raise BusinessValidationError("The start date is after the end date.", fields={"date_from": ["Invalid range."]})
        if (date_to - date_from).days > MAX_RANGE_DAYS:
            raise BusinessValidationError("Choose a range of one year or less.", fields={"date_from": ["Range too long."]})
        dept = (request.query_params.get("department") or "").strip() or None
        dept_name = ""
        if dept:
            from apps.accounts.models import Department

            if not report.by_department:
                raise BusinessValidationError("This report cannot be filtered by department.",
                                              fields={"department": ["Not available for this report."]})
            found = Department.objects.filter(code=dept).first()
            if found is None:
                raise BusinessValidationError("Unknown department.", fields={"department": ["Unknown department."]})
            dept_name = found.name
        rows = report.run(date_from, date_to, dept=dept) if report.by_department else report.run(date_from, date_to)

        if request.query_params.get("export") == "csv":
            if not request.user.has_permissions(["reports.export"]):
                raise PermissionDenied()
            buffer = io.StringIO()
            buffer.write("﻿")  # BOM so Excel opens UTF-8 (Amharic names) correctly
            writer = csv.writer(buffer)
            writer.writerow([c.label for c in report.columns])
            for row in rows:
                writer.writerow([_serialise(row.get(c.key)) for c in report.columns])
            record_event(self.ctx(), action="report.export", object_type="report", object_id=key,
                         details={"format": "csv", "rows": len(rows), "date_from": date_from.isoformat(),
                                  "date_to": date_to.isoformat(), "department": dept or ""})
            response = HttpResponse(buffer.getvalue(), content_type="text/csv; charset=utf-8")
            suffix = f"_{dept}" if dept else ""
            response["Content-Disposition"] = f'attachment; filename="{key}{suffix}_{date_from}_{date_to}.csv"'
            response["Cache-Control"] = "no-store"
            return response

        return Response({
            "key": report.key, "title": report.title, "description": report.description,
            "date_from": date_from, "date_to": date_to, "uses_dates": report.uses_dates,
            "by_department": report.by_department, "department": dept or "", "department_name": dept_name,
            "generated_at": timezone.now(),
            "columns": [{"key": c.key, "label": c.label, "kind": c.kind} for c in report.columns],
            "rows": [{k: _serialise(v) for k, v in row.items()} for row in rows],
            "can_export": request.user.has_permissions(["reports.export"]),
        })


urlpatterns = [
    path("reports/", ReportCatalogView.as_view()),
    path("reports/<str:key>/", ReportRunView.as_view()),
]
