import json
from urllib.parse import unquote

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Q
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from backup.models import BackupProfile
from backup_data.models import RouterBackup
from routerfleet_tools.models import WebadminSettings
from routerlib.router_functions import update_router_information
from user_manager.models import UserAcl
from .forms import RouterForm, RouterGroupForm
from .models import Router, RouterGroup, RouterInformation, RouterStatus, BackupSchedule
from dashboard.models import ActivityLog
import threading
import time
from routerlib.backup_functions import perform_backup

def trigger_soft_cron():
    # Helper to run cron tasks in local dev without real crontab
    try:
        from backup_data.views import (
            view_cron_generate_backup_schedule, 
            view_cron_create_backup_tasks, 
            view_cron_perform_backup_tasks
        )
        # Mock request object for the views
        class MockRequest:
            GET = {}
        mock_req = MockRequest()
        
        view_cron_generate_backup_schedule(mock_req)
        view_cron_create_backup_tasks(mock_req)
        view_cron_perform_backup_tasks(mock_req)
    except Exception as e:
        print(f"Soft-cron error: {e}")

LAST_CRON_RUN = 0

def run_soft_cron_thread():
    global LAST_CRON_RUN
    current_time = time.time()
    # Only run once every 60 seconds
    if current_time - LAST_CRON_RUN > 60:
        LAST_CRON_RUN = current_time
        threading.Thread(target=trigger_soft_cron, daemon=True).start()


@login_required
def view_router_list(request):
    run_soft_cron_thread()
    router_list = Router.objects.all().prefetch_related(
        'routerstatus', 
        'routerinformation', 
        'backupschedule', 
        'routergroup_set'
    ).order_by('name')

    status_filter = request.GET.get('status')
    if status_filter == 'online':
        router_list = router_list.filter(routerstatus__status_online=True, monitoring=True)
    elif status_filter == 'offline':
        router_list = router_list.filter(routerstatus__status_online=False, monitoring=True)

    last_router_status_change = RouterStatus.objects.filter(last_status_change__isnull=False).order_by('-last_status_change').first()
    if last_router_status_change:
        last_status_change_timestamp = last_router_status_change.last_status_change.isoformat()
    else:
        last_status_change_timestamp = 0

    default_backup_profile, default_backup_profile_created = BackupProfile.objects.get_or_create(name='default')
    filter_group = None
    if request.GET.get('filter_group'):
        if request.GET.get('filter_group') == 'all':
            pass
        else:
            filter_group = get_object_or_404(RouterGroup, uuid=request.GET.get('filter_group'))
            router_list = router_list.filter(routergroup=filter_group)

    if request.GET.get('q'):
        q = request.GET.get('q')
        router_list = router_list.filter(
            Q(name__icontains=q) | 
            Q(address__icontains=q) | 
            Q(internal_notes__icontains=q) |
            Q(router_type__icontains=q) |
            Q(routerinformation__os_version__icontains=q) |
            Q(routerinformation__model_name__icontains=q) |
            Q(routerinformation__serial_number__icontains=q)
        ).distinct()

    if not filter_group and request.GET.get('filter_group') != 'all':
        filter_group = RouterGroup.objects.filter(default_group=True).first()
    # Parse the router_visible_columns cookie
    visible_columns = []
    if 'router_visible_columns' in request.COOKIES:
        try:
            visible_columns = json.loads(unquote(request.COOKIES['router_visible_columns']))
        except json.JSONDecodeError:
            # If the cookie is invalid, use default columns
            visible_columns = ["name", "type", "address", "status", "backup", "groups"]
    else:
        # Default columns if cookie doesn't exist
        visible_columns = ["name", "type", "address", "status", "backup", "groups"]

    context = {
        'router_list': router_list,
        'page_title': 'Directorio de Equipos',
        'filter_group_list': RouterGroup.objects.all().order_by('name'),
        'filter_group': filter_group,
        'last_status_change_timestamp': last_status_change_timestamp,
        'visible_columns': visible_columns,
    }
    return render(request, 'router_manager/router_list.html', context=context)


@login_required()
def view_router_availability(request):
    router = get_object_or_404(Router, uuid=request.GET.get('uuid'))
    data = {
        'router': router,
        'downtime_list': router.routerdowntime_set.all().order_by('-start_time'),
    }
    return render(request, 'router_manager/router_availability.html', context=data)


@login_required()
def view_router_details(request):
    router = get_object_or_404(Router, uuid=request.GET.get('uuid'))
    router_status, router_status_created = RouterStatus.objects.get_or_create(router=router)
    router_backup_list = router.routerbackup_set.all().order_by('-created')
    if router.router_type != 'monitoring':
        router_information, _ = RouterInformation.objects.get_or_create(router=router)
    else:
        router_information = None
    downtime_last_week = router.routerdowntime_set.filter(start_time__gte=timezone.now() - timezone.timedelta(days=7)).aggregate(total=Sum('total_down_time'))['total']
    if downtime_last_week is None:
        downtime_last_week = 0
    total_last_week = 7 * 24 * 60 * 60  # total seconds in a week
    last_week_availability = round((total_last_week - downtime_last_week) / total_last_week * 100, 3)
    if downtime_last_week > 0 and last_week_availability == 100:
        last_week_availability = 99.999

    if router_status.backup_lock:
        if not router_backup_list.filter(success=False, error=False).exists():
            router_status.backup_lock = None
            router_status.save()
            messages.warning(request, 'Bloqueo de respaldo eliminado|Se eliminó el bloqueo de respaldo porque no hay tareas de respaldo activas.')

    context = {
        'router': router,
        'router_information': router_information,
        'router_status': router_status,
        'router_backup_list': router_backup_list,
        'page_title': 'Detalles del Nodo',
        'offline_time_last_week': downtime_last_week,
        'last_week_availability': last_week_availability,
        'command_task_list': router.commandtask_set.all().order_by('-created')[:25],
    }


    return render(request, 'router_manager/router_details.html', context=context)


@login_required()
def view_manage_router(request):
    if not UserAcl.objects.filter(user=request.user).filter(user_level__gte=30).exists():
        return render(request, 'access_denied.html', {'page_title': 'Access Denied'})
    webadmin_settings, webadmin_settings_created = WebadminSettings.objects.get_or_create(name='webadmin_settings')

    uuid = request.GET.get('uuid')
    if uuid:
        router = get_object_or_404(Router, uuid=uuid)
        if request.GET.get('action') == 'delete':
            if request.GET.get('confirmation') in ['delete', 'borrar']:
                router.delete()
                messages.success(request, 'Equipo eliminado correctamente')
                webadmin_settings.router_config_last_updated = timezone.now()
                webadmin_settings.save()
                return redirect('router_list')
            else:
                messages.warning(request, 'Equipo no eliminado|Confirmación inválida')
                return redirect('router_list')
        elif request.GET.get('action') == 'refresh_information':
            router_information, created = RouterInformation.objects.get_or_create(router=router)
            router_information.next_retry = timezone.now()
            router_information.retry_count = 0
            router_information.success = False
            router_information.error = False
            router_information.error_message = ''
            router_information.save()
            success, error_msg = update_router_information(router_information)
            if success:
                messages.success(request, 'Información del equipo actualizada correctamente')
            else:
                messages.warning(request, f'Error al actualizar información del equipo: {error_msg}')
            return redirect('/router/details/?uuid=' + str(router.uuid))
    else:
        router = None

    form = RouterForm(request.POST or None, instance=router)
    if form.is_valid():
        saved_router = form.save()
        
        # Log the activity
        action = "Equipo Editado" if uuid else "Equipo Creado"
        ActivityLog.objects.create(
            user=request.user,
            action=action,
            details=f"Equipo '{saved_router.name}' ({saved_router.address})",
            router=saved_router
        )

        # Handle group assignment (M2M)
        selected_group = form.cleaned_data.get('router_group')
        # Remove router from all current groups
        for group in RouterGroup.objects.filter(routers=saved_router):
            group.routers.remove(saved_router)
        # Add to selected group if one was chosen
        if selected_group:
            selected_group.routers.add(saved_router)
        messages.success(request, 'Equipo guardado correctamente|Puede tomar unos minutos hasta que inicie el monitoreo para este equipo.')
        router_status, router_status_created = RouterStatus.objects.get_or_create(router=saved_router)
        BackupSchedule.objects.filter(router=saved_router).delete()
        if saved_router.router_type == 'monitoring':
            RouterInformation.objects.filter(router=saved_router).delete()
        webadmin_settings.router_config_last_updated = timezone.now()
        webadmin_settings.save()
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('ajax'):
            return JsonResponse({'status': 'success', 'message': 'Equipo guardado correctamente'})
        return redirect('router_list')

    context = {
        'form': form,
        'page_title': 'Gestionar Nodo',
        'instance': router
    }
    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('ajax'):
        return render(request, 'router_manager/router_form_modal.html', context=context, status=400 if form.errors else 200)
    return render(request, 'generic_form.html', context=context)


@login_required()
def view_router_group_list(request):
    context = {
        'router_group_list': RouterGroup.objects.all().order_by('name'),
        'page_title': 'Grupos de Nodos',
    }
    return render(request, 'router_manager/router_group_list.html', context=context)


@login_required()
def view_manage_router_group(request):
    if not UserAcl.objects.filter(user=request.user).filter(user_level__gte=40).exists():
        return render(request, 'access_denied.html', {'page_title': 'Acceso Denegado'})
    if request.GET.get('uuid'):
        router_group = get_object_or_404(RouterGroup, uuid=request.GET.get('uuid'))
        if request.GET.get('action') == 'delete':
            if request.GET.get('confirmation') == 'delete':
                router_group.delete()
                messages.success(request, 'Grupo de Nodos eliminado correctamente')
                return redirect('router_group_list')
            else:
                messages.warning(request, 'Grupo de Nodos no eliminado|Confirmación inválida')
                return redirect('router_group_list')
    else:
        router_group = None

    form = RouterGroupForm(request.POST or None, instance=router_group)
    if form.is_valid():
        form.save()
        messages.success(request, 'Grupo de Nodos guardado correctamente')
        return redirect('router_group_list')

    context = {
        'form': form,
        'page_title': 'Gestionar Grupo de Nodos',
        'instance': router_group
    }
    return render(request, 'generic_form.html', context=context)





import time

def process_backup_fully(backup_uuid):
    # Process all steps of a backup (usually Execute -> Retrieve)
    for _ in range(3): # Max 3 attempts/steps
        try:
            backup = RouterBackup.objects.get(uuid=backup_uuid)
            if backup.success or backup.error:
                break
            perform_backup(backup)
            # If it's waiting for retrieval, wait a few seconds instead of the profile's long interval
            if backup.backup_pending_retrieval and not backup.success:
                time.sleep(5)
            else:
                break
        except Exception:
            break

def create_instant_backup(router):
    # Auto-cleanup stuck tasks older than 5 minutes
    stuck_tasks = RouterBackup.objects.filter(router=router, success=False, error=False, created__lt=timezone.now() - timezone.timedelta(minutes=5))
    if stuck_tasks.exists():
        stuck_tasks.update(error=True, error_message='Backup task timed out/stuck (autocleaned after 5m)')
        # Also clear the backup lock if it matches the stuck task
        router.routerstatus.backup_lock = None
        router.routerstatus.save()

    if RouterBackup.objects.filter(router=router, success=False, error=False).exists():
        return 'Active router backup task already exists'

    if router.routerstatus.backup_lock:
        return 'Router backup is currently locked'

    if not router.backup_profile:
        return 'Router has no backup profile'

    router_backup = RouterBackup.objects.create(
        router=router,
        schedule_time=timezone.now(),
        schedule_type='instant'
    )

    router.routerstatus.backup_lock = router_backup.schedule_time
    router.routerstatus.save()

    # Process the backup in the background immediately
    threading.Thread(target=process_backup_fully, args=(router_backup.uuid,)).start()

    return None


@login_required()
def view_create_instant_backup_task(request):
    if not UserAcl.objects.filter(user=request.user, user_level__gte=20).exists():
        return render(request, 'access_denied.html', {'page_title': 'Acceso Denegado'})

    router = get_object_or_404(Router, uuid=request.GET.get('uuid'))
    router_details_url = f'/router/details/?uuid={router.uuid}'

    error = create_instant_backup(router)
    if error:
        messages.warning(request, f'Tarea de respaldo no creada | {error}')
    else:
        messages.success(request, 'Tarea de respaldo creada correctamente')

    return redirect(router_details_url)


@login_required
def view_create_instant_backup_multiple_routers(request):
    if request.method == 'POST':
        if not UserAcl.objects.filter(user=request.user, user_level__gte=20).exists():
            return JsonResponse({'error': 'Permiso denegado.'}, status=403)

        uuids = request.POST.getlist('routers[]')
        if not uuids:
            return JsonResponse({'error': 'No se seleccionaron equipos.'}, status=400)

        results = []
        for uuid in uuids:
            router = get_object_or_404(Router, uuid=uuid)
            error = create_instant_backup(router)
            results.append({'router': router.name, 'status': error})

        return JsonResponse({'results': results})

    return JsonResponse({'error': 'Método de solicitud no válido.'}, status=405)


@login_required
def view_manage_router_groups_multiple(request):
    if not UserAcl.objects.filter(user=request.user, user_level__gte=20).exists():
        return render(request, 'access_denied.html', {'page_title': 'Acceso Denegado'})

    if request.method == 'POST':
        router_uuids = request.POST.getlist('router_uuids')
        add_group_uuid = request.POST.get('add_group')
        remove_group_uuid = request.POST.get('remove_group')

        if not router_uuids:
            messages.warning(request, 'No se seleccionaron equipos')
            return redirect('router_list')

        # Validate that the same group is not selected for both add and remove
        if add_group_uuid and remove_group_uuid and add_group_uuid == remove_group_uuid:
            messages.warning(request, 'No se puede añadir y eliminar del mismo grupo')
            return redirect('router_list')

        routers = Router.objects.filter(uuid__in=router_uuids)

        # Process add to group
        if add_group_uuid:
            try:
                group = RouterGroup.objects.get(uuid=add_group_uuid)
                for router in routers:
                    group.routers.add(router)
                messages.success(request, f'Se añadieron {routers.count()} equipo(s) al grupo {group.name}')
            except RouterGroup.DoesNotExist:
                messages.error(request, 'Grupo no encontrado')

        # Process remove from group
        if remove_group_uuid:
            try:
                group = RouterGroup.objects.get(uuid=remove_group_uuid)
                for router in routers:
                    group.routers.remove(router)
                messages.success(request, f'Se eliminaron {routers.count()} equipo(s) del grupo {group.name}')
            except RouterGroup.DoesNotExist:
                messages.error(request, 'Grupo no encontrado')

        return redirect('router_list')

    # GET request - display form
    router_uuids = request.GET.getlist('routers[]')
    if not router_uuids:
        messages.warning(request, 'No se seleccionaron equipos')
        return redirect('router_list')

    routers = Router.objects.filter(uuid__in=router_uuids)
    groups = RouterGroup.objects.all().order_by('name')

    context = {
        'routers': routers,
        'groups': groups,
        'page_title': 'Gestionar Grupos de Nodos',
    }

    return render(request, 'router_manager/manage_router_groups.html', context)


def view_cron_update_router_information(request):
    data = {'status': 'success'}
    refresh_interval = 24 #hours

    router_list = Router.objects.filter(enabled=True).exclude(router_type='monitoring').exclude(routerstatus__status_online=False)
    router = router_list.filter(routerinformation__isnull=True).first()
    if not router:
        router = router_list.filter(routerinformation__next_retry__lt=timezone.now()).first()
    if not router:
        router = router_list.filter(routerinformation__last_retrieval__isnull=True).first()
    if not router:
        router = router_list.filter(routerinformation__last_retrieval__lt=timezone.now() - timezone.timedelta(hours=refresh_interval)).first()

    if router:
        router_information, created = RouterInformation.objects.get_or_create(router=router)
        success, error_message = update_router_information(router_information)
        if not success:
            data['status'] = 'error'
            data['message'] = 'Failed to update router'
    else:
        data['message'] = 'No routers need update'

    return JsonResponse(data)
