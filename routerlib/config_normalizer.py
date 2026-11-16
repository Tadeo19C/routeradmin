"""
Módulo de Normalización Inteligente de Configuraciones de Red para MEGACOM.
Elimina comentarios volátiles, marcas de tiempo de exportación y diferencias de formato
para evitar falsos positivos de 'Configuración Modificada' (Config Drift).
"""
import re


def normalize_routeros_config(text: str) -> str:
    """
    Normaliza scripts de configuración exportados de MikroTik RouterOS (/export).
    Elimina cabeceras con fecha/hora de exportación, ID de software y modelo,
    así como espacios en blanco redundantes al final de cada línea.
    """
    if not text:
        return ""
    
    lines = []
    for raw_line in text.replace('\r\n', '\n').split('\n'):
        line = raw_line.rstrip()
        stripped = line.strip()
        
        # Omitir comentarios de cabecera con timestamps volátiles
        # Ejemplos comunes:
        # # 2026-11-16 09:00:00 by RouterOS 7.15
        # # software id = XXXX-XXXX
        # # model = RB750Gr3
        # # serial number = XXXXXXXXXX
        if stripped.startswith('#'):
            lower = stripped.lower()
            if any(marker in lower for marker in [
                'by routeros', 'software id', 'serial number', 'model =', 
                'jan/', 'feb/', 'mar/', 'apr/', 'may/', 'jun/', 
                'jul/', 'aug/', 'sep/', 'oct/', 'nov/', 'dec/'
            ]):
                continue
            # Si es solo una línea vacía de comentario '#'
            if stripped == '#':
                continue
        
        if stripped:  # Omitir líneas completamente en blanco
            lines.append(line)
            
    return '\n'.join(lines).strip()


def normalize_cisco_config(text: str) -> str:
    """
    Normaliza configuraciones de Cisco IOS (show running-config).
    Elimina marcas de tiempo de guardado NVRAM, versión de exportación y bytes de config.
    """
    if not text:
        return ""
    
    lines = []
    for raw_line in text.replace('\r\n', '\n').split('\n'):
        line = raw_line.rstrip()
        stripped = line.strip()
        
        # Ignorar comentarios volátiles de Cisco
        if any(stripped.startswith(prefix) for prefix in [
            'Building configuration...',
            'Current configuration :',
            '! Last configuration change at',
            '! NVRAM config last updated at',
            'ntp clock-period',
        ]):
            continue
            
        if stripped:
            lines.append(line)
            
    return '\n'.join(lines).strip()


def normalize_openwrt_config(text: str) -> str:
    """
    Normaliza exportaciones UCI de OpenWrt.
    """
    if not text:
        return ""
    
    lines = []
    for raw_line in text.replace('\r\n', '\n').split('\n'):
        line = raw_line.rstrip()
        if line.strip():
            lines.append(line)
            
    return '\n'.join(lines).strip()


def normalize_config(text: str, router_type: str = 'mikrotik') -> str:
    """
    Función unificada de normalización según el fabricante/sistema del router.
    """
    if not text:
        return ""
    
    r_type = (router_type or '').lower()
    if 'mikrotik' in r_type:
        return normalize_routeros_config(text)
    elif 'cisco' in r_type:
        return normalize_cisco_config(text)
    elif 'openwrt' in r_type:
        return normalize_openwrt_config(text)
    else:
        # Normalización estándar para airOS u otros
        return '\n'.join(line.rstrip() for line in text.replace('\r\n', '\n').split('\n') if line.strip()).strip()
