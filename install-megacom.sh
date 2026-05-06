#!/bin/bash

# MEGACOM - Instalador Automático "Todo en Uno"
# Este script descarga, extrae y configura la última versión de MEGACOM.

set -e

echo "================================================="
echo "        MEGACOM - Instalador Profesional         "
echo "================================================="

# Variables
REPO_URL="https://github.com/Tadeo19C/routeradmin/archive/refs/heads/master.zip"
INSTALL_DIR="routeradmin-master" # GitHub zip extraction folder name usually
ZIP_FILE="megacom.zip"

# 1. Verificar dependencias básicas
echo "[1/5] Verificando dependencias locales..."
DEPENDENCIAS=("curl" "unzip" "docker")

for cmd in "${DEPENDENCIAS[@]}"; do
    if ! command -v "$cmd" &> /dev/null; then
        if [ "$cmd" == "unzip" ] || [ "$cmd" == "curl" ]; then
            echo "Instalando dependencia faltante: $cmd..."
            if command -v apt-get &> /dev/null; then
                sudo apt-get update && sudo apt-get install -y "$cmd"
            else
                echo "Error: El comando '$cmd' no está instalado y no se pudo instalar automáticamente. Instálalo manualmente."
                exit 1
            fi
        else
            echo "Error: El comando '$cmd' no está instalado. Por favor, instala Docker e intenta de nuevo."
            exit 1
        fi
    fi
done

# Verificación extra para Docker Compose (plugin o legacy)
if ! docker compose version &> /dev/null && ! command -v docker-compose &> /dev/null; then
    echo "Docker Compose no detectado. Intentando instalar el plugin..."
    if command -v apt-get &> /dev/null; then
        sudo apt-get update && sudo apt-get install -y docker-compose-v2
    else
        echo "Error: Docker Compose no está instalado y no pudo instalarse automáticamente."
        exit 1
    fi
fi

# 2. Descargar el proyecto
echo "[2/5] Descargando la última versión desde GitHub..."
curl -L $REPO_URL -o $ZIP_FILE

# Limpieza preventiva de contenedores viejos
echo "Limpiando instalaciones previas si existen..."
docker stop megacom-app megacom-web megacom-db 2>/dev/null || true
docker rm megacom-app megacom-web megacom-db 2>/dev/null || true

# 3. Extraer archivos
echo "[3/5] Extrayendo archivos..."
unzip -qo $ZIP_FILE
rm $ZIP_FILE

# 4. Determinar carpeta extraída (GitHub reresentado por repo-branch)
EXTRACTED_DIR=$(ls -d */ | grep "routeradmin-master" | head -n 1)
if [ -z "$EXTRACTED_DIR" ]; then
    # Fallback si el nombre cambia
    EXTRACTED_DIR=$(ls -d */ | head -n 1)
fi

cd "$EXTRACTED_DIR"
chmod +x setup.sh

# 5. Ejecutar la instalación
echo "[4/5] Iniciando el proceso de instalación automática..."
./setup.sh

echo "================================================="
echo "¡INSTALACIÓN COMPLETADA EXITOSAMENTE!"
echo "Accede a MEGACOM en: http://tu-ip-servidor"
echo "================================================="
