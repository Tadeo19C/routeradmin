#!/bin/bash
PRODUCTION_SETTINGS_FILE="/app/routerfleet/production_settings.py"

set -e

mkdir -p /app_secrets
mkdir -p /var/lib/routerfleet
mkdir -p /app_static_files

if [ -z "$SERVER_ADDRESS" ]; then
    SERVER_ADDRESS="0.0.0.0"
fi

POSTGRES_HOST="${POSTGRES_HOST:-megacom-db}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_DB="${POSTGRES_DB:-megacom}"
POSTGRES_USER="${POSTGRES_USER:-admin}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-password123}"

DEBUG_VALUE="False"
if [[ "${DEBUG_MODE,,}" == "true" ]]; then
    DEBUG_VALUE="True"
fi

if [ ! -f /app_secrets/secret_key ]; then
    python -c "import secrets; print(secrets.token_urlsafe(50))" > /app_secrets/secret_key
fi

if [ ! -f /app_secrets/monitoring_key ]; then
    cat /proc/sys/kernel/random/uuid > /app_secrets/monitoring_key
fi

if [ ! -f /app_secrets/fernet_key ]; then
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" > /app_secrets/fernet_key
fi

export FERNET_KEY="$(cat /app_secrets/fernet_key)"

# Auto-detect working PostgreSQL credentials in case .env had different defaults than the initialized volume
read -r WORKING_DB WORKING_USER WORKING_PASS < <(python - <<PYCODE
import psycopg2
import os

host = os.environ.get("POSTGRES_HOST", "megacom-db")
port = int(os.environ.get("POSTGRES_PORT", "5432"))
candidates = [
    (os.environ.get("POSTGRES_DB", "megacom"), os.environ.get("POSTGRES_USER", "admin"), os.environ.get("POSTGRES_PASSWORD", "password123")),
    ("megacom", "admin", "password123"),
    ("routerfleet", "routerfleet", "your_database_password"),
    ("postgres", "admin", "password123"),
    ("postgres", "routerfleet", "your_database_password"),
]

for db, usr, pwd in candidates:
    try:
        conn = psycopg2.connect(dbname=db, user=usr, password=pwd, host=host, port=port, connect_timeout=3)
        conn.close()
        print(f"{db} {usr} {pwd}")
        break
    except Exception:
        continue
else:
    print(f"{candidates[0][0]} {candidates[0][1]} {candidates[0][2]}")
PYCODE
)

if [ -n "$WORKING_DB" ]; then
    POSTGRES_DB="$WORKING_DB"
    POSTGRES_USER="$WORKING_USER"
    POSTGRES_PASSWORD="$WORKING_PASS"
fi

cat > $PRODUCTION_SETTINGS_FILE <<EOL
DEBUG = $DEBUG_VALUE
ALLOWED_HOSTS = ['*']
USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECRET_KEY = '$(cat /app_secrets/secret_key)'
FERNET_KEY = '$(cat /app_secrets/fernet_key)'
STATIC_ROOT = '/app_static_files/'
MEDIA_ROOT = '/var/lib/routerfleet/'
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': '$POSTGRES_DB',
        'USER': '$POSTGRES_USER',
        'PASSWORD': '$POSTGRES_PASSWORD',
        'HOST': '$POSTGRES_HOST',
        'PORT': '$POSTGRES_PORT',
    }
}
EOL

if [ -n "$TZ" ]; then
    echo "TIME_ZONE = '$TZ'" >> $PRODUCTION_SETTINGS_FILE
fi

echo "MONITORING_KEY = '$(cat /app_secrets/monitoring_key)'" >> $PRODUCTION_SETTINGS_FILE

exec "$@"
