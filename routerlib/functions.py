from io import StringIO
import time
import re
import paramiko
import telnetlib
from routerlib.crypto import decrypt_credential


def get_router_features(router_type):
    if router_type in ['openwrt', 'mikrotik', 'mikrotik-branded', 'ubiquiti-airos', 'cisco-ios', 'cisco-xe']:
        return ['backup', 'reverse_monitoring', 'ssh', 'ssh_key']
    else:
        return []


def get_router_backup_file_extension(router_type):
    if router_type == 'mikrotik' or router_type == 'mikrotik-branded':
        return {'text': 'rsc', 'binary': 'backup'}
    elif router_type == 'openwrt':
        return {'text': 'txt', 'binary': 'tar.gz'}
    elif router_type == 'ubiquiti-airos':
        return {'text': 'cfg', 'binary': None}
    elif router_type == 'cisco-ios':
        return {'text': 'cfg', 'binary': None}
    else:
        return {'text': 'txt', 'binary': 'bin'}


def gen_backup_name(router_backup):
    return f'routerfleet-backup-{router_backup.id}-{router_backup.schedule_type}-{router_backup.created.strftime("%Y-%m-%d_%H-%M")}'


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
    Establece conexión SSH con reintentos exponenciales y timeouts controlados.
    Descifra automáticamente contraseñas y llaves si vienen cifradas en reposo.
    """
    decrypted_password = decrypt_credential(password)
    
    last_exception = None
    for attempt in range(max_retries):
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            if sshkey:
                priv_key_str = getattr(sshkey, 'private_key', str(sshkey))
                private_key = load_private_key_from_string(priv_key_str)
                ssh_client.connect(
                    address, port=port, username=username, pkey=private_key,
                    look_for_keys=False, timeout=15, banner_timeout=15, auth_timeout=20, allow_agent=False
                )
            else:
                ssh_client.connect(
                    address, port=port, username=username, password=decrypted_password,
                    look_for_keys=False, timeout=15, banner_timeout=15, auth_timeout=20, allow_agent=False
                )
            return ssh_client
        except (paramiko.ssh_exception.AuthenticationException, paramiko.ssh_exception.BadHostKeyException) as e:
            # Errores definitivos de credenciales: no reintentar
            ssh_client.close()
            raise e
        except Exception as e:
            ssh_client.close()
            last_exception = e
            if attempt < max_retries - 1:
                time.sleep(retry_delay * (attempt + 1))
    
    if last_exception:
        raise last_exception


def test_authentication(router_type, address, port, username, password, sshkey=None):
    router_features = get_router_features(router_type)
    if 'ssh' in router_features:
        connection_type = 'ssh'
    elif 'telnet' in router_features:
        connection_type = 'telnet'
    else:
        return False, 'Router type not supported'

    if connection_type == 'ssh':
        return test_ssh_authentication(router_type, address, port, username, password, sshkey)
    elif connection_type == 'telnet':
        return test_telnet_authentication(address, username, password, sshkey=None)


def test_ssh_authentication(router_type, address, port, username, password, sshkey=None):
    ssh_client = None
    try:
        ssh_client = connect_to_ssh(address, port, username, password, sshkey, max_retries=2, retry_delay=1)
        if router_type == 'mikrotik' or router_type == 'mikrotik-branded':
            stdin, stdout, stderr = ssh_client.exec_command('/system resource print', timeout=20)
            output = stdout.read().decode(errors='replace')
            if router_type == 'mikrotik':
                if 'platform: MikroTik' in output:
                    result = True, 'Success: MikroTik device confirmed'
                else:
                    result = False, 'Device is not MikroTik'
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

        elif router_type == 'cisco-ios':
            stdin, stdout, stderr = ssh_client.exec_command('show version', timeout=25)
            output = stdout.read().decode(errors='replace')
            if 'Cisco IOS Software' in output:
                result = True, 'Success: Cisco IOS device confirmed'
            else:
                result = False, 'Device is not Cisco IOS'

        else:
            result = False, 'Unsupported device type'

        return result
    except Exception as e:
        return False, str(e)
    finally:
        if ssh_client:
            try:
                ssh_client.close()
            except Exception:
                pass


def test_telnet_authentication(address, username, password, sshkey=None):
    try:
        decrypted_password = decrypt_credential(password)
        tn = telnetlib.Telnet(address, timeout=15)
        tn.read_until(b"login: ", timeout=10)
        tn.write(username.encode('ascii') + b"\n")
        tn.read_until(b"Password: ", timeout=10)
        tn.write(decrypted_password.encode('ascii') + b"\n")
        tn.write(b"exit\n")
        tn.close()
        return True, 'Success'
    except Exception as e:
        print(f"Telnet connection failed: {e}")
        return False, str(e)
