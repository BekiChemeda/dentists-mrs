from django.apps import AppConfig


class DentalConfig(AppConfig):
    name = "apps.dental"
    label = "dental"
    verbose_name = "Dental records"

    def ready(self):
        # Dental reports join the shared report registry (Reports page, CSV export, permissions).
        from apps.reports.reports import REPORTS

        from .reports import DENTAL_REPORTS

        REPORTS.update({r.key: r for r in DENTAL_REPORTS})
