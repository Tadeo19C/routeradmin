# MEGACOM

Bienvenido a **MEGACOM** - la evolución en la gestión y respaldo centralizado de routers. Este proyecto está diseñado para revolucionar la forma en que manejamos las configuraciones de equipos de red, enfocándose en la simplicidad, seguridad y regionalización para Centroamérica.

## Introducción

**MEGACOM** ha sido desarrollado con el objetivo de facilitar la administración de flotas de dispositivos, con un enfoque inicial en equipos MikroTik. Este proyecto representa un sistema robusto que no solo simplifica, sino que también protege las tareas de gestión de red a través de diversos dispositivos.

## Características Principales

- **Gestión Centralizada de Respaldos:** Administra fácilmente los respaldos de tus routers y equipos de red desde una interfaz única y profesional.
- **Comparación de Respaldos (Diff):** Compara versiones de configuración para identificar cambios y rastrear el historial de modificaciones.
- **Perfiles de Respaldo Múltiples:** Crea diferentes perfiles para gestionar horarios, retención y políticas de respaldo personalizadas.
- **Compatibilidad con MikroTik:** Soporte optimizado para dispositivos MikroTik con planes de expansión basados en la comunidad.
- **Actualizaciones Continuas:** Mejoras regulares en funcionalidad, rendimiento y seguridad.
- **Seguridad Reforzada (Hardening):** Protección contra inyección de comandos, gestión de concurrencia y reintentos ante fallos de red.
- **Localización Completa:** Interfaz y documentación totalmente en español, ajustada a la zona horaria de Centroamérica.

## Capturas de Pantalla
### Comparación de Respaldos
Identifica cambios rápidamente entre diferentes fechas de respaldo.
![Comparación de Respaldos](screenshots/backup-diff.png)
### Perfiles de Respaldo
Configura múltiples agendas de respaldo para diferentes nodos.
![Perfiles de Respaldo](screenshots/backup-profiles.png)
### Detalles del Equipo
Visualiza información detallada y el historial completo de cada router.
![Detalles del Equipo](screenshots/router-details.png)
### Gestión de Usuarios
Administra accesos y permisos de forma segura.
![Gestión de Usuarios](screenshots/user-manager.png)

## Instrucciones de Despliegue

Sigue estos pasos para desplegar **MEGACOM** en tu servidor:

### Paso 1: Preparar el Entorno
Crea un directorio para el proyecto y entra en él.
```bash
mkdir megacom && cd megacom
```

### Paso 2: Obtener los Archivos de Configuración
Puedes descargar el paquete ZIP preparado o clonar el repositorio. Asegúrate de tener el archivo `docker-compose.megacom.yml`.

### Paso 3: Configurar el archivo `.env`
Crea un archivo `.env` basado en `.env.example` con tus variables:
```env
SERVER_ADDRESS=tu-ip-o-dominio
DEBUG_MODE=False
TIMEZONE=America/Guatemala
# Configuración de base de datos
DATABASE_ENGINE=sqlite
```

### Paso 4: Ejecutar el Instalador Automático
Hemos incluido un script para facilitar todo el proceso:
```bash
chmod +x setup.sh
./setup.sh
```

### Paso 5: Acceder a la Interfaz Web
Visita `http://tu-ip-servidor` en tu navegador para comenzar. El sistema te pedirá crear la primera cuenta de administrador.

## Contribuciones
Como proyecto en evolución, MEGACOM agradece el apoyo de la comunidad. Ya sea que seas desarrollador, ingeniero de redes o entusiasta, hay muchas formas de ayudar a mejorar esta herramienta.

## Soporte
Para reportar fallos o sugerir mejoras, utiliza la sección de Issues en el repositorio oficial.

## Licencia
MEGACOM se distribuye bajo la [Licencia MIT](LICENSE).
