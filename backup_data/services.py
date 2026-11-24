"""
Capa de Servicios de Negocio para Respaldos en BACKUP WEB.
Desacopla la lógica del ciclo de vida de los respaldos de las vistas HTTP de Django,
permitiendo que sea invocada limpiamente por Celery, comandos de consola (manage.py)
o las vistas web sin requerir simulación de requests.
"""
import os
import shutil
import subprocess
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, Tuple, Optional

from django.db.models import Q
from django.utils import timezone
from django.conf import settings

from backup.models import BackupProfile
from backup_data.models import RouterBackup
from message_center.functions import notify_backup_fail, notify_backup_task_lock_expired
from message_center.models import Message
from router_manager.models import Router, BackupSchedule, RouterStatus
from routerlib.backup_functions import perform_backup, append_task_console_output


def next_weekday(now: datetime, weekday: int, hour: int, minute: int = 0) -> datetime:
    now_local = timezone.localtime(timezone.now())
    days_ahead = weekday - now_local.weekday()
    if days_ahead < 0 or (days_ahead == 0 and (now_local.hour > hour or (now_local.hour == hour and now_local.minute >= minute))):
        days_ahead += 7
    next_backup = now_local + timedelta(days=days_ahead)
    return next_backup.replace(hour=hour, minute=minute, second=0, microsecond=0)


def find_next_active_day(start_date: datetime, active_days: list, backup_hour: int, backup_minute: int = 0) -> Optional[datetime]:
    now_local = timezone.localtime()
    for i in range(7):
        potential_date = timezone.localtime(start_date + timedelta(days=i))
        weekday = potential_date.weekday()
        if active_days[weekday]:
            next_active_date = potential_date.replace(hour=backup_hour, minute=backup_minute, second=0, microsecond=0)
            if next_active_date > now_local:
                return next_active_date
            if i == 0 and (now_local.hour > backup_hour or (now_local.hour == backup_hour and now_local.minute >= backup_minute)):
                continue
    return None


def calculate_next_backup(backup_profile: BackupProfile) -> Tuple[Optional[datetime], Optional[datetime], Optional[datetime]]:
    now = timezone.now()

    if backup_profile.daily_backup:
        weekdays_enabled = [
            backup_profile.daily_day_monday,
            backup_profile.daily_day_tuesday,
            backup_profile.daily_day_wednesday,
            backup_profile.daily_day_thursday,
            backup_profile.daily_day_friday,
            backup_profile.daily_day_saturday,
            backup_profile.daily_day_sunday,
        ]
        daily_min = getattr(backup_profile, "daily_minute", 0) or 0
        next_daily_backup = find_next_active_day(now, weekdays_enabled, backup_profile.daily_hour, daily_min)
    else:
        next_daily_backup = None

    if backup_profile.weekly_backup:
        weekday = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'].index(backup_profile.weekly_day)
        weekly_min = getattr(backup_profile, "weekly_minute", 0) or 0
        next_weekly_backup = next_weekday(now, weekday, backup_profile.weekly_hour, weekly_min)
    else:
        next_weekly_backup = None

    if backup_profile.monthly_backup:
        potential_monthly_backup = datetime(year=now.year, month=now.month, day=backup_profile.monthly_day,
                                            hour=backup_profile.monthly_hour, tzinfo=timezone.get_current_timezone())
        if potential_monthly_backup <= now:
            month_increment = 1 if now.month < 12 else -11
            year_increment = 0 if now.month < 12 else 1
            next_monthly_backup = potential_monthly_backup.replace(year=now.year + year_increment,
                                                                   month=now.month + month_increment)
        else:
            next_monthly_backup = potential_monthly_backup
    else:
        next_monthly_backup = None

    return next_daily_backup, next_weekly_backup, next_monthly_backup


def create_backup_tasks_from_schedule_list(schedule_list, schedule_type: str) -> int:
    tasks_created = 0
    for schedule in schedule_list:
        if schedule_type == 'daily':
            schedule_time = schedule.next_daily_backup
            schedule.next_daily_backup = None
        elif schedule_type == 'weekly':
            schedule_time = schedule.next_weekly_backup
            schedule.next_weekly_backup = None
        elif schedule_type == 'monthly':
            schedule_time = schedule.next_monthly_backup
            schedule.next_monthly_backup = None
        elif schedule_type == 'hourly':
            schedule_time = schedule.next_hourly_backup
            schedule.next_hourly_backup = None
        else:
            return tasks_created
        schedule.save()

        backup = RouterBackup.objects.create(
            router=schedule.router, schedule_time=schedule_time, schedule_type=schedule_type
        )
        tasks_created += 1
        backup.save()
        backup.router.routerstatus.backup_lock = backup.schedule_time
        backup.router.routerstatus.save()

    return tasks_created


def wrap_perform_backup(backup_id: int) -> bool:
    """Wrapper para ejecución concurrente segura de un respaldo."""
    try:
        backup = RouterBackup.objects.get(id=backup_id)
        backup.task_lock = timezone.now()
        backup.save(update_fields=["task_lock"])
        
        perform_backup(backup)
        
        if backup.pk:
            backup.task_lock = None
            backup.save(update_fields=["task_lock"])
        return True
    except Exception:
        return False


def service_generate_backup_schedule() -> Dict[str, Any]:
    """Genera y actualiza los calendarios de respaldo según los perfiles activos."""
    data = {
        'backup_schedule_created': 0,
        'daily_backup_schedule_created': 0,
        'weekly_backup_schedule_created': 0,
        'monthly_backup_schedule_created': 0,
        'hourly_backup_schedule_created': 0,
        'daily_backup_schedule_removed': 0,
        'weekly_backup_schedule_removed': 0,
        'monthly_backup_schedule_removed': 0,
        'hourly_backup_schedule_removed': 0
    }

    for router in Router.objects.filter(backupschedule__isnull=True):
        new_backup_schedule, _ = BackupSchedule.objects.get_or_create(router=router)
        data['backup_schedule_created'] += 1

    for backup_profile in BackupProfile.objects.all():
        backup_schedule_list = BackupSchedule.objects.filter(router__backup_profile=backup_profile)
        next_daily_backup, next_weekly_backup, next_monthly_backup = calculate_next_backup(backup_profile)

        if backup_profile.daily_backup and not next_daily_backup:
            backup_profile.profile_error_information = 'Error calculating next daily backup. Check profile settings'
            backup_profile.save()
        if backup_profile.weekly_backup and not next_weekly_backup:
            backup_profile.profile_error_information = 'Error calculating next weekly backup. Check profile settings'
            backup_profile.save()
        if backup_profile.monthly_backup and not next_monthly_backup:
            backup_profile.profile_error_information = 'Error calculating next monthly backup. Check profile settings'
            backup_profile.save()

        if backup_profile.daily_backup:
            daily_schedule_list = backup_schedule_list.filter(next_daily_backup__isnull=True)
            for schedule in daily_schedule_list:
                schedule.next_daily_backup = next_daily_backup
                schedule.save()
                data['daily_backup_schedule_created'] += 1
        else:
            daily_schedule_list = backup_schedule_list.filter(next_daily_backup__isnull=False)
            for schedule in daily_schedule_list:
                schedule.next_daily_backup = None
                schedule.save()
                data['daily_backup_schedule_removed'] += 1

        if backup_profile.weekly_backup:
            weekly_schedule_list = backup_schedule_list.filter(next_weekly_backup__isnull=True)
            for schedule in weekly_schedule_list:
                schedule.next_weekly_backup = next_weekly_backup
                schedule.save()
                data['weekly_backup_schedule_created'] += 1
        else:
            weekly_schedule_list = backup_schedule_list.filter(next_weekly_backup__isnull=False)
            for schedule in weekly_schedule_list:
                schedule.next_weekly_backup = None
                schedule.save()
                data['weekly_backup_schedule_removed'] += 1

        if backup_profile.monthly_backup:
            monthly_schedule_list = backup_schedule_list.filter(next_monthly_backup__isnull=True)
            for schedule in monthly_schedule_list:
                schedule.next_monthly_backup = next_monthly_backup
                schedule.save()
                data['monthly_backup_schedule_created'] += 1
        else:
            monthly_schedule_list = backup_schedule_list.filter(next_monthly_backup__isnull=False)
            for schedule in monthly_schedule_list:
                schedule.next_monthly_backup = None
                schedule.save()
                data['monthly_backup_schedule_removed'] += 1

        if backup_profile.hourly_backup:
            hourly_schedule_list = backup_schedule_list.filter(next_hourly_backup__isnull=True)
            for schedule in hourly_schedule_list:
                if RouterBackup.objects.filter(router=schedule.router, success=False, error=False).exists():
                    continue
                router_status = getattr(schedule.router, 'routerstatus', None)
                last_check = router_status.last_backup if router_status else None
                if not last_check:
                    last_backup_obj = RouterBackup.objects.filter(router=schedule.router, success=True).order_by('-created').first()
                    if last_backup_obj:
                        last_check = last_backup_obj.updated or last_backup_obj.created

                if not last_check or (timezone.now() - last_check).total_seconds() >= (backup_profile.hourly_interval * 3600):
                    schedule.next_hourly_backup = timezone.now()
                else:
                    schedule.next_hourly_backup = last_check + timedelta(hours=backup_profile.hourly_interval)
                schedule.save()
                data['hourly_backup_schedule_created'] += 1
        else:
            hourly_schedule_list = backup_schedule_list.filter(next_hourly_backup__isnull=False)
            for schedule in hourly_schedule_list:
                schedule.next_hourly_backup = None
                schedule.save()
                data['hourly_backup_schedule_removed'] += 1

    return data


def service_create_backup_tasks() -> Dict[str, Any]:
    """Crea las tareas de respaldo para los routers que alcanzaron su horario programado."""
    data = {
        'daily_backup_tasks_created': 0,
        'weekly_backup_tasks_created': 0,
        'monthly_backup_tasks_created': 0,
        'hourly_backup_tasks_created': 0
    }
    
    now = timezone.now()
    base_filter = Q(router__enabled=True, router__routerstatus__backup_lock__isnull=True) & (
        Q(router__monitoring=False) | Q(router__monitoring=True, router__routerstatus__status_online=True)
    )

    monthly_pending = BackupSchedule.objects.filter(next_monthly_backup__lte=now).filter(base_filter)
    data['monthly_backup_tasks_created'] = create_backup_tasks_from_schedule_list(monthly_pending, 'monthly')

    weekly_pending = BackupSchedule.objects.filter(next_weekly_backup__lte=now).filter(base_filter)
    data['weekly_backup_tasks_created'] = create_backup_tasks_from_schedule_list(weekly_pending, 'weekly')

    daily_pending = BackupSchedule.objects.filter(next_daily_backup__lte=now).filter(base_filter)
    data['daily_backup_tasks_created'] = create_backup_tasks_from_schedule_list(daily_pending, 'daily')

    hourly_pending = BackupSchedule.objects.filter(next_hourly_backup__lte=now).filter(base_filter)
    data['hourly_backup_tasks_created'] = create_backup_tasks_from_schedule_list(hourly_pending, 'hourly')

    return data


def service_perform_backup_tasks(max_workers: int = 10, max_execution_time: int = 45) -> Dict[str, Any]:
    """Ejecuta los respaldos pendientes de forma paralela y controlada."""
    data = {'backup_tasks_performed': 0}
    execution_start_time = timezone.now()
    
    pending_backup_list = RouterBackup.objects.filter(
        success=False, error=False, task_lock__isnull=True
    ).filter(
        Q(schedule_time__lte=timezone.now(), next_retry__isnull=True) | Q(next_retry__lte=timezone.now())
    ).filter(
        Q(router__monitoring=False) | Q(router__monitoring=True, router__routerstatus__status_online=True)
    ).values_list('id', flat=True)[:50]

    if not pending_backup_list:
        return data

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_backup = {executor.submit(wrap_perform_backup, b_id): b_id for b_id in pending_backup_list}
        
        for future in as_completed(future_to_backup, timeout=max_execution_time + 5):
            try:
                if future.result():
                    data['backup_tasks_performed'] += 1
            except Exception:
                pass
            
            if (timezone.now() - execution_start_time).total_seconds() > max_execution_time:
                break

    return data


def service_housekeeping() -> Dict[str, Any]:
    """Mantenimiento: libera locks expirados, limpia mensajes viejos y aplica retención."""
    max_backup_task_age = timezone.now() - timedelta(hours=18)
    max_backup_task_lock = timezone.now() - timedelta(hours=6)
    max_command_lock_age = timezone.now() - timedelta(hours=2)
    data = {
        'backup_tasks_expired': 0,
        'backup_locks_removed': 0,
        'backup_task_locks_expired': 0,
        'command_locks_removed': 0,
        'messages_removed': 0,
    }

    for backup in RouterBackup.objects.filter(task_lock__lt=max_backup_task_lock, success=False, error=False):
        backup.task_lock = None
        backup.save(update_fields=["task_lock"])
        data['backup_task_locks_expired'] += 1
        append_task_console_output(backup, '### WARNING: Backup task expired.')
        notify_backup_task_lock_expired(backup)

    for backup in RouterBackup.objects.filter(created__lt=max_backup_task_age, success=False, error=False, task_lock__isnull=True):
        backup.error = True
        backup.error_message = 'Backup task expired'
        backup.save()
        backup.router.routerstatus.last_backup_failed = timezone.now()
        backup.router.routerstatus.save()
        notify_backup_fail(backup)

        if not RouterBackup.objects.filter(router=backup.router, success=False, error=False).exists():
            backup.router.routerstatus.backup_lock = None
            backup.router.routerstatus.save()
        data['backup_tasks_expired'] += 1

    for router_status in RouterStatus.objects.filter(backup_lock__lt=max_backup_task_age):
        if not RouterBackup.objects.filter(router=router_status.router, success=False, error=False).exists():
            router_status.backup_lock = None
            router_status.last_backup_failed = timezone.now()
            router_status.save()
            data['backup_locks_removed'] += 1

    for router_status in RouterStatus.objects.filter(command_lock__lt=max_command_lock_age):
        router_status.command_lock = None
        router_status.save()
        data['command_locks_removed'] += 1

    for backup_profile in BackupProfile.objects.all():
        if backup_profile.name == 'default':
            backup_list = RouterBackup.objects.filter(Q(router__backup_profile=backup_profile) | Q(router__backup_profile__isnull=True))
        else:
            backup_list = RouterBackup.objects.filter(router__backup_profile=backup_profile)

        if backup_profile.retain_backups_on_error:
            backup_list = backup_list.filter(router__routerstatus__last_backup_failed__isnull=True)

        backup_list.filter(schedule_type='instant', created__lt=timezone.now() - timedelta(days=backup_profile.instant_retention)).delete()
        backup_list.filter(schedule_type='monthly', created__lt=timezone.now() - timedelta(days=backup_profile.monthly_retention)).delete()
        backup_list.filter(schedule_type='weekly', created__lt=timezone.now() - timedelta(days=backup_profile.weekly_retention)).delete()
        backup_list.filter(schedule_type='daily', created__lt=timezone.now() - timedelta(days=backup_profile.daily_retention)).delete()

    expired_messages = Message.objects.filter(created__lt=timezone.now() - timedelta(days=30))
    data['messages_removed'] = expired_messages.count()
    expired_messages.delete()

    return data


def service_system_self_backup() -> Dict[str, Any]:
    """Genera copia de seguridad de la base de datos de BACKUP WEB (SQLite o PostgreSQL)."""
    db_path = settings.DATABASES['default']['NAME']
    backup_dir = os.path.join(settings.MEDIA_ROOT, 'backups', 'system_db')
    
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir, exist_ok=True)
        
    timestamp = timezone.now().strftime('%Y%m%d_%H%M')
    backup_filename = f"db_backupweb_{timestamp}.sqlite3"
    backup_path = os.path.join(backup_dir, backup_filename)
    
    data = {
        'status': 'success',
        'backup_created': False,
        'filename': backup_filename,
        'rotation_count': 0
    }
    
    try:
        if settings.DATABASES['default']['ENGINE'] == 'django.db.backends.sqlite3':
            shutil.copy2(db_path, backup_path)
            data['backup_created'] = True
        elif settings.DATABASES['default']['ENGINE'] == 'django.db.backends.postgresql':
            db_name = settings.DATABASES['default']['NAME']
            db_user = settings.DATABASES['default']['USER']
            db_password = settings.DATABASES['default']['PASSWORD']
            db_host = settings.DATABASES['default']['HOST']
            db_port = settings.DATABASES['default']['PORT']
            
            env = os.environ.copy()
            env['PGPASSWORD'] = db_password
            
            backup_filename = f"db_backupweb_{timestamp}.sql"
            backup_path = os.path.join(backup_dir, backup_filename)
            data['filename'] = backup_filename
            
            cmd = ['pg_dump', '-h', db_host, '-p', str(db_port), '-U', db_user, '-f', backup_path, db_name]
            subprocess.run(cmd, env=env, check=True)
            data['backup_created'] = True
        else:
            data['status'] = 'error'
            data['message'] = f"Unsupported database engine: {settings.DATABASES['default']['ENGINE']}"
            return data
        
        # Rotación: mantener los últimos 30 respaldos
        all_backups = sorted([
            f for f in os.listdir(backup_dir) 
            if f.startswith('db_backupweb_') and (f.endswith('.sqlite3') or f.endswith('.sql'))
        ], reverse=True)
        
        if len(all_backups) > 30:
            for old_backup in all_backups[30:]:
                os.remove(os.path.join(backup_dir, old_backup))
                data['rotation_count'] += 1
                
    except Exception as e:
        data['status'] = 'error'
        data['message'] = str(e)
        
    return data
