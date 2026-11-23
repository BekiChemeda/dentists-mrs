from django.urls import path, re_path

from . import api

urlpatterns = [
    path("vitals/", api.VitalsView.as_view()),
    path("visits/<uuid:visit_id>/vitals/", api.VitalsView.as_view()),
    path("visits/<uuid:visit_id>/vitals/preview/", api.VitalsPreviewView.as_view()),
    path("visits/<uuid:visit_id>/encounters/", api.StartEncounterView.as_view()),
    path("encounters/", api.EncounterListView.as_view()),
    path("encounters/<uuid:pk>/", api.EncounterDetailView.as_view()),
    path("encounters/<uuid:pk>/sign/", api.SignEncounterView.as_view()),
    path("encounters/<uuid:pk>/amendments/", api.AmendEncounterView.as_view()),
    path("encounters/<uuid:pk>/diagnoses/", api.DiagnosisCreateView.as_view()),
    path("encounters/<uuid:pk>/prescriptions/", api.PrescriptionCreateView.as_view()),
    path("diagnoses/<uuid:pk>/remove/", api.DiagnosisRemoveView.as_view()),
    path("icd-codes/", api.IcdSearchView.as_view()),
    path("encounters/<uuid:pk>/referrals/", api.EncounterReferralsView.as_view()),
    path("encounters/<uuid:pk>/certificates/", api.EncounterCertificatesView.as_view()),
    path("encounters/<uuid:pk>/internal-referrals/", api.EncounterInternalReferralsView.as_view()),
    path("internal-referrals/<uuid:pk>/cancel/", api.InternalReferralCancelView.as_view()),
    path("visits/<uuid:visit_id>/internal-referrals/", api.VisitInternalReferralView.as_view()),
    path("patients/<uuid:patient_id>/documents/", api.PatientDocumentsView.as_view()),
    path("patients/<uuid:patient_id>/diagnoses/", api.PatientDiagnosesView.as_view()),
    path("patients/<uuid:patient_id>/clinical-summary/", api.PatientClinicalSummaryView.as_view()),
    re_path(r"^(?P<kind>referrals|certificates)/(?P<pk>[0-9a-f-]{36})/cancel/$", api.DocumentCancelView.as_view()),
    path("prescriptions/", api.PrescriptionListView.as_view()),
    path("prescriptions/<uuid:pk>/cancel/", api.PrescriptionCancelView.as_view()),
]
