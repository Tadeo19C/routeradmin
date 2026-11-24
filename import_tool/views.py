from django.http import JsonResponse, HttpResponse
import csv
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required

from backup.models import BackupProfile
from router_manager.models import Router, SUPPORTED_ROUTER_TYPES, RouterGroup, RouterStatus
from routerlib.functions import test_authentication
from user_manager.models import UserAcl
from .models import CsvData, ImportTask
from .forms import CsvDataForm
from django.contrib import messages
import ipaddress
import socket

SUPPORTED_ROUTER_TYPES = [rt[0] for rt in SUPPORTED_ROUTER_TYPES]


@login_required()
def run_import_task(request):
    if not UserAcl.objects.filter(user=request.user).filter(user_level__gte=50).exists():
        return render(request, 'access_denied.html', {'page_title': 'Acceso Denegado'})
    import_task = get_object_or_404(ImportTask, uuid=request.GET.get('uuid'), import_success=False, import_error=False)
    ssh_key = None
    backup_profile = None
    router_group = None

    name = import_task.name.strip()

    if Router.objects.filter(name=name).exists():
        error_message = f'El equipo con el nombre "{name}" ya existe.'
        import_task.import_error = True
        import_task.import_error_message = error_message
        import_task.save()
        return JsonResponse({'status': 'error', 'error_message': error_message})

    address = import_task.address.lower().strip()
    
    if Router.objects.filter(address=address).exists():
        error_message = f'La dirección IP "{address}" ya está registrada en otro equipo.'
        import_task.import_error = True
        import_task.import_error_message = error_message
        import_task.save()
        return JsonResponse({'status': 'error', 'error_message': error_message})
    try:
        socket.gethostbyname(address)
    except socket.gaierror:
        try:
            ipaddress.ip_address(address)
        except ValueError:
            error_message = 'The address field must be a valid hostname or IP address.'
            import_task.import_error = True
            import_task.import_error_message = error_message
            import_task.save()
            return JsonResponse({'status': 'error', 'error_message': error_message})

    if not 1 <= import_task.port <= 65535:
        error_message = 'Invalid port number'
        import_task.import_error = True
        import_task.import_error_message = error_message
        import_task.save()
        return JsonResponse({'status': 'error', 'error_message': error_message})

    if import_task.router_type not in SUPPORTED_ROUTER_TYPES:
        error_message = f'Invalid router_type "{import_task.router_type}"'
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

    if not import_task.password and not ssh_key:
        error_message = 'You must provide a password or an SSH Key'
        import_task.import_error = True
        import_task.import_error_message = error_message
        import_task.save()
        return JsonResponse({'status': 'error', 'error_message': error_message})

    protocol = getattr(import_task, 'connection_protocol', 'ssh') or 'ssh'
    test_authentication_success, test_authentication_message = test_authentication(
        import_task.router_type, address, import_task.port, import_task.username, import_task.password, ssh_key,
        connection_protocol=protocol
    )
    if not test_authentication_success:
        if test_authentication_message:
            error_message = 'Could not authenticate: ' + test_authentication_message
        else:
            error_message = 'Could not authenticate to the router. Please check the credentials and try again.'
        import_task.import_error = True
        import_task.import_error_message = error_message
        import_task.save()
        return JsonResponse({'status': 'error', 'error_message': error_message})

    new_router = Router.objects.create(
        name=import_task.name, username=import_task.username, password=import_task.password,
        address=address, port=import_task.port, router_type=import_task.router_type,
        connection_protocol=protocol, backup_profile=backup_profile,
        monitoring=import_task.monitoring
    )
    router_status, router_status_created = RouterStatus.objects.get_or_create(router=new_router)

    if router_group:
        router_group.routers.add(new_router)
        router_group.save()

    import_task.router = new_router
    import_task.import_success = True
    import_task.backup_profile = backup_profile
    import_task.router_group = router_group
    import_task.save()

    return JsonResponse({'status': 'success', 'message': 'Task completed successfully.'})


@login_required()
def view_import_tool_list(request):
    if not UserAcl.objects.filter(user=request.user).filter(user_level__gte=50).exists():
        return render(request, 'access_denied.html', {'page_title': 'Acceso Denegado'})
    import_list = []
    for csv_data in CsvData.objects.all().order_by('-created'):
        import_summary = {
            'csv_data': csv_data,
            'task_count': csv_data.importtask_set.filter(csv_data=csv_data).count(),
            'success_count': csv_data.importtask_set.filter(csv_data=csv_data, import_success=True).count(),
            'error_count': csv_data.importtask_set.filter(csv_data=csv_data, import_error=True).count(),
        }
        if import_summary['task_count'] != import_summary['success_count'] + import_summary['error_count']:
            import_summary['status'] = 'In Progress'
        elif import_summary['error_count'] > 0:
            import_summary['status'] = 'Completed with Errors'
        else:
            if import_summary['task_count'] == 0:
                import_summary['status'] = 'Not started'
            else:
                import_summary['status'] = 'Completed'
        import_list.append(import_summary)
    data = {
        'import_list': import_list,
        'page_title': 'Lista de Importaciones CSV',
    }
    return render(request, 'import_tool/import_tool_list.html', context=data)


@login_required()
def view_import_details(request):
    if not UserAcl.objects.filter(user=request.user).filter(user_level__gte=50).exists():
        return render(request, 'access_denied.html', {'page_title': 'Acceso Denegado'})
    csv_data = get_object_or_404(CsvData, uuid=request.GET.get('uuid'))
    import_task_list = ImportTask.objects.filter(csv_data=csv_data).order_by('import_id')
    action = None
    if request.GET.get('view') == 'raw':
        import_view = 'raw'
    elif request.GET.get('view') == 'processed':
        import_view = 'processed'
    else:
        import_view = 'tasks'

    if request.GET.get('action') == 'create_tasks':
        tasks_created = 0
        for task in csv_data.import_data:
            import_task, import_task_created = ImportTask.objects.get_or_create(
                csv_data=csv_data, import_id=task['import_id'], defaults={
                    'name': task['name'],
                    'username': task['username'],
                    'password': task['password'],
                    'address': task['address'],
                    'port': task['port'],
                    'router_type': task['router_type'],
                    'backup_profile_name': task['backup_profile'],
                    'router_group_name': task['router_group'],
                    'ssh_key_name': task['ssh_key'],
                    'monitoring': True if task['monitoring'] == 'true' else False,
                }
            )
            if import_task_created:
                tasks_created += 1
        if tasks_created > 0:
            messages.success(request, f'Tasks created: {tasks_created}')
        else:
            messages.warning(request, 'No new tasks created.')
        return redirect(f'/router/import_tool/details/?uuid={csv_data.uuid}')

    elif request.GET.get('action') == 'start_import':
        action = 'start_import'
        import_view = 'tasks'
        pass

    elif request.GET.get('action') == 'delete_errors':
        tasks_deleted = 0
        for task in import_task_list.filter(import_error=True):
            task.delete()
            tasks_deleted += 1
        if tasks_deleted > 0:
            messages.success(request, f'Error tasks deleted: {tasks_deleted}')
        else:
            messages.warning(request, 'No error tasks deleted.')
        return redirect(f'/router/import_tool/details/?uuid={csv_data.uuid}')

    elif request.GET.get('action') == 'delete':
        import_task_list.delete()
        csv_data.delete()
        messages.success(request, 'CSV data and all tasks deleted.')
        return redirect('/router/import_tool')

    data = {
        'csv_data': csv_data,
        'action': action,
        'import_task_list': import_task_list,
        'import_view': import_view,
        'page_title': f'Detalles de Importación - {csv_data.id}',
    }
    return render(request, 'import_tool/import_details.html', context=data)


@login_required()
def view_import_csv_file(request):
    if not UserAcl.objects.filter(user=request.user).filter(user_level__gte=50).exists():
        return render(request, 'access_denied.html', {'page_title': 'Acceso Denegado'})

    form_description_content = '''
    <strong><i class="fas fa-info-circle text-primary mr-1"></i> Guía de Carga Masiva en Excel (.CSV)</strong>
    <p class="mt-1">Puedes descargar la <b>Plantilla Excel</b>, llenarla en Microsoft Excel o LibreOffice con todos tus nodos y equipos, guardarla como <code>.csv</code> y subirla directamente aquí.</p>
    <p class="mb-1"><b>Columnas soportadas:</b></p>
    <ul class="pl-3 mb-2">
        <li><code>name</code>: Nombre del equipo (ej. <code>rt crucero</code>)</li>
        <li><code>username</code> / <code>password</code>: Credenciales de acceso</li>
        <li><code>address</code> / <code>port</code>: IP y puerto (<code>22</code> SSH o <code>23</code> Telnet)</li>
        <li><code>router_type</code>: <code>mikrotik</code>, <code>cisco-ios</code>, <code>huawei</code>, <code>zte</code>, <code>ubiquiti-airos</code>, <code>openwrt</code></li>
        <li><code>connection_protocol</code>: <code>ssh</code> o <code>telnet</code></li>
        <li><code>router_group</code>: Nombre del Nodo (si el Nodo no existe, <b>el sistema lo crea automáticamente</b>)</li>
        <li><code>backup_profile</code>: Perfil de respaldo (ej. <code>default</code>)</li>
        <li><code>monitoring</code>: <code>true</code> o <code>false</code></li>
    </ul>
    <strong>Ejemplo de filas:</strong>
    <pre>"name","username","password","address","port","router_type","connection_protocol","backup_profile","router_group","monitoring"
"rt crucero","admin","clave123","192.168.130.5","22","mikrotik","ssh","default","crucero","true"
"sw crucero","admin","clave123","172.20.250.91","22","cisco-ios","ssh","default","crucero","true"
"fw crucero","admin","clave123","172.20.250.115","23","huawei","telnet","default","crucero","true"</pre>
    '''

    form = CsvDataForm(request.POST or None, request.FILES or None)
    if form.is_valid():
        csv_data_instance = form.save(commit=False)
        csv_data_instance.import_data = form.cleaned_data['import_data']
        csv_data_instance.save()

        # Automatic Task Creation for a single-step workflow
        tasks_created = 0
        for task in csv_data_instance.import_data:
            # We use name, address etc from the cleaned JSON data
            import_task, created = ImportTask.objects.get_or_create(
                csv_data=csv_data_instance, 
                import_id=task['import_id'], 
                defaults={
                    'name': task.get('name'),
                    'username': task.get('username'),
                    'password': task.get('password'),
                    'address': task.get('address'),
                    'port': task.get('port', 22),
                    'router_type': task.get('router_type'),
                    'connection_protocol': task.get('connection_protocol', 'ssh'),
                    'backup_profile_name': task.get('backup_profile'),
                    'router_group_name': task.get('router_group'),
                    'monitoring': True if str(task.get('monitoring', 'true')).lower() == 'true' else False,
                }
            )
            if created:
                tasks_created += 1

        messages.success(request, f'CSV procesado. Se han preparado {tasks_created} equipos para importar.')
        return redirect('/router/import_tool/details/?uuid=' + str(csv_data_instance.uuid))

    data = {
        'form': form,
        'page_title': 'Importar Equipos desde Excel',
    }

    return render(request, 'import_tool/import_csv_form.html', context=data)



@login_required()
def view_download_csv_template(request):
    """Descarga una plantilla CSV clásica lista para abrir en Microsoft Excel con columnas simples."""
    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = 'attachment; filename="plantilla_equipos_excel.csv"'
    writer = csv.writer(response, delimiter=';', quoting=csv.QUOTE_MINIMAL)
    writer.writerow(['Nombre', 'IP', 'Usuario', 'Contraseña', 'Marca', 'Nodo'])
    writer.writerow(['Router Principal', '192.168.1.1', 'admin', 'clave123', 'mikrotik', 'Nodo Centro'])
    writer.writerow(['Switch Acceso 1', '10.0.0.2', 'admin', 'clave123', 'cisco', 'Nodo Centro'])
    writer.writerow(['Firewall Borde', '172.16.0.1', 'admin', 'clave123', 'huawei', 'Nodo Norte'])
    writer.writerow(['Router Repetidor', '192.168.10.5', 'admin', 'clave123', 'mikrotik', 'General'])
    return response


@login_required()
def view_export_routers_csv(request):
    """Exporta todos los equipos actuales en formato CSV compatible con Excel y con la herramienta de importación."""
    if not UserAcl.objects.filter(user=request.user).filter(user_level__gte=30).exists():
        return render(request, 'access_denied.html', {'page_title': 'Acceso Denegado'})
    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = 'attachment; filename="inventario_equipos_backupweb.csv"'
    writer = csv.writer(response, quoting=csv.QUOTE_ALL)
    writer.writerow([
        'name', 'username', 'password', 'address', 'port',
        'router_type', 'connection_protocol', 'backup_profile', 'router_group', 'monitoring'
    ])
    for r in Router.objects.all().prefetch_related('routergroup_set', 'backup_profile').order_by('name'):
        grp = r.routergroup_set.first()
        writer.writerow([
            r.name,
            r.username or '',
            r.decrypted_password or '',
            r.address,
            str(r.port),
            r.router_type,
            getattr(r, 'connection_protocol', 'ssh') or 'ssh',
            r.backup_profile.name if r.backup_profile else 'default',
            grp.name if grp else '',
            'true' if r.monitoring else 'false',
        ])
    return response
