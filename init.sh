#!/bin/bash
set -e

shopt -s nullglob

echo "[*] Esperando a que la base de datos este lista..."
python - <<'PYCODE'
import time
import sys
import django
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "routerfleet.settings")
django.setup()
from django.db import connections

for attempt in range(30):
    try:
        connections['default'].ensure_connection()
        print("[OK] Base de datos conectada correctamente.")
        sys.exit(0)
    except Exception as e:
        print(f"[*] Esperando base de datos ({attempt+1}/30)...")
        time.sleep(2)

print("[ERROR] No se pudo conectar a la base de datos despues de 60 segundos.")
sys.exit(1)
PYCODE

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec gunicorn routerfleet.wsgi:application \
  --bind 0.0.0.0:8000 \
  --worker-class sync \
  --workers 4 \
  --timeout 300 \
  --graceful-timeout 30 \
  --max-requests 1000 \
  --max-requests-jitter 200 \
  --log-level info \
  --capture-output \
  --access-logfile - \
  --error-logfile -
