import os
import sys
from django.apps import AppConfig


class BackupDataConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'backup_data'

    def ready(self):
        # Evitar ejecución en comandos administrativos de Django
        skip_commands = ['makemigrations', 'migrate', 'check', 'collectstatic', 'shell', 'dbshell', 'createsuperuser']
        if any(cmd in sys.argv for cmd in skip_commands):
            return

        # En runserver con autoreload, iniciar solo en el proceso hijo activo (RUN_MAIN == 'true')
        if 'runserver' in sys.argv:
            if os.environ.get('RUN_MAIN') == 'true' or '--noreload' in sys.argv:
                from backup_data.scheduler import start_scheduler
                start_scheduler(interval_seconds=45)
        else:
            # En Gunicorn, uWSGI, Daphne o ejecuciones directas
            from backup_data.scheduler import start_scheduler
            start_scheduler(interval_seconds=45)
