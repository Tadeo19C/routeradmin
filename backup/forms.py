from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Submit, Row, Column, HTML, Field, Div
from .models import BackupProfile


class BackupProfileForm(forms.ModelForm):
    daily_hour = forms.TimeField(widget=forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}))
    weekly_hour = forms.TimeField(widget=forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}))

    class Meta:
        model = BackupProfile
        fields = [
            'name', 'daily_backup', 'weekly_backup', 'monthly_backup', 'hourly_backup',
            'daily_retention', 'weekly_retention', 'monthly_retention', 'hourly_retention',
            'retain_backups_on_error', 'daily_day_monday', 'daily_day_tuesday',
            'daily_day_wednesday', 'daily_day_thursday', 'daily_day_friday',
            'daily_day_saturday', 'daily_day_sunday', 'weekly_day',
            'monthly_day', 'daily_hour', 'weekly_hour', 'monthly_hour',
            'max_retry', 'retry_interval', 'backup_interval', 'retrieve_interval', 'instant_retention',
            'parameter_sensitive', 'parameter_terse', 'hourly_interval'
        ]
        # widgets = {
        #     'weekly_day': forms.Select(),
        #     'monthly_day': forms.Select(),
        #     'daily_hour': forms.Select(choices=HOUR_CHOICES),
        #     'weekly_hour': forms.Select(choices=HOUR_CHOICES),
        #     'monthly_hour': forms.Select(choices=HOUR_CHOICES),
        #     'max_retry': forms.Select(),
        #     'retry_interval': forms.Select(),
        #     'backup_interval': forms.Select(),
        # }

    def __init__(self, *args, **kwargs):
        super(BackupProfileForm, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.form_method = 'post'
        self.helper.form_class = 'form-horizontal'
        self.helper.label_class = 'col-sm-5 col-form-label col-form-label-sm font-weight-bold text-primary mb-0'
        self.helper.field_class = 'col-sm-7'
        self.helper.form_error_title = 'Error'

        # Apply small size to all fields
        for field_name in self.fields:
            field = self.fields[field_name]
            if not isinstance(field.widget, (forms.HiddenInput, forms.RadioSelect, forms.CheckboxSelectMultiple)):
                existing_classes = field.widget.attrs.get('class', '')
                if 'form-control' not in existing_classes:
                    new_classes = f"{existing_classes} form-control form-control-sm".strip()
                    field.widget.attrs.update({'class': new_classes})
                elif 'form-control-sm' not in existing_classes:
                    new_classes = f"{existing_classes} form-control-sm".strip()
                    field.widget.attrs.update({'class': new_classes})

        self.fields['parameter_sensitive'].widget = forms.HiddenInput()
        self.fields['parameter_terse'].widget = forms.HiddenInput()

        # Premium clock-style widgets for hours
        self.initial['daily_hour'] = f"{self.instance.daily_hour if self.instance.pk else 3:02d}:00"
        self.initial['weekly_hour'] = f"{self.instance.weekly_hour if self.instance.pk else 1:02d}:00"
        self.fields['daily_hour'].widget = forms.TimeInput(attrs={'type': 'time'}) # Classes added by loop
        self.fields['weekly_hour'].widget = forms.TimeInput(attrs={'type': 'time'})

        # Hide monthly as requested
        self.fields['monthly_backup'].widget = forms.HiddenInput()
        self.fields['monthly_retention'].widget = forms.HiddenInput()
        self.fields['monthly_day'].widget = forms.HiddenInput()
        self.fields['monthly_hour'].widget = forms.HiddenInput()
        self.fields['daily_day_monday'].label = 'Lun'
        self.fields['daily_day_tuesday'].label = 'Mar'
        self.fields['daily_day_wednesday'].label = 'Mie'
        self.fields['daily_day_thursday'].label = 'Jue'
        self.fields['daily_day_friday'].label = 'Vie'
        self.fields['daily_day_saturday'].label = 'Sab'
        self.fields['daily_day_sunday'].label = 'Dom'
        self.fields['name'].label = 'Nombre'
        self.fields['daily_backup'].label = 'Diario'
        self.fields['weekly_backup'].label = 'Semanal'
        # self.fields['monthly_backup'].label = 'Mensual'
        self.fields['retain_backups_on_error'].label = 'Retener respaldos en error'
        self.fields['max_retry'].label = 'Máximos Intentos'
        self.fields['retry_interval'].label = 'Intervalo de Reintento'
        self.fields['backup_interval'].label = 'Intervalo de Respaldo'
        self.fields['retrieve_interval'].label = 'Intervalo de Recuperación'
        self.fields['daily_retention'].label = 'Retención'
        self.fields['weekly_retention'].label = 'Retención'
        self.fields['hourly_retention'].label = 'Retención'
        self.fields['instant_retention'].label = 'Retención Instantánea'
        self.fields['hourly_backup'].label = 'Horario'
        self.fields['hourly_interval'].label = 'Intervalo'
        
        if self.instance.pk and self.instance.name == 'default':
            self.fields['name'].widget.attrs['readonly'] = True

        if self.instance.pk and self.instance.name != 'default':
            delete_html = "<a href='javascript:void(0)' class='btn btn-outline-danger btn-sm' data-command='delete' onclick='openCommandDialog(this)'>Borrar</a>"
        else:
            delete_html = ''

        self.helper.layout = Layout(
            Row(
                Column('name', css_class='form-group col-md-6 mb-2'),
                Column('retain_backups_on_error', css_class='form-group col-md-6 mb-2 mt-4'),
                css_class='form-row'
            ),
            Row(
                Column('hourly_backup', css_class='form-group col-md-4 mb-2'),
                Column('daily_backup', css_class='form-group col-md-4 mb-2'),
                Column('weekly_backup', css_class='form-group col-md-4 mb-2'),
                css_class='form-row mb-3 bg-light p-2 rounded border'
            ),

            # Hourly Section
            Row(
                Column(HTML('<span class="badge badge-primary px-3 py-1 mb-2">HORARIO</span>'), css_class='col-md-12 text-center'),
                Column('hourly_interval', css_class='form-group col-md-6 mb-2'),
                Column('hourly_retention', css_class='form-group col-md-6 mb-2'),
                css_id='hourly_settings', css_class='form-row mb-1'
            ),

            # Daily Section
            Div(
                Row(
                   Column(HTML('<span class="badge badge-primary px-3 py-1 mb-2">DIARIO</span>'), css_class='col-md-12 text-center'),
                    Column('daily_hour', css_class='form-group col-md-6 mb-2'),
                    Column('daily_retention', css_class='form-group col-md-6 mb-2'),
                    css_class='form-row'
                ),
                # Day selection: Using smaller checkboxes
                Div(
                    Div('daily_day_monday', css_class='px-1', style='flex: 1 1 14%; min-width: 0;'),
                    Div('daily_day_tuesday', css_class='px-1', style='flex: 1 1 14%; min-width: 0;'),
                    Div('daily_day_wednesday', css_class='px-1', style='flex: 1 1 14%; min-width: 0;'),
                    Div('daily_day_thursday', css_class='px-1', style='flex: 1 1 14%; min-width: 0;'),
                    Div('daily_day_friday', css_class='px-1', style='flex: 1 1 14%; min-width: 0;'),
                    Div('daily_day_saturday', css_class='px-1', style='flex: 1 1 14%; min-width: 0;'),
                    Div('daily_day_sunday', css_class='px-1', style='flex: 1 1 14%; min-width: 0;'),
                    css_class='d-flex flex-nowrap w-100 justify-content-between px-2 py-1 border-bottom small'
                ),
                css_id='daily_settings', css_class='mb-3'
            ),

            # Weekly Section
            Row(
                Column(HTML('<span class="badge badge-primary px-3 py-1 mb-2">SEMANAL</span>'), css_class='col-md-12 text-center'),
                Column('weekly_day', css_class='form-group col-md-4 mb-2'),
                Column('weekly_hour', css_class='form-group col-md-4 mb-2'),
                Column('weekly_retention', css_class='form-group col-md-4 mb-2'),
                css_id='weekly_settings', css_class='form-row mb-3'
            ),

            # System Section
            Row(
                Column(HTML('<span class="badge badge-secondary px-3 py-1 mb-2">SISTEMA</span>'), css_class='col-md-12 text-center'),
                Column('max_retry', css_class='form-group col-md-6 mb-2'),
                Column('retry_interval', css_class='form-group col-md-6 mb-2'),
                Column('backup_interval', css_class='form-group col-md-6 mb-2'),
                Column('retrieve_interval', css_class='form-group col-md-6 mb-2'),
                Column('instant_retention', css_class='form-group col-md-12 mb-2'),
                css_id='misc_settings', css_class='form-row mb-1'
            ),
            HTML("""
<style>
    .form-horizontal .col-form-label-sm { 
        font-size: 0.72rem !important; 
        text-transform: uppercase;
        letter-spacing: 0.2px;
    }
    .form-control-sm { 
        font-size: 0.8rem !important; 
        height: calc(1.5em + 0.5rem + 2px) !important;
        padding: 0.25rem 0.5rem !important;
    }
    .badge { font-size: 70% !important; }
    .bg-light { background-color: #f1f3f5 !important; }
</style>
"""),
            # Hidden fields
            'monthly_backup', 'monthly_hour', 'monthly_day', 'monthly_retention',
            'parameter_sensitive', 'parameter_terse',

            Row(
                Column(
                    Submit('submit', 'Guardar Perfil', css_class='btn btn-success btn-sm'),
                    HTML(' <a class="btn btn-secondary btn-sm" href="/backup/profile_list/">Atrás</a> '),
                    HTML(delete_html),
                    css_class='col-md-12 mt-3 text-right'
                )
            )
        )

    def clean(self):
        cleaned_data = super().clean()
        
        # Convert datetime.time back to integer choices format
        for field in ['daily_hour', 'weekly_hour']:
            val = cleaned_data.get(field)
            if val is not None:
                cleaned_data[field] = val.hour

        daily_backup = cleaned_data.get('daily_backup')
        weekly_backup = cleaned_data.get('weekly_backup')
        monthly_backup = cleaned_data.get('monthly_backup')

        daily_day_monday = cleaned_data.get('daily_day_monday')
        daily_day_tuesday = cleaned_data.get('daily_day_tuesday')
        daily_day_wednesday = cleaned_data.get('daily_day_wednesday')
        daily_day_thursday = cleaned_data.get('daily_day_thursday')
        daily_day_friday = cleaned_data.get('daily_day_friday')
        daily_day_saturday = cleaned_data.get('daily_day_saturday')
        daily_day_sunday = cleaned_data.get('daily_day_sunday')
        name = cleaned_data.get('name')

        if self.instance.pk:
            if self.instance.name == 'default' and name != 'default':
                raise forms.ValidationError('No puedes cambiar el nombre del perfil predeterminado')

        if daily_backup:
            if not daily_day_monday and not daily_day_tuesday and not daily_day_wednesday and not daily_day_thursday and not daily_day_friday and not daily_day_saturday and not daily_day_sunday:
                raise forms.ValidationError('Debes seleccionar al menos un día para los respaldos diarios')

        if not daily_backup and not weekly_backup and not monthly_backup and not cleaned_data.get('hourly_backup'):
            raise forms.ValidationError('Debes seleccionar al menos un tipo de respaldo')

        return cleaned_data
