from rest_framework import serializers

from pot.models import CustomUser, Property, PropertyHistory


class ActiveTenantBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ['id', 'public_code', 'email', 'first_name', 'last_name', 'document_number']


class PropertyListSerializer(serializers.ModelSerializer):
    type_display = serializers.CharField(source='get_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    active_tenant = serializers.SerializerMethodField()

    class Meta:
        model = Property
        fields = [
            'id',
            'code',
            'address',
            'city',
            'building_name',
            'unit_label',
            'type',
            'type_display',
            'status',
            'status_display',
            'owner_name',
            'active_tenant',
            'created_at',
            'updated_at',
        ]

    def get_active_tenant(self, obj):
        tenant = obj.get_active_tenant()
        if not tenant:
            return None
        return ActiveTenantBriefSerializer(tenant).data


class PropertyDetailSerializer(PropertyListSerializer):
    cover_image = serializers.ImageField(read_only=True)
    created_by_email = serializers.EmailField(
        source='created_by.email',
        read_only=True,
        default=None,
    )
    observations = serializers.CharField(allow_null=True, required=False)

    class Meta(PropertyListSerializer.Meta):
        fields = PropertyListSerializer.Meta.fields + [
            'cover_image',
            'observations',
            'created_by_email',
        ]


class PropertyCreateSerializer(serializers.Serializer):
    address = serializers.CharField(max_length=255)
    type = serializers.ChoiceField(choices=Property.Type.choices)
    owner_name = serializers.CharField(max_length=150)
    city = serializers.CharField(max_length=100, required=False, allow_blank=True, default='')
    building_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default='')
    unit_label = serializers.CharField(max_length=50, required=False, allow_blank=True, default='')
    observations = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    cover_image = serializers.ImageField(required=False, allow_null=True)


class PropertyUpdateSerializer(serializers.Serializer):
    address = serializers.CharField(max_length=255, required=False)
    type = serializers.ChoiceField(choices=Property.Type.choices, required=False)
    owner_name = serializers.CharField(max_length=150, required=False)
    status = serializers.ChoiceField(choices=Property.Status.choices, required=False)
    city = serializers.CharField(max_length=100, required=False, allow_blank=True)
    building_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    unit_label = serializers.CharField(max_length=50, required=False, allow_blank=True)
    observations = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    cover_image = serializers.ImageField(required=False, allow_null=True)


class PropertyHistorySerializer(serializers.ModelSerializer):
    event_type_display = serializers.CharField(source='get_event_type_display', read_only=True)
    related_user_email = serializers.EmailField(
        source='related_user.email',
        read_only=True,
        default=None,
    )
    created_by_email = serializers.EmailField(
        source='created_by.email',
        read_only=True,
        default=None,
    )

    class Meta:
        model = PropertyHistory
        fields = [
            'id',
            'event_type',
            'event_type_display',
            'description',
            'details',
            'related_user',
            'related_user_email',
            'created_by',
            'created_by_email',
            'created_at',
        ]
