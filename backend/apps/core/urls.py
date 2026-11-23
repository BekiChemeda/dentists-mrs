from django.urls import path

from .api import ClinicSettingsView, SetupChecklistView
from .branding import ClinicLogoManageView, ClinicLogoView
from apps.notifications.email_api import urlpatterns as email_urls

from .system import urlpatterns as system_urls
from .views import CsrfView, HealthView

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("auth/csrf/", CsrfView.as_view(), name="csrf"),
    path("settings/clinic/", ClinicSettingsView.as_view(), name="clinic-settings"),
    path("settings/setup-checklist/", SetupChecklistView.as_view(), name="setup-checklist"),
    path("settings/clinic/logo/", ClinicLogoManageView.as_view(), name="clinic-logo-manage"),
    path("branding/logo/", ClinicLogoView.as_view(), name="clinic-logo"),
] + system_urls + email_urls
