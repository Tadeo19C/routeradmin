import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'routerfleet.settings')
django.setup()

from router_manager.models import Router

types = Router.objects.values('router_type').annotate(count=django.db.models.Count('router_type'))
print("Current Router Types in DB:")
for t in types:
    print(f"- {t['router_type']}: {t['count']}")
