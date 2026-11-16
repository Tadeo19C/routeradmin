"""
Cliente Nativo y Ultraligero para la API de MikroTik RouterOS (Puerto 8728).
Permite telemetría instantánea y lecturas en tiempo real sin requerir librerías externas.
"""
import socket
import binascii
import hashlib
from typing import List, Dict, Optional, Tuple, Any
from routerlib.crypto import decrypt_credential


class RouterOSAPIError(Exception):
    pass


class RouterOSAPI:
    def __init__(self, host: str, port: int = 8728, timeout: float = 4.0):
        self.host = host
        self.port = int(port or 8728)
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None

    def connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect((self.host, self.port))

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    def _read_exact(self, length: int) -> bytes:
        data = b''
        while len(data) < length:
            chunk = self.sock.recv(length - len(data))
            if not chunk:
                raise RouterOSAPIError("Conexión cerrada inesperadamente por el router.")
            data += chunk
        return data

    def _read_length(self) -> int:
        b1 = self._read_exact(1)[0]
        if (b1 & 0x80) == 0x00:
            return b1
        elif (b1 & 0xC0) == 0x80:
            b2 = self._read_exact(1)[0]
            return ((b1 & ~0xC0) << 8) + b2
        elif (b1 & 0xE0) == 0xC0:
            raw = self._read_exact(2)
            return ((b1 & ~0xE0) << 16) + (raw[0] << 8) + raw[1]
        elif (b1 & 0xF0) == 0xE0:
            raw = self._read_exact(3)
            return ((b1 & ~0xF0) << 24) + (raw[0] << 16) + (raw[1] << 8) + raw[2]
        elif (b1 & 0xF8) == 0xF0:
            raw = self._read_exact(4)
            return (raw[0] << 24) + (raw[1] << 16) + (raw[2] << 8) + raw[3]
        return 0

    @staticmethod
    def _encode_length(length: int) -> bytes:
        if length < 0x80:
            return bytes([length])
        elif length < 0x4000:
            length |= 0x8000
            return bytes([(length >> 8) & 0xFF, length & 0xFF])
        elif length < 0x200000:
            length |= 0xC00000
            return bytes([(length >> 16) & 0xFF, (length >> 8) & 0xFF, length & 0xFF])
        elif length < 0x10000000:
            length |= 0xE0000000
            return bytes([(length >> 24) & 0xFF, (length >> 16) & 0xFF, (length >> 8) & 0xFF, length & 0xFF])
        else:
            return bytes([0xF0, (length >> 24) & 0xFF, (length >> 16) & 0xFF, (length >> 8) & 0xFF, length & 0xFF])

    def write_word(self, word: str):
        encoded = word.encode('utf-8', errors='replace')
        self.sock.sendall(self._encode_length(len(encoded)) + encoded)

    def write_sentence(self, words: List[str]):
        for word in words:
            self.write_word(word)
        self.sock.sendall(b'\x00')

    def read_sentence(self) -> List[str]:
        words = []
        while True:
            length = self._read_length()
            if length == 0:
                break
            word_bytes = self._read_exact(length)
            words.append(word_bytes.decode('utf-8', errors='replace'))
        return words

    def login(self, username: str, password: str) -> bool:
        password = decrypt_credential(password) or ""
        # 1. Enviar /login inicial (compatible con v6.43+ y v7)
        self.write_sentence(['/login', f'=name={username}', f'=password={password}'])
        reply = self.read_sentence()

        if not reply:
            return False

        if reply[0] == '!done':
            # Si contiene =ret=, es versión legacy de RouterOS (requiere desafío MD5)
            ret_val = None
            for w in reply[1:]:
                if w.startswith('=ret='):
                    ret_val = w[5:]
                    break
            if ret_val:
                # Desafío MD5 legacy
                challenge = binascii.unhexlify(ret_val)
                md = hashlib.md5()
                md.update(b'\x00' + password.encode('utf-8') + challenge)
                response_hash = '00' + md.hexdigest()
                self.write_sentence(['/login', f'=name={username}', f'=response={response_hash}'])
                reply2 = self.read_sentence()
                return bool(reply2 and reply2[0] == '!done')
            return True
        elif reply[0] == '!trap':
            msg = "Autenticación rechazada por el router"
            for w in reply[1:]:
                if w.startswith('=message='):
                    msg = w[9:]
            raise RouterOSAPIError(msg)
        return False

    def query(self, command: str, **attributes) -> List[Dict[str, str]]:
        words = [command]
        for k, v in attributes.items():
            words.append(f'={k}={v}')
        self.write_sentence(words)

        results = []
        while True:
            sentence = self.read_sentence()
            if not sentence:
                break
            status = sentence[0]
            if status == '!re':
                item = {}
                for w in sentence[1:]:
                    if w.startswith('='):
                        parts = w[1:].split('=', 1)
                        if len(parts) == 2:
                            item[parts[0]] = parts[1]
                results.append(item)
            elif status == '!done':
                break
            elif status == '!trap':
                msg = "Error de comando en RouterOS"
                for w in sentence[1:]:
                    if w.startswith('=message='):
                        msg = w[9:]
                raise RouterOSAPIError(msg)
        return results


def fetch_mikrotik_telemetry(address: str, port: int, username: str, password: str, timeout: float = 3.5) -> Dict[str, Any]:
    """
    Función de alto nivel para obtener telemetría instantánea de un router MikroTik vía API.
    Retorna un diccionario con CPU, RAM, Uptime, Versión y Hardware estructurado.
    """
    api = RouterOSAPI(address, port=port or 8728, timeout=timeout)
    try:
        api.connect()
        if not api.login(username, password):
            return {'success': False, 'error': 'Credenciales incorrectas en API MikroTik'}

        resources = api.query('/system/resource/print')
        routerboard = api.query('/system/routerboard/print')

        res_data = resources[0] if resources else {}
        rb_data = routerboard[0] if routerboard else {}

        # Parsear memoria a formato amigable
        total_mem = int(res_data.get('total-memory', 0) or 0)
        free_mem = int(res_data.get('free-memory', 0) or 0)
        used_mem = total_mem - free_mem if total_mem > free_mem else 0
        mem_pct = round((used_mem / total_mem) * 100, 1) if total_mem > 0 else 0

        total_hdd = int(res_data.get('total-hdd-space', 0) or 0)
        free_hdd = int(res_data.get('free-hdd-space', 0) or 0)
        used_hdd = total_hdd - free_hdd if total_hdd > free_hdd else 0
        hdd_pct = round((used_hdd / total_hdd) * 100, 1) if total_hdd > 0 else 0

        return {
            'success': True,
            'source': 'api',
            'uptime': res_data.get('uptime', 'N/A'),
            'version': res_data.get('version', 'N/A'),
            'cpu_load': int(res_data.get('cpu-load', 0) or 0),
            'cpu_count': int(res_data.get('cpu-count', 1) or 1),
            'cpu_frequency': res_data.get('cpu-frequency', 'N/A'),
            'cpu': res_data.get('cpu', 'N/A'),
            'board_name': res_data.get('board-name', rb_data.get('model', 'MikroTik')),
            'model': rb_data.get('model', res_data.get('board-name', '')),
            'serial_number': rb_data.get('serial-number', ''),
            'current_firmware': rb_data.get('current-firmware', ''),
            'upgrade_firmware': rb_data.get('upgrade-firmware', ''),
            'architecture': res_data.get('architecture-name', ''),
            'memory': {
                'total_bytes': total_mem,
                'free_bytes': free_mem,
                'used_bytes': used_mem,
                'usage_percentage': mem_pct,
                'total_human': f"{total_mem / (1024*1024):.1f} MB" if total_mem else "N/A",
                'free_human': f"{free_mem / (1024*1024):.1f} MB" if free_mem else "N/A",
            },
            'storage': {
                'total_bytes': total_hdd,
                'free_bytes': free_hdd,
                'usage_percentage': hdd_pct,
                'total_human': f"{total_hdd / (1024*1024):.1f} MB" if total_hdd else "N/A",
            }
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}
    finally:
        api.close()
