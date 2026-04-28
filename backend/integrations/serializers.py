from rest_framework import serializers

from .models import IntegrationSetting


class IntegrationSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = IntegrationSetting
        fields = "__all__"
