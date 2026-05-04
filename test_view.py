import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'routerfleet.settings')
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from router_manager.models import Router

c = Client()
user = User.objects.first()
if user:
    c.force_login(user)

router = Router.objects.exclude(router_type='monitoring').first()
if router:
    print(f"Testing router: {router.uuid}")
    try:
        response = c.get(f'/router/details/?uuid={router.uuid}')
        html = response.content.decode('utf-8')
        if "Fetching router information on next cron" in html:
            print("Successfully rendered default state!")
        elif "Router Information" in html:
            print("Rendered, but missing default clock icon.")
        else:
            print("Router Information block missing entirely from rendering!")
            
        print("Status code:", response.status_code)
    except Exception as e:
        import traceback
        traceback.print_exc()
else:
    print("No non-monitoring router found")
