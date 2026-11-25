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
        fields = ['custom_logo']
        widgets = {
            'custom_logo': forms.FileInput(attrs={
                'class': 'custom-file-input',
                'id': 'customLogoInput',
                'accept': '.png,.jpg,.jpeg,.svg,.webp,.gif,.ico,image/*',
            }),
        }
        labels = {
            'custom_logo': 'Archivo de Logo',
        }
        help_texts = {
            'custom_logo': 'Formatos recomendados: PNG o SVG transparente. Tamaño máximo: 5 MB.',
        }

    def clean_custom_logo(self):
        file = self.cleaned_data.get('custom_logo')
        if file and hasattr(file, 'size'):
            if file.size > MAX_FILE_SIZE_MB * 1024 * 1024:
                raise ValidationError(f"El archivo supera el tamaño máximo permitido ({MAX_FILE_SIZE_MB} MB).")

            ext = os.path.splitext(file.name)[1].lower()
            if ext not in ALLOWED_IMAGE_EXTENSIONS:
                raise ValidationError(
                    f"Formato no admitido '{ext}'. Formatos válidos: {', '.join(ALLOWED_IMAGE_EXTENSIONS)}"
                )
        return file
