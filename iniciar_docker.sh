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

echo "[*] Levantando contenedores con Docker Compose..."
docker compose -f docker-compose.megacom.yml up -d --build

echo ""
echo "==================================================="
echo "  SISTEMA INSTALADO Y CORRIENDO EXITOSAMENTE!"
echo "==================================================="
echo "  Acceso Web: http://localhost:8080 (o http://IP-DEL-SERVIDOR)"
echo "==================================================="
