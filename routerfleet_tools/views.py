from django.shortcuts import render, redirect, Http404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import WebadminSettings
from .forms import SystemBrandingForm
from django.http import JsonResponse
from django.conf import settings
from django.utils import timezone
import requests


@login_required
def view_system_branding(request):
    if not (request.user.is_superuser or request.user.is_staff):
        return render(request, 'access_denied.html', status=403)

    settings_obj, _ = WebadminSettings.objects.get_or_create(name='webadmin_settings')
    if settings_obj.app_title != 'Tdox-Config':
        settings_obj.app_title = 'Tdox-Config'
        settings_obj.save(update_fields=['app_title'])

    if request.method == 'POST':
        action = request.POST.get('action', '')

        # Action: Restore default logo
        if action == 'restore_default' or request.POST.get('remove_logo') == '1':
            if settings_obj.custom_logo:
                settings_obj.custom_logo.delete(save=False)
                settings_obj.custom_logo = None
            settings_obj.app_title = 'Tdox-Config'
            settings_obj.save()
            messages.success(request, "Se ha restaurado el logo predeterminado de Tdox-Config.")
            return redirect('system_branding')

        form = SystemBrandingForm(request.POST, request.FILES, instance=settings_obj)
        if form.is_valid():
            branding = form.save(commit=False)
            branding.app_title = 'Tdox-Config'
            branding.save()
            messages.success(request, "Logo del sistema actualizado exitosamente.")
            return redirect('system_branding')
    else:
        form = SystemBrandingForm(instance=settings_obj)

    context = {
        'form': form,
        'settings_obj': settings_obj,
        'page_title': 'Personalizar Logo',
    }
    return render(request, 'routerfleet_tools/system_branding.html', context)


def view_cron_check_updates(request):
    webadmin_settings, webadmin_settings_created = WebadminSettings.objects.get_or_create(name='webadmin_settings')
    webadmin_settings.cron_last_run = timezone.now()
    webadmin_settings.save()

    if webadmin_settings.last_checked is None or timezone.now() - webadmin_settings.last_checked > timezone.timedelta(
            hours=1):
        try:
            version = settings.ROUTERFLEET_VERSION / 10000
            url = f'https://updates.eth0.com.br/api/check_updates/?app=routerfleet&version={version}'
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()

            if 'update_available' in data:
                webadmin_settings.update_available = data['update_available']

                if data['update_available']:
                    webadmin_settings.latest_version = float(data['current_version']) * 10000

                webadmin_settings.last_checked = timezone.now()
                webadmin_settings.save()

                response_data = {
                    'update_available': webadmin_settings.update_available,
                    'latest_version': webadmin_settings.latest_version,
                    'current_version': settings.ROUTERFLEET_VERSION,
                }
                return JsonResponse(response_data)

        except Exception as e:
            webadmin_settings.update_available = False
            webadmin_settings.save()
            return JsonResponse({'update_available': False})

    return JsonResponse({'update_available': webadmin_settings.update_available})
