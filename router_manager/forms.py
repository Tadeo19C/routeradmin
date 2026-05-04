from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Submit, Row, Column, HTML
from django.core.validators import RegexValidator
from .models import Router, RouterGroup
from backup.models import BackupProfile, HOUR_CHOICES
from routerlib.functions import test_authentication, connect_to_ssh
import ipaddress
import socket


class RouterForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput, required=False)
    router_group = forms.ModelChoiceField(
        queryset=RouterGroup.objects.all().order_by('name'),
        required=False,
        empty_label='-- Sin nodo --',
        label='Nodo'
    )
    
    use_custom_backup = forms.BooleanField(required=False, label="Configurar Respaldo Automático")
    custom_hourly = forms.BooleanField(required=False, label="Respaldo por Hora")
    custom_hourly_interval = forms.ChoiceField(required=False, label="Intervalo", choices=(
        (1, 'Cada 1 hr'), (2, 'Cada 2 hrs'), (4, 'Cada 4 hrs'), (6, 'Cada 6 hrs'), (8, 'Cada 8 hrs'), (12, 'Cada 12 hrs')
    ), initial=6)

    custom_daily = forms.BooleanField(required=False, label="Respaldo Diario")
    custom_daily_hour = forms.ChoiceField(required=False, label="Hora de Respaldo", choices=HOUR_CHOICES, initial=3)

    custom_weekly = forms.BooleanField(required=False, label="Respaldo Semanal")
    custom_weekly_day = forms.ChoiceField(required=False, label="Día Semanal", choices=(
        ('monday', 'Lunes'), ('tuesday', 'Martes'), ('wednesday', 'Miércoles'), ('thursday', 'Jueves'), 
        ('friday', 'Viernes'), ('saturday', 'Sábado'), ('sunday', 'Domingo')
    ), initial='sunday')
    custom_weekly_hour = forms.ChoiceField(required=False, label="Hora Semanal", choices=HOUR_CHOICES, initial=1)

    class Meta:
        model = Router
        fields = ['name', 'connection_protocol', 'port', 'address', 'username', 'password', 'monitoring', 'router_type', 'enabled', 'backup_profile']
        widgets = {
            'monitoring': forms.HiddenInput(),
            'enabled': forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super(RouterForm, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.form_method = 'post'
        if self.instance.pk:
            delete_html = "<a href='javascript:void(0)' class='btn btn-outline-danger' data-command='delete' onclick='openCommandDialog(this)'>Delete</a>"
            if self.instance.password:
                self.fields['password'].widget.attrs['placeholder'] = '************'
            # Pre-select the current group if the router belongs to one
            current_group = self.instance.routergroup_set.first()
            if current_group:
                self.fields['router_group'].initial = current_group
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
                Column('name', css_class='form-group col-md-8 mb-0'),
                Column('router_type', css_class='form-group col-md-4 mb-0'),
                css_class='form-row'
            ),
            Row(
                Column('address', css_class='form-group col-md-4 mb-0'),
                Column('connection_protocol', css_class='form-group col-md-4 mb-0'),
                Column('port', css_class='form-group col-md-4 mb-0'),
                css_class='form-row'
            ),
            Row(
                Column('username', css_class='form-group col-md-6 mb-0'),
                Column('password', css_class='form-group col-md-6 mb-0'),
                css_class='form-row'
            ),
            Row(
                Column('router_group', css_class='form-group col-md-6 mb-0'),
                Column('backup_profile', css_class='form-group col-md-6 mb-0'),
                css_class='form-row'
            ),
            Row(
                Column('use_custom_backup', css_class='form-group col-md-12 mb-0 font-weight-bold float-right d-flex justify-content-end'),
                css_class='form-row'
            ),
            Row(
                Column('custom_hourly', 'custom_hourly_interval', css_class='form-group col-md-4 mb-0 custom-backup-fields'),
                Column('custom_daily', 'custom_daily_hour', css_class='form-group col-md-4 mb-0 custom-backup-fields'),
                Column('custom_weekly', 'custom_weekly_day', 'custom_weekly_hour', css_class='form-group col-md-4 mb-0 custom-backup-fields'),
                css_class='form-row'
            ),
            'monitoring',
            'enabled',
            Row(
                Column(
                    Submit('submit', 'Save', css_class='btn btn-success'),
                    HTML(delete_html),
                    css_class='col-md-12'),
                css_class='form-row'
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

        if name:
            name = name.strip()
            cleaned_data['name'] = name

        if address:
            address = address.lower().strip()
            cleaned_data['address'] = address

            try:
                ipaddress.ip_address(address)
            except ValueError:
                raise forms.ValidationError('Formato inválido. Solo se permiten direcciones IP numéricas válidas (ej. 192.168.1.1). No se admiten nombres ni letras.')

        if router_type == 'monitoring':
            cleaned_data['password'] = ''
            if backup_profile or cleaned_data.get('use_custom_backup'):
                raise forms.ValidationError('Monitoring only routers cannot have a backup profile')
            return cleaned_data
        else:
            if not port:
                raise forms.ValidationError('You must provide a port')
            if not 1 <= port <= 65535:
                raise forms.ValidationError('Invalid port number')

        if not password and not self.instance.password:
            raise forms.ValidationError('You must provide a password')

        if not password and self.instance.password:
            cleaned_data['password'] = self.instance.password

        test_authentication_success, test_authentication_message = test_authentication(
            router_type, cleaned_data['address'], port, username, cleaned_data['password']
        )
        if not test_authentication_success:
            if test_authentication_message:
                raise forms.ValidationError('Could not authenticate: ' + test_authentication_message)
            else:
                raise forms.ValidationError('Could not authenticate to the router. Please check the credentials and try again.')
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.cleaned_data.get('use_custom_backup'):
            profile_name = f"Perfil Automático - {instance.name}"
            # Se create or get
            profile, created = BackupProfile.objects.get_or_create(name=profile_name)
            
            profile.hourly_backup = self.cleaned_data.get('custom_hourly', False)
            if profile.hourly_backup:
                profile.hourly_interval = self.cleaned_data.get('custom_hourly_interval')
                
            profile.daily_backup = self.cleaned_data.get('custom_daily', False)
            if profile.daily_backup:
                profile.daily_hour = self.cleaned_data.get('custom_daily_hour')
                
            profile.weekly_backup = self.cleaned_data.get('custom_weekly', False)
            if profile.weekly_backup:
                profile.weekly_day = self.cleaned_data.get('custom_weekly_day')
                profile.weekly_hour = self.cleaned_data.get('custom_weekly_hour')
                
            profile.save()
            instance.backup_profile = profile
            
        if commit:
            instance.save()
        return instance

class RouterGroupForm(forms.ModelForm):
    class Meta:
        model = RouterGroup
        fields = ['name', 'default_group', 'internal_notes', 'routers']
        widgets = {
            'internal_notes': forms.Textarea(attrs={'rows': 4, 'cols': 40}),  # Define como um Textarea simples
        }

    def __init__(self, *args, **kwargs):
        super(RouterGroupForm, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        if self.instance.pk:
            delete_html = "<a href='javascript:void(0)' class='btn btn-outline-danger' data-command='delete' onclick='openCommandDialog(this)'>Delete</a>"
        else:
            delete_html = ''
        self.helper.layout = Layout(
            'name',
            'internal_notes',
            'routers',
            'default_group',
            Row(
                Column(
                    Submit('submit', 'Save', css_class='btn btn-success'),
                    HTML(' <a class="btn btn-secondary" href="/router/group_list/">Back</a> '),
                    HTML(delete_html),
                    css_class='col-md-12'),
                css_class='form-row'
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
