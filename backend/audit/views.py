from rest_framework import generics

from accounts.permissions import IsAdminOrSuperAdmin
from .models import AccessLog, AuditLog, ShareHistory
from .serializers import AccessLogSerializer, AuditLogSerializer, ShareHistorySerializer


class AuditLogListView(generics.ListAPIView):
    queryset = AuditLog.objects.all().order_by("-operation_time")
    serializer_class = AuditLogSerializer
    permission_classes = [IsAdminOrSuperAdmin]


class AccessLogListView(generics.ListAPIView):
    queryset = AccessLog.objects.select_related("document", "visitor").all().order_by("-visited_at")
    serializer_class = AccessLogSerializer
    permission_classes = [IsAdminOrSuperAdmin]


class ShareHistoryListView(generics.ListAPIView):
    queryset = ShareHistory.objects.select_related("document", "sharer").all().order_by("-shared_at")
    serializer_class = ShareHistorySerializer
    permission_classes = [IsAdminOrSuperAdmin]
