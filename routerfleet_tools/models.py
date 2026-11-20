from django.db import models
import uuid


class WebadminSettings(models.Model):
    name = models.CharField(default='webadmin_settings', max_length=20, unique=True)
    custom_logo = models.FileField(upload_to='branding/', blank=True, null=True, verbose_name="Logo Personalizado")
    app_title = models.CharField(max_length=64, default='BACKUP WEB', verbose_name="Título del Sistema")
    update_available = models.BooleanField(default=False)
    current_version = models.PositiveIntegerField(default=0)
    latest_version = models.PositiveIntegerField(default=0)
    last_checked = models.DateTimeField(blank=True, null=True)
    router_config_last_updated = models.DateTimeField(blank=True, null=True)
    cron_last_run = models.DateTimeField(blank=True, null=True)
    monitoring_last_run = models.DateTimeField(blank=True, null=True)

    updated = models.DateTimeField(auto_now=True)
    created = models.DateTimeField(auto_now_add=True)
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    def __str__(self):
        return self.name

    @property
    def logo_url(self):
        if self.custom_logo:
            try:
                return self.custom_logo.url
            except Exception:
                return None
        return None
