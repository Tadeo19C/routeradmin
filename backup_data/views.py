"""
Controlador HTTP de Vistas para backup_data en MEGACOM.
Delega toda la lógica de negocio a backup_data.services, manteniendo
los endpoints HTTP compatibles con cron/Docker.
"""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse

# Re-exportamos helpers para compatibilidad hacia atrás
from backup_data.services import (
    next_weekday,
    find_next_active_day,
    calculate_next_backup,
    create_backup_tasks_from_schedule_list,
    wrap_perform_backup,
    service_generate_backup_schedule,
    service_create_backup_tasks,
    service_perform_backup_tasks,
    service_housekeeping,
    service_system_self_backup,
)


def view_cron_generate_backup_schedule(request):
    data = service_generate_backup_schedule()
    return JsonResponse(data)


def view_cron_create_backup_tasks(request):
    data = service_create_backup_tasks()
    return JsonResponse(data)


def view_cron_perform_backup_tasks(request):
    data = service_perform_backup_tasks()
    return JsonResponse(data)


def view_cron_housekeeping(request):
    data = service_housekeeping()
    return JsonResponse(data)


def view_cron_system_self_backup(request):
    data = service_system_self_backup()
    return JsonResponse(data)
