@echo off
echo ===================================================
echo   BACKUP WEB - Instalador Docker Plug ^& Play
echo ===================================================
echo.

where docker >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Docker no esta instalado o no se encuentra en el PATH.
    echo Por favor instale Docker Desktop desde: https://www.docker.com/products/docker-desktop/
    echo.
    pause
    exit /b 1
)

if not exist .env (
    echo [*] Generando archivo de configuracion .env inicial...
    copy .env.example .env >nul
)

echo [*] Construyendo y levantando los contenedores de BACKUP WEB (Puertos 80 y 81)...
docker compose -f docker-compose.megacom.yml up -d --build --remove-orphans

if %ERRORLEVEL% equ 0 (
    echo.
    echo ===================================================
    echo   SISTEMA INSTALADO Y CORRIENDO EXITOSAMENTE!
    echo ===================================================
    echo   Acceso Puerto 80: http://localhost
    echo   Acceso Puerto 81: http://localhost:81
    echo ===================================================
) else (
    echo.
    echo [ERROR] Ocurrio un fallo al levantar los contenedores.
)

pause
