from django.urls import path

from .views import IntegrationSettingListCreateView, IntegrationStatusView


urlpatterns = [
    path("status/", IntegrationStatusView.as_view(), name="integration-status"),
    path("settings/", IntegrationSettingListCreateView.as_view(), name="integration-settings"),
]
