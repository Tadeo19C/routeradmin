# Guía de Pruebas de MEGACOM

Esta guía detalla cómo verificar que la instalación de **MEGACOM** ha sido exitosa y que todas las funciones principales están operativas.

## 1. Verificación de Infraestructura (Servidor)

Ejecuta estos comandos en la terminal de Linux para confirmar que los contenedores están funcionando:

*   **Estado de Contenedores:**
    ```bash
    docker compose -f docker-compose.megacom.yml ps
    ```
    *Resultado esperado:* Todos los contenedores (`megacom-app`, `megacom-db`, `megacom-web`) deben mostrar el estado `Up` o `Healthy`.

*   **Logs de la Aplicación:**
    ```bash
    docker logs megacom-app
    ```
    *Resultado esperado:* No deben aparecer errores de conexión a la base de datos. Debes ver mensajes indicando que Gunicorn está escuchando en el puerto 8001.

## 2. Pruebas de Funcionalidad (Interfaz Web)

Accede a `http://tu-ip-servidor` y realiza las siguientes pruebas:

### A. Acceso Inicial
- **Prueba:** Abre la URL por primera vez.
- **Resultado:** El sistema debe redirigirte automáticamente a la página de creación de la cuenta de Administrador.

### B. Gestión de Nodos (Grupos)
- **Prueba:** Ve a la sección de "Equipos" y crea un nuevo "Nodo" llamado "Test Nodo".
- **Resultado:** El nodo debe aparecer en la lista sin errores.

### C. Monitoreo en Tiempo Real
- **Prueba:** Agrega un router MikroTik real con una IP válida.
- **Resultado:** En el Dashboard, el equipo debe aparecer inicialmente como "Offline" y cambiar a "Online" (verde) en menos de 1 minuto.

### D. Ejecución de Respaldo Manual
- **Prueba:** Entra a los detalles del router que agregaste y haz clic en "Realizar Respaldo Ahora".
- **Resultado:** Se debe abrir una ventana de progreso y, al finalizar, debe aparecer un nuevo archivo en el historial de respaldos.

### E. Comparación de Configuraciones (Diff)
- **Prueba:** Realiza un segundo respaldo después de cambiar algo pequeño en el router. Selecciónalos ambos y haz clic en "Comparar".
- **Resultado:** El sistema debe resaltar en rojo/verde las líneas que cambiaron.

## 3. Resolución de Problemas Comunes
- **Si la web no carga:** Verifica que el puerto 80 esté abierto en el firewall de Ubuntu (`ufw allow 80`).
- **Si el router sale Offline:** Asegúrate de que el servidor tenga acceso por ping al router y que las credenciales sean correctas.
