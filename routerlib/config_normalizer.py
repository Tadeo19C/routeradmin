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

        if stripped.startswith('#'):
            lower = stripped.lower()
            if any(marker in lower for marker in [
                'by routeros', 'software id', 'serial number', 'model =',
                'jan/', 'feb/', 'mar/', 'apr/', 'may/', 'jun/',
                'jul/', 'aug/', 'sep/', 'oct/', 'nov/', 'dec/'
            ]):
                continue
            if stripped == '#':
                continue

        if stripped:
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


def normalize_huawei_config(text: str) -> str:
    """
    Normaliza configuraciones de Huawei VRP (display current-configuration).
    Elimina marcas de tiempo volátiles (!Last configuration was updated/saved at...).
    """
    if not text:
        return ""

    lines = []
    for raw_line in text.replace('\r\n', '\n').split('\n'):
        line = raw_line.rstrip()
        stripped = line.strip()

        if any(stripped.lower().startswith(prefix) for prefix in [
            '!software version',
            '!last configuration was updated at',
            '!last configuration was saved at',
            '!time:',
            'current configuration :',
        ]):
            continue

        if stripped == '#':
            continue

        if stripped:
            lines.append(line)

    return '\n'.join(lines).strip()


def normalize_zte_config(text: str) -> str:
    """
    Normaliza configuraciones de ZTE ZXR10 / ZXA10 (show running-config).
    Elimina cabeceras de construcción y marcas de tiempo volátiles.
    """
    if not text:
        return ""

    lines = []
    for raw_line in text.replace('\r\n', '\n').split('\n'):
        line = raw_line.rstrip()
        stripped = line.strip()

        if any(stripped.lower().startswith(prefix) for prefix in [
            'building configuration',
            'current configuration',
            '! last configuration',
            '!<last',
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
    elif 'huawei' in r_type:
        return normalize_huawei_config(text)
    elif 'zte' in r_type:
        return normalize_zte_config(text)
    elif 'openwrt' in r_type:
        return normalize_openwrt_config(text)
    else:
        return '\n'.join(line.rstrip() for line in text.replace('\r\n', '\n').split('\n') if line.strip()).strip()
