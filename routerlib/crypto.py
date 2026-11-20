"""
Módulo de Cifrado Seguro de Credenciales en Reposo para BACKUP WEB.
Utiliza cifrado simétrico robusto Fernet (AES-128 en modo CBC con HMAC-SHA256).
"""
import base64
import hashlib
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

ENCRYPTED_PREFIX = "enc::"


def _get_fernet() -> Fernet:
    """
    Obtiene la instancia de Fernet utilizando la clave de cifrado de settings
    o derivándola criptográficamente de SECRET_KEY mediante SHA-256.
    """
    secret = getattr(settings, 'CREDENTIAL_ENCRYPTION_KEY', None) or settings.SECRET_KEY
    if isinstance(secret, str):
        secret_bytes = secret.encode('utf-8')
    else:
        secret_bytes = bytes(secret)
    
    key = base64.urlsafe_b64encode(hashlib.sha256(secret_bytes).digest())
    return Fernet(key)


def encrypt_credential(value: Optional[str]) -> Optional[str]:
    """
    Cifra una credencial (contraseña o llave privada).
    Si ya está cifrada con el prefijo enc::, se devuelve intacta.
    """
    if not value or not isinstance(value, str):
        return value
    if value.startswith(ENCRYPTED_PREFIX):
        return value
    
    try:
        f = _get_fernet()
        token = f.encrypt(value.encode('utf-8')).decode('utf-8')
        return f"{ENCRYPTED_PREFIX}{token}"
    except Exception:
        # En caso de fallo inesperado, se devuelve el valor original para no romper el flujo
        return value


def decrypt_credential(value: Optional[str]) -> Optional[str]:
    """
    Descifra una credencial cifrada con el prefijo enc::.
    Si el valor no está cifrado (legacy o texto plano), se devuelve tal cual.
    """
    if not value or not isinstance(value, str):
        return value
    if not value.startswith(ENCRYPTED_PREFIX):
        return value
    
    token = value[len(ENCRYPTED_PREFIX):]
    try:
        f = _get_fernet()
        return f.decrypt(token.encode('utf-8')).decode('utf-8')
    except (InvalidToken, Exception):
        # Si la clave cambió o el token está corrupto, se devuelve el valor original
        return value
