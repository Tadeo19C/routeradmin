import ipaddress
import json
import re
from django import forms
from django.core.exceptions import ValidationError
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout

from backup.models import BackupProfile
from router_manager.models import Router, SUPPORTED_ROUTER_TYPES
from router_manager.normalization import BatchCategoryGroupResolver, canonical_key, strip_accents
from .models import CsvData
from .excel_utils import parse_excel_or_csv_bytes

SUPPORTED_TYPES_SET = [rt[0] for rt in SUPPORTED_ROUTER_TYPES]

HEADER_SYNONYMS = {
    'nombre': 'name', 'equipo': 'name', 'dispositivo': 'name', 'router': 'name', 'hostname': 'name', 'name': 'name',
    'ip': 'address', 'direccion': 'address', 'direccion_ip': 'address', 'dirección ip': 'address', 'direccion ip': 'address', 'address': 'address', 'host': 'address',
    'usuario': 'username', 'user': 'username', 'login': 'username', 'username': 'username',
    'password': 'password', 'contraseña': 'password', 'contrasena': 'password', 'clave': 'password', 'pass': 'password', 'pwd': 'password',
    'marca': 'router_type', 'tipo': 'router_type', 'fabricante': 'router_type', 'vendor': 'router_type', 'router_type': 'router_type',
    'protocolo': 'connection_protocol', 'protocol': 'connection_protocol', 'connection_protocol': 'connection_protocol', 'proto': 'connection_protocol',
    'puerto': 'port', 'port': 'port',
    'grupo': 'router_group', 'group': 'router_group', 'nodo': 'router_group', 'node': 'router_group', 'zona': 'router_group', 'sitio': 'router_group', 'router_group': 'router_group',
    'categoria': 'category_name', 'categoría': 'category_name', 'category': 'category_name', 'pestana': 'category_name', 'pestaña': 'category_name', 'seccion': 'category_name', 'sección': 'category_name', 'category_name': 'category_name',
    'perfil': 'backup_profile', 'profile': 'backup_profile', 'backup_profile': 'backup_profile',
    'monitoreo': 'monitoring', 'monitoring': 'monitoring',
}

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
        label='Archivo Excel (.xlsx / .csv)',
        widget=forms.FileInput(attrs={
            'accept': '.xlsx,.xls,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel,text/csv',
            'class': 'form-control-file',
        })
    )

    class Meta:
        model = CsvData
        fields = ['csv_file']

    def __init__(self, *args, **kwargs):
        super(CsvDataForm, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.layout = Layout('csv_file')

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
                "Descargue la Plantilla Excel para ver las columnas requeridas."
            )

        all_existing_routers = list(
            Router.objects.all().prefetch_related('routergroup_set__category')
        )
        existing_by_name_key = {}
        existing_by_ip = {}
        for er in all_existing_routers:
            existing_by_name_key[canonical_key(er.name)] = er
            if er.address:
                existing_by_ip[er.address.strip().lower()] = er

        first_ip_line = {}
        first_name_line = {}
        cat_grp_resolver = BatchCategoryGroupResolver()
        import_data = []
        unchanged_count = 0

        for line_number, raw_row in enumerate(raw_rows, start=2):
            row = {}
            for orig_k, orig_v in raw_row.items():
                if orig_k in header_map:
                    row[header_map[orig_k]] = (str(orig_v).strip() if orig_v is not None else '')

            if not any(row.values()):
                continue

            row_errors = []

            # 1. Validar IP y duplicados de IP dentro del mismo Excel
            address = row.get('address', '').strip().lower()
            if not address:
                row_errors.append("Falta la Dirección IP en esta fila.")
            elif not self._is_valid_ip_or_hostname(address):
                row_errors.append(f"Dirección IP o Host con formato inválido ('{address}').")
            elif address in first_ip_line:
                row_errors.append(
                    f"IP duplicada dentro del mismo archivo Excel ('{address}' ya aparece en la fila {first_ip_line[address]})."
                )
            else:
                first_ip_line[address] = line_number
            row['address'] = address or 'SIN-IP'

            # 2. Validar Nombre y duplicados de Nombre dentro del mismo Excel (sin renombrar en silencio)
            raw_name = re.sub(r'\s+', ' ', row.get('name', '').strip())
            raw_name_was_given = bool(raw_name)
            name = raw_name or (f"Router_{address.replace('.', '_')}" if address else f"Fila_{line_number}")
            name_key = canonical_key(name)

            if name_key and name_key in first_name_line:
                row_errors.append(
                    f"Nombre de dispositivo duplicado dentro del mismo archivo Excel ('{name}' ya aparece en la fila {first_name_line[name_key]})."
                )
            elif name_key:
                first_name_line[name_key] = line_number
            row['name'] = name

            # 3. Verificar coincidencias y conflictos contra dispositivos ya registrados en BD
            matched_router = None
            name_match_db = existing_by_name_key.get(name_key) if raw_name_was_given else None
            ip_match_db = existing_by_ip.get(address) if address else None

            if name_match_db and ip_match_db:
                if name_match_db.id == ip_match_db.id:
                    matched_router = name_match_db
                else:
                    row_errors.append(
                        f"Conflicto de duplicado: El nombre '{name}' pertenece al dispositivo ({name_match_db.address}) "
                        f"pero la IP '{address}' ya pertenece a otro dispositivo distinto ('{ip_match_db.name}')."
                    )
            elif name_match_db and not ip_match_db:
                # El dispositivo existe por nombre y está cambiando a una IP libre -> Actualización válida de IP
                matched_router = name_match_db
            elif ip_match_db and not name_match_db:
                if not raw_name_was_given:
                    matched_router = ip_match_db
                    name = matched_router.name
                    row['name'] = name
                else:
                    # Trae un nombre distinto pero usa una IP que YA está ocupada en BD
                    row_errors.append(
                        f"IP duplicada: La dirección '{address}' ya está registrada en el dispositivo '{ip_match_db.name}'."
                    )

            cur_g_existing = matched_router.routergroup_set.all()[0] if (matched_router and matched_router.routergroup_set.all()) else None

            raw_user = row.get('username', '').strip()
            row['username'] = raw_user or (matched_router.username if matched_router else 'admin') or 'admin'
            row['password'] = row.get('password') or ''

            # 4. Marca / Fabricante
            raw_type_cell = row.get('router_type', '').strip()
            if raw_type_cell:
                raw_type = strip_accents(raw_type_cell.lower())
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
                        row_errors.append(f"Fabricante o marca no reconocida ('{raw_type_cell}').")
                        normalized_type = 'mikrotik'
            elif matched_router:
                normalized_type = matched_router.router_type
            else:
                normalized_type = 'mikrotik'
            row['router_type'] = normalized_type

            # 5. Protocolo y Puerto
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
            elif raw_proto == '':
                proto = ''
            else:
                row_errors.append(f"Protocolo inválido ('{raw_proto}'). Use SSH, Telnet o API.")
                proto = 'ssh'

            custom_port = None
            if raw_port:
                try:
                    p_val = int(float(raw_port))
                    if 1 <= p_val <= 65535:
                        custom_port = p_val
                    else:
                        row_errors.append(f"Puerto fuera de rango ('{raw_port}'). Debe estar entre 1 y 65535.")
                except ValueError:
                    row_errors.append(f"Puerto inválido ('{raw_port}'). Debe ser numérico (1 a 65535).")

            if not proto:
                if custom_port is not None:
                    if custom_port in (23, 2323):
                        proto = 'telnet'
                    elif custom_port in (80, 443, 8080, 8443, 10443, 8728, 8729):
                        proto = 'api'
                    else:
                        proto = (matched_router.connection_protocol if matched_router else 'ssh') or 'ssh'
                elif matched_router:
                    proto = (matched_router.connection_protocol or 'ssh').lower()
                else:
                    proto = 'ssh'

            if custom_port is not None:
                port = custom_port
            elif matched_router and not raw_proto:
                port = int(matched_router.port or 22)
            elif matched_router and raw_proto and proto == (matched_router.connection_protocol or 'ssh').lower():
                port = int(matched_router.port or 22)
            else:
                if proto == 'telnet':
                    port = 23
                elif proto == 'api':
                    port = 443 if normalized_type == 'fortinet' else (8728 if normalized_type == 'mikrotik' else 80)
                else:
                    port = 22

            row['connection_protocol'] = proto
            row['port'] = port

            # 6. Categoría (debe existir previamente en Dispositivos) y Grupo
            raw_cat = row.get('category_name', '').strip()
            raw_grp = row.get('router_group', '').strip()
            if not raw_cat and cur_g_existing and cur_g_existing.category:
                raw_cat = cur_g_existing.category.name
            if not raw_grp and cur_g_existing:
                raw_grp = cur_g_existing.name

            resolved_cat_name, resolved_grp_name, cat_err = cat_grp_resolver.resolve_with_error(raw_cat, raw_grp)
            if cat_err:
                row_errors.append(cat_err)
            row['category_name'] = resolved_cat_name
            row['router_group'] = resolved_grp_name

            row['backup_profile'] = row.get('backup_profile') or 'default'
            BackupProfile.objects.get_or_create(name=row['backup_profile'])

            raw_mon = row.get('monitoring', '').strip().lower()
            if raw_mon:
                mon_bool = False if raw_mon in ('0', 'no', 'false') else True
            elif matched_router:
                mon_bool = bool(matched_router.monitoring)
            else:
                mon_bool = True
            row['monitoring'] = 'true' if mon_bool else 'false'

            row['import_id'] = line_number

            # Si esta fila tiene errores de validación/duplicados, incluirla en ROJO en el Preview explicando exactamente por qué
            if row_errors:
                row['action_type'] = 'error'
                row['target_router_id'] = None
                row['changes'] = []
                row['error_message'] = ' | '.join(row_errors)
                import_data.append(row)
                continue

            if matched_router:
                changes = []
                if matched_router.name != name:
                    changes.append({'field': 'Nombre', 'old': matched_router.name, 'new': name})
                if (matched_router.address or '').strip().lower() != address:
                    changes.append({'field': 'IP', 'old': matched_router.address, 'new': address})
                if (matched_router.username or 'admin') != row['username']:
                    changes.append({'field': 'Usuario', 'old': matched_router.username or 'admin', 'new': row['username']})
                if row['password'] and (matched_router.decrypted_password or '') != row['password']:
                    changes.append({'field': 'Password', 'old': '••••••', 'new': 'Actualizada'})
                if (matched_router.router_type or '').lower() != normalized_type:
                    changes.append({'field': 'Marca', 'old': matched_router.router_type, 'new': normalized_type})
                if (matched_router.connection_protocol or 'ssh').lower() != proto:
                    changes.append({'field': 'Protocolo', 'old': (matched_router.connection_protocol or 'ssh').upper(), 'new': proto.upper()})
                if int(matched_router.port or 22) != int(port):
                    changes.append({'field': 'Puerto', 'old': str(matched_router.port or 22), 'new': str(port)})

                cur_cat_name = cur_g_existing.category.name if (cur_g_existing and cur_g_existing.category) else ''
                cur_grp_name = cur_g_existing.name if cur_g_existing else ''

                if cur_cat_name != resolved_cat_name:
                    changes.append({'field': 'Categoría', 'old': cur_cat_name or '---', 'new': resolved_cat_name})
                if cur_grp_name.upper() != resolved_grp_name.upper():
                    changes.append({'field': 'Grupo', 'old': cur_grp_name or '---', 'new': resolved_grp_name})
                if bool(matched_router.monitoring) != mon_bool:
                    changes.append({'field': 'Monitoreo', 'old': 'Sí' if matched_router.monitoring else 'No', 'new': 'Sí' if mon_bool else 'No'})

                if not changes:
                    unchanged_count += 1
                    continue

                row['action_type'] = 'update'
                row['target_router_id'] = matched_router.id
                row['changes'] = changes
                row['error_message'] = ''
            else:
                row['action_type'] = 'new'
                row['target_router_id'] = None
                row['changes'] = []
                row['error_message'] = ''

            import_data.append(row)

        if not import_data and unchanged_count == 0:
            raise ValidationError("El archivo de Excel no contiene filas con datos para analizar.")

        cleaned_data['import_data'] = import_data
        cleaned_data['unchanged_count'] = unchanged_count
        cleaned_data['raw_csv_data'] = json.dumps(import_data, ensure_ascii=False)
        return cleaned_data

    def _is_valid_ip_or_hostname(self, value):
        try:
            ipaddress.ip_address(value)
            return True
        except ValueError:
            pass
        hostname_pattern = re.compile(r"^(?=.{1,253}$)(?:(?!-)[A-Za-z0-9-]{1,63}(?<!-)\.)+[A-Za-z]{2,6}$")
        return bool(hostname_pattern.match(value))
