import re
import json
from urllib.parse import unquote

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Q
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from backup.models import BackupProfile
from backup_data.models import RouterBackup
from routerfleet_tools.models import WebadminSettings
from routerlib.router_functions import update_router_information
from user_manager.models import UserAcl
from django.conf import settings
from .forms import DeviceCategoryForm, RouterForm, RouterGroupForm, RouterClientForm
from .models import DeviceCategory, Router, RouterGroup, RouterClient, RouterInformation, RouterStatus, BackupSchedule
from .normalization import get_first_category, find_matching_node, get_category_limit_message
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
    qs = request.META.get('QUERY_STRING', '')
    return redirect('/router/group_list/' + ('?' + qs if qs else ''))


def _legacy_view_router_list(request):
    run_soft_cron_thread()
    router_list = Router.objects.all().prefetch_related(
        'routerstatus', 
        'routerinformation', 
        'backupschedule', 
        'routergroup_set'
    ).order_by('name')

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

    all_groups = list(RouterGroup.objects.all().order_by('name'))
    routers_eval = list(router_list)
    latest_backups_map = {}
    for rb in RouterBackup.objects.filter(success=True).order_by('router_id', '-created').values('router_id', 'uuid'):
        if rb['router_id'] not in latest_backups_map:
            latest_backups_map[rb['router_id']] = str(rb['uuid'])
    for r in routers_eval:
        r.latest_backup_uuid = latest_backups_map.get(r.id)
    grouped_nodes = []
    for grp in all_groups:
        grp_routers = [r for r in routers_eval if grp in r.routergroup_set.all()]
        if not grp_routers and (request.GET.get('q') or request.GET.get('status')):
            continue
        online_cnt = sum(
            1 for r in grp_routers
            if not r.monitoring or (getattr(r, 'routerstatus', None) and r.routerstatus.status_online)
        )
        offline_cnt = len(grp_routers) - online_cnt
        grouped_nodes.append({
            'group': grp,
            'name': grp.name,
            'uuid': str(grp.uuid),
            'internal_notes': grp.internal_notes or '',
            'routers': grp_routers,
            'total_count': len(grp_routers),
            'online_count': online_cnt,
            'offline_count': offline_cnt,
        })

    ungrouped_routers = [r for r in routers_eval if not r.routergroup_set.all()]
    if ungrouped_routers:
        online_cnt = sum(
            1 for r in ungrouped_routers
            if not r.monitoring or (getattr(r, 'routerstatus', None) and r.routerstatus.status_online)
        )
        grouped_nodes.append({
            'group': None,
            'name': 'Equipos Sin Nodo Asignado',
            'uuid': 'ungrouped',
            'internal_notes': '',
            'routers': ungrouped_routers,
            'total_count': len(ungrouped_routers),
            'online_count': online_cnt,
            'offline_count': len(ungrouped_routers) - online_cnt,
        })

    context = {
        'router_list': routers_eval,
        'grouped_nodes': grouped_nodes,
        'page_title': 'Dispositivos',
        'filter_group_list': all_groups,
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


def _user_has_acl(user, min_level=30):
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    return UserAcl.objects.filter(user=user, user_level__gte=min_level).exists()


def _delete_router_cleanly(router):
    if router.backup_profile and router.backup_profile.name.startswith("Perfil Automático -"):
        profile_to_delete = router.backup_profile
        router.backup_profile = None
        router.save(update_fields=['backup_profile'])
        if profile_to_delete.router_set.count() == 0:
            profile_to_delete.delete()
    router.delete()


def _resolve_active_category(request):
    cat_param = (
        request.GET.get('category')
        or request.POST.get('category')
        or request.POST.get('category_uuid')
        or ''
    ).strip()
    if cat_param:
        cat = DeviceCategory.objects.filter(uuid=cat_param).first()
        if cat:
            return cat
    return get_first_category()


@login_required()
def view_manage_category(request):
    if not _user_has_acl(request.user, 30):
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('ajax'):
            return JsonResponse({'status': 'error', 'message': 'Acceso Denegado'}, status=403)
        return render(request, 'access_denied.html', {'page_title': 'Acceso Denegado'})

    is_ajax = bool(request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('ajax'))
    action_param = (request.GET.get('action') or request.POST.get('action') or '').strip()
    if action_param == 'delete_all':
        if (request.GET.get('confirmation') or request.POST.get('confirmation') or '').strip().lower() in ('delete', 'borrar', 'confirm', 'todo'):
            all_devs = list(Router.objects.all().select_related('backup_profile'))
            dev_count = len(all_devs)
            cat_count = DeviceCategory.objects.count()
            for dev in all_devs:
                _delete_router_cleanly(dev)
            RouterGroup.objects.all().delete()
            DeviceCategory.objects.all().delete()
            ActivityLog.objects.create(
                user=request.user,
                action="Inventario Completo Eliminado",
                details=f"Se eliminaron todas las categorías ({cat_count}), grupos y dispositivos ({dev_count})",
            )
            WebadminSettings.objects.filter(name='webadmin_settings').update(router_config_last_updated=timezone.now())
            messages.success(request, f"Se eliminaron todas las categorías ({cat_count}), grupos y dispositivos ({dev_count}) correctamente.")
        else:
            messages.warning(request, "Eliminación cancelada|Confirmación inválida.")
        return redirect('/router/group_list/')

    raw_uuid = (request.GET.get('uuid') or request.POST.get('uuid') or '').strip()
    category_obj = get_object_or_404(DeviceCategory, uuid=raw_uuid) if raw_uuid else None

    if category_obj and action_param == 'delete':
        if (request.GET.get('confirmation') or '').strip().lower() in ('delete', 'borrar', 'confirm'):
            cat_name = category_obj.name
            all_devs = list(
                Router.objects.filter(routergroup__category=category_obj)
                .distinct()
                .select_related('backup_profile')
            )
            dev_count = len(all_devs)
            for dev in all_devs:
                _delete_router_cleanly(dev)
            category_obj.delete()
            fallback_cat = get_first_category()
            ActivityLog.objects.create(
                user=request.user,
                action="Categoría Eliminada",
                details=f"Categoría '{cat_name}' eliminada junto con {dev_count} dispositivo(s)",
            )
            WebadminSettings.objects.filter(name='webadmin_settings').update(router_config_last_updated=timezone.now())
            messages.success(request, f"Categoría '{cat_name}' y sus {dev_count} dispositivo(s) fueron eliminados correctamente.")
            if fallback_cat:
                return redirect(f'/router/group_list/?category={fallback_cat.uuid}')
            return redirect('/router/group_list/')
        return redirect('/router/group_list/')

    if request.method == 'POST':
        max_cats = getattr(settings, 'MAX_DEVICE_CATEGORIES', 3)
        if not category_obj and DeviceCategory.objects.count() >= max_cats:
            limit_msg = get_category_limit_message(request.POST.get('name', '').strip())
            if is_ajax:
                return JsonResponse({'status': 'limit_reached', 'message': limit_msg}, status=400)
            messages.error(request, f"Límite alcanzado|{limit_msg}")
            return redirect('/router/group_list/')

        form = DeviceCategoryForm(request.POST, instance=category_obj)
        if form.is_valid():
            is_edit = bool(category_obj and category_obj.pk)
            if not is_edit:
                form.instance.position = (DeviceCategory.objects.count() or 0) + 1
            saved_cat = form.save()
            ActivityLog.objects.create(
                user=request.user,
                action="Categoría Editada" if is_edit else "Categoría Creada",
                details=f"Categoría '{saved_cat.name}'",
            )
            target_url = f'/router/group_list/?category={saved_cat.uuid}'
            if is_ajax:
                return JsonResponse({
                    'status': 'success',
                    'uuid': str(saved_cat.uuid),
                    'name': saved_cat.name,
                    'redirect_url': target_url,
                })
            messages.success(request, f"Categoría '{saved_cat.name}' guardada correctamente.")
            return redirect(target_url)
        else:
            err_text = ' '.join(str(v[0]) for v in form.errors.values())
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': err_text}, status=400)
            messages.error(request, err_text)
            return redirect('/router/group_list/')

    return redirect('/router/group_list/')


@login_required()
def view_manage_router(request):
    if not _user_has_acl(request.user, 30):
        return render(request, 'access_denied.html', {'page_title': 'Acceso Denegado'})
    webadmin_settings, _ = WebadminSettings.objects.get_or_create(name='webadmin_settings')

    uuid = request.GET.get('uuid')
    if uuid:
        router = get_object_or_404(Router, uuid=uuid)
        cur_grp = router.routergroup_set.select_related('category').first()
        router_cat = cur_grp.category if (cur_grp and cur_grp.category) else _resolve_active_category(request)
        back_url = f'/router/group_list/?category={router_cat.uuid}' if router_cat else '/router/group_list/'
        if request.GET.get('action') == 'delete':
            if request.GET.get('confirmation') in ['delete', 'borrar', 'confirm']:
                ActivityLog.objects.create(
                    user=request.user,
                    action="Dispositivo Eliminado",
                    details=f"Dispositivo '{router.name}' ({router.address})",
                    router=None
                )
                _delete_router_cleanly(router)
                messages.success(request, 'Dispositivo eliminado correctamente')
                webadmin_settings.router_config_last_updated = timezone.now()
                webadmin_settings.save()
                return redirect(back_url)
            else:
                messages.warning(request, 'Dispositivo no eliminado|Confirmación inválida')
                return redirect(back_url)
        elif request.GET.get('action') == 'refresh_information':
            router_information, _ = RouterInformation.objects.get_or_create(router=router)
            router_information.next_retry = timezone.now()
            router_information.retry_count = 0
            router_information.success = False
            router_information.error = False
            router_information.error_message = ''
            router_information.save()
            success, error_msg = update_router_information(router_information)
            if success:
                messages.success(request, 'Información del dispositivo actualizada correctamente')
            else:
                messages.warning(request, f'Error al actualizar información del dispositivo: {error_msg}')
            return redirect('/router/details/?uuid=' + str(router.uuid))
    else:
        router = None

    preselect_group = None
    if not router:
        gid = request.GET.get('group_id')
        if gid and str(gid).isdigit():
            preselect_group = RouterGroup.objects.select_related('category').filter(pk=int(gid)).first()

    if preselect_group and preselect_group.category:
        active_category = preselect_group.category
    elif router:
        cur_grp = router.routergroup_set.select_related('category').first()
        active_category = cur_grp.category if (cur_grp and cur_grp.category) else _resolve_active_category(request)
    else:
        active_category = _resolve_active_category(request)

    if not active_category:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('ajax'):
            return HttpResponse('<div class="p-4 text-center"><h6 class="font-weight-bold mb-2">Primero crea una Categoría</h6><p class="small text-muted mb-3">No existen categorías creadas todavía. Crea primero una categoría para agregar grupos y dispositivos.</p><button type="button" class="btn btn-primary btn-sm" data-dismiss="modal">Entendido</button></div>')
        messages.warning(request, 'Primero debe crear una categoría antes de agregar dispositivos.')
        return redirect('/router/group_list/')

    form = RouterForm(
        request.POST or None,
        instance=router,
        category=active_category,
        preselect_group=preselect_group,
    )
    if form.is_valid():
        saved_router = form.save()
        selected_group = form.cleaned_data.get('router_group')

        action = "Dispositivo Editado" if uuid else "Dispositivo Creado"
        ActivityLog.objects.create(
            user=request.user,
            action=action,
            details=f"Dispositivo '{saved_router.name}' ({saved_router.address}) [{active_category.name} -> {selected_group.name if selected_group else ''}]",
            router=saved_router
        )

        for group in RouterGroup.objects.filter(routers=saved_router):
            group.routers.remove(saved_router)
        for client in RouterClient.objects.filter(routers=saved_router):
            client.routers.remove(saved_router)
        if selected_group:
            selected_group.routers.add(saved_router)
            target_cat = selected_group.category or active_category
        else:
            target_cat = active_category

        messages.success(request, 'Dispositivo guardado correctamente|Sincronizando información y calendario de respaldo.')
        RouterStatus.objects.get_or_create(router=saved_router)
        BackupSchedule.objects.filter(router=saved_router).delete()
        from backup_data.services import service_generate_backup_schedule
        service_generate_backup_schedule()
        if saved_router.router_type == 'monitoring':
            RouterInformation.objects.filter(router=saved_router).delete()
        else:
            ri, _ = RouterInformation.objects.get_or_create(router=saved_router)
            threading.Thread(target=update_router_information, args=(ri,), daemon=True).start()
        webadmin_settings.router_config_last_updated = timezone.now()
        webadmin_settings.save()
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('ajax'):
            return JsonResponse({'status': 'success', 'message': 'Dispositivo guardado correctamente'})
        return redirect(f'/router/group_list/?category={target_cat.uuid}')

    context = {
        'form': form,
        'page_title': 'Gestionar Dispositivo',
        'instance': router,
        'active_category': active_category,
        'preselect_group': preselect_group,
    }
    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('ajax'):
        return render(request, 'router_manager/router_form_modal.html', context=context, status=400 if form.errors else 200)
    return render(request, 'generic_form.html', context=context)


@login_required()
def view_router_group_list(request):
    categories = list(DeviceCategory.objects.order_by('position', 'id'))
    status_filter = request.GET.get('status')
    explicit_cat = (request.GET.get('category') or '').strip()
    max_cats = getattr(settings, 'MAX_DEVICE_CATEGORIES', 3)

    if not categories:
        context = {
            'categories': [],
            'active_category': None,
            'can_add_category': True,
            'max_device_categories': max_cats,
            'category_limit_email': getattr(settings, 'CATEGORY_LIMIT_CONTACT_EMAIL', 'soporte@tdox-config.com'),
            'router_group_list': [],
            'grouped_nodes': [],
            'total_nodes_count': 0,
            'total_devices_count': 0,
            'total_online_count': 0,
            'total_offline_count': 0,
            'last_status_change_timestamp': 0,
            'status_filter': status_filter,
            'page_title': 'Dispositivos',
        }
        return render(request, 'router_manager/router_group_list.html', context=context)

    active_category = _resolve_active_category(request)
    if active_category not in categories:
        active_category = categories[0]
    # Si viene un filtro desde Dashboard (?status=offline / online) sin categoría fija y la actual tiene 0 coincidencias, enfocar la que sí tenga
    if status_filter in ('online', 'offline') and not explicit_cat:
        want_online = (status_filter == 'online')
        if not Router.objects.filter(routergroup__category=active_category, routerstatus__status_online=want_online, monitoring=True).exists():
            for cand_cat in categories:
                if Router.objects.filter(routergroup__category=cand_cat, routerstatus__status_online=want_online, monitoring=True).exists():
                    active_category = cand_cat
                    break

    all_groups = list(
        RouterGroup.objects.filter(category=active_category)
        .prefetch_related('routers', 'routers__routerstatus', 'routers__routerinformation')
        .order_by('name')
    )
    routers_qs = (
        Router.objects.filter(routergroup__category=active_category)
        .distinct()
        .select_related('routerstatus', 'routerinformation', 'backup_profile')
        .prefetch_related('routergroup_set')
        .order_by('name')
    )
    status_filter = request.GET.get('status')
    if status_filter == 'online':
        routers_qs = routers_qs.filter(routerstatus__status_online=True, monitoring=True)
    elif status_filter == 'offline':
        routers_qs = routers_qs.filter(routerstatus__status_online=False, monitoring=True)
    q = (request.GET.get('q') or '').strip()
    if q:
        routers_qs = routers_qs.filter(
            Q(name__icontains=q) | Q(address__icontains=q) | Q(router_type__icontains=q)
        ).distinct()
    all_routers = list(routers_qs)

    latest_backups_map = {}
    for rb in RouterBackup.objects.filter(success=True).order_by('router_id', '-created').values('router_id', 'uuid'):
        if rb['router_id'] not in latest_backups_map:
            latest_backups_map[rb['router_id']] = str(rb['uuid'])

    total_online = 0
    for r in all_routers:
        r.latest_backup_uuid = latest_backups_map.get(r.id)
        if not r.monitoring or (getattr(r, 'routerstatus', None) and r.routerstatus.status_online):
            total_online += 1
    total_devices = len(all_routers)
    total_offline = total_devices - total_online

    grouped_nodes = []
    for grp in all_groups:
        grp_routers = [r for r in all_routers if grp in r.routergroup_set.all()]
        online_cnt = sum(
            1 for r in grp_routers
            if not r.monitoring or (getattr(r, 'routerstatus', None) and r.routerstatus.status_online)
        )
        offline_cnt = len(grp_routers) - online_cnt
        grouped_nodes.append({
            'group': grp,
            'name': grp.name,
            'uuid': str(grp.uuid),
            'default_group': grp.default_group,
            'internal_notes': grp.internal_notes or '',
            'routers': grp_routers,
            'total_count': len(grp_routers),
            'online_count': online_cnt,
            'offline_count': offline_cnt,
        })

    last_router_status_change = RouterStatus.objects.filter(last_status_change__isnull=False).order_by('-last_status_change').first()
    last_status_change_timestamp = last_router_status_change.last_status_change.isoformat() if last_router_status_change else 0
    max_cats = getattr(settings, 'MAX_DEVICE_CATEGORIES', 3)

    context = {
        'categories': categories,
        'active_category': active_category,
        'can_add_category': len(categories) < max_cats,
        'max_device_categories': max_cats,
        'category_limit_email': getattr(settings, 'CATEGORY_LIMIT_CONTACT_EMAIL', 'soporte@tdox-config.com'),
        'router_group_list': all_groups,
        'grouped_nodes': grouped_nodes,
        'total_nodes_count': len(all_groups),
        'total_devices_count': total_devices,
        'total_online_count': total_online,
        'total_offline_count': total_offline,
        'last_status_change_timestamp': last_status_change_timestamp,
        'status_filter': status_filter,
        'page_title': active_category.name,
    }
    return render(request, 'router_manager/router_group_list.html', context=context)


@login_required()
def view_manage_router_group(request):
    if not _user_has_acl(request.user, 30):
        return render(request, 'access_denied.html', {'page_title': 'Acceso Denegado'})

    raw_uuid = (request.GET.get('uuid') or '').strip()
    if raw_uuid and raw_uuid != 'ungrouped':
        router_group = get_object_or_404(RouterGroup, uuid=raw_uuid)
        active_category = router_group.category or _resolve_active_category(request)
        if request.GET.get('action') == 'delete':
            if request.GET.get('confirmation') in ('delete', 'borrar', 'confirm'):
                grp_name = router_group.name
                devices_in_group = list(router_group.routers.select_related('backup_profile').all())
                deleted_count = len(devices_in_group)
                for dev in devices_in_group:
                    _delete_router_cleanly(dev)
                router_group.delete()
                ActivityLog.objects.create(
                    user=request.user,
                    action="Grupo Eliminado",
                    details=f"Grupo '{grp_name}' ({active_category.name}) eliminado junto con {deleted_count} dispositivo(s)",
                )
                WebadminSettings.objects.filter(name='webadmin_settings').update(router_config_last_updated=timezone.now())
                messages.success(request, f"Grupo '{grp_name}' y sus {deleted_count} dispositivo(s) fueron eliminados correctamente.")
                return redirect(f'/router/group_list/?category={active_category.uuid}')
            else:
                messages.warning(request, 'Grupo no eliminado|Confirmación inválida')
                return redirect(f'/router/group_list/?category={active_category.uuid}')
    else:
        router_group = None
        active_category = _resolve_active_category(request)

    if not active_category:
        messages.warning(request, 'Primero debe crear una categoría antes de agregar grupos.')
        return redirect('/router/group_list/')

    next_url = request.POST.get('next') or request.GET.get('next') or ''
    form = RouterGroupForm(request.POST or None, instance=router_group, category=active_category, next_url=next_url)
    if form.is_valid():
        saved_group = form.save()
        action = "Grupo Editado" if raw_uuid else "Grupo Creado"
        ActivityLog.objects.create(
            user=request.user,
            action=action,
            details=f"Grupo '{saved_group.name}' en categoría '{active_category.name}'",
        )
        messages.success(request, f"Grupo '{saved_group.name}' guardado correctamente en {active_category.name}.")
        if next_url:
            sep = '&' if '?' in next_url else '?'
            return redirect(f"{next_url}{sep}created_group={saved_group.id}")
        return redirect(f'/router/group_list/?category={active_category.uuid}')

    context = {
        'form': form,
        'form_size': 'col-xl-7 col-lg-8 mx-auto',
        'page_title': f"Editar Grupo ({active_category.name}): {router_group.name}" if router_group else f"Nuevo Grupo en {active_category.name}",
        'delete_confirmation_message': "Al eliminar el grupo también se eliminarán todos sus dispositivos. Escriba 'borrar' para confirmar:",
        'instance': router_group,
    }
    return render(request, 'generic_form.html', context=context)


from django.views.decorators.http import require_POST

@login_required()
@require_POST
def view_ajax_quick_create_group(request):
    if not _user_has_acl(request.user, 30):
        return JsonResponse({'status': 'error', 'message': 'Acceso Denegado'}, status=403)

    active_category = _resolve_active_category(request)
    name = re.sub(r'\s+', ' ', request.POST.get('name', '').strip()).upper()
    if not name:
        return JsonResponse({'status': 'error', 'message': 'El nombre del grupo es requerido.'}, status=400)

    existing_grp = (
        RouterGroup.objects.filter(category=active_category, name__iexact=name).first()
        or find_matching_node(name, category=active_category)
    )
    if existing_grp:
        return JsonResponse({'status': 'error', 'message': f"Ya existe este grupo en '{active_category.name}' como '{existing_grp.name}'."}, status=400)

    group = RouterGroup.objects.create(category=active_category, name=name)

    ActivityLog.objects.create(
        user=request.user,
        action="Grupo Creado (Rápido)",
        details=f"Grupo '{group.name}' creado en '{active_category.name}'",
    )

    return JsonResponse({
        'status': 'success',
        'uuid': str(group.uuid),
        'id': group.id,
        'name': group.name
    })


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
    if not _user_has_acl(request.user, 20):
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
@require_POST
def view_delete_multiple_items(request):
    if not _user_has_acl(request.user, 30):
        return JsonResponse({'status': 'error', 'message': 'Permiso denegado.'}, status=403)

    group_uuids = request.POST.getlist('groups[]')
    router_uuids = request.POST.getlist('routers[]')

    if not group_uuids and not router_uuids:
        return JsonResponse({'status': 'error', 'message': 'No se seleccionaron elementos.'}, status=400)

    deleted_groups = 0
    deleted_routers = 0

    for g_uuid in group_uuids:
        grp = RouterGroup.objects.filter(uuid=g_uuid).first()
        if grp:
            for dev in list(grp.routers.select_related('backup_profile').all()):
                _delete_router_cleanly(dev)
                deleted_routers += 1
            grp.delete()
            deleted_groups += 1

    for r_uuid in router_uuids:
        dev = Router.objects.filter(uuid=r_uuid).select_related('backup_profile').first()
        if dev:
            _delete_router_cleanly(dev)
            deleted_routers += 1

    ActivityLog.objects.create(
        user=request.user,
        action="Eliminación Masiva",
        details=f"Se eliminaron {deleted_groups} grupo(s) y {deleted_routers} dispositivo(s) seleccionados",
    )
    WebadminSettings.objects.filter(name='webadmin_settings').update(router_config_last_updated=timezone.now())

    return JsonResponse({
        'status': 'success',
        'deleted_groups': deleted_groups,
        'deleted_routers': deleted_routers,
        'message': f"Eliminados correctamente: {deleted_groups} grupo(s) y {deleted_routers} dispositivo(s).",
    })


@login_required
def view_create_instant_backup_multiple_routers(request):
    if request.method == 'POST':
        if not _user_has_acl(request.user, 20):
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
    if not _user_has_acl(request.user, 20):
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


@login_required()
def view_ajax_test_connection(request):
    """
    AJAX endpoint to test router connectivity before saving the form.
    """
    from routerlib.functions import test_authentication
    
    address = request.POST.get('address')
    username = request.POST.get('username')
    password = request.POST.get('password')
    enable_password = request.POST.get('enable_password')
    port = request.POST.get('port')
    router_type = request.POST.get('router_type')
    connection_protocol = request.POST.get('connection_protocol', 'ssh')
    
    if not all([address, username, port, router_type]):
        return JsonResponse({'status': 'error', 'message': 'Faltan datos requeridos (IP, Usuario, Puerto, Tipo)'})

    uuid = request.POST.get('uuid')
    if uuid:
        router = get_object_or_404(Router, uuid=uuid)
        if not password:
            password = router.password
        if not enable_password and router.enable_password:
            enable_password = router.enable_password

    success, message = test_authentication(
        router_type, address, port, username, password,
        connection_protocol=connection_protocol,
        enable_password=enable_password
    )
    
    if success:
        return JsonResponse({'status': 'success', 'message': 'Conectado correctamente al equipo.'})
    else:
        raw_msg = str(message or '').lower()
        if 'authentication' in raw_msg or 'password' in raw_msg or 'login incorrect' in raw_msg or 'auth' in raw_msg:
            friendly = 'Usuario o contraseña incorrectos. Verifique las credenciales del equipo.'
        elif 'timed out' in raw_msg or 'timeout' in raw_msg:
            friendly = f'Tiempo de espera agotado hacia {address}:{port}. Verifique que el equipo esté encendido y el puerto abierto.'
        elif 'refused' in raw_msg or '111' in raw_msg:
            friendly = f'Conexión rechazada en {address}:{port}. Verifique que el servicio {connection_protocol.upper()} esté habilitado.'
        elif 'getaddrinfo' in raw_msg or 'name or service not known' in raw_msg or 'unreachable' in raw_msg:
            friendly = f'No se pudo alcanzar la dirección {address}. Verifique la IP o la ruta de red.'
        else:
            friendly = f'No se pudo conectar: {message}'
        return JsonResponse({'status': 'error', 'message': friendly})


@login_required()
def view_ajax_router_telemetry(request):
    """
    Endpoint AJAX para obtener telemetría en tiempo real (CPU, RAM, Uptime)
    utilizando la API ultrarrápida de MikroTik cuando esté disponible.
    """
    router_uuid = request.GET.get('uuid') or request.POST.get('uuid')
    if not router_uuid:
        return JsonResponse({'status': 'error', 'message': 'UUID no proporcionado'}, status=400)
    
    router = get_object_or_404(Router, uuid=router_uuid)
    
    if router.router_type in ('mikrotik', 'mikrotik-branded'):
        from routerlib.mikrotik_api import fetch_mikrotik_telemetry
        mk_port = int(router.port) if (getattr(router, 'connection_protocol', 'ssh') == 'api' and router.port) else 8728
        telemetry = fetch_mikrotik_telemetry(router.address, mk_port, router.username, router.password, timeout=3.0)
        if telemetry.get('success'):
            return JsonResponse({'status': 'success', 'telemetry': telemetry})
        else:
            return JsonResponse({
                'status': 'partial',
                'message': f'API MikroTik no disponible ({telemetry.get("error")}). El monitoreo continúa por SSH.',
                'telemetry': None
            })
    
    return JsonResponse({'status': 'unsupported', 'message': 'Telemetría por API solo soportada en MikroTik'})



@login_required()
def view_router_client_list(request):
    cats = list(DeviceCategory.objects.order_by('position', 'id'))
    target = next((c for c in cats if c.name.lower().startswith('client')), cats[1] if len(cats) > 1 else (cats[0] if cats else None))
    return redirect(f'/router/group_list/?category={target.uuid}' if target else '/router/group_list/')


@login_required()
def view_manage_router_client(request):
    cats = list(DeviceCategory.objects.order_by('position', 'id'))
    target = next((c for c in cats if c.name.lower().startswith('client')), cats[1] if len(cats) > 1 else (cats[0] if cats else None))
    if not target:
        return redirect('/router/group_list/')
    next_param = request.GET.get('next')
    url = f'/router/manage_group/?category={target.uuid}'
    if next_param:
        from urllib.parse import quote
        url += f'&next={quote(next_param)}'
    return redirect(url)
