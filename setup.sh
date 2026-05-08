#!/bin/bash

# MEGACOM - Script de Configuración Profesional
# Construye y levanta la plataforma completa con Docker Compose.

echo "================================================="
echo "       MEGACOM - Configuración Profesional       "
echo "================================================="

# Verificar Docker
if ! command -v docker &> /dev/null; then
  echo "Error: Docker no está instalado. Instálalo primero." >&2
  exit 1
fi

# Verificar Docker Compose (plugin o legacy)
if docker compose version &> /dev/null; then
  DOCKER_COMPOSE_CMD="docker compose"
elif command -v docker-compose &> /dev/null; then
  DOCKER_COMPOSE_CMD="docker-compose"
else
  echo "Error: Docker Compose no está instalado ('docker compose' ni 'docker-compose' encontrados)." >&2
  exit 1
fi

echo "Usando: $DOCKER_COMPOSE_CMD"

# Crear .env si no existe
if [ ! -f .env ]; then
  echo "Creando archivo .env desde el ejemplo..."
  cp .env.example .env
  echo "Edita el archivo .env con tus configuraciones específicas."
fi

# Construir e iniciar
echo "Construyendo e iniciando contenedores MEGACOM..."
echo "  → PostgreSQL 16 (base de datos)"
echo "  → Redis 7 (broker de tareas)"
echo "  → App Django + Gunicorn"
echo "  → Celery Worker (procesamiento asíncrono)"
echo "  → Celery Beat (programador de tareas)"
echo "  → Nginx (servidor web)"

$DOCKER_COMPOSE_CMD -f docker-compose.megacom.yml build --no-cache
$DOCKER_COMPOSE_CMD -f docker-compose.megacom.yml up -d

echo "================================================="
echo "¡MEGACOM se está desplegando!"
echo "Espera unos segundos a que la base de datos inicie."
echo "Accede a la plataforma en: http://tu-ip-servidor"
echo "================================================="
