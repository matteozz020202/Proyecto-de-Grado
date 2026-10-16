from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm


class ProfileForm(forms.ModelForm):
    class Meta:
        model = get_user_model()
        fields = ("first_name", "last_name", "email")
        labels = {"first_name": "Nombre", "last_name": "Apellido", "email": "Correo electrónico"}


class RegistrationForm(UserCreationForm):
    full_name = forms.CharField(label="Nombre completo", max_length=150, widget=forms.TextInput(attrs={"autocomplete": "name"}))
    email = forms.EmailField(label="Correo electrónico", widget=forms.EmailInput(attrs={"autocomplete": "email"}))

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("username", "full_name", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Usuario"
        self.fields["username"].widget.attrs["autocomplete"] = "username"
        self.fields["password1"].label = "Contraseña"
        self.fields["password2"].label = "Confirmar contraseña"
        self.fields["password1"].help_text = "Usa al menos 8 caracteres. Evita contraseñas comunes, solo números o similares a tus datos."
        self.fields["password2"].help_text = ""

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("No podemos usar este correo para crear la cuenta. Usa otro correo o inicia sesión.")
        return email

    def _post_clean(self):
        # Incluye el nombre en la validación de similitud de contraseñas de Django.
        self.instance.first_name = self.cleaned_data.get("full_name", "")
        super()._post_clean()


class LoginForm(forms.Form):
    username = forms.CharField(label="Usuario", max_length=150, widget=forms.TextInput(attrs={"autocomplete": "username", "placeholder": "Tu nombre de usuario"}))
    password = forms.CharField(label="Contraseña", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "current-password", "placeholder": "Tu contraseña"}))
