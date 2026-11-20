#!/bin/bash
PRODUCTION_SETTINGS_FILE="/app/routerfleet/production_settings.py"

set -e

mkdir -p /app_secrets
mkdir -p /var/lib/routerfleet
mkdir -p /app_static_files

if [ -z "$SERVER_ADDRESS" ]; then
    SERVER_ADDRESS="0.0.0.0"
fi

if [[ "${DATABASE_ENGINE,,}" == "sqlite" ]]; then
    DATABASES_CONFIG="DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': '/var/lib/routerfleet_sqlite/routerfleet-db.sqlite3',
        }
    }"
else
    POSTGRES_HOST="${POSTGRES_HOST:-megacom-db}"
    POSTGRES_PORT="${POSTGRES_PORT:-5432}"
    POSTGRES_DB="${POSTGRES_DB:-megacom}"
    POSTGRES_USER="${POSTGRES_USER:-admin}"
    POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-password123}"

    DATABASES_CONFIG="DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': '$POSTGRES_DB',
            'USER': '$POSTGRES_USER',
            'PASSWORD': '$POSTGRES_PASSWORD',
            'HOST': '$POSTGRES_HOST',
            'PORT': '$POSTGRES_PORT',
        }
    }"
fi

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

cat > $PRODUCTION_SETTINGS_FILE <<EOL
DEBUG = $DEBUG_VALUE
ALLOWED_HOSTS = ['*']
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECRET_KEY = '$(cat /app_secrets/secret_key)'
FERNET_KEY = '$(cat /app_secrets/fernet_key)'
$DATABASES_CONFIG
EOL

if [ -n "$TZ" ]; then
    echo "TIME_ZONE = '$TZ'" >> $PRODUCTION_SETTINGS_FILE
fi

echo "MONITORING_KEY = '$(cat /app_secrets/monitoring_key)'" >> $PRODUCTION_SETTINGS_FILE

exec "$@"
