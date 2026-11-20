import os
from django import forms
from django.core.exceptions import ValidationError
from .models import WebadminSettings


ALLOWED_IMAGE_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.svg', '.webp', '.gif', '.ico']
MAX_FILE_SIZE_MB = 5


class SystemBrandingForm(forms.ModelForm):
    remove_logo = forms.BooleanField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = WebadminSettings
        fields = ['app_title', 'custom_logo']
        widgets = {
            'app_title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej: BACKUP WEB',
                'maxlength': '64',
            }),
            'custom_logo': forms.FileInput(attrs={
                'class': 'custom-file-input',
                'id': 'customLogoInput',
                'accept': '.png,.jpg,.jpeg,.svg,.webp,.gif,.ico,image/*',
            }),
        }
        labels = {
            'app_title': 'Nombre de la Plataforma',
            'custom_logo': 'Archivo de Logo',
        }
        help_texts = {
            'app_title': 'Nombre mostrado en la barra superior, pestaña del navegador y pantalla de inicio de sesión.',
            'custom_logo': 'Formatos recomendados: PNG o SVG transparente. Tamaño máximo: 5 MB.',
        }

    def clean_custom_logo(self):
        file = self.cleaned_data.get('custom_logo')
        if file and hasattr(file, 'size'):
            # Check file size
            if file.size > MAX_FILE_SIZE_MB * 1024 * 1024:
                raise ValidationError(f"El archivo supera el tamaño máximo permitido ({MAX_FILE_SIZE_MB} MB).")

            # Check file extension
            ext = os.path.splitext(file.name)[1].lower()
            if ext not in ALLOWED_IMAGE_EXTENSIONS:
                raise ValidationError(
                    f"Formato no admitido '{ext}'. Formatos válidos: {', '.join(ALLOWED_IMAGE_EXTENSIONS)}"
                )
        return file
