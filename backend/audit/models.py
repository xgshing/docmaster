from django.db import models

from accounts.models import User


class AuditLog(models.Model):
    actor = models.CharField(max_length=150)
    action_type = models.CharField(max_length=64)
    content = models.TextField()
    operation_time = models.DateTimeField(auto_now_add=True)
    ip_address = models.CharField(max_length=64, blank=True)


class AccessLog(models.Model):
    document = models.ForeignKey("documents.Document", on_delete=models.CASCADE, related_name="access_logs")
    visitor = models.ForeignKey(User, on_delete=models.CASCADE, related_name="access_logs")
    visited_at = models.DateTimeField(auto_now_add=True)
    action_type = models.CharField(max_length=64)


class ShareHistory(models.Model):
    document = models.ForeignKey("documents.Document", on_delete=models.CASCADE, related_name="share_histories")
    sharer = models.ForeignKey(User, on_delete=models.CASCADE, related_name="shared_histories")
    shared_with = models.CharField(max_length=255)
    shared_at = models.DateTimeField(auto_now_add=True)
