import threading
import time
import logging
import sys
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger(__name__)

_scheduler_thread = None
_stop_event = threading.Event()

def run_scheduler_loop(interval_seconds=60):
    logger.info("RouterFleet Background Scheduler started (interval: %ds).", interval_seconds)
    last_housekeeping = timezone.now() - timedelta(minutes=15)
    
    # Small initial wait to allow Django and DB initialization to complete cleanly
    time.sleep(3)
    
    while not _stop_event.is_set():
        try:
            from backup_data.services import (
                service_generate_backup_schedule,
                service_create_backup_tasks,
                service_perform_backup_tasks,
                service_housekeeping
            )
            # 1. Regenerate schedules for all active profiles and routers
            service_generate_backup_schedule()
            
            # 2. Create tasks for due backups (hourly, daily, weekly, monthly)
            service_create_backup_tasks()
            
            # 3. Perform pending backups with thread pool
            service_perform_backup_tasks()
            
            # 4. Dispatch pending alerts & notifications (WhatsApp, ntfy, email)
            try:
                from message_center.functions import concatenate_notifications, send_notification_message
                concatenate_notifications('status_online')
                concatenate_notifications('status_offline')
                concatenate_notifications('backup_fail')
                send_notification_message()
            except Exception as e:
                logger.debug(f"Notifications dispatch note: {e}")
                
            # 5. Housekeeping every 10 minutes
            if timezone.now() - last_housekeeping >= timedelta(minutes=10):
                service_housekeeping()
                last_housekeeping = timezone.now()

        except Exception as e:
            logger.error(f"Error in scheduler tick: {e}", exc_info=True)

        # Sleep interval_seconds or wake up early on shutdown
        _stop_event.wait(interval_seconds)

def start_scheduler(interval_seconds=60):
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
    print("[SCHEDULER] Motor de tareas programadas en segundo plano iniciado correctamente.")

def stop_scheduler():
    _stop_event.set()
