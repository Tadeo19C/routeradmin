from backup.models import BackupProfile
from router_manager.models import SUPPORTED_ROUTER_TYPES, RouterGroup
from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Submit, Row, Column, HTML
from .models import CsvData
import csv
import io
import re
from django.core.exceptions import ValidationError

SUPPORTED_TYPES_SET = [rt[0] for rt in SUPPORTED_ROUTER_TYPES]

# Mapeo de sinónimos de columnas para aceptar tanto español como inglés
HEADER_SYNONYMS = {
    'nombre': 'name', 'equipo': 'name', 'dispositivo': 'name', 'router': 'name', 'hostname': 'name', 'name': 'name',
    'ip': 'address', 'direccion': 'address', 'direccion_ip': 'address', 'dirección ip': 'address', 'direccion ip': 'address', 'address': 'address', 'host': 'address',
    'usuario': 'username', 'user': 'username', 'login': 'username', 'username': 'username',
    'password': 'password', 'contraseña': 'password', 'contrasena': 'password', 'clave': 'password', 'pass': 'password',
    'marca': 'router_type', 'tipo': 'router_type', 'fabricante': 'router_type', 'vendor': 'router_type', 'router_type': 'router_type',
    'nodo': 'router_group', 'zona': 'router_group', 'grupo': 'router_group', 'node': 'router_group', 'group': 'router_group', 'sitio': 'router_group', 'router_group': 'router_group',
    'puerto': 'port', 'port': 'port',
    'protocolo': 'connection_protocol', 'protocol': 'connection_protocol', 'connection_protocol': 'connection_protocol',
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
    'huawei': 'huawei',
    'huawei-vrp': 'huawei',
    'zte': 'zte',
    'ubiquiti': 'ubiquiti-airos',
    'ubiquiti-airos': 'ubiquiti-airos',
    'airos': 'ubiquiti-airos',
    'openwrt': 'openwrt',
}


class CsvDataForm(forms.ModelForm):
    csv_file = forms.FileField(
        required=False,
        label='Archivo de Excel (.csv)',
        help_text='Seleccione su archivo editado en Excel o LibreOffice.'
    )

    class Meta:
        model = CsvData
        fields = ['csv_file', 'raw_csv_data']
        labels = {
            'raw_csv_data': 'O pegar texto separado por comas / punto y coma (Opcional)',
        }

    def __init__(self, *args, **kwargs):
        super(CsvDataForm, self).__init__(*args, **kwargs)
        self.fields['raw_csv_data'].required = False
        self.fields['raw_csv_data'].widget.attrs['rows'] = 4
        self.fields['raw_csv_data'].widget.attrs['placeholder'] = (
            'Nombre;IP;Usuario;Contraseña;Marca;Nodo\n'
            'Router Central;192.168.1.1;admin;clave123;mikrotik;Nodo Centro'
        )
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
                            <p class="text-muted small mb-0">Descarga la plantilla vacía de solo 6 columnas, llénala en Excel y súbela directamente.</p>
                        </div>
                        <div class="d-flex flex-wrap" style="gap: 8px;">
                            <a href="/router/import_tool/template_csv/" class="btn btn-sm btn-primary">
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
                Column('csv_file', css_class='form-group col-md-12 mb-3'),
                Column('raw_csv_data', css_class='form-group col-md-12 mb-2'),
                css_class='form-row'
            ),
            Row(
                Column(
                    Submit('submit', 'Procesar e Importar Equipos', css_class='btn btn-success font-weight-bold'),
                    HTML(' <a class="btn btn-outline-secondary" href="/router/import_tool/">Volver</a> '),
                    css_class='col-md-12 mt-2'
                ),
                css_class='form-row'
            )
        )

    def clean(self):
        cleaned_data = super().clean()
        uploaded_file = cleaned_data.get('csv_file')
        raw_csv_data = (cleaned_data.get('raw_csv_data') or '').strip()

        if uploaded_file:
            raw_bytes = uploaded_file.read()
            try:
                raw_csv_data = raw_bytes.decode('utf-8-sig').strip()
            except UnicodeDecodeError:
                raw_csv_data = raw_bytes.decode('latin-1', errors='replace').strip()
            cleaned_data['raw_csv_data'] = raw_csv_data

        if not raw_csv_data:
            raise ValidationError("Debe seleccionar un archivo Excel (.csv) o pegar los datos.")

        # Detectar delimitador de Excel automáticamente (, o ;)
        first_line = raw_csv_data.splitlines()[0] if raw_csv_data.splitlines() else ''
        delimiter = ';' if (first_line.count(';') > first_line.count(',')) else ','

        csv_file = io.StringIO(raw_csv_data)
        reader = csv.DictReader(csv_file, delimiter=delimiter)

        if not reader.fieldnames:
            raise ValidationError("El archivo está vacío o no contiene encabezados válidos.")

        # Mapear encabezados usando sinónimos amigables
        header_map = {}
        for h in reader.fieldnames:
            if not h:
                continue
            h_clean = h.strip().lower()
            mapped = HEADER_SYNONYMS.get(h_clean, h_clean)
            header_map[h] = mapped

        # Únicos campos obligatorios: name y address
        mapped_headers = set(header_map.values())
        if 'address' not in mapped_headers and 'name' not in mapped_headers:
            raise ValidationError(
                "El archivo debe contener al menos las columnas 'IP' y 'Nombre'. "
                "Descargue la Plantilla Excel para ver el formato recomendado."
            )

        seen_ips = set()
        seen_names = set()
        import_data = []
        import_id = 0

        for line_number, raw_row in enumerate(reader, start=2):
            # Mapear fila con encabezados estandarizados
            row = {}
            for orig_k, orig_v in raw_row.items():
                if orig_k in header_map:
                    row[header_map[orig_k]] = (orig_v.strip() if orig_v else '')

            if not any(row.values()):
                continue

            # Validar IP
            address = row.get('address', '').strip()
            if not address or not self._is_valid_ip_or_hostname(address):
                raise ValidationError(f"Línea {line_number}: Dirección IP inválida o vacía ('{address}').")

            if address in seen_ips:
                raise ValidationError(f"Línea {line_number}: Dirección IP duplicada en el archivo ('{address}').")
            seen_ips.add(address)
            row['address'] = address

            # Nombre del equipo (si no viene, se autogenera)
            name = row.get('name', '').strip()
            if not name:
                name = f"Router_{address.replace('.', '_')}"
            if name in seen_names:
                name = f"{name}_{line_number}"
            seen_names.add(name)
            row['name'] = name

            # Credenciales con valores por defecto inteligentes
            row['username'] = row.get('username') or 'admin'
            row['password'] = row.get('password') or ''

            # Puerto y protocolo automáticos
            raw_port = row.get('port', '')
            raw_proto = (row.get('connection_protocol') or '').lower()

            if raw_port and raw_port.isdigit():
                port = int(raw_port)
            elif raw_proto == 'telnet':
                port = 23
            else:
                port = 22
            row['port'] = port

            if not raw_proto:
                raw_proto = 'telnet' if port == 23 else 'ssh'
            row['connection_protocol'] = raw_proto if raw_proto in ('ssh', 'telnet') else 'ssh'

            # Tipo de equipo / Marca (MikroTik por defecto)
            raw_type = (row.get('router_type') or 'mikrotik').lower()
            normalized_type = VENDOR_MAPPINGS.get(raw_type, raw_type)
            if normalized_type not in SUPPORTED_TYPES_SET:
                normalized_type = 'mikrotik'
            row['router_type'] = normalized_type

            # Nodo / Zona (si no viene, usa el nodo por defecto o "General")
            node_name = row.get('router_group', '').strip()
            if not node_name:
                default_node = RouterGroup.objects.filter(default_group=True).first()
                node_name = default_node.name if default_node else 'General'
            row['router_group'] = node_name

            # Auto-crear el Nodo si no existe en la base de datos
            RouterGroup.objects.get_or_create(name=node_name)

            # Perfil de respaldo y monitoreo
            row['backup_profile'] = row.get('backup_profile') or 'default'
            BackupProfile.objects.get_or_create(name=row['backup_profile'])

            mon_val = str(row.get('monitoring', 'true')).lower()
            row['monitoring'] = 'false' if mon_val in ('0', 'no', 'false') else 'true'

            import_id += 1
            row['import_id'] = import_id
            import_data.append(row)

        if not import_data:
            raise ValidationError("El archivo no contiene ninguna fila válida de equipos para importar.")

        cleaned_data['import_data'] = import_data
        return cleaned_data

    def _is_valid_ip_or_hostname(self, value):
        ip_pattern = re.compile(r"^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$")
        hostname_pattern = re.compile(r"^(?=.{1,253}$)(?:(?!-)[A-Za-z0-9-]{1,63}(?<!-)\.)+[A-Za-z]{2,6}$")
        return ip_pattern.match(value) or hostname_pattern.match(value)
