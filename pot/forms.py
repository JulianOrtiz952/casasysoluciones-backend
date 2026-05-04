from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError

from pot.models import CustomUser, Inventory, InventorySpace, Property, PropertyHistory


class LoginForm(AuthenticationForm):
    username = forms.EmailField(
        label='Email',
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'correo@ejemplo.com', 'autocomplete': 'username'}),
    )
    password = forms.CharField(
        label='Contraseña',
        strip=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Contraseña', 'autocomplete': 'current-password'}),
    )


class UserTenantCreateForm(forms.ModelForm):
    properties = forms.ModelMultipleChoiceField(
        queryset=Property.objects.filter(status=Property.Status.AVAILABLE),
        widget=forms.CheckboxSelectMultiple,
        required=True,
        label='Inmuebles a asociar',
    )

    class Meta:
        model = CustomUser
        fields = ['first_name', 'last_name', 'email', 'phone', 'properties']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if email and CustomUser.objects.filter(email__iexact=email).exists():
            raise ValidationError('Este email ya está registrado')
        return email


class PasswordResetRequestForm(forms.Form):
    email = forms.EmailField(required=True, widget=forms.EmailInput(attrs={'class': 'form-control'}))


class PasswordResetConfirmForm(forms.Form):
    new_password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control'}))
    confirm_password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control'}))

    def clean(self):
        data = super().clean()
        a, b = data.get('new_password'), data.get('confirm_password')
        if a and b and a != b:
            raise ValidationError('Las contraseñas no coinciden')
        return data


class FirstPasswordChangeForm(forms.Form):
    new_password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control'}))
    confirm_password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control'}))

    def clean(self):
        data = super().clean()
        a, b = data.get('new_password'), data.get('confirm_password')
        if a and b and a != b:
            raise ValidationError('Las contraseñas no coinciden')
        return data


class UserEditRoleForm(forms.Form):
    role = forms.ChoiceField(choices=CustomUser.Role.choices, widget=forms.Select(attrs={'class': 'form-control'}))


class PropertyForm(forms.ModelForm):
    class Meta:
        model = Property
        fields = ['address', 'type', 'owner_name', 'status', 'observations']
        widgets = {
            'address': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Dirección completa'}),
            'type': forms.Select(attrs={'class': 'form-control'}),
            'owner_name': forms.TextInput(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'observations': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def clean_address(self):
        address = (self.cleaned_data.get('address') or '').strip()
        qs = Property.objects.filter(address__iexact=address)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError('Ya existe un inmueble con esta dirección')
        return address


class PropertyFilterForm(forms.Form):
    status = forms.ChoiceField(
        choices=[('', 'Todos')] + list(Property.Status.choices),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
    )
    property_type = forms.ChoiceField(
        choices=[('', 'Todos')] + list(Property.Type.choices),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
    )
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Dirección o código'}),
    )


class PropertyHistoryFilterForm(forms.Form):
    fecha_desde = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}))
    fecha_hasta = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}))
    tipo_evento = forms.ChoiceField(
        choices=[('', 'Todos')] + list(PropertyHistory.EventType.choices),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
    )
    tenant = forms.ModelChoiceField(
        queryset=CustomUser.objects.filter(role=CustomUser.Role.TENANT),
        required=False,
        empty_label='Todos',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )


class InventoryInitialForm(forms.ModelForm):
    class Meta:
        model = Inventory
        fields = ['property', 'tenant', 'delivery_date', 'observations']
        widgets = {
            'property': forms.Select(attrs={'class': 'form-control'}),
            'tenant': forms.Select(attrs={'class': 'form-control'}),
            'delivery_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'observations': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class InventorySpaceForm(forms.ModelForm):
    class Meta:
        model = InventorySpace
        fields = ['space_name', 'condition', 'observations']
        widgets = {
            'space_name': forms.TextInput(attrs={'class': 'form-control'}),
            'condition': forms.Select(attrs={'class': 'form-control'}),
            'observations': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def clean_condition(self):
        c = self.cleaned_data.get('condition')
        if not c:
            raise ValidationError('Selecciona estado del espacio')
        return c


class InventoryPhotoUploadForm(forms.Form):
    image = forms.ImageField(
        widget=forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': 'image/jpeg,image/png'}),
    )
    description = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )

    def clean_image(self):
        image = self.cleaned_data.get('image')
        if not image:
            return image
        name = image.name or ''
        ext = name.split('.')[-1].lower() if '.' in name else ''
        if ext not in ('jpg', 'jpeg', 'png'):
            raise ValidationError('Solo JPG o PNG')
        if image.size > 5 * 1024 * 1024:
            raise ValidationError('Máximo 5 MB')
        return image


class AssociatePropertyForm(forms.Form):
    property = forms.ModelChoiceField(
        queryset=Property.objects.all(),
        widget=forms.Select(attrs={'class': 'form-control'}),
    )
