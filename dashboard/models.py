import uuid
from django.db import models
from django.conf import settings
from router_manager.models import Router

class ActivityLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=255)
    details = models.TextField(blank=True, null=True)
    router = models.ForeignKey(Router, on_delete=models.SET_NULL, null=True, blank=True)
    
    created = models.DateTimeField(auto_now_add=True)
    uuid = models.UUIDField(unique=True, editable=False, default=uuid.uuid4)

    class Meta:
        ordering = ['-created']

    def __str__(self):
        return f"{self.created} - {self.action}"
