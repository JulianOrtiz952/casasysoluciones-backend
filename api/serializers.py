from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import HistorialAlquiler, ImagenInmueble, Inmueble, Inquilino

User = get_user_model()


class ImagenInmuebleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImagenInmueble
        fields = ['id', 'imagen', 'es_portada', 'creado_en']


class InmuebleSerializer(serializers.ModelSerializer):
    imagenes = ImagenInmuebleSerializer(many=True, read_only=True)

    class Meta:
        model = Inmueble
        fields = '__all__'


class InquilinoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Inquilino
        fields = '__all__'


class HistorialAlquilerSerializer(serializers.ModelSerializer):
    inmueble_detalle = InmuebleSerializer(source='inmueble', read_only=True)
    inquilino_detalle = InquilinoSerializer(source='inquilino', read_only=True)

    class Meta:
        model = HistorialAlquiler
        fields = '__all__'


class ChangePasswordSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True)


class UserSerializer(serializers.ModelSerializer):
    role = serializers.ChoiceField(choices=User.Role.choices, required=False)
    role_display = serializers.CharField(source='get_role_display', read_only=True)

    class Meta:
        model = User
        fields = ['id', 'email', 'first_name', 'last_name', 'password', 'role', 'role_display', 'is_active', 'document_type', 'document_number', 'phone', 'public_code']
        extra_kwargs = {'password': {'write_only': True, 'required': False, 'allow_blank': True, 'allow_null': True}}

    def create(self, validated_data):
        role = validated_data.pop('role', User.Role.ASSISTANT)
        password = validated_data.pop('password', None)
        document_number = validated_data.get('document_number')
        if not password and document_number:
            password = document_number
        elif not password:
            password = 'DefaultPassword123!'
        email = validated_data.pop('email')
        user = User.objects.create_user(email=email, password=password, **validated_data)
        user.role = role
        if role == User.Role.ADMIN:
            user.is_staff = True
        user.save()
        return user

    def update(self, instance, validated_data):
        role = validated_data.pop('role', None)
        if 'password' in validated_data:
            pwd = validated_data.pop('password')
            if pwd:
                instance.set_password(pwd)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if role is not None:
            instance.role = role
            if role == User.Role.ADMIN:
                instance.is_superuser = True
                instance.is_staff = True
            else:
                instance.is_superuser = False
                instance.is_staff = False
            instance.save()
        return instance


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['email'] = user.email
        token['rol'] = user.role
        return token
