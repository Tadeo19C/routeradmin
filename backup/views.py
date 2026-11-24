from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse, FileResponse
from django.shortcuts import render, get_object_or_404, redirect, Http404
from django.contrib import messages

from routerfleet_tools.models import WebadminSettings
from routerlib.backup_functions import perform_backup
from .models import BackupProfile
from .forms import BackupProfileForm
from router_manager.models import Router, BackupSchedule
from backup_data.models import RouterBackup
import difflib
import unicodedata
from routerlib.functions import gen_backup_name, get_router_backup_file_extension
from django.conf import settings
from user_manager.models import UserAcl
from django.utils import timezone


@login_required()
def view_backup_profile_list(request):
    default_backup_profile, _ = BackupProfile.objects.get_or_create(name='default')
    BackupProfile.objects.filter(name__startswith='Perfil Automático -', router__isnull=True).delete()
    context = {
        'backup_profile_list': BackupProfile.objects.all().order_by('name'),
        'page_title': 'Backup Profiles'
    }
    return render(request, 'backup/backup_profile_list.html', context)


@login_required()
def view_manage_backup_profile(request):
    if not UserAcl.objects.filter(user=request.user).filter(user_level__gte=40).exists():
        return render(request, 'access_denied.html', {'page_title': 'Access Denied'})
    if request.GET.get('uuid'):
        backup_profile = get_object_or_404(BackupProfile, uuid=request.GET.get('uuid'))
        if request.GET.get('action') == 'delete':
            if request.GET.get('confirmation') == 'delete':
                if backup_profile.name == 'default':
                    messages.warning(request, 'Backup profile not deleted|Default profile cannot be deleted')
                    return redirect('backup_profile_list')
                else:
                    if Router.objects.filter(backup_profile=backup_profile).exists():
                        messages.warning(request, 'Backup profile in use|Backup profile is in use and cannot be deleted')
                        return redirect('backup_profile_list')
                    else:
                        backup_profile.delete()
                        messages.success(request, 'Backup profile deleted successfully')
                return redirect('backup_profile_list')
            else:
                messages.warning(request, 'Backup profile not deleted|Invalid confirmation')
                return redirect('backup_profile_list')
    else:
        backup_profile = None

    form = BackupProfileForm(request.POST or None, instance=backup_profile)
    if form.is_valid():
        form.instance.profile_error_information = ''
        form.save()
        BackupSchedule.objects.filter(router__backup_profile=form.instance).delete()
        from backup_data.services import service_generate_backup_schedule
        service_generate_backup_schedule()
        messages.success(request, 'Backup Profile saved successfully')
        return redirect('backup_profile_list')

    context = {
        'form': form,
        'page_title': 'Manage Backup Profile',
        'instance': backup_profile
    }
    return render(request, 'backup/backup_profile_form.html', context=context)


@login_required()
def view_backup_list(request):
    backup_list = RouterBackup.objects.select_related('router', 'router__routerstatus').all().order_by('-created')
    router_uuid = request.GET.get('router')
    if router_uuid:
        backup_list = backup_list.filter(router__uuid=router_uuid)

    if request.GET.get('type') == 'queue':
        backup_list = backup_list.filter(error=False, success=False).order_by('next_retry')
        view_type = 'queue'
    elif request.GET.get('type') == 'errors' or request.GET.get('status') == 'error':
        backup_list = backup_list.filter(error=True).order_by('-created')
        view_type = 'errors'
    else:
        # Mostrar solo respaldos reales (iniciales o con cambios reales detectados)
        backup_list = backup_list.filter(success=True, identical_to_previous=False).order_by('-created')
        view_type = 'success'

    backup_list = list(backup_list)
    if view_type == 'success':
        last_seen_by_router = {}
        for b in reversed(backup_list):
            b.prev_backup_uuid = last_seen_by_router.get(b.router_id)
            last_seen_by_router[b.router_id] = str(b.uuid)

    context = {
        'backup_list': backup_list,
        'page_title': 'Lista de Respaldos',
        'view_type': view_type,
    }
    return render(request, 'backup/backup_list.html', context)


@login_required()
def view_backup_details(request):
    if not UserAcl.objects.filter(user=request.user).filter(user_level__gte=20).exists():
        return render(request, 'access_denied.html', {'page_title': 'Access Denied'})
    backup = get_object_or_404(RouterBackup, uuid=request.GET.get('uuid'))

    if request.GET.get('show_console') == 'true':
        show_console = True
    else:
        show_console = False

    if request.GET.get('action') == 'anticipate':
        if not backup.success and not backup.error:
            backup.next_retry = timezone.now()
            backup.save()
            messages.success(request, 'Backup task anticipated|Backup task will be retried shortly')
        else:
            messages.warning(request, 'Backup task not anticipated|Task is already completed')
        return redirect(f'/backup/backup_details/?uuid={backup.uuid}&show_console={str(show_console).lower()}')
    hash_list = [backup.backup_text_hash]
    backup_list = []
    for backup_item in RouterBackup.objects.filter(router=backup.router, success=True).order_by('-created'):
        if backup_item.backup_text_hash and backup_item.backup_text_hash not in hash_list:
            hash_list.append(backup_item.backup_text_hash)
            backup_list.append(backup_item)
    webadmin_settings, _ = WebadminSettings.objects.get_or_create(name='webadmin_settings')
    
    # Safety Layer: Truncate very large backups for display
    display_text = backup.backup_text or ""
    backup_truncated = False
    SIZE_LIMIT = 512000 # 500KB
    if len(display_text) > SIZE_LIMIT:
        display_text = display_text[:SIZE_LIMIT] + "\n\n[... TEXTO TRUNCADO POR SEGURIDAD. DESCARGUE EL ARCHIVO PARA VER EL CONTENIDO COMPLETO ...]"
        backup_truncated = True

    context = {
        'backup': backup,
        'display_text': display_text,
        'backup_truncated': backup_truncated,
        'backup_list': backup_list,
        'page_title': 'Detalles del Respaldo',
        'webadmin_settings': webadmin_settings,
        'now': timezone.now(),
        '5_minutes_ago': timezone.now() - timezone.timedelta(minutes=5),
        'show_console': show_console
    }
    return render(request, 'backup/backup_details.html', context)


def normalize_text(text):
    text = unicodedata.normalize('NFC', text)
    text = text.replace('\r\n', '\n')
    text = text.replace('\r', '')
    text = '\n'.join([line.rstrip() for line in text.splitlines()])
    return text


@login_required()
def view_compare_backups(request):
    if not UserAcl.objects.filter(user=request.user).filter(user_level__gte=20).exists():
        return render(request, 'access_denied.html', {'page_title': 'Access Denied'})
    
    backup1 = get_object_or_404(RouterBackup, uuid=request.GET.get('uuid'))
    compare_uuid = request.GET.get('compare_uuid')
    target_rev = request.GET.get('target_rev')

    if target_rev and target_rev.isdigit():
        target_b = RouterBackup.objects.filter(router=backup1.router, id=int(target_rev)).first()
        if target_b:
            backup2 = target_b
        else:
            backup2 = backup1
    elif not compare_uuid:
        previous = RouterBackup.objects.filter(
            router=backup1.router, success=True, created__lt=backup1.created, backup_text__isnull=False
        ).exclude(backup_text='').order_by('-created').first()
        if previous:
            backup2 = backup1
            backup1 = previous
        else:
            backup2 = backup1
    else:
        backup2 = get_object_or_404(RouterBackup, uuid=compare_uuid)

    # Asegurar que el más antiguo quede a la izquierda (backup1) y el más nuevo a la derecha (backup2)
    if backup1.created > backup2.created:
        backup1, backup2 = backup2, backup1

    router = backup1.router
    show_all = request.GET.get('display') == 'all'
    ignore_ws = request.GET.get('ignore_ws') == '1'
    show_lines = 100000 if show_all else 3

    # Normalización inteligente de configuración
    from routerlib.config_normalizer import normalize_config
    text1_norm = normalize_config(backup1.backup_text or '', router.router_type)
    text2_norm = normalize_config(backup2.backup_text or '', router.router_type)

    if ignore_ws:
        import re
        lines1 = [re.sub(r'\s+', ' ', line.strip()) + '\n' for line in text1_norm.splitlines()]
        lines2 = [re.sub(r'\s+', ' ', line.strip()) + '\n' for line in text2_norm.splitlines()]
    else:
        lines1 = [line + '\n' for line in text1_norm.splitlines()]
        lines2 = [line + '\n' for line in text2_norm.splitlines()]

    fromfile_label = f"Rev #{backup1.id} ({backup1.created.strftime('%d/%m/%Y %H:%M')})"
    tofile_label = f"Rev #{backup2.id} ({backup2.created.strftime('%d/%m/%Y %H:%M')})"

    diff = difflib.unified_diff(
        lines1,
        lines2,
        fromfile=fromfile_label,
        tofile=tofile_label,
        lineterm='',
        n=show_lines
    )
    diff_str = '\n'.join(list(diff))

    # Obtener listado de revisiones para el navegador temporal y menú rápido
    all_backups = RouterBackup.objects.filter(
        router=router, success=True, backup_text__isnull=False
    ).exclude(backup_text='').order_by('-created')

    prev_backup = all_backups.filter(created__lt=backup1.created).first()
    next_backup = all_backups.filter(created__gt=backup2.created).order_by('created').first()
    latest_backup = all_backups.first()

    primary_group = router.routergroup_set.first()

    context = {
        'backup1': backup1,
        'backup2': backup2,
        'router': router,
        'primary_group': primary_group,
        'diff_str': diff_str,
        'page_title': f'Comparar: {router.name} (Rev #{backup1.id} ➔ #{backup2.id})',
        'show_all': show_all,
        'ignore_ws': ignore_ws,
        'all_backups': all_backups[:35],
        'prev_backup': prev_backup,
        'next_backup': next_backup,
        'latest_backup': latest_backup,
    }

    return render(request, 'backup/compare_backups.html', context)


def view_debug_run_backups(request):
    data = {
        'backup_count': 0,
    }
    if settings.DEBUG:
        for backup in RouterBackup.objects.filter(success=False, error=False):
            data['backup_count'] += 1
            perform_backup(backup)
    else:
        data['error'] = 'Debug mode is not enabled'
    return JsonResponse(data)


@login_required()
def view_backup_download(request):
    if not UserAcl.objects.filter(user=request.user).filter(user_level__gte=20).exists():
        return render(request, 'access_denied.html', {'page_title': 'Access Denied'})
    backup = get_object_or_404(RouterBackup, uuid=request.GET.get('uuid'))
    ext_map = get_router_backup_file_extension(backup.router.router_type)
    if request.GET.get('type') == 'text':
        content = backup.backup_text or ''
        response = HttpResponse(content, content_type='text/plain; charset=utf-8')
        if backup.backup_text_filename:
            filename = backup.backup_text_filename
        else:
            filename = f'{gen_backup_name(backup)}.{ext_map["text"]}'
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
    elif request.GET.get('type') == 'binary':
        if backup.backup_binary and backup.backup_binary.name:
            try:
                return FileResponse(backup.backup_binary.open('rb'), as_attachment=True)
            except Exception:
                pass
        # Fallback binario a partir de la configuración si el archivo físico no existe por separado
        bin_ext = ext_map.get('binary') or 'backup'
        filename = f'{gen_backup_name(backup)}.{bin_ext}'
        content = (backup.backup_text or '').encode('utf-8')
        response = HttpResponse(content, content_type='application/octet-stream')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
    else:
        raise Http404


@login_required()
def view_backup_delete(request):
    if not UserAcl.objects.filter(user=request.user).filter(user_level__gte=30).exists():
        return render(request, 'access_denied.html', {'page_title': 'Access Denied'})
    backup = get_object_or_404(RouterBackup, uuid=request.GET.get('uuid'))
    router = backup.router
    redirect_url = f'/router/details/?uuid={backup.router.uuid}'
    if request.GET.get('confirmation') in [f'delete{backup.id}', f'borrar{backup.id}']:
        backup.delete()
        messages.success(request, 'Backup deleted successfully')
        if router.routerstatus.backup_lock:
            if not RouterBackup.objects.filter(router=router, success=False, error=False).exists():
                router.routerstatus.backup_lock = None
                router.routerstatus.save()
        return redirect(redirect_url)
    else:
        messages.warning(request, 'Backup not deleted|Invalid confirmation')
        return redirect(f'/backup/backup_details/?uuid={backup.uuid}')
@login_required()
def view_get_backup_profile_details(request):
    profile_uuid = request.GET.get('uuid')
    if not profile_uuid:
        return JsonResponse({'error': 'Missing UUID'}, status=400)
    
    profile = get_object_or_404(BackupProfile, uuid=profile_uuid)
    data = {
        'name': profile.name,
        'hourly_backup': profile.hourly_backup,
        'daily_backup': profile.daily_backup,
        'weekly_backup': profile.weekly_backup,
        'hourly_interval': profile.hourly_interval,
        'daily_hour': profile.daily_hour,
        'daily_minute': getattr(profile, 'daily_minute', 0) or 0,
        'weekly_day': profile.weekly_day,
        'weekly_hour': profile.weekly_hour,
        'weekly_minute': getattr(profile, 'weekly_minute', 0) or 0,
        # Add other fields if needed for the UI
    }
    return JsonResponse(data)


@login_required()
def view_config_search(request):
    """
    Buscador Global de Configuraciones (Network-Wide Config Search).
    Busca texto o expresiones regulares a través del último respaldo exitoso
    de todos los equipos activos (MikroTik, Cisco IOS, Huawei VRP, ZTE).
    """
    import time
    import re
    from router_manager.models import RouterGroup, SUPPORTED_ROUTER_TYPES

    if not UserAcl.objects.filter(user=request.user).filter(user_level__gte=20).exists():
        return render(request, 'access_denied.html', {'page_title': 'Acceso Denegado'})

    q = (request.GET.get('q') or '').strip()
    router_type = (request.GET.get('router_type') or '').strip()
    group_uuid = (request.GET.get('group') or '').strip()
    use_regex = request.GET.get('regex') == '1'
    case_sensitive = request.GET.get('case') == '1'

    results = []
    total_matches = 0
    scanned_routers_count = 0
    elapsed_ms = 0
    regex_error = None

    routers_qs = Router.objects.filter(enabled=True).exclude(router_type='monitoring').prefetch_related('routergroup_set')
    if router_type:
        routers_qs = routers_qs.filter(router_type=router_type)
    if group_uuid:
        routers_qs = routers_qs.filter(routergroup__uuid=group_uuid)

    if q:
        t0 = time.perf_counter()
        flags = 0 if case_sensitive else re.IGNORECASE
        pattern = None
        if use_regex:
            try:
                pattern = re.compile(q, flags)
            except re.error as e:
                regex_error = f"Expresión regular inválida: {e}"
        else:
            pattern = re.compile(re.escape(q), flags)

        if pattern:
            for r in routers_qs.order_by('name'):
                latest_b = (
                    RouterBackup.objects.filter(router=r, success=True, backup_text__isnull=False)
                    .exclude(backup_text='')
                    .order_by('-created')
                    .first()
                )
                if not latest_b or not latest_b.backup_text:
                    continue
                scanned_routers_count += 1
                matched_lines = []
                for idx, line in enumerate(latest_b.backup_text.splitlines(), 1):
                    if pattern.search(line):
                        matched_lines.append({
                            'line_number': idx,
                            'line_text': line,
                        })
                        total_matches += 1
                        if len(matched_lines) >= 100:
                            break
                if matched_lines:
                    results.append({
                        'router': r,
                        'backup': latest_b,
                        'matches': matched_lines,
                        'match_count': len(matched_lines),
                    })
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)

    context = {
        'page_title': 'Buscador Global de Configuraciones',
        'q': q,
        'router_type': router_type,
        'group_uuid': group_uuid,
        'use_regex': use_regex,
        'case_sensitive': case_sensitive,
        'results': results,
        'total_matches': total_matches,
        'matched_routers_count': len(results),
        'scanned_routers_count': scanned_routers_count,
        'elapsed_ms': elapsed_ms,
        'regex_error': regex_error,
        'router_types': SUPPORTED_ROUTER_TYPES,
        'router_groups': RouterGroup.objects.all().order_by('name'),
        'view_type': 'search',
    }
    return render(request, 'backup/config_search.html', context)


@login_required()
def view_send_backup_email_now(request):
    """Envía bajo demanda un respaldo específico al canal de correo configurado."""
    if not UserAcl.objects.filter(user=request.user).filter(user_level__gte=20).exists():
        return render(request, 'access_denied.html', {'page_title': 'Acceso Denegado'})

    backup = get_object_or_404(RouterBackup, uuid=request.GET.get('uuid'))
    from message_center.models import MessageChannel, Message
    from message_center.functions import send_notification_message

    email_channels = MessageChannel.objects.filter(channel_type='email', enabled=True)
    if not email_channels.exists():
        messages.warning(request, 'Correo no configurado|Primero configure su correo destinatario y SMTP en la pestaña "Correo de Respaldos".')
        return redirect('/message_center/email_backups/')

    sent_to = []
    for ch in email_channels:
        msg_body = (
            f"📦 Respaldo enviado desde BACKUP WEB\n"
            f"Equipo: {backup.router.name} ({backup.router.address})\n"
            f"Fabricante / Tipo: {backup.router.get_router_type_display()}\n"
            f"Revisión: #{backup.id} ({backup.created.strftime('%d/%m/%Y %H:%M:%S')})\n\n"
            f"Se adjunta el archivo de configuración de este respaldo."
        )
        msg = Message.objects.create(
            channel=ch,
            router_backup=backup,
            subject=f"[BACKUP WEB] Respaldo #{backup.id} - {backup.router.name}",
            message=msg_body,
        )
        send_notification_message(msg)
        if msg.status == 'sent':
            sent_to.append(ch.destination)
        else:
            messages.warning(request, f'Error al enviar a {ch.destination}|{msg.error_message}')

    if sent_to:
        messages.success(request, f'Respaldo enviado por correo|Se envió el respaldo #{backup.id} de {backup.router.name} a {", ".join(sent_to)}.')

    next_url = request.META.get('HTTP_REFERER') or '/backup/backup_list/'
    return redirect(next_url)
