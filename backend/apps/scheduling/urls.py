from django.urls import path, re_path

from . import api

urlpatterns = [
    path("doctors/", api.DoctorListView.as_view()),
    path("calendar/", api.CalendarView.as_view()),
    path("calendar/holidays/", api.HolidayListCreateView.as_view()),
    path("calendar/holidays/<int:pk>/", api.HolidayDetailView.as_view()),
    path("appointment-types/", api.AppointmentTypeListView.as_view()),
    path("appointment-types/<uuid:pk>/", api.AppointmentTypeDetailView.as_view()),
    path("appointments/", api.AppointmentListCreateView.as_view()),
    path("appointments/<uuid:pk>/<str:action>/", api.AppointmentActionView.as_view()),
    path("visits/", api.VisitListCreateView.as_view()),
    path("visits/call-next/", api.CallNextView.as_view()),
    path("visits/<uuid:pk>/", api.VisitDetailView.as_view()),
    path("visits/<uuid:pk>/timeline/", api.VisitTimelineView.as_view()),
    path("visits/<uuid:pk>/outstanding/", api.VisitOutstandingView.as_view()),
    re_path(r"^visits/(?P<pk>[0-9a-f-]{36})/(?P<action>call|skip|return|complete|reopen)/$",
            api.VisitActionView.as_view()),
]
