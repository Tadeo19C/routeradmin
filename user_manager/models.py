from django.db import models
from django.contrib.auth.models import User
import uuid


class UserAcl(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    user_level = models.PositiveIntegerField(default=0, choices=(
        (10, 'Visor'),
        (20, 'Operador de Respaldos'),
        (30, 'Gestor de Equipos'),
        (40, 'Gestor de Configuración'),
        (50, 'Administrador'),
    ))

    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)
    uuid = models.UUIDField(primary_key=True, editable=False, default=uuid.uuid4)

    def __str__(self):
        return self.user.username
