#!/usr/bin/env bash
set -e

echo "==================================================="
echo "  MEGACOM ROUTERFLEET - Instalador Docker Plug & Play"
echo "==================================================="

if ! command -v docker &> /dev/null; then
    echo "[ERROR] Docker no está instalado en este servidor."
    echo "Instálalo con: curl -fsSL https://get.docker.com | sh"
    exit 1
fi

if [ ! -f .env ]; then
    echo "[*] Creando archivo .env base..."
    cp .env.example .env
fi

DOCKER_CMD="docker"
if ! docker info &> /dev/null; then
    DOCKER_CMD="sudo docker"
fi

echo "[*] Levantando contenedores con Docker Compose..."
$DOCKER_CMD compose -f docker-compose.megacom.yml up -d --build --remove-orphans

echo ""
echo "==================================================="
echo "  SISTEMA INSTALADO Y CORRIENDO EXITOSAMENTE!"
echo "==================================================="
echo "  Acceso Web: http://$(hostname -I | awk '{print $1}')"
echo "==================================================="
