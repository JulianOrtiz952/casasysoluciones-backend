from rest_framework import serializers

from pot.models import CustomUser, Property, UserAudit, UserPropertyAssociation


class PropertyBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Property
        fields = ['id', 'code', 'address', 'city', 'type', 'status']


class UserPropertyAssociationSerializer(serializers.ModelSerializer):
    property = PropertyBriefSerializer(read_only=True)
    is_active = serializers.SerializerMethodField()

    class Meta:
        model = UserPropertyAssociation
        fields = ['id', 'property', 'associated_at', 'dissociated_at', 'is_active']

    def get_is_active(self, obj):
        return obj.is_association_active()


class UserAuditSerializer(serializers.ModelSerializer):
    changed_by_email = serializers.EmailField(source='changed_by.email', read_only=True, default=None)

    class Meta:
        model = UserAudit
        fields = ['id', 'action', 'details', 'changed_by_email', 'created_at']


class UserListSerializer(serializers.ModelSerializer):
    role_display = serializers.CharField(source='get_role_display', read_only=True)
    active_properties_count = serializers.SerializerMethodField()

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
            'role',
            'role_display',
            'is_active',
            'active_properties_count',
            'created_at',
        ]

    def get_active_properties_count(self, obj):
        return obj.property_associations.filter(dissociated_at__isnull=True).count()


class UserDetailSerializer(UserListSerializer):
    associations = serializers.SerializerMethodField()
    recent_audits = serializers.SerializerMethodField()

    class Meta(UserListSerializer.Meta):
        fields = UserListSerializer.Meta.fields + ['password_changed', 'associations', 'recent_audits']

    def get_associations(self, obj):
        assocs = obj.property_associations.select_related('property').order_by('-associated_at')[:20]
        return UserPropertyAssociationSerializer(assocs, many=True).data

    def get_recent_audits(self, obj):
        audits = obj.audits.order_by('-created_at')[:20]
        return UserAuditSerializer(audits, many=True).data


class UserCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    first_name = serializers.CharField(required=False, allow_blank=True, default='')
    last_name = serializers.CharField(required=False, allow_blank=True, default='')
    phone = serializers.CharField(required=False, allow_blank=True, default='')
    document_type = serializers.ChoiceField(
        choices=CustomUser.DocumentType.choices,
        required=False,
        allow_blank=True,
    )
    document_number = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    property_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
    )

    def validate_first_name(self, value):
        import re
        if value and not re.match(r'^[a-zA-ZáéíóúÁÉÍÓÚñÑüÜ\s]*$', value):
            raise serializers.ValidationError("El nombre no debe contener caracteres especiales, solo letras, espacios y tildes.")
        return value

    def validate_last_name(self, value):
        import re
        if value and not re.match(r'^[a-zA-ZáéíóúÁÉÍÓÚñÑüÜ\s]*$', value):
            raise serializers.ValidationError("El apellido no debe contener caracteres especiales, solo letras, espacios y tildes.")
        return value

    def validate_phone(self, value):
        import re
        if value:
            value = value.strip()
            if value and not re.match(r'^\d{10}$', value):
                raise serializers.ValidationError("El teléfono celular debe tener exactamente 10 dígitos numéricos.")
        return value

    def validate_document_number(self, value):
        import re
        if value:
            value = value.strip()
            if value and not re.match(r'^\d{8,11}$', value):
                raise serializers.ValidationError("El número de identificación debe tener entre 8 y 11 dígitos numéricos.")
        return value


class UserUpdateSerializer(serializers.Serializer):
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)
    phone = serializers.CharField(required=False, allow_blank=True)
    document_type = serializers.ChoiceField(
        choices=CustomUser.DocumentType.choices,
        required=False,
        allow_blank=True,
    )
    document_number = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def validate_first_name(self, value):
        import re
        if value and not re.match(r'^[a-zA-ZáéíóúÁÉÍÓÚñÑüÜ\s]*$', value):
            raise serializers.ValidationError("El nombre no debe contener caracteres especiales, solo letras, espacios y tildes.")
        return value

    def validate_last_name(self, value):
        import re
        if value and not re.match(r'^[a-zA-ZáéíóúÁÉÍÓÚñÑüÜ\s]*$', value):
            raise serializers.ValidationError("El apellido no debe contener caracteres especiales, solo letras, espacios y tildes.")
        return value

    def validate_phone(self, value):
        import re
        if value:
            value = value.strip()
            if value and not re.match(r'^\d{10}$', value):
                raise serializers.ValidationError("El teléfono celular debe tener exactamente 10 dígitos numéricos.")
        return value

    def validate_document_number(self, value):
        import re
        if value:
            value = value.strip()
            if value and not re.match(r'^\d{8,11}$', value):
                raise serializers.ValidationError("El número de identificación debe tener entre 8 y 11 dígitos numéricos.")
        return value


class RoleChangeSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=CustomUser.Role.choices)
    confirm = serializers.BooleanField(required=False, default=False)


class DeactivateSerializer(serializers.Serializer):
    confirm = serializers.BooleanField(required=False, default=False)


class TenantPropertyAssociateSerializer(serializers.Serializer):
    property_id = serializers.IntegerField(min_value=1)


class TenantListSerializer(UserListSerializer):
    active_properties = serializers.SerializerMethodField()

    class Meta(UserListSerializer.Meta):
        fields = UserListSerializer.Meta.fields + ['active_properties']

    def get_active_properties(self, obj):
        assocs = obj.property_associations.filter(dissociated_at__isnull=True).select_related('property')
        return PropertyBriefSerializer([a.property for a in assocs], many=True).data
