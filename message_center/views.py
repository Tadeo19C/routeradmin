from django.http import JsonResponse, Http404
from django.shortcuts import render, redirect, Http404, get_object_or_404
from django.contrib import messages
import pytz
from router_manager.models import Router
from routerfleet_tools.models import WebadminSettings
from user_manager.models import UserAcl
from .forms import MessageSettingsForm, MessageChannelForm
from .models import Notification, MessageChannel, Message, MessageSettings
from django.contrib.auth.decorators import login_required
from django.conf import settings
from .functions import notify_router_status_update, notify_backup_fail, send_notification_message, \
    concatenate_notifications, generate_backup_report, generate_status_report
from backup_data.models import RouterBackup
import datetime
from django.utils import timezone
from django.db.models import Q
import uuid

@login_required()
def view_debug_test_messages(request):
    if not settings.DEBUG:
        raise Http404
    data = {'status': 'success', 'message': ''}
    router = None
    router_backup = None
    if request.GET.get('router_uuid'):
        router = get_object_or_404(Router, uuid=request.GET.get('router_uuid'))
        data['message'] = f'Sending status update notification for router {router.name}'
        notify_router_status_update(router)
    elif request.GET.get('backup_id'):
        router_backup = get_object_or_404(RouterBackup, id=request.GET.get('backup_id'))
        data['message'] = f'Sending backup fail notification for backup {router_backup.id} of router {router_backup.router.name}'
        notify_backup_fail(router_backup)
    else:
        data['message'] = 'No router_uuid or backup_id provided.'

    # Process pending messages to send the test notification immediately
    for message in Message.objects.filter(status='pending'):
        send_notification_message(message)
    return JsonResponse(data)


def view_cron_daily_reports(request):
    message_settings, _ = MessageSettings.objects.get_or_create(name='message_settings')
    now = timezone.now()
    data = {
        'status': 'success', 'valid_report_window': False, 'next_report_time': None,
        'report_time_exception': False, 'no_channel_available': '',
        'run_backup_report': False, 'run_status_report': False,
    }
    last_report_limit = now - datetime.timedelta(hours=12)

    try:
        report_hour, report_minute = map(int, message_settings.daily_report_time.split(':'))
        if not 0 <= report_hour <= 23:
            report_hour = 0
        if not 0 <= report_minute <= 59:
            report_minute = 0
        user_timezone = pytz.timezone(settings.TIME_ZONE)
        local_now = now.astimezone(user_timezone)
        report_time = local_now.replace(hour=report_hour, minute=report_minute, second=0, microsecond=0)
    except:
        report_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
        data['report_time_exception'] = True

    if report_time < now - datetime.timedelta(hours=2):
        report_time = report_time + datetime.timedelta(days=1)
    data['next_report_time'] = report_time.isoformat()
    report_time_window_start = report_time - datetime.timedelta(hours=1)
    report_time_window_end = report_time + datetime.timedelta(hours=1)

    if now < report_time:
        data['status'] = 'waiting for backup time'
        return JsonResponse(data)

    if report_time_window_start < now < report_time_window_end:
        data['valid_report_window'] = True
    else:
        return JsonResponse(data)

    run_backup_report = False
    run_status_report = False
    if message_settings.last_daily_backup_report:
        if message_settings.last_daily_backup_report < last_report_limit:
            run_backup_report = True
    else:
        run_backup_report = True
    if message_settings.last_daily_status_report:
        if message_settings.last_daily_status_report < last_report_limit:
            run_status_report = True
    else:
        run_status_report = True

    data['run_backup_report'] = run_backup_report
    data['run_status_report'] = run_status_report

    # Run only one report at a time
    if run_backup_report:
        if MessageChannel.objects.filter(enabled=True, daily_backup_report=True):
            generate_backup_report(data)
        else:
            data['run_backup_report'] = False
            data['no_channel_available'] = 'backup_report '
    elif run_status_report:
        if MessageChannel.objects.filter(enabled=True, daily_status_report=True):
            generate_status_report(data)
        else:
            data['run_status_report'] = False
            data['no_channel_available'] += 'status_report'

    return JsonResponse(data)


def view_cron_send_messages(request):
    data = {
        'status': 'success',
        'messages_sent': 0,
    }
    message_settings, _ = MessageSettings.objects.get_or_create(name='message_settings')
    webadmin_settings, _ = WebadminSettings.objects.get_or_create(name='webadmin_settings')
    update_notification = ''
    if webadmin_settings.update_available:
        update_notification = '\n\nA new version of RouterFleet is available. Please update your installation to get the latest security and feature updates.'
    message_list = Message.objects.filter(status='pending', next_retry__isnull=True)

    if not message_list:
        message_list = Message.objects.filter(status='pending', next_retry__lte=timezone.now())

    for message in message_list:
        if update_notification and message.retry_count == 0:
            if len(message.message + update_notification) < message_settings.max_length:
                message.message += update_notification
                message.save()
        send_notification_message(message)
        data['messages_sent'] += 1
    return JsonResponse(data)


def remove_offline_notifications_for_online_routers():
    # This function is used to remove change status notifications for routers that are currently online but have
    # pending offline notifications.
    # This prevents the system from sending a double status change notification when the router goes offline and then
    # online again.
    offline_list = Notification.objects.filter(
        notification_type='status_offline', router__routerstatus__status_online=True
    )
    for notification in offline_list:
        Notification.objects.filter(router=notification.router).filter(
            Q(notification_type='status_offline') | Q(notification_type='status_online')
        ).delete()
    return


def view_cron_concatenate_notifications(request):
    data = {
        'status': 'success',
        'notification_type': {
            'status_online': 0,
            'status_offline': 0,
            'backup_fail': 0,
        }
    }
    message_settings, _ = MessageSettings.objects.get_or_create(name='message_settings')
    status_change_limit = timezone.now() - datetime.timedelta(seconds=message_settings.status_change_delay)
    backup_fail_limit = timezone.now() - datetime.timedelta(seconds=message_settings.backup_fails_delay)

    if message_settings.concatenate_status_change:
        remove_offline_notifications_for_online_routers()

    if Notification.objects.filter(created__lte=status_change_limit, notification_type='status_offline').exists():
        data['notification_type']['status_offline'] = concatenate_notifications('status_offline')
    if Notification.objects.filter(created__lte=status_change_limit, notification_type='status_online').exists():
        data['notification_type']['status_online'] = concatenate_notifications('status_online')
    if Notification.objects.filter(created__lte=backup_fail_limit, notification_type='backup_fail').exists():
        data['notification_type']['backup_fail'] = concatenate_notifications('backup_fail')
    return JsonResponse(data)


@login_required()
def view_message_channel_list(request):
    if not UserAcl.objects.filter(user=request.user).filter(user_level__gte=20).exists():
        return render(request, 'access_denied.html', {'page_title': 'Acceso Denegado'})
    message_settings, _ = MessageSettings.objects.get_or_create(name='message_settings')
    message_channels = MessageChannel.objects.all()
    context = {
        'page_title': 'Canales de Notificación',
        'message_settings': message_settings,
        'message_channels': message_channels,
    }
    return render(request, 'message_center/message_channel_list.html', context=context)


@login_required()
def view_message_history(request):
    if not UserAcl.objects.filter(user=request.user).filter(user_level__gte=20).exists():
        return render(request, 'access_denied.html', {'page_title': 'Acceso Denegado'})
    message_settings, _ = MessageSettings.objects.get_or_create(name='message_settings')
    message_list = Message.objects.all().order_by('-created')
    context = {
        'page_title': 'Historial de Mensajes',
        'message_settings': message_settings,
        'message_list': message_list,
    }
    return render(request, 'message_center/message_history.html', context=context)


@login_required()
def view_manage_message_settings(request):
    if not UserAcl.objects.filter(user=request.user).filter(user_level__gte=40).exists():
        return render(request, 'access_denied.html', {'page_title': 'Acceso Denegado'})
    message_settings, _ = MessageSettings.objects.get_or_create(name='message_settings')
    form = MessageSettingsForm(request.POST or None, instance=message_settings)
    if form.is_valid():
        form.save()
        messages.success(request, 'Ajustes de Mensajes guardados correctamente')
        return redirect('/message_center/channel_list/')
    form_description_content = '''
    <strong>Longitud Máxima</strong>
    <p>Longitud máxima de un mensaje en caracteres. Los mensajes más largos serán truncados.</p>
    <strong>Hora de Reporte Diario</strong>
    <p>Hora del día para enviar los reportes diarios de estado y respaldo. Formato: HH:MM (reloj de 24 horas)</p>
    <strong>Máximo de Reintentos e Intervalo</strong>
    <p>Número máximo de reintentos para un mensaje fallido y el intervalo entre reintentos en segundos.</p>
    <strong>Concatenar Cambios de Estado</strong>
    <p>
    Cuando está habilitado, el sistema agrupará notificaciones de cambio de estado de múltiples routers en un solo mensaje.
    Si un router se desconecta y vuelve a conectarse dentro del retraso de cambio de estado, el sistema no enviará ningún mensaje.
    </p>
    <strong>Concatenar Fallas de Respaldo</strong>
    <p>En lugar de enviar un mensaje por cada falla de respaldo, el sistema agrupará múltiples fallas en un solo mensaje.</p>
    <strong>Retraso de Cambio de Estado y Falla de Respaldo</strong>
    <p>Tiempo en segundos para esperar notificaciones adicionales antes de enviar un mensaje concatenado.</p>
    '''

    context = {
        'page_title': 'Ajustes de Notificaciones',
        'message_settings': message_settings,
        'form': form,
        'form_description': {
            'size': '',
            'content': form_description_content
        },
    }
    return render(request, 'generic_form.html', context=context)


@login_required()
def view_manage_message_channel(request):
    if not UserAcl.objects.filter(user=request.user).filter(user_level__gte=40).exists():
        return render(request, 'access_denied.html', {'page_title': 'Acceso Denegado'})
    message_settings, _ = MessageSettings.objects.get_or_create(name='message_settings')
    if request.GET.get('uuid'):
        message_channel = MessageChannel.objects.get(uuid=request.GET.get('uuid'))
        if request.GET.get('action') == 'delete':
            if request.GET.get('confirmation') == 'delete':
                message_channel.delete()
                messages.success(request, 'Canal de Notificación eliminado correctamente')
                return redirect('/message_center/channel_list/')
            else:
                messages.warning(request, 'Canal de Notificación no eliminado|Confirmación inválida')
                return redirect('/message_center/channel_list/')
    else:
        message_channel = None

    form = MessageChannelForm(request.POST or None, instance=message_channel)
    if form.is_valid():
        form.save()
        messages.success(request, 'Canal de Notificación guardado correctamente')
        return redirect('/message_center/channel_list/')
    form_description_content = f'''
    <strong>Destino</strong>
    <p>Dirección de destino para el canal de mensajes. 
    <ul>
    <li>Para CallMeBot, este es el número de teléfono.</li>
    <li>Para ntfy.sh, este es el nombre del tema. Considere usar algo <strong>muy</strong> único, como: routerfleet-{uuid.uuid4()}</li>
    </ul>
    </p>
    <strong>Token</strong>
    <p>Para CallMeBot, este es el token API. Para ntfy.sh, deje esto en blanco.</p>
    <strong>Cambio de Estado y Falla de Respaldo</strong>
    <p>Habilitar o deshabilitar notificaciones para cambios de estado y fallas de respaldo.</p>
    <strong>Reporte Diario de Estado y Respaldo</strong>
    <p>Habilitar o deshabilitar reportes diarios. Este es un resumen rápido del estado online/offline y el éxito/falla de los respaldos.</p>
    
    '''

    context = {
        'page_title': 'Gestionar Canal de Notificación',
        'message_settings': message_settings,
        'form': form,
        'form_description': {
            'size': '',
            'content': form_description_content
        },
    }
    return render(request, 'generic_form.html', context=context)
