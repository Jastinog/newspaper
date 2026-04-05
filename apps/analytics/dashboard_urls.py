from django.urls import path

from apps.analytics.views import analytics_dashboard, analytics_timeline_api

urlpatterns = [
    path("dashboard/", analytics_dashboard, name="analytics_dashboard"),
    path("dashboard/api/timeline/", analytics_timeline_api, name="analytics_timeline_api"),
]
