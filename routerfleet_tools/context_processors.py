from .models import WebadminSettings


def branding_context(request):
    try:
        settings_obj = WebadminSettings.objects.filter(name='webadmin_settings').first()
        if not settings_obj:
            settings_obj, _ = WebadminSettings.objects.get_or_create(name='webadmin_settings')
        
        logo_url = settings_obj.logo_url
        app_title = settings_obj.app_title or 'BACKUP WEB'
    except Exception:
        logo_url = None
        app_title = 'BACKUP WEB'
        settings_obj = None

    return {
        'custom_logo_url': logo_url,
        'custom_app_title': app_title,
        'system_settings': settings_obj,
    }
