from django.urls import path

from apps.analytics.views import (
    analytics_bots_timeline_api,
    analytics_dashboard,
    analytics_timeline_api,
    bot_history_api,
    client_history_api,
)

urlpatterns = [
    path("dashboard/", analytics_dashboard, name="analytics_dashboard"),
    path("dashboard/api/timeline/", analytics_timeline_api, name="analytics_timeline_api"),
    path("dashboard/api/bots-timeline/", analytics_bots_timeline_api, name="analytics_bots_timeline_api"),
    path("dashboard/api/bot-history/", bot_history_api, name="bot_history_api"),
    path("dashboard/api/client/<int:client_pk>/history/", client_history_api, name="client_history_api"),
]
