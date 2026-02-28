from rest_framework import serializers
from .models import Inmueble, Inquilino, HistorialAlquiler, ImagenInmueble, UserProfile
from django.contrib.auth.models import User
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

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
    username = serializers.CharField(required=True)
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True)


class UserSerializer(serializers.ModelSerializer):
    rol = serializers.ChoiceField(choices=UserProfile.ROLES_CHOICES, write_only=True, required=False)
    role_display = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'password', 'rol', 'role_display', 'is_active']
        extra_kwargs = {'password': {'write_only': True}}

    def get_role_display(self, obj):
        try:
            return obj.profile.rol
        except UserProfile.DoesNotExist:
            return 'SUPER' if obj.is_superuser else 'OPERARIO'

    def create(self, validated_data):
        rol = validated_data.pop('rol', 'OPERARIO')
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data.get('email', ''),
            password=validated_data['password']
        )
        if rol == 'SUPER':
            user.is_superuser = True
            user.is_staff = True
            user.save()
            
        # Actualizamos el profile ya que el signal lo creó
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.rol = rol
        profile.save()
        
        return user

    def update(self, instance, validated_data):
        rol = validated_data.pop('rol', None)
        if 'password' in validated_data:
            instance.set_password(validated_data.pop('password'))
            
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if rol:
            profile, _ = UserProfile.objects.get_or_create(user=instance)
            profile.rol = rol
            profile.save()
            if rol == 'SUPER':
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

        # Agregamos atributos personalizados al payload del JWT
        token['username'] = user.username
        try:
            token['rol'] = user.profile.rol
        except UserProfile.DoesNotExist:
            token['rol'] = 'SUPER' if user.is_superuser else 'OPERARIO'
            
        return token
