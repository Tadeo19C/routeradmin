import re
import html
import ipaddress
from django import forms
from django.conf import settings
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Submit, Row, Column, HTML
from crispy_forms.bootstrap import InlineRadios
from .models import DeviceCategory, Router, RouterGroup, RouterClient
from .normalization import (
    ensure_default_category,
    find_matching_category,
    find_matching_node,
    find_matching_client,
    canonical_key,
    get_category_limit_message,
)
from backup.models import BackupProfile
from routerlib.functions import test_authentication

HOUR_CHOICES_12H = (
    (0, '12:00 AM'), (1, '01:00 AM'), (2, '02:00 AM'), (3, '03:00 AM'), (4, '04:00 AM'), (5, '05:00 AM'), (6, '06:00 AM'), (7, '07:00 AM'),
    (8, '08:00 AM'), (9, '09:00 AM'), (10, '10:00 AM'), (11, '11:00 AM'), (12, '12:00 PM'), (13, '01:00 PM'), (14, '02:00 PM'),
    (15, '03:00 PM'), (16, '04:00 PM'), (17, '05:00 PM'), (18, '06:00 PM'), (19, '07:00 PM'), (20, '08:00 PM'), (21, '09:00 PM'),
    (22, '10:00 PM'), (23, '11:00 PM')
)


class DeviceCategoryForm(forms.ModelForm):
    class Meta:
        model = DeviceCategory
        fields = ['name']
        labels = {'name': 'Nombre de la Categoría'}
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej: Nodos, Clientes, Sucursales, Torres...',
                'autocomplete': 'off',
                'maxlength': '60',
            })
        }

    def clean_name(self):
        name = re.sub(r'\s+', ' ', (self.cleaned_data.get('name') or '').strip())
        if not name:
            raise forms.ValidationError('Debe ingresar un nombre para la categoría.')

        if not self.instance.pk:
            max_cats = getattr(settings, 'MAX_DEVICE_CATEGORIES', 3)
            if DeviceCategory.objects.count() >= max_cats:
                raise forms.ValidationError(get_category_limit_message(name))

        others = DeviceCategory.objects.exclude(pk=self.instance.pk) if self.instance.pk else DeviceCategory.objects.all()
        dup = others.filter(name__iexact=name).first() or find_matching_category(name, queryset=others)
        if dup:
            raise forms.ValidationError(f"Ya existe una categoría equivalente llamada '{dup.name}'.")
        return name


class RouterForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput, required=False)
    category_uuid = forms.CharField(required=False, widget=forms.HiddenInput())
    router_group = forms.ModelChoiceField(
        queryset=RouterGroup.objects.none(),
        required=True,
        empty_label='-- Seleccione un Grupo --',
        label='Grupo'
    )
    backup_profile = forms.ModelChoiceField(
        queryset=BackupProfile.objects.all().order_by('name'),
        required=False,
        widget=forms.HiddenInput()
    )
    custom_daily_minute = forms.IntegerField(required=False, initial=0, widget=forms.HiddenInput())
    custom_weekly_minute = forms.IntegerField(required=False, initial=0, widget=forms.HiddenInput())

    backup_type = forms.ChoiceField(
        required=True,
        label="",
        choices=(('hourly', 'Por Hora'), ('daily', 'Diario'), ('weekly', 'Semanal')),
        widget=forms.RadioSelect,
        initial='daily'
    )
    custom_hourly_interval = forms.ChoiceField(required=False, label="Intervalo", choices=(
        (1, 'Cada 1 hr'), (2, 'Cada 2 hrs'), (4, 'Cada 4 hrs'), (6, 'Cada 6 hrs'), (8, 'Cada 8 hrs'), (12, 'Cada 12 hrs')
    ), initial=6)

    custom_daily_hour = forms.ChoiceField(required=False, label="Hora de Respaldo", choices=HOUR_CHOICES_12H, initial=3)

    custom_weekly_day = forms.ChoiceField(required=False, label="Día Semanal", choices=(
        ('monday', 'Lunes'), ('tuesday', 'Martes'), ('wednesday', 'Miércoles'), ('thursday', 'Jueves'),
        ('friday', 'Viernes'), ('saturday', 'Sábado'), ('sunday', 'Domingo')
    ), initial='sunday')
    custom_weekly_hour = forms.ChoiceField(required=False, label="Hora Semanal", choices=HOUR_CHOICES_12H, initial=1)

    class Meta:
        model = Router
        fields = ['name', 'router_type', 'connection_protocol', 'address', 'port', 'username', 'password', 'monitoring', 'enabled']
        labels = {
            'name': 'Nombre',
            'router_type': 'Fabricante / Tipo',
            'connection_protocol': 'Protocolo',
            'address': 'Dirección IP',
            'port': 'Puerto',
            'username': 'Usuario',
            'password': 'Password',
        }
        widgets = {
            'monitoring': forms.HiddenInput(),
            'enabled': forms.HiddenInput(),
        }

    def __init__(self, *args, category=None, preselect_group=None, **kwargs):
        # Ignorar argumentos heredados si alguna llamada antigua los pasa
        kwargs.pop('scope', None)
        kwargs.pop('preselect_client', None)
        super(RouterForm, self).__init__(*args, **kwargs)

        if category is not None:
            self.category = category
        elif self.instance and self.instance.pk:
            cur_grp = self.instance.routergroup_set.select_related('category').first()
            self.category = cur_grp.category if (cur_grp and cur_grp.category) else ensure_default_category()
        else:
            self.category = ensure_default_category()

        self.initial['category_uuid'] = str(self.category.uuid)
        self.fields['category_uuid'].initial = str(self.category.uuid)

        cat_groups_qs = RouterGroup.objects.filter(category=self.category).order_by('name')
        self.fields['router_group'].queryset = cat_groups_qs
        self.fields['router_group'].label = f"Grupo ({self.category.name})"
        self.fields['router_group'].empty_label = f"-- Seleccione un Grupo en {self.category.name} --"
        self.fields['router_group'].required = True

        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.form_method = 'post'
        self.helper.label_class = 'small font-weight-bold text-primary mb-1'
        self.helper.form_error_title = 'Error'

        for field in self.fields:
            if not isinstance(self.fields[field].widget, (forms.HiddenInput, forms.RadioSelect, forms.CheckboxInput)):
                self.fields[field].widget.attrs['class'] = 'form-control form-control-sm'

        if self.instance.pk:
            safe_js_name = str(self.instance.name or '').replace("\\", "\\\\").replace("'", "\\'")
            delete_html = f"<a href='javascript:void(0)' class='btn btn-outline-danger btn-sm ml-1' onclick=\"confirmDeleteRouter('{self.instance.uuid}', '{safe_js_name}')\">Borrar</a>"
            if self.instance.password:
                self.fields['password'].widget.attrs['placeholder'] = '************'
            current_group = self.instance.routergroup_set.filter(category=self.category).first() or self.instance.routergroup_set.first()
            if current_group:
                self.fields['router_group'].initial = current_group

            if self.instance.backup_profile:
                profile = self.instance.backup_profile
                if profile.hourly_backup:
                    self.initial['backup_type'] = 'hourly'
                elif profile.daily_backup:
                    self.initial['backup_type'] = 'daily'
                elif profile.weekly_backup:
                    self.initial['backup_type'] = 'weekly'
                else:
                    self.initial['backup_type'] = 'none'

                self.initial['custom_hourly_interval'] = profile.hourly_interval
                self.initial['custom_daily_hour'] = profile.daily_hour
                self.initial['custom_daily_minute'] = getattr(profile, 'daily_minute', 0) or 0
                self.initial['custom_weekly_day'] = profile.weekly_day
                self.initial['custom_weekly_hour'] = profile.weekly_hour
                self.initial['custom_weekly_minute'] = getattr(profile, 'weekly_minute', 0) or 0
        else:
            delete_html = ''
            default_prof = BackupProfile.objects.filter(name='default').first() or BackupProfile.objects.first()
            if default_prof:
                self.fields['backup_profile'].initial = default_prof
            if preselect_group and preselect_group.category_id == self.category.id:
                self.fields['router_group'].initial = preselect_group
            else:
                default_grp = cat_groups_qs.filter(default_group=True).first()
                if not default_grp and cat_groups_qs.count() == 1:
                    default_grp = cat_groups_qs.first()
                if default_grp:
                    self.fields['router_group'].initial = default_grp

        self.fields['address'].widget.attrs.update({
            'pattern': r'^(\d{1,3}\.){3}\d{1,3}$',
            'title': 'Ingrese una dirección IP válida (ej. 192.168.1.1). No se admiten letras.',
            'placeholder': '192.168.1.1'
        })
        self.fields['port'].widget.attrs.update({
            'min': '1',
            'max': '65535',
            'list': 'suggested-ports-datalist',
            'autocomplete': 'off',
            'placeholder': 'Ej: 22, 2222, 8728...',
            'title': 'Seleccione o digite libremente cualquier puerto (1 a 65535)'
        })

        self.initial['monitoring'] = True
        self.initial['enabled'] = True
        self.helper.layout = Layout(
            'category_uuid',
            Row(
                Column('name', css_class='form-group col-md-6 mb-2'),
                Column('router_type', css_class='form-group col-md-6 mb-2'),
                css_class='form-row'
            ),
            Row(
                Column('address', css_class='form-group col-md-6 mb-2'),
                Column('connection_protocol', css_class='form-group col-md-3 mb-2'),
                Column('port', css_class='form-group col-md-3 mb-2'),
                css_class='form-row'
            ),
            Row(
                Column('router_group', css_class='form-group col-md-12 mb-2'),
                css_class='form-row'
            ),
            Row(
                Column('username', css_class='form-group col-md-4 mb-2'),
                Column('password', css_class='form-group col-md-5 mb-2'),
                Column(
                    HTML('<div class="form-group mb-2"><label class="small mb-1 d-block">&nbsp;</label><button type="button" id="btn-test-connection" class="btn btn-outline-info btn-sm btn-block"><i class="fas fa-plug mr-1"></i> Probar Conexión</button></div>'),
                    css_class='col-md-3'
                ),
                css_class='form-row'
            ),
            HTML('<hr class="my-2">'),
            'backup_profile',
            'custom_daily_minute',
            'custom_weekly_minute',
            HTML('<div class="text-center mb-1"><span class="small font-weight-bold text-uppercase text-muted" style="letter-spacing:0.4px;"><i class="far fa-calendar-check text-primary mr-1"></i> Frecuencia de Respaldo</span></div>'),
            Row(
                Column(InlineRadios('backup_type'), css_class='col-12 text-center mb-1'),
                css_class='form-row'
            ),
            Row(
                Column('custom_hourly_interval', css_class='col-md-5'),
                Column('custom_daily_hour', css_class='col-md-5'),
                Column('custom_weekly_day', 'custom_weekly_hour', css_class='col-md-5'),
                css_class='form-row justify-content-center'
            ),
            'monitoring',
            'enabled',
            HTML('<hr class="my-2">'),
            Row(
                Column(
                    HTML('<button type="button" class="btn btn-outline-secondary btn-sm mr-1" data-dismiss="modal">Cancelar</button>'),
                    Submit('submit', 'Guardar Dispositivo', css_class='btn btn-success btn-sm font-weight-bold px-3'),
                    HTML(delete_html),
                    css_class='col-md-12 text-right'
                ),
                css_class='form-row mt-2'
            )
        )

    def clean(self):
        cleaned_data = super().clean()
        name = cleaned_data.get('name')
        username = cleaned_data.get('username')
        password = cleaned_data.get('password')
        address = cleaned_data.get('address')
        router_type = cleaned_data.get('router_type')
        port = cleaned_data.get('port')

        if address:
            address = address.lower().strip()
            cleaned_data['address'] = address
            try:
                ipaddress.ip_address(address)
            except ValueError:
                raise forms.ValidationError('Formato inválido. Solo se permiten direcciones IP numéricas válidas (ej. 192.168.1.1). No se admiten nombres ni letras.')

            qs = Router.objects.filter(address=address)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError('Ya existe un dispositivo registrado con esta dirección IP.')

        if name:
            name = re.sub(r'\s+', ' ', name.strip())
            cleaned_data['name'] = name
            qs = Router.objects.all()
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            target_ck = canonical_key(name)
            for existing_r in qs.only('id', 'name'):
                if canonical_key(existing_r.name) == target_ck:
                    raise forms.ValidationError(f"Ya existe un dispositivo registrado con un nombre equivalente ('{existing_r.name}').")

        if not port:
            raise forms.ValidationError('Debe proporcionar un puerto.')
        if not 1 <= port <= 65535:
            raise forms.ValidationError('Número de puerto inválido (debe estar entre 1 y 65535).')
        if not username:
            raise forms.ValidationError('Debe proporcionar un nombre de usuario.')
        if not password and not self.instance.password:
            raise forms.ValidationError('Debe proporcionar una contraseña para este tipo de dispositivo.')

        if not password and self.instance.password:
            cleaned_data['password'] = self.instance.password
        connection_protocol = cleaned_data.get('connection_protocol') or 'ssh'
        test_authentication_success, test_authentication_message = test_authentication(
            router_type, cleaned_data['address'], port, username, cleaned_data['password'],
            connection_protocol=connection_protocol
        )
        if not test_authentication_success:
            if test_authentication_message:
                raise forms.ValidationError('No se pudo autenticar: ' + test_authentication_message)
            else:
                raise forms.ValidationError('No se pudo autenticar con el dispositivo. Por favor verifique las credenciales e intente de nuevo.')
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)

        backup_type = self.cleaned_data.get('backup_type')
        backup_profile = self.cleaned_data.get('backup_profile')

        if backup_profile:
            instance.backup_profile = backup_profile
        elif backup_type and backup_type != 'none':
            profile_name = f"Perfil Automático - {instance.name}"
            existing_prof = instance.backup_profile
            if existing_prof and existing_prof.name.startswith("Perfil Automático -") and existing_prof.router_set.exclude(pk=instance.pk).count() == 0:
                profile = existing_prof
                if profile.name != profile_name and not BackupProfile.objects.filter(name=profile_name).exclude(pk=profile.pk).exists():
                    profile.name = profile_name
            else:
                profile, _ = BackupProfile.objects.get_or_create(name=profile_name)

            profile.hourly_backup = False
            profile.daily_backup = False
            profile.weekly_backup = False

            if backup_type == 'hourly':
                profile.hourly_backup = True
                profile.hourly_interval = self.cleaned_data.get('custom_hourly_interval')
            elif backup_type == 'daily':
                profile.daily_backup = True
                profile.daily_hour = self.cleaned_data.get('custom_daily_hour')
                profile.daily_minute = self.cleaned_data.get('custom_daily_minute') or 0
            elif backup_type == 'weekly':
                profile.weekly_backup = True
                profile.weekly_day = self.cleaned_data.get('custom_weekly_day')
                profile.weekly_hour = self.cleaned_data.get('custom_weekly_hour')
                profile.weekly_minute = self.cleaned_data.get('custom_weekly_minute') or 0

            profile.save()
            instance.backup_profile = profile
        else:
            if instance.backup_profile and instance.backup_profile.name.startswith("Perfil Automático"):
                instance.backup_profile = None

        if commit:
            instance.save()
            BackupProfile.objects.filter(name__startswith="Perfil Automático -", router__isnull=True).delete()
        return instance


class RouterGroupForm(forms.ModelForm):
    routers = forms.ModelMultipleChoiceField(
        queryset=Router.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple(),
        label='Dispositivos'
    )

    class Meta:
        model = RouterGroup
        fields = ['name', 'default_group', 'internal_notes', 'routers']
        labels = {
            'name': 'Nombre del Grupo',
            'default_group': 'Grupo por Defecto',
            'internal_notes': 'Notas Internas',
            'routers': 'Dispositivos',
        }
        help_texts = {
            'name': 'Se guardará automáticamente en MAYÚSCULAS como nombre único en esta categoría.',
        }
        widgets = {
            'name': forms.TextInput(attrs={
                'placeholder': 'EJ: MANAGUA, CRUCERO, POLICÍA, SUCURSAL NORTE...',
                'autocomplete': 'off',
                'style': 'text-transform: uppercase; font-weight: 600; letter-spacing: 0.4px;',
                'oninput': 'this.value = this.value.toUpperCase();',
            }),
            'internal_notes': forms.Textarea(attrs={'rows': 3, 'cols': 40, 'placeholder': 'Ubicación, referencia o notas internas (opcional)'}),
        }

    def __init__(self, *args, category=None, next_url='', **kwargs):
        super(RouterGroupForm, self).__init__(*args, **kwargs)
        if category is not None:
            self.category = category
        elif self.instance and self.instance.pk and self.instance.category:
            self.category = self.instance.category
        else:
            self.category = ensure_default_category()

        # Solo dispositivos pertenecientes a esta misma Categoría
        self.fields['routers'].queryset = Router.objects.filter(
            routergroup__category=self.category
        ).distinct().order_by('name')

        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.form_class = 'form-horizontal'
        self.helper.label_class = 'col-sm-3 col-form-label font-weight-bold text-sm-right'
        self.helper.field_class = 'col-sm-9'

        default_back = f'/router/group_list/?category={self.category.uuid}'
        back_href = html.escape(next_url or default_back)
        next_hidden = f'<input type="hidden" name="next" value="{html.escape(next_url)}">' if next_url else ''
        cat_hidden = f'<input type="hidden" name="category" value="{self.category.uuid}">'
        if self.instance.pk:
            delete_html = "<a href='javascript:void(0)' class='btn btn-outline-danger btn-sm ml-1' data-command='delete' onclick='openCommandDialog(this)'>Borrar</a>"
        else:
            delete_html = ''

        self.helper.layout = Layout(
            HTML(cat_hidden + next_hidden),
            'name',
            'internal_notes',
            'routers',
            'default_group',
            Row(
                Column(
                    Submit('submit', 'Guardar Grupo', css_class='btn btn-success btn-sm font-weight-bold px-3'),
                    HTML(f' <a class="btn btn-secondary btn-sm ml-1" href="{back_href}">Atrás</a> '),
                    HTML(delete_html),
                    css_class='col-md-12 text-right'
                ),
                css_class='form-row mt-3 pt-2 border-top'
            )
        )

    def clean(self):
        cleaned_data = super().clean()
        name = cleaned_data.get('name')
        default_group = cleaned_data.get('default_group')

        if name:
            name = re.sub(r'\s+', ' ', name.strip()).upper()
            cleaned_data['name'] = name
            other_groups = RouterGroup.objects.filter(category=self.category)
            if self.instance.pk:
                other_groups = other_groups.exclude(pk=self.instance.pk)
            exact_dup = other_groups.filter(name__iexact=name).first()
            dup_group = exact_dup or find_matching_node(name, queryset=other_groups)
            if dup_group:
                raise forms.ValidationError(
                    f"Ya existe este grupo registrado en '{self.category.name}' como '{dup_group.name}'."
                )

        if default_group:
            RouterGroup.objects.filter(category=self.category, default_group=True).update(default_group=False)
        return cleaned_data

    def save(self, commit=True):
        prev_routers = list(self.instance.routers.all()) if self.instance.pk else []
        instance = super().save(commit=False)
        instance.category = self.category
        if commit:
            instance.save()
            selected_routers = list(self.cleaned_data.get('routers') or [])
            # Mover los seleccionados a este grupo (quitándolos de otros grupos para no duplicar pertenencia)
            for r in selected_routers:
                for other_g in RouterGroup.objects.filter(routers=r).exclude(pk=instance.pk):
                    other_g.routers.remove(r)
                instance.routers.add(r)
            # Evitar dispositivos huérfanos ("SIN NODO ASIGNADO"): solo remover si ya pertenece a otro grupo
            selected_ids = {r.id for r in selected_routers}
            for old_r in prev_routers:
                if old_r.id not in selected_ids:
                    if RouterGroup.objects.filter(routers=old_r).exclude(pk=instance.pk).exists():
                        instance.routers.remove(old_r)
        return instance


class RouterClientForm(RouterGroupForm):
    """Alias compatible hacia atrás con el nuevo sistema unificado de Categorías."""
    pass
