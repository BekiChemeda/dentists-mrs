from django.urls import path, re_path

from .api import ortho_views as ov
from .api import views as v

UUID = r"[0-9a-f-]{36}"

urlpatterns = [
    # Catalogues
    path("dental/catalog/", v.CatalogView.as_view()),
    path("dental/finding-types/", v.FindingTypeListView.as_view()),
    path("dental/finding-types/<uuid:pk>/", v.FindingTypeDetailView.as_view()),
    path("dental/diagnosis-terms/", v.DiagnosisTermListView.as_view()),
    path("dental/diagnosis-terms/<uuid:pk>/", v.DiagnosisTermDetailView.as_view()),
    path("dental/procedures/", v.ProcedureListView.as_view()),
    path("dental/procedures/<uuid:pk>/", v.ProcedureDetailView.as_view()),
    path("dental/procedures/<uuid:pk>/materials/", v.ProcedureMaterialsView.as_view()),
    path("dental/clinicians/", v.ClinicianListView.as_view()),
    path("dental/technicians/", v.TechnicianListView.as_view()),
    # Patient-level record
    path("dental/patients/<uuid:patient_id>/summary/", v.PatientSummaryView.as_view()),
    path("dental/patients/<uuid:patient_id>/profile/", v.ProfileView.as_view()),
    path("dental/patients/<uuid:patient_id>/risk-reviews/", v.RiskReviewView.as_view()),
    path("dental/patients/<uuid:patient_id>/chart/", v.ChartView.as_view()),
    path("dental/patients/<uuid:patient_id>/chart/history/", v.ChartHistoryView.as_view()),
    path("dental/patients/<uuid:patient_id>/chart/compare/", v.ChartCompareView.as_view()),
    path("dental/patients/<uuid:patient_id>/diagnoses/", v.PatientDiagnosesView.as_view()),
    path("dental/patients/<uuid:patient_id>/perio/", v.PatientPerioView.as_view()),
    path("dental/patients/<uuid:patient_id>/plans/", v.PatientPlansView.as_view()),
    path("dental/patients/<uuid:patient_id>/images/", v.PatientImagesView.as_view()),
    path("dental/patients/<uuid:patient_id>/recalls/", v.PatientRecallsView.as_view()),
    path("dental/patients/<uuid:patient_id>/lab-cases/", v.PatientLabCasesView.as_view()),
    # Examinations
    path("dental/visits/<uuid:visit_id>/encounters/", v.StartEncounterView.as_view()),
    path("dental/encounters/", v.EncounterListView.as_view()),
    path("dental/encounters/<uuid:pk>/", v.EncounterDetailView.as_view()),
    path("dental/encounters/<uuid:pk>/sign/", v.SignEncounterView.as_view()),
    path("dental/encounters/<uuid:pk>/amendments/", v.AmendEncounterView.as_view()),
    path("dental/encounters/<uuid:pk>/diagnoses/", v.EncounterDiagnosisView.as_view()),
    path("dental/encounters/<uuid:pk>/findings/", v.EncounterFindingsView.as_view()),
    path("dental/encounters/<uuid:pk>/perio/", v.EncounterPerioView.as_view()),
    path("dental/encounters/<uuid:pk>/procedures/", v.EncounterProceduresView.as_view()),
    path("dental/encounters/<uuid:pk>/prescriptions/", v.EncounterPrescriptionView.as_view()),
    re_path(rf"^dental/diagnoses/(?P<pk>{UUID})/(?P<action>remove|resolve)/$", v.DiagnosisActionView.as_view()),
    path("dental/findings/<uuid:pk>/", v.FindingDetailView.as_view()),
    re_path(rf"^dental/findings/(?P<pk>{UUID})/(?P<action>resolve|void)/$", v.FindingActionView.as_view()),
    path("dental/perio/compare/", v.PerioCompareView.as_view()),
    # Treatment plans
    path("dental/plans/<uuid:pk>/", v.PlanDetailView.as_view()),
    path("dental/plans/<uuid:pk>/revisions/", v.PlanRevisionsView.as_view()),
    re_path(rf"^dental/plans/(?P<pk>{UUID})/(?P<action>items|present|decision|cancel|expire)/$",
            v.PlanActionView.as_view()),
    path("dental/plan-items/<uuid:pk>/", v.PlanItemView.as_view()),
    re_path(rf"^dental/plan-items/(?P<pk>{UUID})/(?P<action>remove|cancel|appointments)/$", v.PlanItemView.as_view()),
    # Procedure records
    path("dental/procedure-records/", v.ProcedureRecordListView.as_view()),
    path("dental/procedure-records/<uuid:pk>/", v.ProcedureRecordDetailView.as_view()),
    re_path(rf"^dental/procedure-records/(?P<pk>{UUID})/(?P<action>materials|sign|discard|amendments)/$",
            v.ProcedureRecordActionView.as_view()),
    # Imaging
    path("dental/images/<uuid:pk>/", v.ImageDetailView.as_view()),
    path("dental/images/<uuid:pk>/file/", v.ImageFileView.as_view()),
    path("dental/images/<uuid:pk>/withdraw/", v.ImageWithdrawView.as_view()),
    # Recalls
    path("dental/recalls/", v.RecallListView.as_view()),
    re_path(rf"^dental/recalls/(?P<pk>{UUID})/(?P<action>book|contact|status)/$", v.RecallActionView.as_view()),
    # Laboratory cases
    path("dental/lab-cases/", v.LabCaseListView.as_view()),
    path("dental/lab-cases/<uuid:pk>/", v.LabCaseDetailView.as_view()),
    re_path(rf"^dental/lab-cases/(?P<pk>{UUID})/(?P<action>move|assign)/$", v.LabCaseDetailView.as_view()),
    # Orthodontics
    path("dental/encounters/<uuid:pk>/ortho-assessment/", ov.EncounterOrthoAssessmentView.as_view()),
    path("dental/patients/<uuid:patient_id>/ortho/", ov.PatientOrthoView.as_view()),
    path("dental/patients/<uuid:patient_id>/ortho/cases/", ov.PatientOrthoCasesView.as_view()),
    path("dental/ortho/cases/", ov.OrthoCaseListView.as_view()),
    path("dental/ortho/cases/<uuid:pk>/", ov.OrthoCaseDetailView.as_view()),
    re_path(rf"^dental/ortho/cases/(?P<pk>{UUID})/(?P<action>visits|billing|start|retention|complete|discontinue)/$",
            ov.OrthoCaseDetailView.as_view()),
    path("dental/ortho/visits/<uuid:pk>/void/", ov.OrthoVisitVoidView.as_view()),
    path("dental/ortho/instalments/<uuid:pk>/bring-forward/", ov.OrthoInstalmentForwardView.as_view()),
]
