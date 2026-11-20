import datetime

from router_manager.models import Router
from .models import MessageChannel, Notification, MessageSettings, Message
from backup_data.models import RouterBackup
from dashboard.models import ActivityLog
import requests
from django.core.mail import send_mail, EmailMessage, get_connection
from django.conf import settings
from django.utils import timezone


def concatenate_notifications(notification_type: str):
    concatenate_count = 0
    message_settings, _ = MessageSettings.objects.get_or_create(name='message_settings')
    message_channel_list = MessageChannel.objects.filter(enabled=True)
    if notification_type == 'status_online':
        notification_text = 'Cambio de estado del Equipo: En línea\n'
        notification_list = Notification.objects.filter(notification_type='status_online')
        message_channel_list = message_channel_list.filter(status_change_online=True)
    elif notification_type == 'status_offline':
        notification_text = 'Cambio de estado del Equipo: Fuera de línea\n'
        notification_list = Notification.objects.filter(notification_type='status_offline')
        message_channel_list = message_channel_list.filter(status_change_offline=True)
    elif notification_type == 'backup_fail':
        notification_text = 'Reporte de fallo de respaldo\n'
        notification_list = Notification.objects.filter(notification_type='backup_fail')
        message_channel_list = message_channel_list.filter(backup_fail=True)
    elif notification_type == 'config_change':
        notification_text = 'Cambio de configuración detectado\n'
        notification_list = Notification.objects.filter(notification_type='config_change')
        message_channel_list = message_channel_list.filter(config_change=True)
    else:
        return 0

    notification_list = notification_list.order_by('created')
    for notification in notification_list:
        notification_text_temp = notification_text
        if notification.router_backup:
            notification_text_temp += f'\n- Respaldo #{notification.router_backup.id} en equipo {notification.router_backup.router.name} ({notification.router_backup.router.address})'
        elif notification.router:
            notification_text_temp += f'\n- Equipo {notification.router.name} ({notification.router.address})'
        if len(notification_text_temp) < message_settings.max_length:
            notification_text = notification_text_temp
            notification.delete()
            concatenate_count += 1
        else:
            break

    if concatenate_count > 0:
        for message_channel in message_channel_list:
            Message.objects.create(
                channel=message_channel,
                subject=notification_text.split('\n')[0],
                message=notification_text
            )
    return concatenate_count


def notify_config_change(router_backup: RouterBackup, previous_backup: RouterBackup, added_lines: int = 0, removed_lines: int = 0):
    """
    Registra en bitácora y envía alerta a los canales activos cuando se detecta
    una modificación real en la configuración de un equipo respecto a la versión previa.
    """
    router = router_backup.router
    summary_str = (
        f"Equipo '{router.name}' ({router.address}) | "
        f"Rev #{previous_backup.id} -> Rev #{router_backup.id} "
        f"(+{added_lines} líneas agregadas, -{removed_lines} eliminadas)"
    )
    try:
        ActivityLog.objects.create(
            user=None,
            action="Cambio de Configuración",
            details=summary_str,
            router=router,
        )
    except Exception:
        pass

    message_channel_list = MessageChannel.objects.filter(enabled=True, config_change=True)
    if not message_channel_list.exists():
        return

    msg_body = (
        f"⚠️ Cambio de configuración detectado en {router.name} ({router.address})\n"
        f"Revisión: #{previous_backup.id} -> #{router_backup.id}\n"
        f"Resumen Diff: +{added_lines} líneas agregadas, -{removed_lines} líneas eliminadas.\n"
        f"Fecha: {timezone.localtime(timezone.now()).strftime('%d/%m/%Y %H:%M:%S')}"
    )
    for channel in message_channel_list:
        Message.objects.create(
            channel=channel,
            router_backup=router_backup,
            subject=f"[MEGACOM] Respaldo Importante / Cambio en {router.name} (Rev #{router_backup.id})",
            message=msg_body,
        )


def generate_backup_report(data):
    message_settings, _ = MessageSettings.objects.get_or_create(name='message_settings')
    yesterday = timezone.now() - datetime.timedelta(days=1)
    failed_backup_list = RouterBackup.objects.filter(error=True, updated__gt=yesterday)
    success_backup_list = RouterBackup.objects.filter(success=True, updated__gt=yesterday)
    pending_backup_list = RouterBackup.objects.filter(success=False, error=False, updated__gt=yesterday)
    if data['report_time_exception']:
        message_text = 'Advertencia: Error al calcular la hora del reporte, por favor verifique la configuración de zona horaria.\n\n'
    else:
        message_text = ''
    message_text += 'Reporte diario de respaldos de MEGACOM:\n'
    message_text += f'Nuevas versiones respaldadas: {success_backup_list.count()}\n'
    message_text += f'Respaldos fallidos: {failed_backup_list.count()}\n'
    message_text += f'Respaldos pendientes: {pending_backup_list.count()}\n'

    if failed_backup_list.count() > 0:
        message_text += '\n=========\n Respaldos fallidos:\n'
        message_text_temp = message_text
        truncate_text = 'Hay más respaldos fallidos, por favor revise la interfaz web para ver la lista completa\n\n'
        for backup in failed_backup_list:
            message_text_temp += f'- Respaldo {backup.id} para el equipo {backup.router.name} ({backup.router.address})\n'
            if len(message_text_temp + truncate_text) < message_settings.max_length:
                message_text = message_text_temp
            else:
                message_text += truncate_text
                break
    for message_channel in MessageChannel.objects.filter(enabled=True, daily_backup_report=True):
        Message.objects.create(
            channel=message_channel,
            subject='Reporte diario de respaldos',
            message=message_text
        )
    message_settings.last_daily_backup_report = timezone.now()
    message_settings.save()
    return


def generate_status_report(data):
    message_settings, _ = MessageSettings.objects.get_or_create(name='message_settings')
    router_list = Router.objects.filter(enabled=True, monitoring=True)
    offline_count = router_list.filter(routerstatus__status_online=False).count()
    if data['report_time_exception']:
        message_text = 'Advertencia: Error al calcular la hora del reporte, por favor verifique la configuración de zona horaria.\n\n'
    else:
        message_text = ''
    message_text += 'Reporte diario de estado de MEGACOM:\n'
    message_text += f'Equipos monitoreados: {router_list.count()}\n'
    message_text += f'En línea: {router_list.filter(routerstatus__status_online=True).count()}\n'
    message_text += f'Fuera de línea: {offline_count}\n'

    if offline_count > 0:
        message_text += '\n=========\n Equipos fuera de línea:\n'
        message_text_temp = message_text
        truncate_text = 'Hay más equipos fuera de línea, por favor revise la interfaz web para ver la lista completa\n\n'
        for router in router_list.filter(routerstatus__status_online=False):
            message_text_temp += f'- {router.name} ({router.address})\n'
            if len(message_text_temp + truncate_text) < message_settings.max_length:
                message_text = message_text_temp
            else:
                message_text += truncate_text
                break

    message_channel_list = MessageChannel.objects.filter(enabled=True, daily_status_report=True)
    for message_channel in message_channel_list:
        Message.objects.create(
            channel=message_channel,
            subject='Reporte diario de estado',
            message=message_text
        )
    message_settings.last_daily_status_report = timezone.now()
    message_settings.save()
    return


def send_notification_message(message: Message):
    message_settings, _ = MessageSettings.objects.get_or_create(name='message_settings')
    if message.status != 'pending':
        return
    if message.retry_count > message_settings.max_retry:
        message.status = 'failed'
        message.completed = timezone.now()
        message.save()
        return

    message_response = {'status': 'pending', 'error_message': '', 'error_status_code': 0}

    url = ''
    method = 'GET'
    headers = {}
    data = None

    if message.channel.channel_type == 'callmebot':
        url = f'https://api.callmebot.com/whatsapp.php?phone={message.channel.destination}&text={message.message}&apikey={message.channel.token}'
    elif message.channel.channel_type == 'ntfy':
        url = f'https://ntfy.sh/{message.channel.destination}'
        method = 'POST'
        data = message.message.encode('utf-8')
        if message.subject:
            headers = {'Title': message.subject}
    elif message.channel.channel_type == 'email':
        try:
            import os
            DEFAULT_SYS_SMTP_USER = os.environ.get('EMAIL_HOST_USER', 'tadeocastle3@gmail.com')
            DEFAULT_SYS_SMTP_PASS = os.environ.get('EMAIL_HOST_PASSWORD', 'khbdmxwtohnznsqj')
            smtp_host = (message_settings.smtp_host or os.environ.get('EMAIL_HOST', 'smtp.gmail.com')).strip()
            smtp_port = message_settings.smtp_port or int(os.environ.get('EMAIL_PORT', 587))
            smtp_user = (message_settings.smtp_user or DEFAULT_SYS_SMTP_USER).strip()
            raw_pass = message_settings.smtp_password or DEFAULT_SYS_SMTP_PASS
            smtp_pass = raw_pass.replace(' ', '').strip() if raw_pass else ''
            smtp_tls = message_settings.smtp_use_tls

            connection = get_connection(
                backend='django.core.mail.backends.smtp.EmailBackend',
                host=smtp_host,
                port=smtp_port,
                username=smtp_user or None,
                password=smtp_pass or None,
                use_tls=smtp_tls,
                fail_silently=False,
            )
            from_addr = f"MEGACOM Respaldos <{smtp_user}>" if smtp_user else getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@megacom.local')
            dest_list = [d.strip() for d in (message.channel.destination or '').split(',') if d.strip()]
            email_msg = EmailMessage(
                subject=message.subject or 'Notificación MEGACOM',
                body=message.message,
                from_email=from_addr,
                to=dest_list,
                connection=connection,
            )

            # Adjuntar el archivo de configuración en texto plano (.rsc / .cfg) para entrega instantánea sin bloqueo de antivirus de Gmail
            rb = message.router_backup
            if rb and message_settings.attach_backup_on_email and rb.backup_text:
                ext = 'rsc' if rb.router.router_type in ('mikrotik', 'mikrotik-branded') else 'cfg'
                safe_router_name = rb.router.name.replace(' ', '_')
                fname = f"{safe_router_name}_rev{rb.id}.{ext}"
                email_msg.attach(fname, rb.backup_text, 'text/plain; charset=utf-8')

            email_msg.send(fail_silently=False)
            message_response['status'] = 'sent'
        except Exception as e:
            message_response['status'] = 'failed'
            message_response['error_message'] = str(e)
            message_response['error_status_code'] = 0
    else:
        message_response['status'] = 'failed'
        message_response['error_message'] = 'Failed to send message: Invalid channel type'
        message_response['error_status_code'] = 0

    if message_response['status'] == 'pending':
        try:
            if method == 'GET':
                response = requests.get(url, timeout=15)
            elif method == 'POST':
                response = requests.post(url, data=data, headers=headers, timeout=15)

            if response.status_code == 200:
                message_response['status'] = 'sent'
            else:
                message_response['status'] = 'failed'
                message_response['error_message'] = response.text
                message_response['error_status_code'] = response.status_code
        except Exception as e:
            message_response['status'] = 'failed'
            message_response['error_message'] = f'Failed to send message: Request exception {str(e)}'
            message_response['error_status_code'] = 0

    if message_response['status'] == 'sent':
        message.status = 'sent'
        message.completed = timezone.now()
        message.save()
    else:
        message.retry_count += 1
        message.error_message = message_response['error_message']
        message.error_status_code = message_response['error_status_code']
        message.next_retry = timezone.now() + datetime.timedelta(seconds=message_settings.retry_interval)
        message.save()
    return


def notify_router_status_update(router: Router):
    message_channel_list = MessageChannel.objects.filter(enabled=True)
    message_settings, _ = MessageSettings.objects.get_or_create(name='message_settings')

    if message_settings.concatenate_status_change:
        if router.routerstatus.status_online:
            if message_channel_list.filter(status_change_online=True):
                Notification.objects.create(notification_type='status_online', router=router)
        else:
            if message_channel_list.filter(status_change_offline=True):
                Notification.objects.create(notification_type='status_offline', router=router)
    else:
        if router.routerstatus.status_online:
            for message_channel in message_channel_list.filter(status_change_online=True):
                Message.objects.create(
                    channel=message_channel,
                    subject='Cambio de estado del Equipo: En línea',
                    message=f'El equipo {router.name} ({router.address}) está ahora en línea'
                )
        else:
            for message_channel in message_channel_list.filter(status_change_offline=True):
                Message.objects.create(
                    channel=message_channel,
                    subject='Cambio de estado del Equipo: Fuera de línea',
                    message=f'El equipo {router.name} ({router.address}) está ahora fuera de línea'
                )
    return


def notify_backup_fail(router_backup: RouterBackup):
    message_settings, _ = MessageSettings.objects.get_or_create(name='message_settings')
    message_channel_list = MessageChannel.objects.filter(enabled=True, backup_fail=True)

    if not message_channel_list:
        return

    if message_settings.concatenate_backup_fails:
        Notification.objects.create(notification_type='backup_fail', router=router_backup.router, router_backup=router_backup)
    else:
        error_message = f'Backup {router_backup.id} failed for router {router_backup.router.name} ({router_backup.router.address})'
        if router_backup.error_message:
            error_message += f'\n\nError message: {router_backup.error_message}'
        for message_channel in message_channel_list:
            Message.objects.create(
                channel=message_channel,
                subject=f'Backup failed: {router_backup.id}',
                message=error_message
            )
    return


def notify_backup_task_lock_expired(router_backup: RouterBackup):
    message_channel_list = MessageChannel.objects.filter(enabled=True)
    if not message_channel_list:
        return

    error_message = f'BLOQUEO DE TAREA EXPIRADO: El bloqueo de tarea de respaldo expiró para el respaldo {router_backup.id} del equipo {router_backup.router.name} ({router_backup.router.address}).'
    if router_backup.error_message:
        error_message += f'\n\nMensaje de error: {router_backup.error_message}'
    for message_channel in message_channel_list:
        Message.objects.create(
            channel=message_channel,
            subject=f'Bloqueo de respaldo expirado: {router_backup.id}',
            message=error_message
        )
    return


def notify_important_backup_email(router_backup: RouterBackup, reason: str = "Respaldo Inicial / Manual"):
    """
    Envía por correo electrónico el archivo de configuración adjunto cuando se realiza
    un respaldo inicial o un respaldo manual instantáneo en canales Email con config_change o daily_backup_report activo.
    """
    router = router_backup.router
    email_channels = MessageChannel.objects.filter(enabled=True, channel_type='email', config_change=True)
    if not email_channels.exists():
        return

    msg_body = (
        f"📦 Respaldo de Configuración Guardado ({reason})\n"
        f"Equipo: {router.name} ({router.address})\n"
        f"Fabricante / Tipo: {router.get_router_type_display()}\n"
        f"Revisión: #{router_backup.id}\n"
        f"Fecha: {timezone.localtime(timezone.now()).strftime('%d/%m/%Y %H:%M:%S')}\n\n"
        f"Se adjunta a este correo el archivo de respaldo de configuración."
    )
    for channel in email_channels:
        msg = Message.objects.create(
            channel=channel,
            router_backup=router_backup,
            subject=f"[MEGACOM] Respaldo Adjunto: {router.name} (Rev #{router_backup.id})",
            message=msg_body,
        )
        send_notification_message(msg)
