@echo off
title MEGACOM RouterFleet - Servidor Local
echo ===================================================
echo   MEGACOM ROUTERFLEET - Servidor Local Windows
echo ===================================================
echo.

:: Verificar si el entorno virtual existe
if not exist .venv\Scripts\activate.bat (
    echo [*] Creando entorno virtual .venv...
    py -m venv .venv 2>nul || python -m venv .venv
    echo [*] Instalando dependencias...
    .\.venv\Scripts\pip.exe install -r requirements.txt
    .\.venv\Scripts\python.exe manage.py migrate
)

echo [*] Iniciando servidor con motor de tareas integrado...
echo [*] Disponible en: http://127.0.0.1:8080/
echo.
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8080
pause
