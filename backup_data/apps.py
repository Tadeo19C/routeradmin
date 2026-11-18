import os
import sys
from django.apps import AppConfig


class BackupDataConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'backup_data'

    def ready(self):
        # En runserver con autoreload, iniciar solo en el proceso hijo activo (RUN_MAIN == 'true')
        if 'runserver' in sys.argv:
            if os.environ.get('RUN_MAIN') == 'true' or '--noreload' in sys.argv:
                from backup_data.scheduler import start_scheduler
                start_scheduler(interval_seconds=45)
        elif any(server_bin in ' '.join(sys.argv).lower() for server_bin in ['gunicorn', 'uwsgi', 'daphne', 'waitress']):
            from backup_data.scheduler import start_scheduler
            start_scheduler(interval_seconds=45)
