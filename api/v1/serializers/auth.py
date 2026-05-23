from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from pot.models import CustomUser, Property, UserPropertyAssociation


class LoginSerializer(serializers.Serializer):
    email = serializers.CharField(required=False, allow_blank=True)
    document_number = serializers.CharField(required=False, allow_blank=True)
    password = serializers.CharField(required=True, write_only=True)

    def validate(self, attrs):
        email = (attrs.get('email') or '').strip()
        document_number = (attrs.get('document_number') or '').strip()
        identifier = email or document_number
        if not identifier:
            raise serializers.ValidationError(
                'Debe indicar email o document_number.',
                code='missing_identifier',
            )
        if email and document_number:
            raise serializers.ValidationError(
                'Indique solo email o document_number, no ambos.',
                code='ambiguous_identifier',
            )
        attrs['identifier'] = identifier
        return attrs


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)


class PasswordResetConfirmSerializer(serializers.Serializer):
    token = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, min_length=8, write_only=True)
    confirm_password = serializers.CharField(required=True, write_only=True)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError(
                {'confirm_password': 'Las contraseñas no coinciden.'},
            )
        return attrs


class FirstPasswordChangeSerializer(serializers.Serializer):
    new_password = serializers.CharField(required=True, min_length=8, write_only=True)
    confirm_password = serializers.CharField(required=True, write_only=True)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError(
                {'confirm_password': 'Las contraseñas no coinciden.'},
            )
        return attrs


class PropertySummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Property
        fields = ['id', 'code', 'address', 'city', 'type', 'status']


class UserMeSerializer(serializers.ModelSerializer):
    role_display = serializers.CharField(source='get_role_display', read_only=True)
    properties = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = [
            'id',
            'public_code',
            'email',
            'first_name',
            'last_name',
            'phone',
            'document_type',
            'document_number',
            'avatar',
            'role',
            'role_display',
            'password_changed',
            'is_active',
            'properties',
        ]

    def get_properties(self, obj):
        if obj.role != CustomUser.Role.TENANT:
            return []
        associations = (
            UserPropertyAssociation.objects.filter(user=obj, dissociated_at__isnull=True)
            .select_related('property')
            .order_by('-associated_at')
        )
        return PropertySummarySerializer([a.property for a in associations], many=True).data


class APITokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['email'] = user.email
        token['role'] = user.role
        token['public_code'] = user.public_code or ''
        return token
