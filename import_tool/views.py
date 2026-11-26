from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required

from backup.models import BackupProfile
from router_manager.models import Router, SUPPORTED_ROUTER_TYPES, RouterGroup, RouterStatus
from user_manager.models import UserAcl
from .models import CsvData, ImportTask
from .forms import CsvDataForm
from .excel_utils import generate_excel_bytes
from django.contrib import messages
import ipaddress
import socket

SUPPORTED_ROUTER_TYPES = [rt[0] for rt in SUPPORTED_ROUTER_TYPES]


@login_required()
def run_import_task(request):
    if not UserAcl.objects.filter(user=request.user).filter(user_level__gte=50).exists():
        return render(request, 'access_denied.html', {'page_title': 'Acceso Denegado'})
    import_task = get_object_or_404(ImportTask, uuid=request.GET.get('uuid'))
    if import_task.import_success:
        return JsonResponse({'status': 'success', 'message': 'Completado'})

    backup_profile = None
    router_group = None

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

    if import_task.router_group_name:
        router_group, _ = RouterGroup.objects.get_or_create(name=import_task.router_group_name)

    protocol = (getattr(import_task, 'connection_protocol', 'ssh') or 'ssh').lower()

    existing_router = Router.objects.filter(address=address).first()
    action_label = 'Nuevo equipo creado'
    if existing_router:
        if name and name != existing_router.name and not Router.objects.filter(name=name).exclude(pk=existing_router.pk).exists():
            existing_router.name = name
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
        action_label = 'Equipo actualizado'
    else:
        unique_name = name
        if Router.objects.filter(name=unique_name).exists():
            unique_name = f"{name} ({address})"
        target_router = Router.objects.create(
            name=unique_name,
            username=import_task.username or 'admin',
            password=import_task.password or '',
            address=address,
            port=import_task.port,
            router_type=import_task.router_type,
            connection_protocol=protocol,
            backup_profile=backup_profile,
            monitoring=import_task.monitoring
        )

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
    """Redirige directamente a la sección de Importar desde Excel para evitar pasos redundantes."""
    return redirect('/router/import_tool/csv/')


@login_required()
def view_import_details(request):
    if not UserAcl.objects.filter(user=request.user).filter(user_level__gte=50).exists():
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

    # Anotar en cada tarea de preview si la IP ya existe (se actualizará) o si es nueva (se creará)
    existing_ips = set(Router.objects.values_list('address', flat=True))
    for t in import_task_list:
        t.will_update = (t.address.lower().strip() in existing_ips)

    data = {
        'csv_data': csv_data,
        'action': action,
        'import_task_list': import_task_list,
        'total_tasks': len(import_task_list),
        'completed_tasks': sum(1 for t in import_task_list if t.import_success),
        'page_title': 'Vista Previa y Proceso de Importación',
    }
    return render(request, 'import_tool/import_details.html', context=data)


@login_required()
def view_import_csv_file(request):
    if not UserAcl.objects.filter(user=request.user).filter(user_level__gte=50).exists():
        return render(request, 'access_denied.html', {'page_title': 'Acceso Denegado'})

    form = CsvDataForm(request.POST or None, request.FILES or None)
    if form.is_valid():
        csv_data_instance = form.save(commit=False)
        csv_data_instance.import_data = form.cleaned_data['import_data']
        csv_data_instance.raw_csv_data = form.cleaned_data.get('raw_csv_data', '')
        csv_data_instance.save()

        tasks_created = 0
        for task in csv_data_instance.import_data:
            _, created = ImportTask.objects.get_or_create(
                csv_data=csv_data_instance,
                import_id=task['import_id'],
                defaults={
                    'name': task.get('name'),
                    'username': task.get('username') or 'admin',
                    'password': task.get('password') or '',
                    'address': task.get('address'),
                    'port': int(task.get('port', 22)),
                    'router_type': task.get('router_type') or 'mikrotik',
                    'connection_protocol': (task.get('connection_protocol') or 'ssh').lower(),
                    'backup_profile_name': task.get('backup_profile') or 'default',
                    'router_group_name': task.get('router_group') or 'General',
                    'monitoring': True if str(task.get('monitoring', 'true')).lower() == 'true' else False,
                }
            )
            if created:
                tasks_created += 1

        messages.info(request, f'Archivo Excel leído correctamente: {tasks_created} equipos listos en la vista previa para importar.')
        return redirect(f'/router/import_tool/details/?uuid={csv_data_instance.uuid}')

    data = {
        'form': form,
        'page_title': 'Herramientas',
    }
    return render(request, 'import_tool/import_csv_form.html', context=data)


@login_required()
def view_download_csv_template(request):
    """Descarga una plantilla nativa de Microsoft Excel (.xlsx) con las 8 columnas solicitadas."""
    headers = ['Nombre', 'IP', 'Usuario', 'Password', 'Marca', 'Protocolo', 'Puerto', 'Nodo']
    rows = [
        ['Router Principal', '192.168.1.1', 'admin', 'clave123', 'mikrotik', 'SSH', '22', 'Nodo Centro'],
        ['Switch Acceso 1', '10.0.0.2', 'admin', 'clave123', 'cisco', 'SSH', '22', 'Nodo Centro'],
        ['Firewall Borde', '172.16.0.1', 'admin', 'clave123', 'huawei', 'Telnet', '23', 'Nodo Norte'],
        ['Router API', '192.168.10.5', 'admin', 'clave123', 'mikrotik', 'API', '80', 'General'],
    ]
    xlsx_bytes = generate_excel_bytes(headers, rows, sheet_name="Plantilla Equipos")
    response = HttpResponse(
        xlsx_bytes,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename="tdox_config_plantilla_equipos.xlsx"'
    return response


@login_required()
def view_export_routers_csv(request):
    """Exporta todos los equipos actuales en formato nativo Microsoft Excel (.xlsx)."""
    if not UserAcl.objects.filter(user=request.user).filter(user_level__gte=30).exists():
        return render(request, 'access_denied.html', {'page_title': 'Acceso Denegado'})

    headers = ['Nombre', 'IP', 'Usuario', 'Password', 'Marca', 'Protocolo', 'Puerto', 'Nodo']
    rows = []
    for r in Router.objects.all().prefetch_related('routergroup_set').order_by('name'):
        grp = r.routergroup_set.first()
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
            grp.name if grp else 'General',
        ])

    xlsx_bytes = generate_excel_bytes(headers, rows, sheet_name="Inventario Equipos")
    response = HttpResponse(
        xlsx_bytes,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename="tdox_config_inventario_equipos.xlsx"'
    return response
