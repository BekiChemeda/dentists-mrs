from django.urls import path

from . import api, attachments

urlpatterns = [
    path("patients/", api.PatientListCreateView.as_view()),
    path("patients/duplicate-check/", api.PatientDuplicateCheckView.as_view()),
    path("patients/<uuid:pk>/", api.PatientDetailView.as_view()),
    path("patients/<uuid:pk>/history/", api.PatientHistoryView.as_view()),
    path("patients/<uuid:pk>/card-qr/", api.PatientCardQrView.as_view()),
    path("patients/<uuid:pk>/merge/", api.PatientMergeView.as_view()),
    path("patients/<uuid:pk>/deactivate/", api.PatientDeactivateView.as_view()),
    path("patients/<uuid:pk>/reactivate/", api.PatientReactivateView.as_view()),
    path("patients/<uuid:pk>/emergency-contacts/", api.EmergencyContactsView.as_view()),
    path("patients/<uuid:patient_id>/attachments/", attachments.PatientAttachmentsView.as_view()),
    path("attachments/<uuid:pk>/file/", attachments.AttachmentFileView.as_view()),
    path("attachments/<uuid:pk>/remove/", attachments.AttachmentRemoveView.as_view()),
    path("patients/<uuid:pk>/allergies/", api.AllergyCreateView.as_view()),
    path("patients/<uuid:pk>/allergies/<uuid:allergy_id>/inactivate/", api.AllergyInactivateView.as_view()),
]
