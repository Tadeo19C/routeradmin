#!/usr/bin/env bash
set -e

echo "==================================================="
echo "  MEGACOM ROUTERFLEET - Instalador Docker Plug & Play"
echo "==================================================="

if ! command -v docker &> /dev/null; then
    echo "[ERROR] Docker no está instalado en este servidor."
    echo "Instálalo con: curl -fsSL https://get.docker.com | sudo sh"
    exit 1
fi

DOCKER_CMD="docker"
if ! docker info &> /dev/null; then
    DOCKER_CMD="sudo docker"
fi

if [ ! -f .env ]; then
    echo "[*] Creando archivo .env inicial..."
    cp .env.example .env
fi

# Detectar si el puerto 80 está ocupado por otro servicio ajeno a megacom-web
PORT80_BUSY_BY_OTHER=0
if command -v ss &> /dev/null; then
    if ss -tulpn 2>/dev/null | grep -q ':80 '; then
        if ! $DOCKER_CMD ps --format '{{.Names}}' 2>/dev/null | grep -q '^megacom-web$'; then
            PORT80_BUSY_BY_OTHER=1
        fi
    fi
fi

if [ "$PORT80_BUSY_BY_OTHER" -eq 1 ]; then
    echo "[!] Aviso: El puerto 80 ya está ocupado por otro servicio en este servidor."
    echo "[*] Habilitando automáticamente los puertos 81 y 8080 para evitar conflictos..."
    export WEB_PORT_PRIMARY=81
    export WEB_PORT_SECONDARY=8080
else
    echo "[*] Habilitando puertos 80 y 81 simultáneamente..."
    export WEB_PORT_PRIMARY=80
    export WEB_PORT_SECONDARY=81
fi

echo "[*] Construyendo y levantando contenedores de MEGACOM..."
$DOCKER_CMD compose -f docker-compose.megacom.yml up -d --build --remove-orphans

SERVER_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
if [ -z "$SERVER_IP" ]; then
    SERVER_IP="localhost"
fi

echo ""
echo "==================================================="
echo "  SISTEMA INSTALADO Y CORRIENDO EXITOSAMENTE!"
echo "==================================================="
if [ "$PORT80_BUSY_BY_OTHER" -eq 1 ]; then
    echo "  Acceso Principal (Puerto 81):   http://${SERVER_IP}:81"
    echo "  Acceso Alterno   (Puerto 8080): http://${SERVER_IP}:8080"
else
    echo "  Acceso Puerto 80: http://${SERVER_IP}"
    echo "  Acceso Puerto 81: http://${SERVER_IP}:81"
fi
echo "==================================================="
