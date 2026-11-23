from django.urls import path

from .api import AuditEventListView

urlpatterns = [
    path("audit-events/", AuditEventListView.as_view(), name="audit-event-list"),
]
