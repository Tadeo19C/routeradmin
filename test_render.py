import os
import django
import sys

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'routerfleet.settings')
django.setup()

from router_manager.forms import RouterForm

try:
    print("Attempting to instantiate RouterForm...")
    form = RouterForm()
    print("Form instantiated successfully.")
    
    print("Attempting to render form...")
    from crispy_forms.utils import render_crispy_form
    rendered = render_crispy_form(form)
    print("Form rendered successfully!")
    print(f"Length of rendered content: {len(rendered)}")
except Exception as e:
    print(f"ERROR: {str(e)}")
    import traceback
    traceback.print_exc()
