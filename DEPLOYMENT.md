# Guía de Despliegue de MEGACOM

Esta guía describe cómo desplegar **MEGACOM** para tus clientes usando Docker. Esto asegura un entorno consistente y una instalación sencilla.

## Requisitos Previos
- Docker y Docker Compose instalados en la máquina host.
- Mínimo 1GB de RAM.

## Instalación vía Script de Configuración Automática (Recomendado)

Hemos proporcionado un script automatizado para manejar la instalación en contenedores:

1.  **Preparar el host**: Asegúrate de que Docker y Docker Compose estén instalados.
2.  **Descargar el paquete**: Extrae los archivos de MEGACOM en una carpeta.
3.  **Ejecutar la configuración**:
    ```bash
    chmod +x setup.sh
    ./setup.sh
    ```
4.  **Configuración Inicial**:
    - El script construirá las imágenes personalizadas de MEGACOM e iniciará los servicios.
    - Abre tu navegador en `http://tu-ip-servidor`.

## Instalación Manual (Docker)

Si prefieres ejecutarlo manualmente, usa el siguiente comando:
```bash
docker-compose -f docker-compose.megacom.yml up -d --build
```

4.  **Configuración Inicial**:
    - Accede a la aplicación en `http://tu-ip-servidor:8000`.
    - Crea el primer usuario administrador cuando se te solicite.

## Actualización de MEGACOM

Para actualizar a la versión más reciente:
```bash
docker-compose down
git pull
docker-compose up -d --build
```

## Recomendaciones de Seguridad
- Usa siempre una contraseña fuerte para la cuenta de administrador.
- Si vas a exponer el sistema a internet, recomendamos usar un Proxy Inverso con HTTPS (como Nginx o Traefik).
- Usa llaves SSH en lugar de contraseñas para los dispositivos MikroTik siempre que sea posible.
