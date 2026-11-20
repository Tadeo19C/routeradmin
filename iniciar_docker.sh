#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

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

if $DOCKER_CMD compose version &> /dev/null; then
    COMPOSE_CMD="$DOCKER_CMD compose"
elif command -v docker-compose &> /dev/null; then
    if ! docker info &> /dev/null; then
        COMPOSE_CMD="sudo docker-compose"
    else
        COMPOSE_CMD="docker-compose"
    fi
else
    COMPOSE_CMD="$DOCKER_CMD compose"
fi

if [ ! -f .env ]; then
    echo "[*] Creando archivo .env inicial..."
    cp .env.example .env
fi

# Funcion para comprobar si un puerto esta ocupado por otro proceso que no sea megacom-web
is_port_busy() {
    local port=$1
    if command -v ss &> /dev/null; then
        if ss -tulpn 2>/dev/null | grep -E -q ":${port}[[:space:]]"; then
            if ! $DOCKER_CMD ps --format '{{.Names}}' 2>/dev/null | grep -q '^megacom-web$'; then
                return 0
            fi
        fi
    fi
    return 1
}

if is_port_busy 80; then
    echo "[!] Aviso: El puerto 80 ya está ocupado por otro servicio en este servidor."
    export WEB_PORT_PRIMARY=8080
else
    export WEB_PORT_PRIMARY=80
fi

if is_port_busy 81; then
    echo "[!] Aviso: El puerto 81 ya está ocupado por otro servicio en este servidor."
    export WEB_PORT_SECONDARY=8081
else
    export WEB_PORT_SECONDARY=81
fi

echo "[*] Habilitando puertos ${WEB_PORT_PRIMARY} y ${WEB_PORT_SECONDARY}..."
echo "[*] Construyendo y levantando contenedores de MEGACOM..."
$COMPOSE_CMD -f docker-compose.megacom.yml up -d --build --remove-orphans

SERVER_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
if [ -z "$SERVER_IP" ]; then
    SERVER_IP="localhost"
fi

echo ""
echo "==================================================="
echo "  SISTEMA INSTALADO Y CORRIENDO EXITOSAMENTE!"
echo "==================================================="
echo "  Acceso 1 (Puerto ${WEB_PORT_PRIMARY}): http://${SERVER_IP}:${WEB_PORT_PRIMARY}"
echo "  Acceso 2 (Puerto ${WEB_PORT_SECONDARY}): http://${SERVER_IP}:${WEB_PORT_SECONDARY}"
echo "==================================================="
