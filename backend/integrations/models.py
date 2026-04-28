from django.db import models


class IntegrationSetting(models.Model):
    key = models.CharField(max_length=64, unique=True)
    value = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)
