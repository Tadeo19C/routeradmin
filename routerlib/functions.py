from io import StringIO
import time
import re
import paramiko
import telnetlib
from routerlib.crypto import decrypt_credential


def get_router_features(router_type):
    if router_type in ['openwrt', 'mikrotik', 'mikrotik-branded', 'ubiquiti-airos', 'cisco-ios', 'cisco-xe', 'huawei', 'zte', 'fortinet']:
        return ['backup', 'reverse_monitoring', 'ssh', 'telnet', 'ssh_key']
    else:
        return []


def get_router_backup_file_extension(router_type):
    if router_type == 'mikrotik' or router_type == 'mikrotik-branded':
        return {'text': 'rsc', 'binary': 'backup'}
    elif router_type == 'openwrt':
        return {'text': 'txt', 'binary': 'tar.gz'}
    elif router_type == 'fortinet':
        return {'text': 'conf', 'binary': None}
    elif router_type in ('ubiquiti-airos', 'cisco-ios', 'huawei', 'zte'):
        return {'text': 'cfg', 'binary': None}
    else:
        return {'text': 'txt', 'binary': None}


def gen_backup_name(router_backup):
    router_name = getattr(router_backup.router, 'name', '') or 'router'
    safe_name = re.sub(r'[^A-Za-z0-9_-]+', '_', router_name.strip()).strip('_') or 'router'
    return f'tdox-config-{safe_name}-{router_backup.id}-{router_backup.created.strftime("%Y-%m-%d_%H-%M")}'


def load_private_key_from_string(key_str):
    if not key_str:
        return None
    decrypted_str = decrypt_credential(key_str)
    key_types = [
        paramiko.RSAKey,
        paramiko.ECDSAKey,
        paramiko.Ed25519Key,
    ]
    for key_type in key_types:
        try:
            key_file_obj = StringIO(decrypted_str)
            return key_type.from_private_key(key_file_obj)
        except paramiko.ssh_exception.SSHException:
            continue
    return None


def connect_to_ssh(address, port, username, password, sshkey=None, max_retries=3, retry_delay=2):
    """
    Establece conexión SSH con reintentos exponenciales, timeouts controlados
    y soporte para algoritmos clásicos de equipos Cisco IOS / Huawei VRP / ZTE / MikroTik.
    Descifra automáticamente contraseñas y llaves si vienen cifradas en reposo.
    """
    decrypted_password = decrypt_credential(password)
    port_num = int(port) if port else 22

    last_exception = None
    for attempt in range(max_retries):
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            connect_kwargs = {
                'hostname': address,
                'port': port_num,
                'username': username,
                'look_for_keys': False,
                'timeout': 15,
                'banner_timeout': 20,
                'auth_timeout': 20,
                'allow_agent': False,
                'disabled_algorithms': {},
            }
            if sshkey:
                priv_key_str = getattr(sshkey, 'private_key', str(sshkey))
                private_key = load_private_key_from_string(priv_key_str)
                connect_kwargs['pkey'] = private_key
            else:
                connect_kwargs['password'] = decrypted_password

            ssh_client.connect(**connect_kwargs)
            return ssh_client
        except (paramiko.ssh_exception.AuthenticationException, paramiko.ssh_exception.BadHostKeyException) as e:
            ssh_client.close()
            raise e
        except Exception as e:
            ssh_client.close()
            last_exception = e
            if attempt < max_retries - 1:
                time.sleep(retry_delay * (attempt + 1))

    if last_exception:
        raise last_exception


def _read_channel_until_prompt(chan, timeout=20, idle_wait=0.4):
    """Lee de un canal interactivo Paramiko hasta encontrar prompt de router (#, >, ] o : )."""
    buf = ""
    start = time.time()
    last_recv = time.time()
    while time.time() - start < timeout:
        if chan.recv_ready():
            chunk = chan.recv(65535).decode('utf-8', errors='ignore')
            buf += chunk
            last_recv = time.time()
        else:
            stripped = buf.rstrip()
            if stripped and (
                stripped.endswith('#')
                or stripped.endswith('>')
                or stripped.endswith(']')
                or stripped.endswith(':')
                or 'Password:' in stripped
                or '[Y/N]:' in stripped
            ):
                if time.time() - last_recv >= idle_wait:
                    break
            time.sleep(0.1)
    return buf


def _clean_interactive_output(raw_output: str, command: str) -> str:
    """Limpia el eco del comando inicial y el prompt final de una salida interactiva (Cisco, Huawei, ZTE)."""
    lines = raw_output.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    if lines and command.strip().lower() in lines[0].strip().lower():
        lines = lines[1:]
    while lines and not lines[-1].strip():
        lines.pop()
    # Prompts típicos: SwGRD-CSCO#, Router>, <HUAWEI>, [HUAWEI], [~HUAWEI], ZXR10#, ZXAN#
    if lines and (
        re.match(r'^[\w\-\.\(\)]+[#>]\s*$', lines[-1].strip())
        or re.match(r'^[<\[][\~\*\w\-\.\(\)\/]+[>\]]\s*$', lines[-1].strip())
    ):
        lines.pop()
    return '\n'.join(lines).strip()


def execute_cisco_commands(address, port, username, password, commands, protocol='ssh', sshkey=None, enable_password=None, timeout=30):
    """
    Ejecuta uno o varios comandos en equipos Cisco IOS tanto por SSH (invoke_shell)
    como por Telnet, gestionando automáticamente el paso a modo privilegiado (enable)
    y desactivando la paginación (terminal length 0).
    """
    decrypted_password = decrypt_credential(password)
    enable_pwd = decrypt_credential(enable_password) if enable_password else decrypted_password
    port_num = int(port) if port else (23 if protocol == 'telnet' else 22)
    outputs = {}

    if protocol == 'telnet':
        tn = None
        try:
            tn = telnetlib.Telnet(address, port_num, timeout=15)
            idx, match, initial_data = tn.expect([b'[Uu]sername:\\s*', b'[Ll]ogin:\\s*', b'[Pp]assword:\\s*', b'[#>\\]]\\s*$'], timeout=12)
            if idx in (0, 1):
                tn.write(username.encode('ascii', errors='ignore') + b"\n")
                idx2, _, _ = tn.expect([b'[Pp]assword:\\s*', b'[#>\\]]\\s*$'], timeout=10)
                if idx2 == 0:
                    tn.write(decrypted_password.encode('ascii', errors='ignore') + b"\n")
            elif idx == 2:
                tn.write(decrypted_password.encode('ascii', errors='ignore') + b"\n")

            _, _, prompt_bytes = tn.expect([b'[#>\\]]\\s*$'], timeout=10)
            prompt_text = prompt_bytes.decode('utf-8', errors='ignore').strip()
            if any(err in prompt_text.lower() for err in ['login invalid', 'authentication failed', 'bad secrets', 'login failed']):
                raise Exception("Credenciales Telnet rechazadas por el equipo Cisco")

            if prompt_text.endswith('>'):
                tn.write(b"enable\n")
                idx_en, _, _ = tn.expect([b'[Pp]assword:\\s*', b'#\\s*$'], timeout=8)
                if idx_en == 0:
                    tn.write(enable_pwd.encode('ascii', errors='ignore') + b"\n")
                    tn.expect([b'#\\s*$', b'>\\s*$'], timeout=8)

            tn.write(b"terminal length 0\n")
            tn.expect([b'[#>]\\s*$'], timeout=8)

            for cmd in commands:
                tn.write(cmd.encode('ascii', errors='ignore') + b"\n")
                _, _, cmd_out = tn.expect([b'\n[\\w\\-\\.\\(\\)]+[#>]\\s*$'], timeout=timeout)
                raw_text = cmd_out.decode('utf-8', errors='ignore')
                outputs[cmd] = _clean_interactive_output(raw_text, cmd)

            tn.write(b"exit\n")
            return outputs
        finally:
            if tn:
                try:
                    tn.close()
                except Exception:
                    pass
    else:
        ssh_client = None
        try:
            ssh_client = connect_to_ssh(address, port_num, username, password, sshkey)
            chan = ssh_client.invoke_shell(width=200, height=1000)
            chan.settimeout(timeout)

            initial_banner = _read_channel_until_prompt(chan, timeout=10, idle_wait=0.4)

            if initial_banner.rstrip().endswith('>'):
                chan.send('enable\n')
                en_prompt = _read_channel_until_prompt(chan, timeout=8, idle_wait=0.3)
                if 'password' in en_prompt.lower():
                    chan.send(enable_pwd + '\n')
                    _read_channel_until_prompt(chan, timeout=8, idle_wait=0.3)

            chan.send('terminal length 0\n')
            _read_channel_until_prompt(chan, timeout=8, idle_wait=0.3)

            for cmd in commands:
                while chan.recv_ready():
                    chan.recv(65535)
                chan.send(cmd + '\n')
                raw_out = _read_channel_until_prompt(chan, timeout=timeout, idle_wait=0.6)
                outputs[cmd] = _clean_interactive_output(raw_out, cmd)

            try:
                chan.send('exit\n')
            except Exception:
                pass
            return outputs
        finally:
            if ssh_client:
                try:
                    ssh_client.close()
                except Exception:
                    pass


def execute_huawei_commands(address, port, username, password, commands, protocol='ssh', sshkey=None, enable_password=None, timeout=35):
    """
    Ejecuta comandos en equipos Huawei VRP (routers NE, switches S-series, OLTs SmartAX)
    tanto por SSH como por Telnet.
    Maneja el aviso de cambio de contraseña inicial [Y/N], eleva con 'super' si aplica,
    y desactiva la paginación con 'screen-length 0 temporary'.
    """
    decrypted_password = decrypt_credential(password)
    super_pwd = decrypt_credential(enable_password) if enable_password else decrypted_password
    port_num = int(port) if port else (23 if protocol == 'telnet' else 22)
    outputs = {}

    if protocol == 'telnet':
        tn = None
        try:
            tn = telnetlib.Telnet(address, port_num, timeout=15)
            idx, _, _ = tn.expect([b'[Uu]sername:\\s*', b'[Ll]ogin:\\s*', b'[Pp]assword:\\s*'], timeout=12)
            if idx in (0, 1):
                tn.write(username.encode('ascii', errors='ignore') + b"\n")
                tn.expect([b'[Pp]assword:\\s*'], timeout=10)
            tn.write(decrypted_password.encode('ascii', errors='ignore') + b"\n")

            idx_p, _, banner_bytes = tn.expect([b'\\[Y/N\\]:\\s*', b'[<\\[][\\~\\*\\w\\-\\.\\(\\)/]+[>\\]]\\s*$', b'[#>]\\s*$'], timeout=12)
            banner_text = banner_bytes.decode('utf-8', errors='ignore')
            if any(err in banner_text.lower() for err in ['authentication fail', 'login failed', 'bad password', 'invalid']):
                raise Exception("Credenciales Telnet rechazadas por el equipo Huawei")

            # Si pregunta por cambio de contraseña en primer inicio de sesión [Y/N]:
            if idx_p == 0 or '[y/n]' in banner_text.lower():
                tn.write(b"N\n")
                tn.expect([b'[<\\[][\\~\\*\\w\\-\\.\\(\\)/]+[>\\]]\\s*$', b'[#>]\\s*$'], timeout=8)

            if enable_password:
                tn.write(b"super\n")
                idx_sup, _, _ = tn.expect([b'[Pp]assword:\s*', b'[<\[][\~\*\w\-\.\(\)/]+[>\]]\s*$'], timeout=6)
                if idx_sup == 0:
                    tn.write(super_pwd.encode('ascii', errors='ignore') + b"\n")
                    tn.expect([b'[<\[][\~\*\w\-\.\(\)/]+[>\]]\s*$'], timeout=6)

            # Desactivar paginación en Huawei VRP
            tn.write(b"screen-length 0 temporary\n")
            tn.expect([b'[<\\[][\\~\\*\\w\\-\\.\\(\\)/]+[>\\]]\\s*$', b'[#>]\\s*$'], timeout=8)

            for cmd in commands:
                tn.write(cmd.encode('ascii', errors='ignore') + b"\n")
                _, _, cmd_out = tn.expect([b'\n[<\\[][\\~\\*\\w\\-\\.\\(\\)/]+[>\\]]\\s*$', b'\n[\\w\\-\\.\\(\\)]+[#>]\\s*$'], timeout=timeout)
                raw_text = cmd_out.decode('utf-8', errors='ignore')
                outputs[cmd] = _clean_interactive_output(raw_text, cmd)

            tn.write(b"quit\n")
            return outputs
        finally:
            if tn:
                try:
                    tn.close()
                except Exception:
                    pass
    else:
        ssh_client = None
        try:
            ssh_client = connect_to_ssh(address, port_num, username, password, sshkey)
            chan = ssh_client.invoke_shell(width=200, height=1000)
            chan.settimeout(timeout)

            initial_banner = _read_channel_until_prompt(chan, timeout=12, idle_wait=0.5)

            # Manejar prompt [Y/N] de cambio de password de Huawei VRP
            if '[y/n]' in initial_banner.lower():
                chan.send('N\n')
                initial_banner = _read_channel_until_prompt(chan, timeout=8, idle_wait=0.4)

            if enable_password:
                chan.send('super\n')
                sup_prompt = _read_channel_until_prompt(chan, timeout=6, idle_wait=0.3)
                if 'password' in sup_prompt.lower():
                    chan.send(super_pwd + '\n')
                    _read_channel_until_prompt(chan, timeout=6, idle_wait=0.3)

            # Desactivar paginación en Huawei VRP
            chan.send('screen-length 0 temporary\n')
            _read_channel_until_prompt(chan, timeout=8, idle_wait=0.3)

            for cmd in commands:
                while chan.recv_ready():
                    chan.recv(65535)
                chan.send(cmd + '\n')
                raw_out = _read_channel_until_prompt(chan, timeout=timeout, idle_wait=0.6)
                outputs[cmd] = _clean_interactive_output(raw_out, cmd)

            try:
                chan.send('quit\n')
            except Exception:
                pass
            return outputs
        finally:
            if ssh_client:
                try:
                    ssh_client.close()
                except Exception:
                    pass


def execute_zte_commands(address, port, username, password, commands, protocol='ssh', sshkey=None, enable_password=None, timeout=35):
    """
    Ejecuta comandos en equipos ZTE (switches/routers ZXR10 y OLTs ZXA10 C300/C320/C600)
    tanto por SSH como por Telnet.
    Eleva automáticamente a modo privilegiado (#) con 'enable' y desactiva paginación
    con 'terminal length 0'.
    """
    return execute_cisco_commands(
        address, port, username, password, commands,
        protocol=protocol, sshkey=sshkey, enable_password=enable_password, timeout=timeout
    )




def _read_fortinet_channel(chan, timeout=30, idle_wait=0.5):
    """
    Lee de un canal interactivo FortiOS (FortiGate) manejando:
    - Prompts de super_admin (#) y read-only / operador ($), con o sin VDOMs: 'FGT # ', 'FGT (global) $ '
    - Banner post-login: "(Press 'a' to accept):"
    - Paginación '--More-- ' enviando espacio automáticamente cuando la cuenta no permite cambiar console output.
    """
    buf = ""
    start = time.time()
    last_recv = time.time()
    while time.time() - start < timeout:
        if chan.recv_ready():
            chunk = chan.recv(65535).decode('utf-8', errors='ignore')
            buf += chunk
            last_recv = time.time()

            tail = buf[-160:]
            if "(press 'a' to accept)" in tail.lower():
                chan.send('a')
                last_recv = time.time()
            elif '--more--' in tail.lower():
                buf = re.sub(r'--More--\s*', '', buf, flags=re.IGNORECASE)
                chan.send(' ')
                last_recv = time.time()
        else:
            stripped = buf.rstrip()
            if stripped and (stripped.endswith('#') or stripped.endswith('$')):
                if time.time() - last_recv >= idle_wait:
                    break
            time.sleep(0.1)
    buf = re.sub(r'\x08+\s*\x08*', '', buf)
    buf = re.sub(r'--More--\s*', '', buf, flags=re.IGNORECASE)
    return buf


def _clean_fortinet_output(raw_output: str, command: str) -> str:
    lines = raw_output.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and command.strip().lower() in lines[0].strip().lower():
        lines = lines[1:]
    while lines and not lines[-1].strip():
        lines.pop()
    # Prompts típicos de FortiGate: 'FGT60F #', 'FG100F (global) #', 'FW-BORDE $'
    if lines and re.match(r'^[\w\-\.\(\)\s]+[#$]\s*$', lines[-1].strip()):
        lines.pop()
    return '\n'.join(lines).strip()


def execute_fortinet_commands(address, port, username, password, commands, protocol='ssh', sshkey=None, enable_password=None, timeout=60):
    """
    Ejecuta comandos nativos de FortiOS en equipos Fortinet (FortiGate) por SSH, Telnet o REST API:
    - Desactiva paginación automáticamente ('config system console' -> 'set output standard' -> 'end',
      con soporte automático para VDOMs vía 'config global' y manejo de '--More--' para cuentas read-only).
    - Soporta respaldo vía REST API FortiOS (token en password) cuando protocol == 'api'.
    """
    decrypted_password = decrypt_credential(password)
    proto = (protocol or 'ssh').lower().strip()
    port_num = int(port) if port else (23 if proto == 'telnet' else (443 if proto == 'api' else 22))
    outputs = {}

    if proto == 'api':
        import requests
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        schemes = ['http', 'https'] if port_num == 80 else ['https', 'http']
        headers = {'Authorization': f'Bearer {decrypted_password}'}
        for cmd in commands:
            cmd_l = cmd.strip().lower()
            ep = '/api/v2/monitor/system/config/backup?scope=global' if cmd_l in ('show', 'show full-configuration') else '/api/v2/monitor/system/status'
            req_timeout = timeout if cmd_l in ('show', 'show full-configuration') else 25
            last_err = None
            for sch in schemes:
                try:
                    resp = requests.get(f"{sch}://{address}:{port_num}{ep}", headers=headers, timeout=req_timeout, verify=False)
                    resp.raise_for_status()
                    outputs[cmd] = resp.text
                    last_err = None
                    break
                except requests.exceptions.HTTPError as he:
                    raise he
                except Exception as ex:
                    last_err = ex
            if last_err is not None:
                raise last_err
        return outputs

    if proto == 'telnet':
        tn = None
        try:
            tn = telnetlib.Telnet(address, port_num, timeout=15)
            idx, _, _ = tn.expect([b'[Ll]ogin:\s*', b'[Uu]sername:\s*'], timeout=12)
            if idx < 0:
                raise Exception("No se recibió prompt de Login Telnet del equipo Fortinet")
            tn.write(username.encode('ascii', errors='ignore') + b"\n")
            idx_p, _, _ = tn.expect([b'[Pp]assword:\s*'], timeout=10)
            if idx_p == 0:
                tn.write(decrypted_password.encode('ascii', errors='ignore') + b"\n")

            idx_pr, _, banner_b = tn.expect([b'[#$]\s*$', b"Press 'a' to accept", b'[Ll]ogin incorrect'], timeout=12)
            if idx_pr == 1:
                tn.write(b"a")
                idx_pr, _, banner_b = tn.expect([b'[#$]\s*$'], timeout=10)
            if idx_pr != 0 or b'incorrect' in banner_b.lower():
                raise Exception("Credenciales Telnet rechazadas por FortiGate")

            tn.write(b"config system console\nset output standard\nend\n")
            tn.expect([b'[#$]\s*$'], timeout=6)

            for cmd in commands:
                tn.write(cmd.encode('ascii', errors='ignore') + b"\n")
                collected = b""
                deadline = time.time() + timeout
                while time.time() < deadline:
                    i_m, _, chunk = tn.expect([b'--More--\s*', b'[\w\-\.\(\)\s]+[#$]\s*$'], timeout=min(15, max(2, deadline - time.time())))
                    collected += chunk
                    if i_m == 0:
                        tn.write(b" ")
                    elif i_m == 1:
                        break
                    else:
                        break
                raw_str = collected.decode('utf-8', errors='ignore')
                raw_str = re.sub(r'--More--\s*', '', raw_str, flags=re.IGNORECASE)
                outputs[cmd] = _clean_fortinet_output(raw_str, cmd)

            tn.write(b"exit\n")
            return outputs
        finally:
            if tn:
                try:
                    tn.close()
                except Exception:
                    pass
    else:
        ssh_client = None
        try:
            ssh_client = connect_to_ssh(address, port_num, username, password, sshkey)
            chan = ssh_client.invoke_shell(width=250, height=1000)
            chan.settimeout(timeout)

            banner = _read_fortinet_channel(chan, timeout=12, idle_wait=0.4)

            # Desactivar paginación en FortiOS (directo, y si tiene VDOMs activos usa config global)
            chan.send('config system console\n')
            res_con = _read_fortinet_channel(chan, timeout=6, idle_wait=0.3)
            if 'command parse error' in res_con.lower() or 'unknown action' in res_con.lower():
                chan.send('config global\nconfig system console\nset output standard\nend\nend\n')
                _read_fortinet_channel(chan, timeout=8, idle_wait=0.3)
            else:
                chan.send('set output standard\nend\n')
                _read_fortinet_channel(chan, timeout=6, idle_wait=0.3)

            for cmd in commands:
                while chan.recv_ready():
                    chan.recv(65535)
                chan.send(cmd + '\n')
                raw_out = _read_fortinet_channel(chan, timeout=timeout, idle_wait=0.7)
                outputs[cmd] = _clean_fortinet_output(raw_out, cmd)

            try:
                chan.send('exit\n')
            except Exception:
                pass
            return outputs
        finally:
            if ssh_client:
                try:
                    ssh_client.close()
                except Exception:
                    pass


def execute_mikrotik_telnet_commands(address, port, username, password, commands, timeout=25):
    """
    Ejecuta comandos en MikroTik RouterOS vía Telnet (usando +ct para evitar códigos ANSI).
    """
    decrypted_password = decrypt_credential(password)
    port_num = int(port) if port else 23
    outputs = {}
    tn = None
    try:
        tn = telnetlib.Telnet(address, port_num, timeout=15)
        idx, _, _ = tn.expect([b'[Ll]ogin:\\s*', b'[Uu]sername:\\s*'], timeout=12)
        if idx < 0:
            raise Exception("No se recibió prompt de Login Telnet de MikroTik")

        login_user = username if '+ct' in username else f"{username}+ct"
        tn.write(login_user.encode('ascii', errors='ignore') + b"\r\n")

        idx_p, _, _ = tn.expect([b'[Pp]assword:\\s*'], timeout=10)
        if idx_p < 0:
            raise Exception("No se recibió prompt de Password Telnet de MikroTik")

        tn.write(decrypted_password.encode('ascii', errors='ignore') + b"\r\n")
        idx_pr, _, banner = tn.expect([b'\\]\\s*>\\s*$', b'[Ll]ogin failed', b'[Ll]ogin:\\s*'], timeout=12)
        banner_str = banner.decode('utf-8', errors='ignore')
        if idx_pr != 0 or 'login failed' in banner_str.lower():
            raise Exception("Credenciales Telnet rechazadas por MikroTik")

        for cmd in commands:
            tn.write(cmd.encode('ascii', errors='ignore') + b"\r\n")
            _, _, cmd_out = tn.expect([b'\\[[\\w\\-@\\.]+\\]\\s*>\\s*$'], timeout=timeout)
            raw_text = cmd_out.decode('utf-8', errors='ignore')
            lines = raw_text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
            if lines and cmd.strip().lower() in lines[0].strip().lower():
                lines = lines[1:]
            while lines and (not lines[-1].strip() or re.search(r'\[.*\]\s*>\s*$', lines[-1].strip())):
                lines.pop()
            outputs[cmd] = '\n'.join(lines).strip()

        tn.write(b"/quit\r\n")
        return outputs
    finally:
        if tn:
            try:
                tn.close()
            except Exception:
                pass


def test_authentication(router_type, address, port, username, password, sshkey=None, connection_protocol='ssh', enable_password=None):
    router_features = get_router_features(router_type)
    if not router_features:
        return False, 'Tipo de equipo no soportado'

    proto = (connection_protocol or 'ssh').lower().strip()
    if proto == 'telnet':
        return test_telnet_authentication(router_type, address, port, username, password, sshkey=sshkey, enable_password=enable_password)
    elif proto == 'api':
        port_num = int(port) if port else (443 if router_type == 'fortinet' else 8728)
        if router_type == 'fortinet':
            try:
                outputs = execute_fortinet_commands(address, port_num, username, password, ['get system status'], protocol='api', timeout=20)
                if outputs.get('get system status'):
                    return True, f'Éxito: FortiGate confirmado por API en puerto {port_num}'
                return False, 'El equipo Fortinet no devolvió estado por API'
            except Exception as e:
                return False, f'Error API Fortinet (puerto {port_num}): {str(e)}'
        elif router_type in ('mikrotik', 'mikrotik-branded'):
            # 1) Probar API nativa RouterOS en el puerto elegido por el usuario
            try:
                from routerlib.mikrotik_api import fetch_mikrotik_telemetry
                tel = fetch_mikrotik_telemetry(address, port_num, username, password, timeout=4.5)
                if tel.get('success'):
                    return True, f'Éxito: MikroTik confirmado por API en puerto {port_num}'
            except Exception:
                pass
            # 2) Probar REST API RouterOS v7 (HTTP/HTTPS en el puerto elegido)
            try:
                import requests, urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                dec_pw = decrypt_credential(password) or ''
                schemes = ['http', 'https'] if port_num in (80, 8080) else ['https', 'http']
                for sch in schemes:
                    try:
                        r = requests.get(f"{sch}://{address}:{port_num}/rest/system/resource", auth=(username, dec_pw), timeout=5, verify=False)
                        if r.status_code == 200 and ('version' in r.text or 'board-name' in r.text):
                            return True, f'Éxito: MikroTik REST API confirmado en puerto {port_num}'
                        elif r.status_code in (401, 403):
                            return False, 'Credenciales rechazadas por MikroTik REST API'
                    except Exception:
                        continue
            except Exception as e:
                return False, f'Error API MikroTik (puerto {port_num}): {str(e)}'
            return False, f'No se pudo conectar por API al puerto {port_num}. Verifique el puerto configurado en el dispositivo.'
        else:
            return test_ssh_authentication(router_type, address, port_num, username, password, sshkey=sshkey, enable_password=enable_password)
    else:
        return test_ssh_authentication(router_type, address, port, username, password, sshkey=sshkey, enable_password=enable_password)


def test_ssh_authentication(router_type, address, port, username, password, sshkey=None, enable_password=None):
    ssh_client = None
    try:
        if router_type == 'cisco-ios':
            outputs = execute_cisco_commands(
                address, port, username, password, ['show version'],
                protocol='ssh', sshkey=sshkey, enable_password=enable_password, timeout=25
            )
            output = outputs.get('show version', '')
            if any(k in output.lower() for k in ['cisco ios', 'internetwork operating system', 'cisco systems', 'ios-xe']):
                return True, 'Éxito: Equipo Cisco IOS confirmado por SSH'
            else:
                return False, 'El equipo respondió pero no se identificó como Cisco IOS'

        elif router_type == 'huawei':
            outputs = execute_huawei_commands(
                address, port, username, password, ['display version'],
                protocol='ssh', sshkey=sshkey, enable_password=enable_password, timeout=25
            )
            output = outputs.get('display version', '')
            if any(k in output.lower() for k in ['huawei', 'vrp', 'versatile routing platform', 'quidway']):
                return True, 'Éxito: Equipo Huawei VRP confirmado por SSH'
            else:
                return False, 'El equipo respondió pero no se identificó como Huawei VRP'

        elif router_type == 'zte':
            outputs = execute_zte_commands(
                address, port, username, password, ['show version'],
                protocol='ssh', sshkey=sshkey, enable_password=enable_password, timeout=25
            )
            output = outputs.get('show version', '')
            if any(k in output.lower() for k in ['zte', 'zxr10', 'zxa10', 'zxan', 'zxros']):
                return True, 'Éxito: Equipo ZTE confirmado por SSH'
            else:
                return False, 'El equipo respondió pero no se identificó como ZTE'

        elif router_type == 'fortinet':
            outputs = execute_fortinet_commands(
                address, port, username, password, ['get system status'],
                protocol='ssh', sshkey=sshkey, enable_password=enable_password, timeout=25
            )
            output = outputs.get('get system status', '')
            if any(k in output.lower() for k in ['fortigate', 'fortios', 'fortinet', 'serial-number:', 'version:']):
                return True, 'Éxito: Equipo Fortinet (FortiGate) confirmado por SSH'
            else:
                return False, 'El equipo respondió pero no se identificó como Fortinet FortiOS'

        ssh_client = connect_to_ssh(address, port, username, password, sshkey, max_retries=2, retry_delay=1)
        if router_type == 'mikrotik' or router_type == 'mikrotik-branded':
            stdin, stdout, stderr = ssh_client.exec_command('/system resource print', timeout=20)
            output = stdout.read().decode(errors='replace')
            if router_type == 'mikrotik':
                if 'platform: MikroTik' in output or 'version:' in output:
                    result = True, 'Éxito: Equipo MikroTik RouterOS confirmado por SSH'
                else:
                    result = False, 'El equipo no parece ser MikroTik'
            else:
                if 'platform: MikroTik' in output:
                    result = False, 'Device is not branded. Please select Mikrotik (RouterOS)'
                elif 'platform: ' in output:
                    result = True, 'Success: MikroTik branded device confirmed'
                else:
                    result = False, 'Device is not MikroTik'

        elif router_type == 'openwrt':
            stdin, stdout, stderr = ssh_client.exec_command('ubus call system board', timeout=20)
            output = stdout.read().decode(errors='replace')
            if 'OpenWrt' in output:
                result = True, 'Success: OpenWRT device confirmed'
            else:
                result = False, 'Device is not OpenWRT'

        elif router_type == 'ubiquiti-airos':
            stdin, stdout, stderr = ssh_client.exec_command('cat /etc/version', timeout=20)
            output = stdout.read().decode(errors='replace').strip()
            if re.match(r'^[A-Z]{2}\.v\d.*$', output):
                result = True, f'Success: Ubiquiti airOS device confirmed ({output})'
            else:
                result = False, 'Device is not airOS'
        else:
            result = False, 'Tipo de equipo no soportado'

        return result
    except Exception as e:
        return False, str(e)
    finally:
        if ssh_client:
            try:
                ssh_client.close()
            except Exception:
                pass


def test_telnet_authentication(router_type, address, port=23, username='', password='', sshkey=None, enable_password=None):
    try:
        if router_type == 'cisco-ios':
            outputs = execute_cisco_commands(
                address, port or 23, username, password, ['show version'],
                protocol='telnet', enable_password=enable_password, timeout=25
            )
            output = outputs.get('show version', '')
            if any(k in output.lower() for k in ['cisco ios', 'internetwork operating system', 'cisco systems', 'ios-xe']):
                return True, 'Éxito: Equipo Cisco IOS confirmado por Telnet'
            return False, 'Conectado por Telnet, pero no se identificó como Cisco IOS'

        elif router_type == 'huawei':
            outputs = execute_huawei_commands(
                address, port or 23, username, password, ['display version'],
                protocol='telnet', enable_password=enable_password, timeout=25
            )
            output = outputs.get('display version', '')
            if any(k in output.lower() for k in ['huawei', 'vrp', 'versatile routing platform', 'quidway']):
                return True, 'Éxito: Equipo Huawei VRP confirmado por Telnet'
            return False, 'Conectado por Telnet, pero no se identificó como Huawei VRP'

        elif router_type == 'zte':
            outputs = execute_zte_commands(
                address, port or 23, username, password, ['show version'],
                protocol='telnet', enable_password=enable_password, timeout=25
            )
            output = outputs.get('show version', '')
            if any(k in output.lower() for k in ['zte', 'zxr10', 'zxa10', 'zxan', 'zxros']):
                return True, 'Éxito: Equipo ZTE confirmado por Telnet'
            return False, 'Conectado por Telnet, pero no se identificó como ZTE'

        elif router_type == 'fortinet':
            outputs = execute_fortinet_commands(
                address, port or 23, username, password, ['get system status'],
                protocol='telnet', enable_password=enable_password, timeout=25
            )
            output = outputs.get('get system status', '')
            if any(k in output.lower() for k in ['fortigate', 'fortios', 'fortinet', 'serial-number:', 'version:']):
                return True, 'Éxito: Equipo Fortinet (FortiGate) confirmado por Telnet'
            return False, 'Conectado por Telnet, pero no se identificó como Fortinet FortiOS'

        elif router_type in ('mikrotik', 'mikrotik-branded'):
            outputs = execute_mikrotik_telnet_commands(
                address, port or 23, username, password, ['/system resource print without-paging'], timeout=20
            )
            output = outputs.get('/system resource print without-paging', '')
            if 'platform:' in output.lower() or 'version:' in output.lower():
                return True, 'Éxito: Equipo MikroTik confirmado por Telnet'
            return False, 'Conectado por Telnet, pero no se identificó como MikroTik'

        else:
            decrypted_password = decrypt_credential(password)
            port_num = int(port) if port else 23
            tn = telnetlib.Telnet(address, port_num, timeout=15)
            idx, _, _ = tn.expect([b'[Ll]ogin:\\s*', b'[Uu]sername:\\s*', b'[Pp]assword:\\s*'], timeout=10)
            if idx in (0, 1):
                tn.write(username.encode('ascii') + b"\n")
                tn.expect([b'[Pp]assword:\\s*'], timeout=10)
            tn.write(decrypted_password.encode('ascii') + b"\n")
            idx_ok, _, resp = tn.expect([b'[#>\\]\\$]\\s*$', b'[Ll]ogin incorrect', b'[Ll]ogin failed', b'[Aa]uthentication failed'], timeout=10)
            tn.write(b"exit\n")
            tn.close()
            if idx_ok == 0:
                return True, 'Éxito: Conexión Telnet autenticada'
            return False, 'Credenciales Telnet inválidas'
    except Exception as e:
        return False, f"Error Telnet: {str(e)}"
