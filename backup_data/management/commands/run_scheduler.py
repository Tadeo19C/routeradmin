import time
from django.core.management.base import BaseCommand
from backup_data.scheduler import run_scheduler_loop

class Command(BaseCommand):
    help = 'Ejecuta el motor de tareas programadas y respaldos continuos de RouterFleet'

    def add_arguments(self, parser):
        parser.add_argument(
            '--interval',
            type=int,
            default=60,
            help='Intervalo de chequeo en segundos (por defecto 60)'
        )

    def handle(self, *args, **options):
        interval = options['interval']
        self.stdout.write(self.style.SUCCESS(f'Iniciando RouterFleet Scheduler cada {interval} segundos...'))
        try:
            run_scheduler_loop(interval_seconds=interval)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING('Scheduler detenido por el usuario.'))
