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


class CsvDataForm(forms.ModelForm):
    csv_file = forms.FileField(
        required=False,
        label='Subir Documento Excel (.csv)',
        help_text='Seleccione su archivo .csv editado en Excel o pegue el contenido abajo.'
    )

    class Meta:
        model = CsvData
        fields = ['csv_file', 'raw_csv_data']
        labels = {
            'raw_csv_data': 'O pegar contenido CSV directamente (Opcional si sube archivo)',
        }

    def __init__(self, *args, **kwargs):
        super(CsvDataForm, self).__init__(*args, **kwargs)
        self.fields['raw_csv_data'].required = False
        self.fields['raw_csv_data'].widget.attrs['rows'] = 6
        self.fields['raw_csv_data'].widget.attrs['placeholder'] = (
            '"name","username","password","address","port","router_type","connection_protocol","backup_profile","router_group","monitoring"\n'
            '"rt central","admin","secreto123","192.168.10.1","22","mikrotik","ssh","default","Nodo Central","true"'
        )
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.attrs = {'enctype': 'multipart/form-data'}
        self.helper.layout = Layout(
            Row(
                Column(
                    HTML('''
                    <div class="d-flex justify-content-between align-items-center flex-wrap mb-3 p-2 rounded border" style="background: var(--secondary); gap: 8px;">
                        <div>
                            <b class="text-primary"><i class="fas fa-file-excel mr-1"></i> Plantilla y Exportación en Excel (.csv)</b>
                            <div class="text-muted small">Descargue la plantilla vacía para llenarla en Excel o exporte su inventario actual de equipos.</div>
                        </div>
                        <div class="d-flex" style="gap: 6px;">
                            <a href="/router/import_tool/template_csv/" class="btn btn-sm btn-outline-primary">
                                <i class="fas fa-download"></i> Descargar Plantilla Excel
                            </a>
                            <a href="/router/import_tool/export_csv/" class="btn btn-sm btn-outline-success">
                                <i class="fas fa-file-export"></i> Exportar Equipos Actuales
                            </a>
                        </div>
                    </div>
                    '''),
                    css_class='col-md-12'
                ),
                css_class='form-row'
            ),
            Row(
                Column('csv_file', css_class='form-group col-md-12 mb-2'),
                Column('raw_csv_data', css_class='form-group col-md-12 mb-2'),
                css_class='form-row'
            ),
            Row(
                Column(
                    Submit('submit', 'Procesar e Importar Documento', css_class='btn btn-primary'),
                    HTML(' <a class="btn btn-secondary" href="/router/import_tool/">Volver</a> '),
                    css_class='col-md-12'
                ),
                css_class='form-row mt-2'
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
            raise ValidationError("Debe subir un archivo Excel (.csv) o pegar los datos en el cuadro de texto.")

        # Support both comma and semicolon (Spanish Excel often exports semicolon-separated CSV)
        first_line = raw_csv_data.splitlines()[0] if raw_csv_data.splitlines() else ''
        delimiter = ';' if (';' in first_line and ',' not in first_line) else ','

        csv_file = io.StringIO(raw_csv_data)
        reader = csv.DictReader(csv_file, delimiter=delimiter)

        if not reader.fieldnames:
            raise ValidationError("El archivo CSV está vacío o no tiene encabezados válidos.")

        norm_headers = [h.strip().lower() for h in reader.fieldnames if h]
        required_fields = {'name', 'username', 'address', 'port', 'router_type'}
        missing_headers = required_fields - set(norm_headers)
        if missing_headers:
            raise ValidationError(
                f"Faltan columnas obligatorias en el encabezado: {', '.join(sorted(missing_headers))}. "
                f"Descargue la Plantilla Excel para ver el formato exacto."
            )

        seen_names = set()
        import_data = []
        import_id = 0

        for line_number, raw_row in enumerate(reader, start=2):
            row = {(k.strip().lower() if k else ''): (v.strip() if v else '') for k, v in raw_row.items() if k}
            if not any(row.values()):
                continue

            if not row.get('password'):
                raise ValidationError(f"Debe proporcionar una contraseña (password) en la línea {line_number}.")

            if row['name'] in seen_names:
                raise ValidationError(f"Nombre duplicado '{row['name']}' en la línea {line_number}.")
            seen_names.add(row['name'])

            rtype = row['router_type'].lower()
            if rtype not in SUPPORTED_TYPES_SET:
                raise ValidationError(
                    f"Tipo de equipo inválido '{row['router_type']}' en la línea {line_number}. "
                    f"Valores válidos: {', '.join(SUPPORTED_TYPES_SET)}"
                )
            row['router_type'] = rtype

            proto = (row.get('connection_protocol') or 'ssh').lower()
            if proto not in ('ssh', 'telnet'):
                raise ValidationError(f"Protocolo inválido '{proto}' en la línea {line_number}. Use 'ssh' o 'telnet'.")
            row['connection_protocol'] = proto

            mon_val = (row.get('monitoring') or 'true').lower()
            if mon_val in ('1', 'si', 'sí', 'yes', 'true'):
                row['monitoring'] = 'true'
            elif mon_val in ('0', 'no', 'false'):
                row['monitoring'] = 'false'
            else:
                raise ValidationError(f"Valor inválido para 'monitoring' en la línea {line_number}. Use 'true' o 'false'.")

            if not self._is_valid_ip_or_hostname(row['address']):
                raise ValidationError(f"Dirección IP inválida '{row['address']}' en la línea {line_number}.")

            if not row['port'].isdigit() or not (1 <= int(row['port']) <= 65535):
                raise ValidationError(f"Puerto inválido '{row['port']}' en la línea {line_number}.")

            row['backup_profile'] = row.get('backup_profile') or 'default'
            row['router_group'] = row.get('router_group') or ''

            # Auto-create Node (RouterGroup) if it doesn't exist yet!
            if row['router_group']:
                RouterGroup.objects.get_or_create(name=row['router_group'])

            # Ensure backup profile exists (defaulting to 'default')
            if row['backup_profile']:
                BackupProfile.objects.get_or_create(name=row['backup_profile'])

            import_id += 1
            row['import_id'] = import_id
            import_data.append(row)

        if not import_data:
            raise ValidationError("El archivo no contiene ninguna fila de equipos para importar.")

        cleaned_data['import_data'] = import_data
        return cleaned_data

    def _is_valid_ip_or_hostname(self, value):
        ip_pattern = re.compile(r"^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$")
        hostname_pattern = re.compile(r"^(?=.{1,253}$)(?:(?!-)[A-Za-z0-9-]{1,63}(?<!-)\.)+[A-Za-z]{2,6}$")
        return ip_pattern.match(value) or hostname_pattern.match(value)
