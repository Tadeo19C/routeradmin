from .models import UserActionLog

class AuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Solo loguear acciones que modifican datos (POST, DELETE, PUT) o logins/logouts
        if request.user.is_authenticated and request.method in ['POST', 'DELETE', 'PUT']:
            # Evitar loguear el propio log de auditoría o estáticos
            if not request.path.startswith('/admin/user_manager/useractionlog/'):
                action = f"{request.method} {request.path}"
                details = f"Params: {request.POST.dict()}" if request.method == 'POST' else ""
                
                # Ocultar contraseñas en los logs
                if 'password' in details:
                    details = "Contraseña oculta por seguridad."

                UserActionLog.objects.create(
                    user=request.user,
                    action=action,
                    details=details,
                    ip_address=self.get_client_ip(request)
                )

        return response

    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
