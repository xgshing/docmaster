from rest_framework import generics, views, response

from accounts.permissions import IsAdminOrSuperAdmin
from .models import IntegrationSetting
from .serializers import IntegrationSettingSerializer
from .services import integration_status


class IntegrationStatusView(views.APIView):
    permission_classes = [IsAdminOrSuperAdmin]

    def get(self, request):
        return response.Response(integration_status())


class IntegrationSettingListCreateView(generics.ListCreateAPIView):
    queryset = IntegrationSetting.objects.all().order_by("key")
    serializer_class = IntegrationSettingSerializer
    permission_classes = [IsAdminOrSuperAdmin]
