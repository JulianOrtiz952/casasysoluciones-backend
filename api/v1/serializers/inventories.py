from rest_framework import serializers

from pot.models import CustomUser, Inventory, InventorySpace, InventorySpacePhoto, InventoryTenantObservation, Property


class InventorySpacePhotoSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()

    class Meta:
        model = InventorySpacePhoto
        fields = ['id', 'description', 'image_url', 'thumbnail_url', 'uploaded_at']

    def get_image_url(self, obj):
        return obj.image.url if obj.image else None

    def get_thumbnail_url(self, obj):
        return obj.get_thumbnail_url() or None


class InventorySpaceSerializer(serializers.ModelSerializer):
    condition_display = serializers.CharField(source='get_condition_display', read_only=True)
    photos = InventorySpacePhotoSerializer(many=True, read_only=True)

    class Meta:
        model = InventorySpace
        fields = [
            'id',
            'space_name',
            'condition',
            'condition_display',
            'observations',
            'order',
            'photos',
            'created_at',
            'updated_at',
        ]


class InventoryTenantBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ['id', 'public_code', 'email', 'first_name', 'last_name', 'document_number']


class InventoryPropertyBriefSerializer(serializers.ModelSerializer):
    type_display = serializers.CharField(source='get_type_display', read_only=True)

    class Meta:
        model = Property
        fields = ['id', 'code', 'address', 'type', 'type_display', 'owner_name']


class InventoryListSerializer(serializers.ModelSerializer):
    inventory_type_display = serializers.CharField(source='get_inventory_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    property = InventoryPropertyBriefSerializer(read_only=True)
    tenant = InventoryTenantBriefSerializer(read_only=True)
    spaces_count = serializers.SerializerMethodField()

    def get_spaces_count(self, obj):
        return obj.spaces.count()

    class Meta:
        model = Inventory
        fields = [
            'id',
            'inventory_type',
            'inventory_type_display',
            'status',
            'status_display',
            'delivery_date',
            'property',
            'tenant',
            'spaces_count',
            'signed_at',
            'created_at',
            'updated_at',
        ]


class InventoryDetailSerializer(InventoryListSerializer):
    observations = serializers.CharField(allow_null=True, required=False)
    spaces = InventorySpaceSerializer(many=True, read_only=True)
    tenant_observations = serializers.SerializerMethodField()

    class Meta(InventoryListSerializer.Meta):
        fields = InventoryListSerializer.Meta.fields + [
            'observations',
            'spaces',
            'tenant_observations',
            'signature_token',
        ]

    def get_tenant_observations(self, obj):
        qs = obj.tenant_observations.all()[:20]
        return [
            {
                'id': o.pk,
                'observation_text': o.observation_text,
                'created_at': o.created_at,
            }
            for o in qs
        ]


class InventoryCreateSerializer(serializers.Serializer):
    property_id = serializers.IntegerField()
    tenant_id = serializers.IntegerField()
    delivery_date = serializers.DateField()
    observations = serializers.CharField(required=False, allow_blank=True, default='')
    inventory_type = serializers.ChoiceField(
        choices=Inventory.Type.choices,
        default=Inventory.Type.INITIAL,
    )


class InventoryStep1Serializer(serializers.Serializer):
    delivery_date = serializers.DateField(required=False)
    observations = serializers.CharField(required=False, allow_blank=True)


class InventorySpaceCreateSerializer(serializers.Serializer):
    space_name = serializers.CharField(max_length=100)
    condition = serializers.ChoiceField(choices=InventorySpace.Condition.choices)
    observations = serializers.CharField(required=False, allow_blank=True, default='')


class InventorySpaceBulkItemSerializer(serializers.Serializer):
    space_name = serializers.CharField(max_length=100)
    condition = serializers.ChoiceField(choices=InventorySpace.Condition.choices)
    observations = serializers.CharField(required=False, allow_blank=True, default='')
    order = serializers.IntegerField(required=False, default=0)


class InventorySpaceBulkSerializer(serializers.Serializer):
    spaces = InventorySpaceBulkItemSerializer(many=True)


class InventoryPhotoUploadSerializer(serializers.Serializer):
    image = serializers.ImageField()
    description = serializers.CharField(required=False, allow_blank=True, default='')

    def validate_image(self, value):
        from pot.services.inventory_service import validar_archivo_imagen

        ok, err = validar_archivo_imagen(value)
        if not ok:
            raise serializers.ValidationError(err)
        return value


class InventoryObservationSerializer(serializers.Serializer):
    observation_text = serializers.CharField()


class SpaceTemplateQuerySerializer(serializers.Serializer):
    property_type = serializers.ChoiceField(choices=Property.Type.choices)
