from django.contrib import admin

from .models import SessionEvent, User, UserGroup, UserGroupMembership


admin.site.register(User)
admin.site.register(UserGroup)
admin.site.register(UserGroupMembership)
admin.site.register(SessionEvent)

# Register your models here.
