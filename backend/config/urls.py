from django.urls import include, path

# The Django admin is intentionally not mounted: every change must go through the
# API services so that permission checks and audit records are never bypassed.
urlpatterns = [
    path("api/v1/", include("apps.core.urls")),
    path("api/v1/", include("apps.accounts.urls")),
    path("api/v1/", include("apps.audit.urls")),
    path("api/v1/", include("apps.notifications.api")),
    path("api/v1/", include("apps.approvals.urls")),
    path("api/v1/", include("apps.patients.urls")),
    path("api/v1/", include("apps.scheduling.urls")),
    path("api/v1/", include("apps.clinical.urls")),
    path("api/v1/", include("apps.inventory.urls")),
    path("api/v1/", include("apps.laboratory.api")),
    path("api/v1/", include("apps.pharmacy.api")),
    path("api/v1/", include("apps.payments.api")),  # before billing: billing/invoices/<id>/pay-by-phone/
    path("api/v1/", include("apps.billing.api")),
    path("api/v1/", include("apps.reports.api")),
    path("api/v1/", include("apps.devices.api")),
]
