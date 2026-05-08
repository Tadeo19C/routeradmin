from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Submit, Row, Column, HTML, Field
from crispy_forms.bootstrap import InlineRadios
from django.core.validators import RegexValidator
from .models import Router, RouterGroup
from backup.models import BackupProfile, HOUR_CHOICES
from routerlib.functions import test_authentication, connect_to_ssh
import ipaddress
import socket

HOUR_CHOICES_12H = (
    (0, '12:00 AM'), (1, '01:00 AM'), (2, '02:00 AM'), (3, '03:00 AM'), (4, '04:00 AM'), (5, '05:00 AM'), (6, '06:00 AM'), (7, '07:00 AM'),
    (8, '08:00 AM'), (9, '09:00 AM'), (10, '10:00 AM'), (11, '11:00 AM'), (12, '12:00 PM'), (13, '01:00 PM'), (14, '02:00 PM'),
    (15, '03:00 PM'), (16, '04:00 PM'), (17, '05:00 PM'), (18, '06:00 PM'), (19, '07:00 PM'), (20, '08:00 PM'), (21, '09:00 PM'),
    (22, '10:00 PM'), (23, '11:00 PM')
)



class RouterForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput, required=False)
    router_group = forms.ModelChoiceField(
        queryset=RouterGroup.objects.all().order_by('name'),
        required=True,
        empty_label='-- Seleccione un Nodo --',
        label='Nodo'
    )
    backup_profile = forms.ModelChoiceField(
        queryset=BackupProfile.objects.all().order_by('name'),
        required=False,
        empty_label='-- Configuración Personalizada --',
        label='Perfil de Respaldo'
    )
    
    backup_type = forms.ChoiceField(
        required=True, 
        label="", # Quitar label para centrarlo mejor
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
            'router_type': 'Tipo de Equipo',
            'connection_protocol': 'Protocolo',
            'address': 'Dirección IP',
            'port': 'Puerto',
            'username': 'Usuario',
            'password': 'Contraseña',
        }
        widgets = {
            'monitoring': forms.HiddenInput(),
            'enabled': forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super(RouterForm, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.form_method = 'post'
        self.helper.form_class = 'form-horizontal'
        self.helper.label_class = 'col-sm-4 col-form-label col-form-label-sm font-weight-bold text-primary mb-0'
        self.helper.field_class = 'col-sm-8'
        self.helper.form_error_title = 'Error'
        
        # Simple class assignment
        for field in self.fields:
            if not isinstance(self.fields[field].widget, forms.HiddenInput):
                self.fields[field].widget.attrs['class'] = 'form-control form-control-sm'
        if self.instance.pk:
            delete_html = "<a href='javascript:void(0)' class='btn btn-outline-danger' data-command='delete' onclick='openCommandDialog(this)'>Borrar</a>"
            if self.instance.password:
                self.fields['password'].widget.attrs['placeholder'] = '************'
            # Pre-select the current group if the router belongs to one
            current_group = self.instance.routergroup_set.first()
            if current_group:
                self.fields['router_group'].initial = current_group
            
            # Populate custom backup fields from the assigned profile
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
                self.initial['custom_weekly_day'] = profile.weekly_day
                self.initial['custom_weekly_hour'] = profile.weekly_hour
        else:
            delete_html = ''

        # Client-side IP Validation
        self.fields['address'].widget.attrs.update({
            'pattern': r'^(\d{1,3}\.){3}\d{1,3}$',
            'title': 'Ingrese una dirección IP válida (ej. 192.168.1.1). No se admiten letras.',
            'placeholder': '192.168.1.1'
        })

        self.initial['monitoring'] = True
        self.initial['enabled'] = True
        self.helper.layout = Layout(
            Row(
                Column('name', css_class='form-group col-md-6 mb-2'),
                Column('router_type', css_class='form-group col-md-6 mb-2'),
                css_class='form-row'
            ),
            Row(
                Column('address', css_class='form-group col-md-6 mb-2'),
                Column('port', css_class='form-group col-md-6 mb-2'),
                css_class='form-row'
            ),
            Row(
                Column('connection_protocol', css_class='form-group col-md-6 mb-2'),
                Column('router_group', css_class='form-group col-md-6 mb-2'),
                css_class='form-row'
            ),
            Row(
                Column('username', css_class='form-group col-md-4 mb-2'),
                Column('password', css_class='form-group col-md-4 mb-2'),
                Column(
                    HTML('<div class="form-group mb-2"><label>&nbsp;</label><div><button type="button" id="btn-test-connection" class="btn btn-outline-info btn-sm btn-block"><i class="fas fa-plug"></i> Probar Conexión</button></div></div>'),
                    css_class='col-md-4'
                ),
                css_class='form-row align-items-end'
            ),
            HTML('<hr class="my-3">'),
            'backup_profile',
            'backup_type',
            # Sub-campos de configuración
            Row(
                Column('custom_hourly_interval', css_class='col-md-4'),
                Column('custom_daily_hour', css_class='col-md-4'),
                Column('custom_weekly_day', 'custom_weekly_hour', css_class='col-md-4'),
                css_class='form-row'
            ),
            'monitoring',
            'enabled',
            Row(
                Column(
                    Submit('submit', 'Guardar Equipo', css_class='btn btn-success btn-sm'),
                    HTML(delete_html),
                    css_class='col-md-12 text-right'),
                css_class='form-row mt-3'
            )
        )

    def clean(self):
        cleaned_data = super().clean()
        name = cleaned_data.get('name')
        username = cleaned_data.get('username')
        password = cleaned_data.get('password')
        address = cleaned_data.get('address')
        router_type = cleaned_data.get('router_type')
        backup_profile = cleaned_data.get('backup_profile')
        port = cleaned_data.get('port')

        if address:
            address = address.lower().strip()
            cleaned_data['address'] = address

            try:
                ipaddress.ip_address(address)
            except ValueError:
                raise forms.ValidationError('Formato inválido. Solo se permiten direcciones IP numéricas válidas (ej. 192.168.1.1). No se admiten nombres ni letras.')

            # Check for unique IP
            qs = Router.objects.filter(address=address)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError('Ya existe un equipo registrado con esta dirección IP.')

        if name:
            name = name.strip()
            cleaned_data['name'] = name
            
            # Check for unique name
            qs = Router.objects.filter(name=name)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError('Ya existe un equipo registrado con este nombre.')

        if not port:
            raise forms.ValidationError('Debe proporcionar un puerto.')
        if not 1 <= port <= 65535:
            raise forms.ValidationError('Número de puerto inválido (debe estar entre 1 y 65535).')
        if not username:
            raise forms.ValidationError('Debe proporcionar un nombre de usuario.')
        if not password and not self.instance.password:
            raise forms.ValidationError('Debe proporcionar una contraseña para este tipo de equipo.')

        if not password and self.instance.password:
            cleaned_data['password'] = self.instance.password

        test_authentication_success, test_authentication_message = test_authentication(
            router_type, cleaned_data['address'], port, username, cleaned_data['password']
        )
        if not test_authentication_success:
            if test_authentication_message:
                raise forms.ValidationError('No se pudo autenticar: ' + test_authentication_message)
            else:
                raise forms.ValidationError('No se pudo autenticar con el router. Por favor verifique las credenciales e intente de nuevo.')
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        
        backup_type = self.cleaned_data.get('backup_type')
        backup_profile = self.cleaned_data.get('backup_profile')
        
        if backup_profile:
            # Si seleccionó un perfil, usamos ese.
            instance.backup_profile = backup_profile
            # Opcional: Podríamos verificar si el usuario modificó los campos custom
            # y en ese caso crear un perfil nuevo, pero por ahora simplificamos.
        elif backup_type and backup_type != 'none':
            profile_name = f"Perfil Automático - {instance.name}"
            profile, created = BackupProfile.objects.get_or_create(name=profile_name)
            
            # Reset all then set the selected one
            profile.hourly_backup = False
            profile.daily_backup = False
            profile.weekly_backup = False

            if backup_type == 'hourly':
                profile.hourly_backup = True
                profile.hourly_interval = self.cleaned_data.get('custom_hourly_interval')
            elif backup_type == 'daily':
                profile.daily_backup = True
                profile.daily_hour = self.cleaned_data.get('custom_daily_hour')
            elif backup_type == 'weekly':
                profile.weekly_backup = True
                profile.weekly_day = self.cleaned_data.get('custom_weekly_day')
                profile.weekly_hour = self.cleaned_data.get('custom_weekly_hour')
                
            profile.save()
            instance.backup_profile = profile
        else:
            # Si no hay respaldo, desvinculamos el perfil automático
            if instance.backup_profile and instance.backup_profile.name.startswith("Perfil Automático"):
                instance.backup_profile = None
            
        if commit:
            instance.save()
        return instance

class RouterGroupForm(forms.ModelForm):
    class Meta:
        model = RouterGroup
        fields = ['name', 'default_group', 'internal_notes', 'routers']
        labels = {
            'name': 'Nombre',
            'default_group': 'Nodo por Defecto',
            'internal_notes': 'Notas Internas',
            'routers': 'Equipos',
        }
        widgets = {
            'internal_notes': forms.Textarea(attrs={'rows': 4, 'cols': 40}),  # Define como um Textarea simples
        }

    def __init__(self, *args, **kwargs):
        super(RouterGroupForm, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.form_class = 'form-horizontal'
        self.helper.label_class = 'col-sm-3 col-form-label font-weight-bold text-right'
        self.helper.field_class = 'col-sm-9'
        if self.instance.pk:
            delete_html = "<a href='javascript:void(0)' class='btn btn-outline-danger' data-command='delete' onclick='openCommandDialog(this)'>Borrar</a>"
        else:
            delete_html = ''
        self.helper.layout = Layout(
            'name',
            'internal_notes',
            'routers',
            'default_group',
            Row(
                Column(
                    Submit('submit', 'Guardar Nodo', css_class='btn btn-success btn-sm'),
                    HTML(' <a class="btn btn-secondary btn-sm" href="/router/group_list/">Atrás</a> '),
                    HTML(delete_html),
                    css_class='col-md-12 text-right'),
                css_class='form-row mt-3'
            )
        )

    def clean(self):
        cleaned_data = super().clean()
        name = cleaned_data.get('name')
        default_group = cleaned_data.get('default_group')

        if name:
            name = name.strip()
            cleaned_data['name'] = name

        if default_group:
            RouterGroup.objects.filter(default_group=True).update(default_group=False)
        return cleaned_data
