import json
import datetime
import re
from django.utils import timezone
from router_manager.models import RouterInformation, Router
from routerlib.functions import (
    connect_to_ssh,
    execute_cisco_commands,
    execute_huawei_commands,
    execute_zte_commands,
    execute_fortinet_commands,
    execute_mikrotik_telnet_commands,
)


def _parse_routeros_key_value_output(output: str) -> dict:
    """
    Parse lines like "key:    value" into a dict.
    Skip blank lines or lines starting with '[' (the prompt).
    """
    data = {}
    for raw_line in output.replace('\r', '').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('['):
            continue
        if ':' not in line:
            continue
        key, val = line.split(':', 1)
        data[key.strip()] = val.strip()
    return data


def _parse_cisco_information(raw_version: str, raw_inventory: str = '', field_max_length: int = 100) -> dict:
    """
    Extrae Modelo, Versión de Modelo, Número de Serie, Versión de OS, Firmware,
    Arquitectura y CPU desde la salida de 'show version' y 'show inventory' de Cisco IOS.
    Soporta Catalyst, ME3400, ISR, ASR, CSR1000v, IOSv e IOS-XE.
    """
    info = {
        'model_name': '',
        'model_version': '',
        'serial_number': '',
        'os_version': '',
        'firmware_version': '',
        'architecture': '',
        'cpu': '',
    }

    ver_match = re.search(r'Version\s+([^\s,]+)', raw_version, re.IGNORECASE)
    if ver_match:
        info['os_version'] = ver_match.group(1).strip()[:field_max_length]

    model_num_match = re.search(r'Model\s+number\s*:\s*(\S+)', raw_version, re.IGNORECASE)
    proc_line_match = re.search(
        r'^[Cc]isco\s+(\S+)\s+(?:\(([^\)]+)\)\s+)?(?:processor\s+)?(?:\(revision\s+([^\)]+)\))?',
        raw_version,
        re.MULTILINE
    )
    inv_pid_match = re.search(r'PID:\s*(\S+)', raw_inventory) if raw_inventory else None

    if model_num_match:
        info['model_name'] = model_num_match.group(1).strip()[:field_max_length]
    elif proc_line_match:
        info['model_name'] = proc_line_match.group(1).strip()[:field_max_length]
    elif inv_pid_match:
        info['model_name'] = inv_pid_match.group(1).strip().rstrip(',')[:field_max_length]

    rev_num_match = re.search(r'Model\s+revision\s+number\s*:\s*(\S+)', raw_version, re.IGNORECASE)
    rev_inline_match = re.search(r'\(revision\s+([^\)]+)\)', raw_version, re.IGNORECASE)
    if rev_num_match:
        info['model_version'] = rev_num_match.group(1).strip()[:field_max_length]
    elif rev_inline_match:
        info['model_version'] = rev_inline_match.group(1).strip()[:field_max_length]

    sys_sn_match = re.search(r'System\s+serial\s+number\s*:\s*(\S+)', raw_version, re.IGNORECASE)
    proc_board_match = re.search(r'Processor\s+board\s+ID\s+(\S+)', raw_version, re.IGNORECASE)
    inv_sn_match = re.search(r'SN:\s*(\S+)', raw_inventory) if raw_inventory else None

    if sys_sn_match:
        info['serial_number'] = sys_sn_match.group(1).strip()[:field_max_length]
    elif proc_board_match:
        info['serial_number'] = proc_board_match.group(1).strip()[:field_max_length]
    elif inv_sn_match:
        info['serial_number'] = inv_sn_match.group(1).strip()[:field_max_length]

    arch_match = re.search(r'^[Cc]isco\s+\S+\s+\(([^\)]+)\)\s+processor', raw_version, re.MULTILINE)
    if arch_match:
        arch = arch_match.group(1).strip()
        info['architecture'] = arch[:field_max_length]
        info['cpu'] = arch[:field_max_length]
    else:
        cpu_match = re.search(r'CPU\s+at\s+\S+', raw_version, re.IGNORECASE)
        if cpu_match:
            info['cpu'] = cpu_match.group(0).strip()[:field_max_length]

    sw_img_match = re.search(r'Cisco\s+IOS\s+Software,\s+[^,]+?\(([^\)]+)\)', raw_version, re.IGNORECASE)
    sys_img_match = re.search(r'System\s+image\s+file\s+is\s+"([^"]+)"', raw_version, re.IGNORECASE)
    if sw_img_match:
        info['firmware_version'] = sw_img_match.group(1).strip()[:field_max_length]
    elif sys_img_match:
        info['firmware_version'] = sys_img_match.group(1).strip()[:field_max_length]

    return info


def _parse_huawei_information(raw_version: str, raw_esn: str = '', raw_device: str = '', field_max_length: int = 100) -> dict:
    """
    Extrae Modelo, Serie (ESN), Versión VRP, Firmware y Arquitectura desde
    'display version', 'display esn' y 'display device' en equipos Huawei VRP.
    """
    info = {
        'model_name': '',
        'model_version': '',
        'serial_number': '',
        'os_version': '',
        'firmware_version': '',
        'architecture': 'VRP',
        'cpu': '',
    }

    # 1. OS Version: "VRP (R) software, Version 5.170 (S5720 V200R011C10SPC600)"
    vrp_ver = re.search(r'VRP\s*\(R\)\s*[Ss]oftware,\s*Version\s+([^\r\n,]+)', raw_version, re.IGNORECASE)
    generic_ver = re.search(r'Version\s+([\d\.]+(?:\s*\([^\)]+\))?)', raw_version, re.IGNORECASE)
    if vrp_ver:
        info['os_version'] = vrp_ver.group(1).strip()[:field_max_length]
    elif generic_ver:
        info['os_version'] = generic_ver.group(1).strip()[:field_max_length]

    # 2. Firmware Release (ej. V200R011C10SPC600 o V800R011C00SPC607B607)
    fw_match = re.search(r'\b(V\d{3}R\d{3}[A-Za-z0-9]+)\b', raw_version)
    if fw_match:
        info['firmware_version'] = fw_match.group(1).strip()[:field_max_length]

    # 3. Model Name: "HUAWEI S5720-28X-LI-AC Routing Switch uptime is..." o "Quidway S5700-28C-HI..."
    model_match = re.search(
        r'^\s*(?:HUAWEI|Quidway)\s+(?!Versatile)([A-Za-z0-9\-\_\/]+).*?\buptime\s+is\b',
        raw_version,
        re.MULTILINE | re.IGNORECASE
    )
    if not model_match:
        model_match = re.search(
            r'^\s*(?:HUAWEI|Quidway)\s+(?!Versatile)([A-Za-z0-9\-\_\/]+)',
            raw_version,
            re.MULTILINE | re.IGNORECASE
        )
    if model_match:
        info['model_name'] = model_match.group(1).strip()[:field_max_length]

    # 4. Serial Number (ESN)
    esn_match = re.search(r'(?:ESN[^:]*:|BarCode=)\s*([A-Za-z0-9\-]{8,})', raw_esn or raw_version, re.IGNORECASE)
    if esn_match:
        info['serial_number'] = esn_match.group(1).strip()[:field_max_length]

    pcb_match = re.search(r'Pcb\s+Version\s*:\s*([^\r\n]+)', raw_version, re.IGNORECASE)
    if pcb_match:
        info['model_version'] = pcb_match.group(1).strip()[:field_max_length]

    # 5. CPU / Board processor
    cpu_match = re.search(r'([A-Za-z0-9\-\_]+\s+processor)', raw_version, re.IGNORECASE)
    if cpu_match:
        info['cpu'] = cpu_match.group(1).strip()[:field_max_length]
        info['architecture'] = cpu_match.group(1).strip()[:field_max_length]

    return info


def _parse_zte_information(raw_version: str, raw_card: str = '', field_max_length: int = 100) -> dict:
    """
    Extrae Modelo, Serie, Versión de Software y Arquitectura desde 'show version' y 'show card'
    en equipos ZTE (switches/routers ZXR10 y OLTs ZXA10 C300/C320/C600).
    """
    info = {
        'model_name': '',
        'model_version': '',
        'serial_number': '',
        'os_version': '',
        'firmware_version': '',
        'architecture': 'ZXROS',
        'cpu': '',
    }

    # 1. Model Name: "ZXR10 5950-36TM-H", "ZXA10 C320", "ZXR10 8900E", etc.
    model_match = re.search(r'\b(ZX[RA]10\s+[A-Za-z0-9\-\_]+|C300|C320|C600|C620|C650)\b', raw_version, re.IGNORECASE)
    if model_match:
        info['model_name'] = model_match.group(1).strip()[:field_max_length]

    # 2. OS Version: "Version: V3.00.11..." o "Software, Version V2.1.0"
    ver_match = re.search(r'Version\s*:?\s*(V?[\d\.]+[A-Za-z0-9\.\-\(\)]*)', raw_version, re.IGNORECASE)
    if ver_match:
        info['os_version'] = ver_match.group(1).strip().rstrip(',')[:field_max_length]

    # 3. Firmware / Bootrom
    boot_match = re.search(r'Bootrom\s+Version\s*:?\s*([^\r\n,]+)', raw_version, re.IGNORECASE)
    if boot_match:
        info['firmware_version'] = boot_match.group(1).strip()[:field_max_length]

    # 4. Serial Number
    sn_match = re.search(r'(?:Serial\s+Number|System\s+serial\s+number|SN)\s*:?\s*([A-Za-z0-9\-]{5,})', raw_version + '\n' + raw_card, re.IGNORECASE)
    if sn_match:
        info['serial_number'] = sn_match.group(1).strip()[:field_max_length]

    # 5. CPU / Architecture
    cpu_match = re.search(r'([^\r\n,]+)\s+processor', raw_version, re.IGNORECASE)
    if cpu_match:
        info['cpu'] = cpu_match.group(1).strip()[:field_max_length]
        info['architecture'] = cpu_match.group(1).strip()[:field_max_length]

    return info


def get_router_information(router_information: RouterInformation):
    """
    Connect to the router, retrieve info, and store it in RouterInformation.
    Soporta SSH y Telnet para MikroTik, Cisco IOS, Huawei VRP y ZTE, además de API MikroTik.
    """
    router = router_information.router
    field_max_length = 100
    success = False
    error_message = ''
    protocol = (getattr(router, 'connection_protocol', 'ssh') or 'ssh').lower()

    # 1. Intento por API MikroTik (Ultrarrápido: ~50ms)
    if router.router_type in ('mikrotik', 'mikrotik-branded'):
        try:
            from routerlib.mikrotik_api import fetch_mikrotik_telemetry
            api_port = int(router.port) if (protocol == 'api' and router.port) else 8728
            telemetry = fetch_mikrotik_telemetry(router.address, api_port, router.username, router.password, timeout=3.0)
            if telemetry.get('success'):
                router_information.model_name = telemetry.get('board_name', '')[:field_max_length]
                router_information.os_version = telemetry.get('version', '')[:field_max_length]
                router_information.architecture = telemetry.get('architecture', '')[:field_max_length]
                router_information.cpu = telemetry.get('cpu', '')[:field_max_length]
                router_information.model_version = telemetry.get('model', '')[:field_max_length]
                router_information.serial_number = telemetry.get('serial_number', '')[:field_max_length]
                router_information.firmware_version = telemetry.get('current_firmware', '')[:field_max_length]
                router_information.success = True
                router_information.error = False
                router_information.retry_count = 0
                router_information.next_retry = None
                router_information.error_message = ''
                router_information.last_retrieval = timezone.now()
                router_information.json_data = json.dumps(telemetry)
                router_information.save()
                return True, ''
        except Exception:
            pass  # Falla silenciosamente a SSH/Telnet si el puerto API está cerrado

    # 2. Equipos Cisco IOS (SSH interactivo o Telnet con soporte enable)
    if router.router_type == 'cisco-ios':
        try:
            outputs = execute_cisco_commands(
                router.address,
                router.port,
                router.username,
                router.password,
                ['show version', 'show inventory'],
                protocol=protocol,
                sshkey=router.ssh_key,
                enable_password=router.enable_password,
                timeout=25
            )
            raw_version = outputs.get('show version', '')
            raw_inventory = outputs.get('show inventory', '')

            if not raw_version or not any(k in raw_version.lower() for k in ['cisco', 'version', 'ios']):
                return False, 'No se pudo obtener la salida de show version del equipo Cisco'

            parsed_info = _parse_cisco_information(raw_version, raw_inventory, field_max_length)
            router_information.model_name = parsed_info['model_name']
            router_information.model_version = parsed_info['model_version']
            router_information.serial_number = parsed_info['serial_number']
            router_information.os_version = parsed_info['os_version']
            router_information.firmware_version = parsed_info['firmware_version']
            router_information.architecture = parsed_info['architecture']
            router_information.cpu = parsed_info['cpu']

            router_information.success = True
            router_information.error = False
            router_information.retry_count = 0
            router_information.next_retry = None
            router_information.error_message = ''
            router_information.last_retrieval = timezone.now()
            router_information.json_data = json.dumps({
                'show version': raw_version,
                'show inventory': raw_inventory,
            })
            router_information.save()
            return True, ''
        except Exception as e:
            return False, str(e)

    # 3. Equipos Huawei VRP (SSH o Telnet)
    if router.router_type == 'huawei':
        try:
            outputs = execute_huawei_commands(
                router.address,
                router.port,
                router.username,
                router.password,
                ['display version', 'display esn', 'display elabel', 'display device'],
                protocol=protocol,
                sshkey=router.ssh_key,
                enable_password=router.enable_password,
                timeout=25
            )
            raw_version = outputs.get('display version', '')
            raw_esn = outputs.get('display esn', '') + '\n' + outputs.get('display elabel', '')
            raw_device = outputs.get('display device', '')

            if not raw_version or not any(k in raw_version.lower() for k in ['huawei', 'vrp', 'version', 'quidway']):
                return False, 'No se pudo obtener la salida de display version del equipo Huawei'

            parsed_info = _parse_huawei_information(raw_version, raw_esn, raw_device, field_max_length)
            router_information.model_name = parsed_info['model_name']
            router_information.model_version = parsed_info['model_version']
            router_information.serial_number = parsed_info['serial_number']
            router_information.os_version = parsed_info['os_version']
            router_information.firmware_version = parsed_info['firmware_version']
            router_information.architecture = parsed_info['architecture']
            router_information.cpu = parsed_info['cpu']

            router_information.success = True
            router_information.error = False
            router_information.retry_count = 0
            router_information.next_retry = None
            router_information.error_message = ''
            router_information.last_retrieval = timezone.now()
            router_information.json_data = json.dumps({
                'display version': raw_version,
                'display esn': raw_esn,
                'display device': raw_device,
            })
            router_information.save()
            return True, ''
        except Exception as e:
            return False, str(e)

    # 4. Equipos ZTE ZXR10 / ZXA10 (SSH o Telnet)
    if router.router_type == 'zte':
        try:
            outputs = execute_zte_commands(
                router.address,
                router.port,
                router.username,
                router.password,
                ['show version', 'show card'],
                protocol=protocol,
                sshkey=router.ssh_key,
                enable_password=router.enable_password,
                timeout=25
            )
            raw_version = outputs.get('show version', '')
            raw_card = outputs.get('show card', '')

            if not raw_version or not any(k in raw_version.lower() for k in ['zte', 'zxr10', 'zxa10', 'zxan', 'version']):
                return False, 'No se pudo obtener la salida de show version del equipo ZTE'

            parsed_info = _parse_zte_information(raw_version, raw_card, field_max_length)
            router_information.model_name = parsed_info['model_name']
            router_information.model_version = parsed_info['model_version']
            router_information.serial_number = parsed_info['serial_number']
            router_information.os_version = parsed_info['os_version']
            router_information.firmware_version = parsed_info['firmware_version']
            router_information.architecture = parsed_info['architecture']
            router_information.cpu = parsed_info['cpu']

            router_information.success = True
            router_information.error = False
            router_information.retry_count = 0
            router_information.next_retry = None
            router_information.error_message = ''
            router_information.last_retrieval = timezone.now()
            router_information.json_data = json.dumps({
                'show version': raw_version,
                'show card': raw_card,
            })
            router_information.save()
            return True, ''
        except Exception as e:
            return False, str(e)

    # 4b. Equipos Fortinet FortiGate / FortiOS (SSH, Telnet o API)
    if router.router_type == 'fortinet':
        try:
            outputs = execute_fortinet_commands(
                router.address,
                router.port,
                router.username,
                router.password,
                ['get system status', 'get system performance status'],
                protocol=protocol,
                sshkey=router.ssh_key,
                enable_password=router.enable_password,
                timeout=25
            )
            raw_status = outputs.get('get system status', '')
            raw_perf = outputs.get('get system performance status', '')

            if not raw_status or not any(k in raw_status.lower() for k in ['fortigate', 'fortios', 'fortinet', 'serial-number', 'version']):
                return False, 'No se pudo obtener get system status del equipo Fortinet'

            parsed_info = _parse_fortinet_information(raw_status, raw_perf, field_max_length)
            router_information.model_name = parsed_info['model_name']
            router_information.model_version = parsed_info['model_version']
            router_information.serial_number = parsed_info['serial_number']
            router_information.os_version = parsed_info['os_version']
            router_information.firmware_version = parsed_info['firmware_version']
            router_information.architecture = parsed_info['architecture']
            router_information.cpu = parsed_info['cpu']

            router_information.success = True
            router_information.error = False
            router_information.retry_count = 0
            router_information.next_retry = None
            router_information.error_message = ''
            router_information.last_retrieval = timezone.now()
            router_information.json_data = json.dumps({
                'get system status': raw_status,
                'get system performance status': raw_perf,
            })
            router_information.save()
            return True, ''
        except Exception as e:
            return False, str(e)

    # 5. MikroTik por Telnet
    if router.router_type in ('mikrotik', 'mikrotik-branded') and protocol == 'telnet':
        try:
            cmds = ['/system resource print without-paging', '/system routerboard print without-paging']
            outputs = execute_mikrotik_telnet_commands(
                router.address, router.port, router.username, router.password, cmds, timeout=20
            )
            sr = _parse_routeros_key_value_output(outputs.get(cmds[0], ''))
            rb = _parse_routeros_key_value_output(outputs.get(cmds[1], ''))
            if sr:
                router_information.model_name = sr.get('board-name', '')[:field_max_length]
                router_information.os_version = sr.get('version', '')[:field_max_length]
                router_information.architecture = sr.get('architecture-name', '')[:field_max_length]
                router_information.cpu = sr.get('cpu', '')[:field_max_length]
                success = True
            if rb:
                router_information.model_version = rb.get('model', '')[:field_max_length]
                router_information.serial_number = rb.get('serial-number', '')[:field_max_length]
                router_information.firmware_version = rb.get('current-firmware', '')[:field_max_length]
                success = True
            if not success:
                return False, 'Failed to retrieve MikroTik information via Telnet'

            router_information.success = True
            router_information.error = False
            router_information.retry_count = 0
            router_information.next_retry = None
            router_information.error_message = ''
            router_information.last_retrieval = timezone.now()
            router_information.json_data = json.dumps({'resource': sr, 'routerboard': rb})
            router_information.save()
            return True, ''
        except Exception as e:
            return False, str(e)

    # 6. Conexión estándar por SSH (MikroTik, OpenWrt, Ubiquiti airOS)
    ssh = None
    try:
        ssh = connect_to_ssh(router.address, router.port, router.username, router.password, router.ssh_key)
        json_data = {}

        if router.router_type in ('mikrotik', 'mikrotik-branded'):
            for cmd in ['/system resource print', '/system routerboard print']:
                stdin, stdout, stderr = ssh.exec_command(cmd, timeout=20)
                raw = stdout.read().decode('utf-8', errors='ignore')
                parsed = _parse_routeros_key_value_output(raw)
                json_data[cmd] = parsed

            rb = json_data['/system routerboard print']
            sr = json_data['/system resource print']

            if sr:
                router_information.model_name = sr.get('board-name', '')[:field_max_length]
                router_information.os_version = sr.get('version', '')[:field_max_length]
                router_information.architecture = sr.get('architecture-name', '')[:field_max_length]
                router_information.cpu = sr.get('cpu', '')[:field_max_length]
                success = True
            if rb:
                router_information.model_version = rb.get('model', '')[:field_max_length]
                router_information.serial_number = rb.get('serial-number', '')[:field_max_length]
                router_information.firmware_version = rb.get('current-firmware', '')[:field_max_length]
                success = True
            if not success:
                return False, 'Failed to retrieve router information'

        elif router.router_type == 'openwrt':
            stdin, stdout, stderr = ssh.exec_command('cat /etc/os-release')
            osrel = {}
            for line in stdout.read().decode('utf-8').splitlines():
                if '=' in line:
                    k, v = line.split('=', 1)
                    osrel[k] = v.strip().strip('"')
            json_data['cat /etc/os-release'] = osrel

            stdin, stdout, stderr = ssh.exec_command('uci get system.@system[0].hostname')
            hostname = stdout.read().decode('utf-8').strip()
            json_data['uci get system.@system[0].hostname'] = hostname

            stdin, stdout, stderr = ssh.exec_command('uname -m')
            arch = stdout.read().decode('utf-8').strip()
            json_data['uname -m'] = arch

            stdin, stdout, stderr = ssh.exec_command('cat /sys/class/net/eth0/address')
            mac = stdout.read().decode('utf-8').strip()
            json_data['cat /sys/class/net/eth0/address'] = mac

            if osrel:
                router_information.model_name = osrel.get('OPENWRT_DEVICE_MODEL', '')[:field_max_length]
                router_information.model_version = osrel.get('VERSION_ID', '')[:field_max_length]
                router_information.serial_number = mac[:field_max_length]
                router_information.os_version = osrel.get('VERSION', '')[:field_max_length]
                router_information.firmware_version = osrel.get('OPENWRT_RELEASE', '')[:field_max_length]
                router_information.architecture = arch[:field_max_length]
                success = True
            if not success:
                return False, 'Failed to retrieve router information'

        elif router.router_type == 'ubiquiti-airos':
            stdin, stdout, stderr = ssh.exec_command('cat /etc/version')
            version_raw = stdout.read().decode('utf-8', errors='ignore').strip()
            json_data['cat /etc/version'] = version_raw
            stdin, stdout, stderr = ssh.exec_command('cat /etc/board.info')
            board_raw = stdout.read().decode('utf-8', errors='ignore')
            json_data['cat /etc/board.info'] = board_raw
            board = {}
            for line in board_raw.splitlines():
                line = line.strip()
                if not line or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                board[k.strip()] = v.strip()
            if not board:
                return False, 'Failed to retrieve router information from /etc/board.info'

            stdin, stdout, stderr = ssh.exec_command('uname -r')
            kernel_version = stdout.read().decode('utf-8', errors='ignore').strip()
            json_data['uname -r'] = kernel_version

            stdin, stdout, stderr = ssh.exec_command('cat /proc/cpuinfo')
            cpuinfo_raw = stdout.read().decode('utf-8', errors='ignore')
            json_data['cat /proc/cpuinfo'] = cpuinfo_raw
            cpuinfo = {}

            for line in cpuinfo_raw.splitlines():
                if ':' not in line:
                    continue
                k, v = line.split(':', 1)
                cpuinfo[k.strip().lower()] = v.strip()

            router_information.model_name = board.get('board.name', '')[:field_max_length]
            router_information.model_version = (
                board.get('board.model', '') or board.get('board.shortname', '')
            )[:field_max_length]
            router_information.serial_number = (
                board.get('board.device_id', '') or board.get('board.hwaddr', '')
            )[:field_max_length]
            router_information.firmware_version = version_raw[:field_max_length]
            router_information.os_version = kernel_version[:field_max_length]
            cpu_model = cpuinfo.get('cpu model', '')
            router_information.architecture = (
                cpu_model.split()[0] if cpu_model else ''
            )[:field_max_length]
            router_information.cpu = (
                cpuinfo.get('system type', '')
                or cpu_model
                or board.get('board.cpurevision', '')
            )[:field_max_length]
            success = True
        else:
            return False, f"Router type not supported: {router.get_router_type_display()}"

        if success:
            router_information.success = True
            router_information.error = False
            router_information.retry_count = 0
            router_information.next_retry = None
            router_information.error_message = ''
            router_information.last_retrieval = timezone.now()
            router_information.json_data = json.dumps(json_data)
            router_information.save()

    except Exception as e:
        success = False
        error_message = str(e)

    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass

    return success, error_message




def _parse_fortinet_information(raw_status: str, raw_perf: str = '', field_max_length: int = 100) -> dict:
    """Extrae modelo, versión FortiOS, número de serie y CPU desde 'get system status' y 'get system performance status'."""
    info = {
        'model_name': 'Fortinet FortiGate',
        'model_version': '',
        'serial_number': '',
        'os_version': '',
        'firmware_version': '',
        'architecture': 'FortiASIC / x86_64',
        'cpu': '',
    }
    # Ej: Version: FortiGate-100F v7.2.8,build1639,240514 (GA.M)
    m_ver = re.search(r'Version:\s*([\w\-]+)\s+(v[\d\.]+[^\r\n]*)', raw_status, re.IGNORECASE)
    if m_ver:
        info['model_name'] = m_ver.group(1).strip()[:field_max_length]
        info['os_version'] = m_ver.group(2).strip()[:field_max_length]
        info['firmware_version'] = m_ver.group(2).strip()[:field_max_length]

    m_sn = re.search(r'Serial-Number:\s*([A-Za-z0-9\-]+)', raw_status, re.IGNORECASE)
    if m_sn:
        info['serial_number'] = m_sn.group(1).strip()[:field_max_length]

    m_bios = re.search(r'BIOS version:\s*([\w\.\-]+)', raw_status, re.IGNORECASE)
    if m_bios:
        info['model_version'] = f"BIOS {m_bios.group(1).strip()}"[:field_max_length]

    m_cpu = re.search(r'CPU states:\s*([^\r\n]+)', raw_perf or '', re.IGNORECASE)
    if m_cpu:
        info['cpu'] = m_cpu.group(1).strip()[:field_max_length]

    return info


def update_router_information(router_information: RouterInformation):
    max_retry = 3
    retry_minutes = 5

    success = False
    error_message = ''

    if router_information.retry_count > max_retry:
        router_information.error = True
        router_information.success = False
        router_information.next_retry = None
        router_information.retry_count = 0
        router_information.last_retrieval = timezone.now()
        if router_information.error_message:
            router_information.error_message += f"\nMax retries reached for {router_information.router.name}"
        else:
            router_information.error_message = f"Max retries reached for {router_information.router.name}"
        router_information.save()
        return False, router_information.error_message
    try:
        success, error_message = get_router_information(router_information)
    except Exception as e:
        success = False
        error_message = f"Failed to update router information for {router_information.router.name}. Exception: {e}"

    if not success:
        router_information.error = True
        router_information.success = False
        router_information.next_retry = timezone.now() + datetime.timedelta(minutes=retry_minutes)
        router_information.retry_count += 1
        router_information.last_retrieval = timezone.now()
        if error_message:
            router_information.error_message = error_message
        else:
            router_information.error_message = f"Failed to update router information for {router_information.router.name}"
        router_information.save()

    return success, error_message
