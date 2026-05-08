from router_manager.models import Router
from django.db.models import Count

duplicates = Router.objects.values('address').annotate(address_count=Count('address')).filter(address_count__gt=1)

if duplicates:
    print("Found duplicate IP addresses:")
    for entry in duplicates:
        print(f"IP: {entry['address']} - Count: {entry['address_count']}")
else:
    print("No duplicate IP addresses found.")
