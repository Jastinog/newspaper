from django.urls import path

from apps.analytics.views import analytics_dashboard, analytics_dashboard_api

urlpatterns = [
    path("dashboard/", analytics_dashboard, name="analytics_dashboard"),
    path("dashboard/api/", analytics_dashboard_api, name="analytics_dashboard_api"),
]
