from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    SUPER_ADMIN = "super_admin", "超级管理员"
    ADMIN = "admin", "普通管理员"
    USER = "user", "普通用户"


class User(AbstractUser):
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.USER)
    email = models.EmailField(blank=True)
    reserved_email = models.EmailField(blank=True)
    is_enabled = models.BooleanField(default=True)
    current_session_key = models.CharField(max_length=64, blank=True)
    last_login_ip = models.GenericIPAddressField(blank=True, null=True)
    personal_root = models.CharField(max_length=512, blank=True)

    def __str__(self) -> str:
        return self.username


class UserGroup(models.Model):
    name = models.CharField(max_length=128, unique=True)
    creator = models.ForeignKey(User, on_delete=models.CASCADE, related_name="created_groups")
    creator_role = models.CharField(max_length=20, choices=Role.choices)
    parent = models.ForeignKey(
        "self", on_delete=models.SET_NULL, blank=True, null=True, related_name="children"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name


class UserGroupMembership(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="group_memberships")
    group = models.ForeignKey(UserGroup, on_delete=models.CASCADE, related_name="memberships")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "group")


class SessionEvent(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="session_events")
    session_key = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    invalidated_at = models.DateTimeField(blank=True, null=True)
    reason = models.CharField(max_length=64, default="login")
