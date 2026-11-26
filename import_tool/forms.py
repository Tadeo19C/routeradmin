from backup.models import BackupProfile
from router_manager.models import SUPPORTED_ROUTER_TYPES, RouterGroup
from router_manager.normalization import BatchNodeResolver, canonical_key, strip_accents
from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Submit, Row, Column, HTML
from .models import CsvData
from .excel_utils import parse_excel_or_csv_bytes
import json
import re
from django.core.exceptions import ValidationError

SUPPORTED_TYPES_SET = [rt[0] for rt in SUPPORTED_ROUTER_TYPES]

# Mapeo de sinónimos de columnas (español e inglés)
HEADER_SYNONYMS = {
    'nombre': 'name', 'equipo': 'name', 'dispositivo': 'name', 'router': 'name', 'hostname': 'name', 'name': 'name',
    'ip': 'address', 'direccion': 'address', 'direccion_ip': 'address', 'dirección ip': 'address', 'direccion ip': 'address', 'address': 'address', 'host': 'address',
    'usuario': 'username', 'user': 'username', 'login': 'username', 'username': 'username',
    'password': 'password', 'contraseña': 'password', 'contrasena': 'password', 'clave': 'password', 'pass': 'password', 'pwd': 'password',
    'marca': 'router_type', 'tipo': 'router_type', 'fabricante': 'router_type', 'vendor': 'router_type', 'router_type': 'router_type',
    'protocolo': 'connection_protocol', 'protocol': 'connection_protocol', 'connection_protocol': 'connection_protocol', 'proto': 'connection_protocol',
    'puerto': 'port', 'port': 'port',
    'nodo': 'router_group', 'zona': 'router_group', 'grupo': 'router_group', 'node': 'router_group', 'group': 'router_group', 'sitio': 'router_group', 'router_group': 'router_group',
    'perfil': 'backup_profile', 'profile': 'backup_profile', 'backup_profile': 'backup_profile',
    'monitoreo': 'monitoring', 'monitoring': 'monitoring',
}

# Normalización de fabricantes amigables
VENDOR_MAPPINGS = {
    'mikrotik': 'mikrotik',
    'routeros': 'mikrotik',
    'cisco': 'cisco-ios',
    'cisco-ios': 'cisco-ios',
    'cisco_ios': 'cisco-ios',
    'cisco ios': 'cisco-ios',
    'catalyst': 'cisco-ios',
    'ios': 'cisco-ios',
    'huawei': 'huawei',
    'huawei-vrp': 'huawei',
    'huawei vrp': 'huawei',
    'vrp': 'huawei',
    'zte': 'zte',
    'fortinet': 'fortinet',
    'fortigate': 'fortinet',
    'fortios': 'fortinet',
    'forti': 'fortinet',
    'fgt': 'fortinet',
    'ubiquiti': 'ubiquiti-airos',
    'ubiquiti-airos': 'ubiquiti-airos',
    'airos': 'ubiquiti-airos',
    'airmax': 'ubiquiti-airos',
    'ubnt': 'ubiquiti-airos',
    'openwrt': 'openwrt',
}


class CsvDataForm(forms.ModelForm):
    csv_file = forms.FileField(
        required=True,
        label='Archivo de Excel (.xlsx)',
        help_text='Seleccione su archivo editado en Excel o LibreOffice.',
        widget=forms.FileInput(attrs={
            'accept': '.xlsx,.xls,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel,text/csv',
        })
    )

    class Meta:
        model = CsvData
        fields = ['csv_file']

    def __init__(self, *args, **kwargs):
        super(CsvDataForm, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.attrs = {'enctype': 'multipart/form-data'}
        self.helper.layout = Layout(
            Row(
                Column(
                    HTML('''
                    <div class="d-flex justify-content-between align-items-center flex-wrap mb-3 p-3 rounded border" style="background: var(--card); gap: 12px;">
                        <div>
                            <h6 class="text-primary font-weight-bold mb-1"><i class="fas fa-file-excel mr-1"></i> Plantilla Excel Clásica</h6>
                            <p class="text-muted small mb-0">Descarga la plantilla en formato Excel (.xlsx), llénala en Excel y súbela directamente.</p>
                        </div>
                        <div class="d-flex flex-wrap" style="gap: 8px;">
                            <a href="/router/import_tool/template_csv/" class="btn btn-sm btn-outline-primary">
                                <i class="fas fa-download mr-1"></i> Descargar Plantilla Excel
                            </a>
                            <a href="/router/import_tool/export_csv/" class="btn btn-sm btn-outline-secondary">
                                <i class="fas fa-file-export mr-1"></i> Exportar Inventario Actual
                            </a>
                        </div>
                    </div>
                    '''),
                    css_class='col-md-12'
                ),
                Column('csv_file', css_class='form-group col-md-6 col-lg-5 mb-3', style='max-width: 380px;'),
                css_class='form-row'
            ),
            Row(
                Column(
                    Submit('submit', 'Procesar e Importar Dispositivos', css_class='btn btn-success font-weight-bold'),
                    HTML(' <a class="btn btn-outline-secondary ml-1" href="/router/list/">Volver</a> '),
                    css_class='col-md-12 mt-2'
                ),
                css_class='form-row'
            )
        )

    def clean(self):
        cleaned_data = super().clean()
        uploaded_file = cleaned_data.get('csv_file')

        if not uploaded_file:
            raise ValidationError("Debe seleccionar un archivo de Excel (.xlsx o .csv).")

        raw_bytes = uploaded_file.read()
        if not raw_bytes:
            raise ValidationError("El archivo seleccionado está vacío.")

        try:
            headers, raw_rows = parse_excel_or_csv_bytes(raw_bytes, filename=getattr(uploaded_file, 'name', ''))
        except Exception as e:
            raise ValidationError(f"No se pudo leer el archivo de Excel: {str(e)}")

        if not headers:
            raise ValidationError("El archivo de Excel está vacío o no contiene encabezados en la primera fila.")

        # Mapear encabezados usando sinónimos amigables
        header_map = {}
        for h in headers:
            if not h:
                continue
            h_clean = str(h).strip().lower()
            h_no_acc = strip_accents(h_clean)
            mapped = HEADER_SYNONYMS.get(h_clean) or HEADER_SYNONYMS.get(h_no_acc, h_clean)
            header_map[h] = mapped

        mapped_headers = set(header_map.values())
        if 'address' not in mapped_headers:
            raise ValidationError(
                "El archivo debe contener la columna 'IP'. "
                "Descargue la Plantilla Excel para ver las columnas."
            )

        seen_ips = set()
        seen_name_keys = set()
        node_resolver = BatchNodeResolver()
        import_data = []
        import_id = 0

        for line_number, raw_row in enumerate(raw_rows, start=2):
            row = {}
            for orig_k, orig_v in raw_row.items():
                if orig_k in header_map:
                    row[header_map[orig_k]] = (str(orig_v).strip() if orig_v is not None else '')

            if not any(row.values()):
                continue

            # Validar IP (insensible a mayúsculas/espacios)
            address = row.get('address', '').strip().lower()
            if not address:
                continue
            if not self._is_valid_ip_or_hostname(address):
                raise ValidationError(f"Fila {line_number}: Dirección IP o Host inválido ('{address}').")

            if address in seen_ips:
                continue
            seen_ips.add(address)
            row['address'] = address

            # Nombre del dispositivo (limpiando espacios dobles y evitando colisiones por mayúsculas/tildes)
            name = re.sub(r'\s+', ' ', row.get('name', '').strip())
            if not name:
                name = f"Router_{address.replace('.', '_')}"
            name_key = canonical_key(name)
            if name_key in seen_name_keys:
                name = f"{name} ({address})"
                name_key = canonical_key(name)
            seen_name_keys.add(name_key)
            row['name'] = name

            # Credenciales
            row['username'] = row.get('username') or 'admin'
            row['password'] = row.get('password') or ''

            # Protocolo (SSH, Telnet, API) y Puerto (22, 23, 80 o puerto personalizado definido en Excel)
            raw_proto = (row.get('connection_protocol') or '').strip().lower()
            raw_port = str(row.get('port') or '').strip()
            if raw_port.endswith('.0'):
                raw_port = raw_port[:-2]

            if raw_proto in ('ssh', 'ssh2'):
                proto = 'ssh'
            elif raw_proto in ('telnet', 'tel'):
                proto = 'telnet'
            elif raw_proto in ('api', 'rest', 'http', 'https', 'mikrotik-api', 'winbox'):
                proto = 'api'
            else:
                proto = ''

            custom_port = None
            if raw_port:
                try:
                    p_val = int(float(raw_port))
                    if 1 <= p_val <= 65535:
                        custom_port = p_val
                except ValueError:
                    pass

            # Si no se especificó protocolo, se detecta automáticamente según el puerto
            if not proto:
                if custom_port == 23:
                    proto = 'telnet'
                elif custom_port in (80, 443, 8728, 8729):
                    proto = 'api'
                else:
                    proto = 'ssh'

            # Si el usuario definió su propio puerto en Excel, se respeta; si no, se asigna por protocolo
            if custom_port is not None:
                port = custom_port
            else:
                if proto == 'telnet':
                    port = 23
                elif proto == 'api':
                    port = 80
                else:
                    port = 22

            row['connection_protocol'] = proto
            row['port'] = port

            # Marca / Fabricante (MikroTik por defecto, con detección flexible para ej. 'FortiGate 100F', 'Cisco Catalyst', etc.)
            raw_type = strip_accents((row.get('router_type') or 'mikrotik').strip().lower())
            normalized_type = VENDOR_MAPPINGS.get(raw_type, raw_type)
            if normalized_type not in SUPPORTED_TYPES_SET:
                if 'forti' in raw_type or raw_type.startswith('fgt'):
                    normalized_type = 'fortinet'
                elif 'cisco' in raw_type or 'catalyst' in raw_type:
                    normalized_type = 'cisco-ios'
                elif 'huawei' in raw_type or 'vrp' in raw_type:
                    normalized_type = 'huawei'
                elif 'zte' in raw_type or 'zxr' in raw_type or 'zxa' in raw_type:
                    normalized_type = 'zte'
                elif 'ubiquiti' in raw_type or 'ubnt' in raw_type or 'airos' in raw_type:
                    normalized_type = 'ubiquiti-airos'
                elif 'openwrt' in raw_type:
                    normalized_type = 'openwrt'
                else:
                    normalized_type = 'mikrotik'
            row['router_type'] = normalized_type
            if custom_port is None and proto == 'api' and normalized_type == 'fortinet':
                row['port'] = 443

            # Nodo / Zona (resolución inteligente anti-duplicados: ignora mayúsculas, tildes, guiones, orden y prefijos 'Nodo ', 'El ', etc.)
            raw_node_name = row.get('router_group', '').strip()
            row['router_group'] = node_resolver.resolve_name(raw_node_name)

            # Perfil de respaldo y monitoreo
            row['backup_profile'] = row.get('backup_profile') or 'default'
            BackupProfile.objects.get_or_create(name=row['backup_profile'])

            mon_val = str(row.get('monitoring', 'true')).lower()
            row['monitoring'] = 'false' if mon_val in ('0', 'no', 'false') else 'true'

            import_id += 1
            row['import_id'] = import_id
            import_data.append(row)

        if not import_data:
            raise ValidationError("El archivo de Excel no contiene filas con equipos válidos para importar.")

        cleaned_data['import_data'] = import_data
        cleaned_data['raw_csv_data'] = json.dumps(import_data, ensure_ascii=False)
        return cleaned_data

    def _is_valid_ip_or_hostname(self, value):
        ip_pattern = re.compile(r"^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$")
        hostname_pattern = re.compile(r"^(?=.{1,253}$)(?:(?!-)[A-Za-z0-9-]{1,63}(?<!-)\.)+[A-Za-z]{2,6}$")
        return ip_pattern.match(value) or hostname_pattern.match(value)
