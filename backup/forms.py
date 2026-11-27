import datetime
import re
from django import forms
from .models import BackupProfile


class BackupProfileForm(forms.ModelForm):
    daily_hour = forms.TimeField(
        required=False,
        label='Hora Diaria',
        widget=forms.TimeInput(attrs={'type': 'time', 'class': 'form-control form-control-sm'}),
    )
    weekly_hour = forms.TimeField(
        required=False,
        label='Hora Semanal',
        widget=forms.TimeInput(attrs={'type': 'time', 'class': 'form-control form-control-sm'}),
    )

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
            'parameter_sensitive', 'parameter_terse', 'hourly_interval',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._parsed_daily_minute = getattr(self.instance, 'daily_minute', 0) or 0 if self.instance.pk else 0
        self._parsed_weekly_minute = getattr(self.instance, 'weekly_minute', 0) or 0 if self.instance.pk else 0

        optional_conditional_fields = [
            'hourly_interval', 'hourly_retention',
            'daily_hour', 'daily_retention',
            'weekly_day', 'weekly_hour', 'weekly_retention',
            'monthly_backup', 'monthly_retention', 'monthly_day', 'monthly_hour',
            'parameter_sensitive', 'parameter_terse',
        ]
        for fname in optional_conditional_fields:
            if fname in self.fields:
                self.fields[fname].required = False

        # Etiquetas en español coherentes con todo el sistema
        self.fields['name'].label = 'Nombre del Perfil'
        self.fields['retain_backups_on_error'].label = 'Proteger historial ante fallos'
        self.fields['hourly_backup'].label = 'Por Hora'
        self.fields['daily_backup'].label = 'Diario'
        self.fields['weekly_backup'].label = 'Semanal'
        self.fields['hourly_interval'].label = 'Intervalo de Ejecución'
        self.fields['hourly_retention'].label = 'Retención Horaria'
        self.fields['daily_retention'].label = 'Retención Diaria'
        self.fields['weekly_day'].label = 'Día de la Semana'
        self.fields['weekly_retention'].label = 'Retención Semanal'
        self.fields['daily_day_monday'].label = 'Lun'
        self.fields['daily_day_tuesday'].label = 'Mar'
        self.fields['daily_day_wednesday'].label = 'Mié'
        self.fields['daily_day_thursday'].label = 'Jue'
        self.fields['daily_day_friday'].label = 'Vie'
        self.fields['daily_day_saturday'].label = 'Sáb'
        self.fields['daily_day_sunday'].label = 'Dom'
        self.fields['max_retry'].label = 'Máximos Intentos'
        self.fields['retry_interval'].label = 'Intervalo de Reintento'
        self.fields['backup_interval'].label = 'Intervalo de Respaldo'
        self.fields['retrieve_interval'].label = 'Intervalo de Recuperación'
        self.fields['instant_retention'].label = 'Retención Instantánea'

        # Ocultar campos internos heredados
        for hidden_name in ('monthly_backup', 'monthly_retention', 'monthly_day', 'monthly_hour', 'parameter_sensitive', 'parameter_terse'):
            self.fields[hidden_name].widget = forms.HiddenInput()

        # Clases Bootstrap compactas para controles de texto/select/número
        for field_name, field in self.fields.items():
            if isinstance(field.widget, (forms.HiddenInput, forms.CheckboxInput)):
                continue
            existing = field.widget.attrs.get('class', '')
            if 'form-control' not in existing:
                field.widget.attrs['class'] = f"{existing} form-control form-control-sm".strip()
            elif 'form-control-sm' not in existing:
                field.widget.attrs['class'] = f"{existing} form-control-sm".strip()

        self.fields['name'].widget.attrs.setdefault('placeholder', 'Ej: Nodos Críticos 6h, Clientes Diario...')
        self.fields['name'].widget.attrs.setdefault('autocomplete', 'off')

        for ret_field in ('hourly_retention', 'daily_retention', 'weekly_retention', 'instant_retention'):
            self.fields[ret_field].widget.attrs['min'] = '1'
            self.fields[ret_field].widget.attrs['max'] = '36500'

        # Inicializar horas conservando hora y minutos exactos
        d_hour = self.instance.daily_hour if (self.instance.pk and self.instance.daily_hour is not None) else 3
        d_min = (getattr(self.instance, 'daily_minute', 0) or 0) if self.instance.pk else 0
        w_hour = self.instance.weekly_hour if (self.instance.pk and self.instance.weekly_hour is not None) else 1
        w_min = (getattr(self.instance, 'weekly_minute', 0) or 0) if self.instance.pk else 0

        self.initial['daily_hour'] = f"{int(d_hour):02d}:{int(d_min):02d}"
        self.initial['weekly_hour'] = f"{int(w_hour):02d}:{int(w_min):02d}"

        if self.instance.pk and self.instance.name == 'default':
            self.fields['name'].widget.attrs['readonly'] = True

    def clean_name(self):
        raw_name = self.cleaned_data.get('name') or ''
        name = re.sub(r'\s+', ' ', raw_name.strip())
        if self.instance.pk and self.instance.name == 'default':
            if name and name != 'default':
                raise forms.ValidationError('No puedes cambiar el nombre del perfil predeterminado (default).')
            return 'default'

        if not name:
            raise forms.ValidationError('Debes ingresar un nombre para el perfil de respaldo.')

        qs = BackupProfile.objects.filter(name__iexact=name)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        existing = qs.first()
        if existing:
            raise forms.ValidationError(f"Ya existe un perfil de respaldo llamado '{existing.name}'.")
        return name

    def clean(self):
        cleaned_data = super().clean()

        hourly_backup = bool(cleaned_data.get('hourly_backup'))
        daily_backup = bool(cleaned_data.get('daily_backup'))
        weekly_backup = bool(cleaned_data.get('weekly_backup'))
        monthly_backup = bool(cleaned_data.get('monthly_backup'))

        # Al menos una frecuencia debe estar seleccionada
        if not (hourly_backup or daily_backup or weekly_backup or monthly_backup):
            raise forms.ValidationError(
                'Debes seleccionar al menos una frecuencia de respaldo (Por Hora, Diario o Semanal).'
            )

        # --- Validación y preservación de HORARIO ---
        default_h_interval = self.instance.hourly_interval if self.instance.pk else 6
        default_h_ret = self.instance.hourly_retention if self.instance.pk else 3
        if hourly_backup:
            h_interval = cleaned_data.get('hourly_interval')
            h_ret = cleaned_data.get('hourly_retention')
            if not h_interval:
                self.add_error('hourly_interval', 'Selecciona cada cuántas horas se ejecutará el respaldo.')
            if h_ret is None or h_ret < 1:
                self.add_error('hourly_retention', 'La retención por hora debe ser de al menos 1 día.')
        else:
            cleaned_data['hourly_interval'] = cleaned_data.get('hourly_interval') or default_h_interval
            h_ret_val = cleaned_data.get('hourly_retention')
            cleaned_data['hourly_retention'] = h_ret_val if (h_ret_val is not None and h_ret_val >= 1) else default_h_ret
            self._errors_pop_safe('hourly_interval', 'hourly_retention')

        # --- Validación y preservación de DIARIO ---
        default_d_hour = self.instance.daily_hour if self.instance.pk else 3
        default_d_min = (getattr(self.instance, 'daily_minute', 0) or 0) if self.instance.pk else 0
        default_d_ret = self.instance.daily_retention if self.instance.pk else 7

        raw_d_time = cleaned_data.get('daily_hour')
        if isinstance(raw_d_time, datetime.time):
            parsed_d_hour = raw_d_time.hour
            self._parsed_daily_minute = raw_d_time.minute
        elif isinstance(raw_d_time, int):
            parsed_d_hour = raw_d_time
        else:
            parsed_d_hour = None

        if daily_backup:
            if parsed_d_hour is None:
                self.add_error('daily_hour', 'Indica una hora válida para el respaldo diario.')
            else:
                cleaned_data['daily_hour'] = parsed_d_hour

            d_ret = cleaned_data.get('daily_retention')
            if d_ret is None or d_ret < 1:
                self.add_error('daily_retention', 'La retención diaria debe ser de al menos 1 día.')

            any_weekday = any([
                cleaned_data.get('daily_day_monday'),
                cleaned_data.get('daily_day_tuesday'),
                cleaned_data.get('daily_day_wednesday'),
                cleaned_data.get('daily_day_thursday'),
                cleaned_data.get('daily_day_friday'),
                cleaned_data.get('daily_day_saturday'),
                cleaned_data.get('daily_day_sunday'),
            ])
            if not any_weekday:
                raise forms.ValidationError(
                    'Debes marcar al menos un día de la semana (Lun–Dom) cuando el respaldo Diario está activo.'
                )
        else:
            cleaned_data['daily_hour'] = parsed_d_hour if parsed_d_hour is not None else default_d_hour
            if parsed_d_hour is None:
                self._parsed_daily_minute = default_d_min
            d_ret_val = cleaned_data.get('daily_retention')
            cleaned_data['daily_retention'] = d_ret_val if (d_ret_val is not None and d_ret_val >= 1) else default_d_ret
            self._errors_pop_safe('daily_hour', 'daily_retention')

        # --- Validación y preservación de SEMANAL ---
        default_w_day = self.instance.weekly_day if self.instance.pk else 'sunday'
        default_w_hour = self.instance.weekly_hour if self.instance.pk else 1
        default_w_min = (getattr(self.instance, 'weekly_minute', 0) or 0) if self.instance.pk else 0
        default_w_ret = self.instance.weekly_retention if self.instance.pk else 30

        raw_w_time = cleaned_data.get('weekly_hour')
        if isinstance(raw_w_time, datetime.time):
            parsed_w_hour = raw_w_time.hour
            self._parsed_weekly_minute = raw_w_time.minute
        elif isinstance(raw_w_time, int):
            parsed_w_hour = raw_w_time
        else:
            parsed_w_hour = None

        if weekly_backup:
            if not cleaned_data.get('weekly_day'):
                self.add_error('weekly_day', 'Selecciona el día de ejecución semanal.')
            if parsed_w_hour is None:
                self.add_error('weekly_hour', 'Indica una hora válida para el respaldo semanal.')
            else:
                cleaned_data['weekly_hour'] = parsed_w_hour

            w_ret = cleaned_data.get('weekly_retention')
            if w_ret is None or w_ret < 1:
                self.add_error('weekly_retention', 'La retención semanal debe ser de al menos 1 día.')
        else:
            cleaned_data['weekly_day'] = cleaned_data.get('weekly_day') or default_w_day
            cleaned_data['weekly_hour'] = parsed_w_hour if parsed_w_hour is not None else default_w_hour
            if parsed_w_hour is None:
                self._parsed_weekly_minute = default_w_min
            w_ret_val = cleaned_data.get('weekly_retention')
            cleaned_data['weekly_retention'] = w_ret_val if (w_ret_val is not None and w_ret_val >= 1) else default_w_ret
            self._errors_pop_safe('weekly_day', 'weekly_hour', 'weekly_retention')

        # --- Retención Instantánea y campos internos heredados ---
        inst_ret = cleaned_data.get('instant_retention')
        if inst_ret is None or inst_ret < 1:
            self.add_error('instant_retention', 'La retención instantánea debe ser de al menos 1 día.')

        cleaned_data['monthly_backup'] = bool(cleaned_data.get('monthly_backup', False))
        cleaned_data['monthly_retention'] = cleaned_data.get('monthly_retention') or (self.instance.monthly_retention if self.instance.pk else 365)
        cleaned_data['monthly_day'] = cleaned_data.get('monthly_day') or (self.instance.monthly_day if self.instance.pk else 1)
        cleaned_data['monthly_hour'] = cleaned_data.get('monthly_hour') if cleaned_data.get('monthly_hour') is not None else (self.instance.monthly_hour if self.instance.pk else 0)
        cleaned_data['parameter_sensitive'] = bool(cleaned_data.get('parameter_sensitive', False))
        cleaned_data['parameter_terse'] = bool(cleaned_data.get('parameter_terse', False))

        return cleaned_data

    def _errors_pop_safe(self, *field_names):
        for fname in field_names:
            if fname in self._errors:
                self._errors.pop(fname, None)

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.daily_minute = self._parsed_daily_minute
        instance.weekly_minute = self._parsed_weekly_minute
        if commit:
            instance.save()
        return instance
