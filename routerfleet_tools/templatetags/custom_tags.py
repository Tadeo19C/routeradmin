from django import template
from django.conf import settings
from routerfleet_tools.models import WebadminSettings
import time

register = template.Library()

_version_cache = None
_version_cache_time = 0

@register.simple_tag
def tag_webadmin_version():
    global _version_cache, _version_cache_time
    
    # Return cached result if fresh (5 minutes)
    if _version_cache and (time.time() - _version_cache_time) < 300:
        return _version_cache
    
    webadmin_settings, settings_created = WebadminSettings.objects.get_or_create(name='webadmin_settings')
    
    # Only save if values actually changed
    changed = False
    if webadmin_settings.current_version != settings.ROUTERFLEET_VERSION:
        webadmin_settings.current_version = settings.ROUTERFLEET_VERSION
        changed = True
    if webadmin_settings.current_version > webadmin_settings.latest_version:
        webadmin_settings.latest_version = webadmin_settings.current_version
        changed = True
    if webadmin_settings.current_version == webadmin_settings.latest_version and webadmin_settings.update_available:
        webadmin_settings.update_available = False
        changed = True
    
    if changed:
        webadmin_settings.save()
    
    _version_cache = {
        'current_version': settings.ROUTERFLEET_VERSION / 10000,
        'latest_version': webadmin_settings.latest_version / 10000,
        'update_available': webadmin_settings.update_available,
    }
    _version_cache_time = time.time()
    return _version_cache
