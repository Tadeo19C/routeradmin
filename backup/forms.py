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
        self.helper.form_method = 'post'
        if self.instance.pk and self.instance.name != 'default':
            delete_html = "<a href='javascript:void(0)' class='btn btn-outline-danger' data-command='delete' onclick='openCommandDialog(this)'>Delete</a>"
        else:
            delete_html = ''

        self.fields['parameter_sensitive'].widget = forms.HiddenInput()
        self.fields['parameter_terse'].widget = forms.HiddenInput()

        # Premium clock-style widgets for hours
        self.initial['daily_hour'] = f"{self.instance.daily_hour if self.instance.pk else 3:02d}:00"
        self.initial['weekly_hour'] = f"{self.instance.weekly_hour if self.instance.pk else 1:02d}:00"
        self.fields['daily_hour'].widget = forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'})
        self.fields['weekly_hour'].widget = forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'})

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
        self.fields['daily_backup'].label = 'Daily'
        self.fields['weekly_backup'].label = 'Weekly'
        self.fields['monthly_backup'].label = 'Monthly'
        self.fields['daily_retention'].label = 'Retention (days)'
        self.fields['weekly_retention'].label = 'Retention (days)'
        self.fields['monthly_retention'].label = 'Retention (days)'
        self.fields['instant_retention'].label = 'Instant Retention (days)'
        self.fields['hourly_backup'].label = 'Hourly'
        self.fields['hourly_interval'].label = 'Interval'
        self.fields['hourly_retention'].label = 'Retention (days)'
        self.fields['parameter_sensitive'].label = 'sensitive'
        self.fields['parameter_terse'].label = 'terse'
        if self.instance.pk and self.instance.name == 'default':
            self.fields['name'].widget.attrs['readonly'] = True

        self.helper.layout = Layout(
            Row(
                Column('name', css_class='form-group col-md-6 mb-1'),
                css_class='form-row'
            ),
            # Toggles Row
            Row(
                Column('daily_backup', css_class='form-group col-md-2 mb-1'),
                Column('weekly_backup', css_class='form-group col-md-2 mb-1'),
                Column('hourly_backup', css_class='form-group col-md-2 mb-1'),
                Column('retain_backups_on_error', css_class='form-group col-md-3 mb-1'),
                css_class='form-row mb-2'
            ),

            # Hourly Section
            Row(
                Column(HTML('<small class="text-primary font-weight-bold">HOURLY:</small>'), css_class='col-md-2'),
                Column('hourly_interval', css_class='form-group col-md-5 mb-1'),
                Column('hourly_retention', css_class='form-group col-md-5 mb-1'),
                css_id='hourly_settings', css_class='form-row mb-1'
            ),

            # Daily Section
            Div(
                Row(
                    Column(HTML('<small class="text-primary font-weight-bold">DAILY:</small>'), css_class='col-md-2'),
                    Column('daily_hour', css_class='form-group col-md-5 mb-1'),
                    Column('daily_retention', css_class='form-group col-md-5 mb-1'),
                    css_class='form-row'
                ),
                # Day selection in one tight flex row
                Div(
                    Div('daily_day_monday', css_class='px-1', style='flex: 1 1 14%; min-width: 0;'),
                    Div('daily_day_tuesday', css_class='px-1', style='flex: 1 1 14%; min-width: 0;'),
                    Div('daily_day_wednesday', css_class='px-1', style='flex: 1 1 14%; min-width: 0;'),
                    Div('daily_day_thursday', css_class='px-1', style='flex: 1 1 14%; min-width: 0;'),
                    Div('daily_day_friday', css_class='px-1', style='flex: 1 1 14%; min-width: 0;'),
                    Div('daily_day_saturday', css_class='px-1', style='flex: 1 1 14%; min-width: 0;'),
                    Div('daily_day_sunday', css_class='px-1', style='flex: 1 1 14%; min-width: 0;'),
                    css_class='d-flex flex-nowrap w-100 justify-content-between px-2 py-1 border-bottom'
                ),
                css_id='daily_settings', css_class='mb-2'
            ),

            # Weekly Section
            Row(
                Column(HTML('<small class="text-primary font-weight-bold">WEEKLY:</small>'), css_class='col-md-2'),
                Column('weekly_hour', css_class='form-group col-md-3 mb-1'),
                Column('weekly_day', css_class='form-group col-md-4 mb-1'),
                Column('weekly_retention', css_class='form-group col-md-3 mb-1'),
                css_id='weekly_settings', css_class='form-row mb-1'
            ),

            # Parameters and Retention
            Row(
                Column(HTML('<small class="text-primary font-weight-bold">SYSTEM:</small>'), css_class='col-md-2'),
                Column('max_retry', css_class='form-group col-md-3 mb-1'),
                Column('retry_interval', css_class='form-group col-md-3 mb-1'),
                Column('backup_interval', css_class='form-group col-md-4 mb-1'),
                css_id='misc_settings', css_class='form-row mb-1'
            ),
            Row(
                Column(HTML('<span class="col-md-2"></span>'), css_class='col-md-2'),
                Column('retrieve_interval', css_class='form-group col-md-5 mb-1'),
                Column('instant_retention', css_class='form-group col-md-5 mb-1'),
                css_class='form-row'
            ),

            # Hidden fields
            'monthly_backup',
            'monthly_hour',
            'monthly_day',
            'monthly_retention',
            'parameter_sensitive',
            'parameter_terse',

            Row(
                Column(
                    Submit('submit', 'Save', css_class='btn btn-success btn-sm'),
                    HTML(' <a class="btn btn-secondary btn-sm" href="/backup/profile_list/">Back</a> '),
                    HTML(delete_html),
                    css_class='col-md-12 mt-2'
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
                raise forms.ValidationError('You cannot change the default profile name')

        if daily_backup:
            if not daily_day_monday and not daily_day_tuesday and not daily_day_wednesday and not daily_day_thursday and not daily_day_friday and not daily_day_saturday and not daily_day_sunday:
                raise forms.ValidationError('You must select at least one day for daily backups')

        if not daily_backup and not weekly_backup and not monthly_backup and not cleaned_data.get('hourly_backup'):
            raise forms.ValidationError('You must select at least one backup type')

        return cleaned_data
