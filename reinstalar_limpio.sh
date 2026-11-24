#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

echo "==================================================="
echo "  NetVault - Reinstalación Limpia (Wipe Completo)"
echo "==================================================="
echo "ADVERTENCIA: Esta acción BORRARÁ permanentemente:"
echo "  - Toda la base de datos (routers, usuarios, contraseñas)"
echo "  - Todos los respaldos descargados y logs"
echo "  - Todos los contenedores y volúmenes de Docker"
echo "==================================================="
read -p "¿Estás seguro de que deseas borrar todo y reinstalar de cero? (s/N): " confirm

if [[ "$confirm" != "s" && "$confirm" != "S" ]]; then
    echo "[*] Operación cancelada. No se modificó nada."
    exit 0
fi

echo ""
echo "[1/4] Deteniendo y eliminando contenedores y volúmenes..."
DOCKER_CMD="docker"
if ! docker info &> /dev/null; then
    DOCKER_CMD="sudo docker"
fi

$DOCKER_CMD compose -f docker-compose.netvault.yml down -v --remove-orphans 2>/dev/null || \
docker-compose -f docker-compose.netvault.yml down -v --remove-orphans 2>/dev/null || true

# Eliminar volúmenes residuales (NetVault y Megacom)
$DOCKER_CMD volume rm -f \
    netvault_postgres_data netvault_media netvault_static netvault_secrets \
    megacom_postgres_data megacom_media megacom_static megacom_secrets \
    routeradmin_netvault_postgres_data routeradmin_netvault_media \
    routeradmin_megacom_postgres_data routeradmin_megacom_media 2>/dev/null || true

echo "[2/4] Limpiando archivos de configuración local..."
rm -f .env

echo "[3/4] Obteniendo la versión más reciente de GitHub..."
git reset --hard HEAD
git pull origin master

echo "[4/4] Iniciando instalación limpia de NetVault..."
./iniciar_docker.sh
