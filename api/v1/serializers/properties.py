from rest_framework import serializers

from pot.models import CustomUser, Property, PropertyHistory, PropertyImage, Ticket


class ActiveTenantBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ['id', 'public_code', 'email', 'first_name', 'last_name', 'document_number']


class PropertyImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = PropertyImage
        fields = ['id', 'image', 'is_cover']

class PropertyListSerializer(serializers.ModelSerializer):
    type_display = serializers.CharField(source='get_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    active_tenant = serializers.SerializerMethodField()
    cover_image = serializers.ImageField(read_only=True)
    images = PropertyImageSerializer(many=True, read_only=True)
    has_active_closure_request = serializers.SerializerMethodField()
    active_closure_ticket_id = serializers.SerializerMethodField()

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
            'price',
            'rooms',
            'bathrooms',
            'living_rooms',
            'kitchens',
            'garages',
            'is_commercial',
            'in_complex',
            'admin_included',
            'admin_value',
            'google_maps_link',
            'active_tenant',
            'cover_image',
            'images',
            'has_active_closure_request',
            'active_closure_ticket_id',
            'is_active',
            'created_at',
            'updated_at',
        ]

    def get_active_tenant(self, obj):
        tenant = obj.get_active_tenant()
        if not tenant:
            return None
        return ActiveTenantBriefSerializer(tenant).data

    def get_has_active_closure_request(self, obj):
        tenant = obj.get_active_tenant()
        if not tenant:
            return False
        return Ticket.objects.filter(
            property=obj,
            tenant=tenant,
            damage_type=Ticket.DamageType.CLOSURE,
            status__in=[Ticket.Status.OPEN, Ticket.Status.ACCEPTED, Ticket.Status.IN_PROGRESS]
        ).exists()

    def get_active_closure_ticket_id(self, obj):
        tenant = obj.get_active_tenant()
        if not tenant:
            return None
        t = Ticket.objects.filter(
            property=obj,
            tenant=tenant,
            damage_type=Ticket.DamageType.CLOSURE,
            status__in=[Ticket.Status.OPEN, Ticket.Status.ACCEPTED, Ticket.Status.IN_PROGRESS]
        ).first()
        return t.id if t else None


class PropertyDetailSerializer(PropertyListSerializer):
    created_by_email = serializers.EmailField(
        source='created_by.email',
        read_only=True,
        default=None,
    )
    observations = serializers.CharField(allow_null=True, required=False)

    class Meta(PropertyListSerializer.Meta):
        fields = PropertyListSerializer.Meta.fields + [
            'observations',
            'description',
            'created_by_email',
        ]


class PropertyCreateSerializer(serializers.Serializer):
    address = serializers.CharField(max_length=255, required=False, allow_blank=True)
    type = serializers.ChoiceField(choices=Property.Type.choices)
    owner_name = serializers.CharField(max_length=150)
    city = serializers.CharField(max_length=100, required=False, allow_blank=True, default='')
    building_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default='')
    unit_label = serializers.CharField(max_length=50, required=False, allow_blank=True, default='')
    
    price = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, default=0)
    rooms = serializers.IntegerField(required=False, allow_null=True)
    bathrooms = serializers.IntegerField(required=False, allow_null=True)
    living_rooms = serializers.IntegerField(required=False, allow_null=True)
    kitchens = serializers.IntegerField(required=False, allow_null=True)
    garages = serializers.IntegerField(required=False, allow_null=True)
    is_commercial = serializers.BooleanField(required=False, default=False)
    in_complex = serializers.BooleanField(required=False, default=False)
    admin_included = serializers.BooleanField(required=False, default=False)
    admin_value = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    google_maps_link = serializers.CharField(max_length=1000, required=False, allow_blank=True, allow_null=True)
    description = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    
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
    
    price = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    rooms = serializers.IntegerField(required=False, allow_null=True)
    bathrooms = serializers.IntegerField(required=False, allow_null=True)
    living_rooms = serializers.IntegerField(required=False, allow_null=True)
    kitchens = serializers.IntegerField(required=False, allow_null=True)
    garages = serializers.IntegerField(required=False, allow_null=True)
    is_commercial = serializers.BooleanField(required=False)
    in_complex = serializers.BooleanField(required=False)
    admin_included = serializers.BooleanField(required=False)
    admin_value = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    google_maps_link = serializers.CharField(max_length=1000, required=False, allow_blank=True, allow_null=True)
    description = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    is_active = serializers.BooleanField(required=False)

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
