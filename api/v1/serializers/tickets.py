from rest_framework import serializers

from pot.models import Property, Ticket, TicketAttachment, TicketHistory


class TicketPropertyBriefSerializer(serializers.ModelSerializer):
    type_display = serializers.CharField(source='get_type_display', read_only=True)

    class Meta:
        model = Property
        fields = ['id', 'code', 'address', 'city', 'type', 'type_display', 'status']


class TicketAttachmentSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    uploaded_by_detail = serializers.SerializerMethodField()

    class Meta:
        model = TicketAttachment
        fields = ['id', 'image_url', 'uploaded_at', 'uploaded_by', 'uploaded_by_detail']

    def get_image_url(self, obj):
        return obj.image.url if obj.image else None

    def get_uploaded_by_detail(self, obj):
        if not obj.uploaded_by:
            return None
        return {
            'id': obj.uploaded_by.id,
            'email': obj.uploaded_by.email,
            'first_name': obj.uploaded_by.first_name,
            'last_name': obj.uploaded_by.last_name,
            'role': obj.uploaded_by.role,
        }


class TicketCreateSerializer(serializers.Serializer):
    property_id = serializers.IntegerField(required=False, allow_null=True)
    description = serializers.CharField()
    damage_type = serializers.ChoiceField(choices=Ticket.DamageType.choices)
    damage_type_other = serializers.CharField(required=False, allow_blank=True, default='')
    priority = serializers.ChoiceField(choices=Ticket.Priority.choices)
    title = serializers.CharField(required=False, allow_blank=True, max_length=200)


class TicketListSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    damage_type_display = serializers.CharField(source='get_damage_type_display', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)
    property = TicketPropertyBriefSerializer(read_only=True)
    attachments_count = serializers.SerializerMethodField()
    assigned_technicians = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    assigned_technicians_detail = serializers.SerializerMethodField()
    tenant_detail = serializers.SerializerMethodField()

    def get_attachments_count(self, obj):
        return obj.attachments.count()

    def get_assigned_technicians_detail(self, obj):
        return [
            {
                'id': tech.id,
                'public_code': tech.public_code,
                'email': tech.email,
                'first_name': tech.first_name,
                'last_name': tech.last_name,
            }
            for tech in obj.assigned_technicians.all()
        ]

    def get_tenant_detail(self, obj):
        if not obj.tenant:
            return None
        return {
            'id': obj.tenant.id,
            'public_code': obj.tenant.public_code,
            'email': obj.tenant.email,
            'first_name': obj.tenant.first_name,
            'last_name': obj.tenant.last_name,
            'phone': obj.tenant.phone,
        }

    class Meta:
        model = Ticket
        fields = [
            'id',
            'public_code',
            'title',
            'description',
            'damage_type',
            'damage_type_display',
            'damage_type_other',
            'priority',
            'priority_display',
            'status',
            'status_display',
            'property',
            'attachments_count',
            'created_at',
            'updated_at',
            'assigned_contractor_name',
            'rejection_reason',
            'assigned_technicians',
            'assigned_technicians_detail',
            'tenant',
            'tenant_detail',
        ]


class TicketDetailSerializer(TicketListSerializer):
    attachments = TicketAttachmentSerializer(many=True, read_only=True)
    final_space_conditions = serializers.JSONField(read_only=True)

    class Meta(TicketListSerializer.Meta):
        fields = TicketListSerializer.Meta.fields + ['attachments', 'final_space_conditions']



class TicketAttachmentUploadSerializer(serializers.Serializer):
    image = serializers.ImageField()


class TicketReportProblemSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=3, max_length=1000)


class TicketHistorySerializer(serializers.ModelSerializer):
    action_display = serializers.CharField(source='get_action_display', read_only=True)
    created_by_detail = serializers.SerializerMethodField()

    class Meta:
        model = TicketHistory
        fields = [
            'id', 'action', 'action_display', 'description',
            'old_value', 'new_value',
            'created_by', 'created_by_detail', 'created_at',
        ]

    def get_created_by_detail(self, obj):
        if not obj.created_by:
            return None
        return {
            'id': obj.created_by.id,
            'email': obj.created_by.email,
            'first_name': obj.created_by.first_name,
            'last_name': obj.created_by.last_name,
            'role': obj.created_by.role,
        }

