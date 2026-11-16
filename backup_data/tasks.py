"""
Tareas asíncronas de Celery para el motor de respaldos de MEGACOM.
Ejecuta los servicios de negocio de forma nativa a través de Celery Beat + Redis
sin requerir la simulación de peticiones HTTP.
"""
from celery import shared_task
from celery.utils.log import get_task_logger

logger = get_task_logger(__name__)


@shared_task(name='megacom.generate_backup_schedule', ignore_result=True)
def task_generate_backup_schedule():
    """Generates backup schedules for all routers based on their profiles."""
    from backup_data.services import service_generate_backup_schedule
    result = service_generate_backup_schedule()
    logger.info(f'generate_backup_schedule: {result}')


@shared_task(name='megacom.create_backup_tasks', ignore_result=True)
def task_create_backup_tasks():
    """Creates individual backup task records for scheduled routers."""
    from backup_data.services import service_create_backup_tasks
    result = service_create_backup_tasks()
    logger.info(f'create_backup_tasks: {result}')


@shared_task(name='megacom.perform_backup_tasks', ignore_result=True)
def task_perform_backup_tasks():
    """Executes pending backup tasks using the parallel thread pool."""
    from backup_data.services import service_perform_backup_tasks
    result = service_perform_backup_tasks()
    logger.info(f'perform_backup_tasks: {result}')


@shared_task(name='megacom.housekeeping', ignore_result=True)
def task_housekeeping():
    """Runs system housekeeping: expired locks, old messages, retention policies."""
    from backup_data.services import service_housekeeping
    result = service_housekeeping()
    logger.info(f'housekeeping: {result}')


@shared_task(name='megacom.system_self_backup', ignore_result=True)
def task_system_self_backup():
    """Creates a daily backup of the MEGACOM database itself."""
    from backup_data.services import service_system_self_backup
    result = service_system_self_backup()
    logger.info(f'system_self_backup: {result}')
