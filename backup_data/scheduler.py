import threading
import time
import logging
import sys
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger(__name__)

_scheduler_thread = None
_stop_event = threading.Event()


def run_scheduler_loop(interval_seconds=45):
    logger.info("RouterFleet Background Scheduler started (interval: %ds).", interval_seconds)
    last_housekeeping = timezone.now() - timedelta(minutes=15)

    # Small initial wait to allow Django and DB initialization to complete cleanly
    time.sleep(3)

    while not _stop_event.is_set():
        try:
            # 1. Monitoreo Activo Concurrente (TCP / ICMP Probe)
            try:
                from monitoring.services import service_check_all_routers_status
                service_check_all_routers_status()
            except Exception as e:
                logger.debug(f"Active monitoring note: {e}")

            from backup_data.services import (
                service_generate_backup_schedule,
                service_create_backup_tasks,
                service_perform_backup_tasks,
                service_housekeeping,
            )
            # 2. Completar tareas de recuperación pendientes
            service_perform_backup_tasks()

            # 3. Regenerar calendarios de respaldo activos
            service_generate_backup_schedule()

            # 4. Crear tareas para respaldos programados vencidos
            service_create_backup_tasks()

            # 5. Ejecutar respaldos pendientes
            service_perform_backup_tasks()

            # 6. Ejecutar trabajos y tareas programadas de Fleet Commander (Comandos Masivos)
            try:
                from fleet_commander.command_functions import create_jobs_from_schedules, perform_pending_command_tasks
                create_jobs_from_schedules()
                perform_pending_command_tasks()
            except Exception as e:
                logger.debug(f"Fleet commander scheduler note: {e}")

            # 7. Auto-sincronizar información de hardware para equipos pendientes
            try:
                from router_manager.models import Router, RouterInformation
                from routerlib.router_functions import update_router_information
                router_needing_info = (
                    Router.objects.filter(enabled=True)
                    .exclude(router_type='monitoring')
                    .filter(routerinformation__isnull=True)
                    .first()
                )
                if not router_needing_info:
                    router_needing_info = (
                        Router.objects.filter(enabled=True)
                        .exclude(router_type='monitoring')
                        .filter(routerinformation__last_retrieval__isnull=True, routerinformation__error=False)
                        .first()
                    )
                if router_needing_info:
                    ri, _ = RouterInformation.objects.get_or_create(router=router_needing_info)
                    update_router_information(ri)
            except Exception as e:
                logger.debug(f"Router info auto-refresh note: {e}")

            # 8. Despachar alertas y notificaciones pendientes (WhatsApp, ntfy, email)
            try:
                from message_center.models import Notification, Message
                from message_center.functions import concatenate_notifications, send_notification_message
                for n_type in ('status_online', 'status_offline', 'backup_fail', 'config_change'):
                    if Notification.objects.filter(notification_type=n_type).exists():
                        concatenate_notifications(n_type)
                for msg in Message.objects.filter(status='pending'):
                    send_notification_message(msg)
            except Exception as e:
                logger.debug(f"Notifications dispatch note: {e}")

            # 9. Housekeeping cada 10 minutos
            if timezone.now() - last_housekeeping >= timedelta(minutes=10):
                service_housekeeping()
                last_housekeeping = timezone.now()

        except Exception as e:
            logger.error(f"Error in scheduler tick: {e}", exc_info=True)

        _stop_event.wait(interval_seconds)


def start_scheduler(interval_seconds=45):
    global _scheduler_thread
    if _scheduler_thread is not None and _scheduler_thread.is_alive():
        return
    _stop_event.clear()
    _scheduler_thread = threading.Thread(
        target=run_scheduler_loop,
        args=(interval_seconds,),
        daemon=True,
        name="RouterFleetScheduler"
    )
    _scheduler_thread.start()
    print("[SCHEDULER] Motor de monitoreo activo, respaldos y comandos iniciado correctamente.")


def stop_scheduler():
    _stop_event.set()
