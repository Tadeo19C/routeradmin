"""
Tareas asíncronas de Celery para el motor de respaldos de MEGACOM.
Estas tareas envuelven las funciones cron existentes para ejecución
distribuida y confiable a través de Celery Beat + Redis.

IMPORTANTE: Las funciones cron HTTP originales NO se modifican.
Celery las invoca internamente, actuando como un orquestador paralelo.
"""
from celery import shared_task
from celery.utils.log import get_task_logger

logger = get_task_logger(__name__)


@shared_task(name='megacom.generate_backup_schedule', ignore_result=True)
def task_generate_backup_schedule():
    """Generates backup schedules for all routers based on their profiles."""
    from backup_data.views import view_cron_generate_backup_schedule
    from django.test import RequestFactory
    from django.contrib.auth.models import User

    factory = RequestFactory()
    user = User.objects.filter(is_superuser=True).first()
    if not user:
        logger.error('No superuser found to run generate_backup_schedule')
        return

    request = factory.get('/cron/generate_backup_schedule/')
    request.user = user
    response = view_cron_generate_backup_schedule(request)
    logger.info(f'generate_backup_schedule: {response.content.decode()}')


@shared_task(name='megacom.create_backup_tasks', ignore_result=True)
def task_create_backup_tasks():
    """Creates individual backup task records for scheduled routers."""
    from backup_data.views import view_cron_create_backup_tasks
    from django.test import RequestFactory
    from django.contrib.auth.models import User

    factory = RequestFactory()
    user = User.objects.filter(is_superuser=True).first()
    if not user:
        logger.error('No superuser found to run create_backup_tasks')
        return

    request = factory.get('/cron/create_backup_tasks/')
    request.user = user
    response = view_cron_create_backup_tasks(request)
    logger.info(f'create_backup_tasks: {response.content.decode()}')


@shared_task(name='megacom.perform_backup_tasks', ignore_result=True)
def task_perform_backup_tasks():
    """Executes pending backup tasks using the parallel thread pool."""
    from backup_data.views import view_cron_perform_backup_tasks
    from django.test import RequestFactory
    from django.contrib.auth.models import User

    factory = RequestFactory()
    user = User.objects.filter(is_superuser=True).first()
    if not user:
        logger.error('No superuser found to run perform_backup_tasks')
        return

    request = factory.get('/cron/perform_backup_tasks/')
    request.user = user
    response = view_cron_perform_backup_tasks(request)
    logger.info(f'perform_backup_tasks: {response.content.decode()}')


@shared_task(name='megacom.housekeeping', ignore_result=True)
def task_housekeeping():
    """Runs system housekeeping: expired locks, old messages, retention policies."""
    from backup_data.views import view_cron_housekeeping
    from django.test import RequestFactory
    from django.contrib.auth.models import User

    factory = RequestFactory()
    user = User.objects.filter(is_superuser=True).first()
    if not user:
        logger.error('No superuser found to run housekeeping')
        return

    request = factory.get('/cron/housekeeping/')
    request.user = user
    response = view_cron_housekeeping(request)
    logger.info(f'housekeeping: {response.content.decode()}')


@shared_task(name='megacom.system_self_backup', ignore_result=True)
def task_system_self_backup():
    """Creates a daily backup of the MEGACOM database itself."""
    from backup_data.views import view_cron_system_self_backup
    from django.test import RequestFactory
    from django.contrib.auth.models import User

    factory = RequestFactory()
    user = User.objects.filter(is_superuser=True).first()
    if not user:
        logger.error('No superuser found to run system_self_backup')
        return

    request = factory.get('/cron/system_self_backup/')
    request.user = user
    response = view_cron_system_self_backup(request)
    logger.info(f'system_self_backup: {response.content.decode()}')
