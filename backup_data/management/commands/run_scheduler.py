import time
from django.core.management.base import BaseCommand
from django.db import connections
from backup_data.scheduler import run_scheduler_loop


class Command(BaseCommand):
    help = 'Inicia el planificador en segundo plano de BACKUP WEB (monitoreo activo, respaldos programados y notificaciones).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--interval',
            type=int,
            default=45,
            help='Intervalo en segundos entre cada ciclo del planificador (por defecto: 45s).'
        )

    def handle(self, *args, **options):
        interval = options['interval']
        # Wait for database and migrations to be ready
        for _ in range(30):
            try:
                connections['default'].ensure_connection()
                from router_manager.models import Router
                Router.objects.exists()
                break
            except Exception:
                time.sleep(2)
        self.stdout.write(self.style.SUCCESS(f'[SCHEDULER] Iniciando planificador BACKUP WEB cada {interval}s...'))
        run_scheduler_loop(interval_seconds=interval)
