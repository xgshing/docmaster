from rest_framework import serializers

from .models import AccessLog, AuditLog, ShareHistory


class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = "__all__"


class AccessLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccessLog
        fields = "__all__"


class ShareHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ShareHistory
        fields = "__all__"
