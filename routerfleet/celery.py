"""
Celery configuration for the MEGACOM platform.
This module initializes Celery for asynchronous task processing,
enabling enterprise-scale backup operations for 1000+ routers.
"""
import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'routerfleet.settings')

app = Celery('routerfleet')

# Read config from Django settings, using the CELERY_ namespace
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks in all installed Django apps
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Simple task to verify Celery is working."""
    print(f'Request: {self.request!r}')
