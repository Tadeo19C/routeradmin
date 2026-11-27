import ipaddress
import socket
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404

from backup.models import BackupProfile
from router_manager.models import DeviceCategory, Router, SUPPORTED_ROUTER_TYPES, RouterGroup, RouterStatus
from router_manager.normalization import (
    get_first_category,
    resolve_existing_category,
    resolve_or_create_node,
    canonical_key,
)
from user_manager.models import UserAcl
from .models import CsvData, ImportTask
from .forms import CsvDataForm
from .excel_utils import generate_excel_bytes

SUPPORTED_ROUTER_TYPES = [rt[0] for rt in SUPPORTED_ROUTER_TYPES]


def _can_use_import_tools(user):
    if not user or not user.is_authenticated:
        return False
    return bool(user.is_superuser or user.is_staff or UserAcl.objects.filter(user=user, user_level__gte=30).exists())


@login_required()
def run_import_task(request):
    if not _can_use_import_tools(request.user):
        return render(request, 'access_denied.html', {'page_title': 'Acceso Denegado'})
    import_task = get_object_or_404(ImportTask, uuid=request.GET.get('uuid'))
    if import_task.import_success:
        return JsonResponse({'status': 'success', 'message': 'Completado'})
    if import_task.import_error or import_task.action_type == 'error':
        return JsonResponse({'status': 'error', 'error_message': import_task.import_error_message or 'Fila con errores de validación'})

    # Bloquear ejecución si el documento completo contiene errores sin corregir
    if ImportTask.objects.filter(csv_data=import_task.csv_data, action_type='error').exists():
        return JsonResponse({
            'status': 'error',
            'error_message': 'El documento contiene filas con errores en rojo. Corrija el Excel antes de importar.'
        })

    name = (import_task.name or '').strip()
    address = (import_task.address or '').lower().strip()

    try:
        socket.gethostbyname(address)
    except socket.gaierror:
        try:
            ipaddress.ip_address(address)
        except ValueError:
            error_message = 'La dirección IP o Host no es válida.'
            import_task.import_error = True
            import_task.import_error_message = error_message
            import_task.save()
            return JsonResponse({'status': 'error', 'error_message': error_message})

    if not 1 <= import_task.port <= 65535:
        error_message = 'Número de puerto inválido.'
        import_task.import_error = True
        import_task.import_error_message = error_message
        import_task.save()
        return JsonResponse({'status': 'error', 'error_message': error_message})

    if import_task.backup_profile_name:
        backup_profile, _ = BackupProfile.objects.get_or_create(name=import_task.backup_profile_name)
    else:
        backup_profile, _ = BackupProfile.objects.get_or_create(name='default')

    try:
        category_obj = resolve_existing_category(import_task.category_name)
    except ValidationError as ve:
        err_msg = ve.messages[0] if getattr(ve, 'messages', None) else str(ve)
        import_task.import_error = True
        import_task.import_error_message = err_msg
        import_task.save()
        return JsonResponse({'status': 'error', 'error_message': err_msg})

    router_group = resolve_or_create_node(import_task.router_group_name, category=category_obj)
    import_task.category_name = category_obj.name
    import_task.router_group_name = router_group.name

    protocol = (getattr(import_task, 'connection_protocol', 'ssh') or 'ssh').lower()

    existing_router = import_task.router
    if not existing_router and import_task.action_type == 'update':
        name_ck = canonical_key(name)
        for r_cand in Router.objects.only('id', 'name'):
            if canonical_key(r_cand.name) == name_ck:
                existing_router = Router.objects.filter(pk=r_cand.id).first()
                break

    if existing_router:
        ip_clash = Router.objects.filter(address__iexact=address).exclude(pk=existing_router.pk).first()
        if ip_clash:
            err_msg = f"La IP '{address}' ya está en uso por '{ip_clash.name}'."
            import_task.import_error = True
            import_task.import_error_message = err_msg
            import_task.save()
            return JsonResponse({'status': 'error', 'error_message': err_msg})

        if name and name != existing_router.name:
            name_ck = canonical_key(name)
            other_collision = any(
                canonical_key(n) == name_ck
                for n in Router.objects.exclude(pk=existing_router.pk).values_list('name', flat=True)
            )
            if not other_collision:
                existing_router.name = name

        existing_router.address = address
        existing_router.username = import_task.username or existing_router.username
        if import_task.password:
            existing_router.password = import_task.password
        existing_router.port = import_task.port
        existing_router.router_type = import_task.router_type
        existing_router.connection_protocol = protocol
        existing_router.monitoring = import_task.monitoring
        if not existing_router.backup_profile:
            existing_router.backup_profile = backup_profile
        existing_router.save()
        target_router = existing_router

        changed_fields = [c.get('field') for c in (import_task.changes_json or []) if isinstance(c, dict) and c.get('field')]
        action_label = f"Actualizado ({', '.join(changed_fields)})" if changed_fields else "Dispositivo actualizado"
    else:
        # Validar que ni IP ni Nombre hayan colisionado antes de crear
        ip_clash = Router.objects.filter(address__iexact=address).first()
        if ip_clash:
            err_msg = f"IP duplicada: '{address}' ya pertenece a '{ip_clash.name}'."
            import_task.import_error = True
            import_task.import_error_message = err_msg
            import_task.save()
            return JsonResponse({'status': 'error', 'error_message': err_msg})

        name_canon = canonical_key(name)
        name_clash = next((n for n in Router.objects.values_list('name', flat=True) if canonical_key(n) == name_canon), None)
        if name_clash:
            err_msg = f"Nombre duplicado: '{name}' ya existe como '{name_clash}'."
            import_task.import_error = True
            import_task.import_error_message = err_msg
            import_task.save()
            return JsonResponse({'status': 'error', 'error_message': err_msg})

        target_router = Router.objects.create(
            name=name,
            username=import_task.username or 'admin',
            password=import_task.password or '',
            address=address,
            port=import_task.port,
            router_type=import_task.router_type,
            connection_protocol=protocol,
            backup_profile=backup_profile,
            monitoring=import_task.monitoring,
        )
        action_label = 'Nuevo dispositivo creado'

    RouterStatus.objects.get_or_create(router=target_router)

    if router_group:
        for grp in RouterGroup.objects.filter(routers=target_router):
            grp.routers.remove(target_router)
        router_group.routers.add(target_router)

    import_task.router = target_router
    import_task.import_success = True
    import_task.import_error = False
    import_task.import_error_message = action_label
    import_task.backup_profile = backup_profile
    import_task.router_group = router_group
    import_task.save()

    try:
        from backup_data.services import service_generate_backup_schedule
        service_generate_backup_schedule()
    except Exception:
        pass

    return JsonResponse({
        'status': 'success',
        'message': action_label,
        'router_uuid': str(target_router.uuid),
    })


@login_required()
def view_import_tool_list(request):
    return redirect('/router/import_tool/csv/')


@login_required()
def view_import_details(request):
    if not _can_use_import_tools(request.user):
        return render(request, 'access_denied.html', {'page_title': 'Acceso Denegado'})
    csv_data = get_object_or_404(CsvData, uuid=request.GET.get('uuid'))
    import_task_list = list(ImportTask.objects.filter(csv_data=csv_data).order_by('import_id'))
    action = request.GET.get('action')

    if action == 'delete_errors':
        ImportTask.objects.filter(csv_data=csv_data, import_error=True).delete()
        return redirect(f'/router/import_tool/details/?uuid={csv_data.uuid}')
    elif action == 'delete':
        ImportTask.objects.filter(csv_data=csv_data).delete()
        csv_data.delete()
        return redirect('/router/import_tool/csv/')

    error_count = sum(1 for t in import_task_list if t.action_type == 'error' or t.import_error)
    new_count = sum(1 for t in import_task_list if t.action_type == 'new' and not t.import_error)
    update_count = sum(1 for t in import_task_list if t.action_type == 'update' and not t.import_error)
    valid_tasks_count = new_count + update_count

    data = {
        'csv_data': csv_data,
        'action': action,
        'import_task_list': import_task_list,
        'total_tasks': valid_tasks_count,
        'error_count': error_count,
        'has_blocking_errors': error_count > 0,
        'new_count': new_count,
        'update_count': update_count,
        'unchanged_count': csv_data.unchanged_count or 0,
        'completed_tasks': sum(1 for t in import_task_list if t.import_success),
        'page_title': 'Vista Previa de Importación',
    }
    return render(request, 'import_tool/import_details.html', context=data)


@login_required()
def view_import_csv_file(request):
    if not _can_use_import_tools(request.user):
        return render(request, 'access_denied.html', {'page_title': 'Acceso Denegado'})

    categories = list(DeviceCategory.objects.order_by('position', 'id'))
    total_inventory = Router.objects.count()

    form = CsvDataForm(request.POST or None, request.FILES or None)
    if form.is_valid():
        import_data = form.cleaned_data['import_data']
        unchanged_count = form.cleaned_data.get('unchanged_count', 0)

        csv_data_instance = form.save(commit=False)
        csv_data_instance.import_data = import_data
        csv_data_instance.unchanged_count = unchanged_count
        csv_data_instance.raw_csv_data = form.cleaned_data.get('raw_csv_data', '')
        csv_data_instance.save()

        default_cat_name = categories[0].name if categories else ''
        for task in import_data:
            is_err = (task.get('action_type') == 'error')
            ImportTask.objects.update_or_create(
                csv_data=csv_data_instance,
                import_id=task['import_id'],
                defaults={
                    'router_id': task.get('target_router_id'),
                    'name': (task.get('name') or '')[:100],
                    'username': (task.get('username') or 'admin')[:100],
                    'password': (task.get('password') or '')[:100],
                    'address': (task.get('address') or '')[:100],
                    'port': int(task.get('port', 22)),
                    'router_type': task.get('router_type') or 'mikrotik',
                    'connection_protocol': (task.get('connection_protocol') or 'ssh').lower()[:10],
                    'backup_profile_name': (task.get('backup_profile') or 'default')[:100],
                    'router_group_name': (task.get('router_group') or 'GENERAL')[:100],
                    'category_name': (task.get('category_name') or default_cat_name)[:60],
                    'action_type': task.get('action_type') or 'new',
                    'changes_json': task.get('changes') or [],
                    'import_error': is_err,
                    'import_error_message': task.get('error_message') or '',
                    'monitoring': True if str(task.get('monitoring', 'true')).lower() == 'true' else False,
                }
            )

        return redirect(f'/router/import_tool/details/?uuid={csv_data_instance.uuid}')

    data = {
        'form': form,
        'categories': categories,
        'total_inventory': total_inventory,
        'page_title': 'Herramientas',
    }
    return render(request, 'import_tool/import_csv_form.html', context=data)


@login_required()
def view_download_csv_template(request):
    cats = list(DeviceCategory.objects.order_by('position', 'id'))
    cat_1 = cats[0].name if cats else 'Nodos'
    cat_2 = cats[1].name if len(cats) > 1 else cat_1

    headers = ['Nombre', 'IP', 'Usuario', 'Password', 'Marca', 'Protocolo', 'Puerto', 'Grupo', 'Categoría']
    rows = [
        ['Router Principal', '192.168.1.1', 'admin', 'clave123', 'mikrotik', 'SSH', '22', 'MANAGUA', cat_1],
        ['Switch Acceso 1', '10.0.0.2', 'admin', 'clave123', 'cisco', 'SSH', '2222', 'MANAGUA', cat_1],
        ['Firewall Borde', '172.16.0.1', 'admin', 'clave123', 'huawei', 'Telnet', '23', 'CRUCERO', cat_1],
        ['FortiGate Enlace', '172.16.0.10', 'admin', 'clave123', 'fortinet', 'SSH', '22', 'POLICÍA NACIONAL', cat_2],
        ['Router API Custom', '192.168.10.5', 'admin', 'clave123', 'mikrotik', 'API', '8728', 'BANCO CENTRAL', cat_2],
    ]
    xlsx_bytes = generate_excel_bytes(headers, rows, sheet_name="Plantilla Dispositivos")
    response = HttpResponse(
        xlsx_bytes,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename="tdox_config_plantilla_dispositivos.xlsx"'
    return response


@login_required()
def view_export_routers_csv(request):
    if not _can_use_import_tools(request.user):
        return render(request, 'access_denied.html', {'page_title': 'Acceso Denegado'})

    first_cat = get_first_category()
    fallback_cat_name = first_cat.name if first_cat else ''
    headers = ['Nombre', 'IP', 'Usuario', 'Password', 'Marca', 'Protocolo', 'Puerto', 'Grupo', 'Categoría']
    rows = []
    for r in Router.objects.all().prefetch_related('routergroup_set__category').order_by('name'):
        grp = r.routergroup_set.first()
        cat_name = grp.category.name if (grp and grp.category) else fallback_cat_name
        grp_name = grp.name if grp else 'GENERAL'

        proto = (getattr(r, 'connection_protocol', 'ssh') or 'ssh').upper()
        if proto == 'TELNET':
            proto_display = 'Telnet'
        elif proto == 'API':
            proto_display = 'API'
        else:
            proto_display = 'SSH'

        rows.append([
            r.name,
            r.address,
            r.username or 'admin',
            r.decrypted_password or '',
            r.router_type or 'mikrotik',
            proto_display,
            str(r.port or 22),
            grp_name,
            cat_name,
        ])

    xlsx_bytes = generate_excel_bytes(headers, rows, sheet_name="Inventario Dispositivos")
    response = HttpResponse(
        xlsx_bytes,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename="tdox_config_inventario_dispositivos.xlsx"'
    return response
