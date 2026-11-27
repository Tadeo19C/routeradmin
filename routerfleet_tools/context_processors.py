from django.conf import settings
from .models import WebadminSettings


def branding_context(request):
    try:
        settings_obj = WebadminSettings.objects.filter(name='webadmin_settings').first()
        if not settings_obj:
            settings_obj, _ = WebadminSettings.objects.get_or_create(name='webadmin_settings')

        logo_url = settings_obj.logo_url
    except Exception:
        logo_url = None
        settings_obj = None

    return {
        'custom_logo_url': logo_url,
        'custom_app_title': 'Tdox-Config',
        'custom_app_subtitle': 'backup configuration',
        'system_settings': settings_obj,
        'max_device_categories': getattr(settings, 'MAX_DEVICE_CATEGORIES', 3),
        'category_limit_email': getattr(settings, 'CATEGORY_LIMIT_CONTACT_EMAIL', 'soporte@tdox-config.com'),
    }
