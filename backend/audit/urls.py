from django.urls import path

from .views import AccessLogListView, AuditLogListView, ShareHistoryListView


urlpatterns = [
    path("logs/", AuditLogListView.as_view(), name="audit-logs"),
    path("access/", AccessLogListView.as_view(), name="access-logs"),
    path("shares/", ShareHistoryListView.as_view(), name="share-logs"),
]
