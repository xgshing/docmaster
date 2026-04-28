from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/accounts/", include("accounts.urls")),
    path("api/documents/", include("documents.urls")),
    path("api/audit/", include("audit.urls")),
    path("api/integrations/", include("integrations.urls")),
]
