from django.contrib import admin

from .models import AccessLog, AuditLog, ShareHistory


admin.site.register(AuditLog)
admin.site.register(AccessLog)
admin.site.register(ShareHistory)

# Register your models here.
