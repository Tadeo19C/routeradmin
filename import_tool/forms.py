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
                "Descargue la Plantilla Excel para ver las columnas."
            )

        # Pre-cargar inventario existente para detección inteligente de cambios (diff por campo)
        all_existing_routers = list(
            Router.objects.all().prefetch_related('routergroup_set__category')
        )
        existing_by_name_key = {}
        existing_by_ip = {}
        for er in all_existing_routers:
            existing_by_name_key[canonical_key(er.name)] = er
            if er.address:
                existing_by_ip[er.address.strip().lower()] = er

        seen_ips = set()
        seen_name_keys = set()
        cat_grp_resolver = BatchCategoryGroupResolver()
        import_data = []
        unchanged_count = 0
        import_id = 0

        for line_number, raw_row in enumerate(raw_rows, start=2):
            row = {}
            for orig_k, orig_v in raw_row.items():
                if orig_k in header_map:
                    row[header_map[orig_k]] = (str(orig_v).strip() if orig_v is not None else '')

            if not any(row.values()):
                continue

            address = row.get('address', '').strip().lower()
            if not address:
                continue
            if not self._is_valid_ip_or_hostname(address):
                raise ValidationError(f"Fila {line_number}: Dirección IP o Host inválido ('{address}').")

            if address in seen_ips:
                continue
            seen_ips.add(address)
            row['address'] = address

            name = re.sub(r'\s+', ' ', row.get('name', '').strip())
            if not name:
                name = f"Router_{address.replace('.', '_')}"
            name_key = canonical_key(name)
            if name_key in seen_name_keys:
                name = f"{name} ({address})"
                name_key = canonical_key(name)
            seen_name_keys.add(name_key)
            row['name'] = name

            # Emparejar primero contra dispositivo existente (por Nombre o por IP) para conservar valores actuales si una celda opcional viene vacía
            raw_name_was_given = bool(row.get('name', '').strip())
            matched_router = existing_by_name_key.get(name_key) if raw_name_was_given else None
            if matched_router:
                other_ip_owner = existing_by_ip.get(address)
                if other_ip_owner and other_ip_owner.id != matched_router.id:
                    raise ValidationError(
                        f"Fila {line_number}: No se puede cambiar la IP de '{name}' a '{address}' porque ya pertenece a '{other_ip_owner.name}'."
                    )
            else:
                matched_router = existing_by_ip.get(address)
                if matched_router and not raw_name_was_given:
                    name = matched_router.name
                    row['name'] = name

            cur_g_existing = matched_router.routergroup_set.all()[0] if (matched_router and matched_router.routergroup_set.all()) else None

            raw_user = row.get('username', '').strip()
            row['username'] = raw_user or (matched_router.username if matched_router else 'admin') or 'admin'
            row['password'] = row.get('password') or ''

            # Marca / Fabricante
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
                        normalized_type = 'mikrotik'
            elif matched_router:
                normalized_type = matched_router.router_type
            else:
                normalized_type = 'mikrotik'
            row['router_type'] = normalized_type

            # Protocolo y Puerto (totalmente libre 1-65535 o conservado/automático si viene vacío)
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
                    else:
                        raise ValidationError(f"Fila {line_number}: El puerto '{raw_port}' debe estar entre 1 y 65535.")
                except ValidationError:
                    raise
                except ValueError:
                    raise ValidationError(f"Fila {line_number}: Puerto inválido ('{raw_port}').")

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

            # Categoría y Grupo
            raw_cat = row.get('category_name', '').strip()
            raw_grp = row.get('router_group', '').strip()
            if not raw_cat and cur_g_existing and cur_g_existing.category:
                raw_cat = cur_g_existing.category.name
            if not raw_grp and cur_g_existing:
                raw_grp = cur_g_existing.name
            resolved_cat_name, resolved_grp_name = cat_grp_resolver.resolve(raw_cat, raw_grp, line_number=line_number)
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

                cur_g = matched_router.routergroup_set.all()[0] if matched_router.routergroup_set.all() else None
                cur_cat_name = cur_g.category.name if (cur_g and cur_g.category) else ''
                cur_grp_name = cur_g.name if cur_g else ''

                if cur_cat_name != resolved_cat_name:
                    changes.append({'field': 'Categoría', 'old': cur_cat_name or '---', 'new': resolved_cat_name})
                if cur_grp_name.upper() != resolved_grp_name.upper():
                    changes.append({'field': 'Grupo', 'old': cur_grp_name or '---', 'new': resolved_grp_name})
                if bool(matched_router.monitoring) != mon_bool:
                    changes.append({'field': 'Monitoreo', 'old': 'Sí' if matched_router.monitoring else 'No', 'new': 'Sí' if mon_bool else 'No'})

                # Si todas las columnas son idénticas al equipo actual, omitir en el preview
                if not changes:
                    unchanged_count += 1
                    continue

                row['action_type'] = 'update'
                row['target_router_id'] = matched_router.id
                row['changes'] = changes
            else:
                row['action_type'] = 'new'
                row['target_router_id'] = None
                row['changes'] = []

            import_id += 1
            row['import_id'] = import_id
            import_data.append(row)

        if not import_data and unchanged_count == 0:
            raise ValidationError("El archivo de Excel no contiene filas con dispositivos válidos para importar.")

        cleaned_data['import_data'] = import_data
        cleaned_data['unchanged_count'] = unchanged_count
        cleaned_data['raw_csv_data'] = json.dumps(import_data, ensure_ascii=False)
        return cleaned_data

    def _is_valid_ip_or_hostname(self, value):
        ip_pattern = re.compile(r"^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$")
        hostname_pattern = re.compile(r"^(?=.{1,253}$)(?:(?!-)[A-Za-z0-9-]{1,63}(?<!-)\.)+[A-Za-z]{2,6}$")
        return ip_pattern.match(value) or hostname_pattern.match(value)
