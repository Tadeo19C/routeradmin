@echo off
echo ===================================================
echo   MEGACOM ROUTERFLEET - Instalador Docker Plug & Play
echo ===================================================
echo.

:: Verificar si Docker está instalado
where docker >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Docker no esta instalado o no se encuentra en el PATH.
    echo Por favor instale Docker Desktop desde: https://www.docker.com/products/docker-desktop/
    echo.
    pause
    exit /b 1
)

:: Copiar .env si no existe
if not exist .env (
    echo [*] Generando archivo de configuracion .env inicial...
    copy .env.example .env >nul
)

echo [*] Construyendo y levantando los contenedores de RouterFleet...
docker compose -f docker-compose.megacom.yml up -d --build

if %ERRORLEVEL% equ 0 (
    echo.
    echo ===================================================
    echo   SISTEMA INSTALADO Y CORRIENDO EXITOSAMENTE!
    echo ===================================================
    echo   Acceso Web: http://localhost:8080 (o http://localhost)
    echo ===================================================
) else (
    echo.
    echo [ERROR] Ocurrio un fallo al levantar los contenedores.
)

pause
