from django.urls import path

from . import api

urlpatterns = [
    path("approvals/", api.ApprovalListView.as_view()),
    path("approvals/<uuid:pk>/<str:action>/", api.ApprovalDecideView.as_view()),
]
