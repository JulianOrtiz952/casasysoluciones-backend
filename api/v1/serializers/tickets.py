from rest_framework import serializers

from pot.models import Property, Ticket, TicketAttachment


class TicketPropertyBriefSerializer(serializers.ModelSerializer):
    type_display = serializers.CharField(source='get_type_display', read_only=True)

    class Meta:
        model = Property
        fields = ['id', 'code', 'address', 'city', 'type', 'type_display', 'status']


class TicketAttachmentSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = TicketAttachment
        fields = ['id', 'image_url', 'uploaded_at']

    def get_image_url(self, obj):
        return obj.image.url if obj.image else None


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

    def get_attachments_count(self, obj):
        return obj.attachments.count()

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
        ]


class TicketDetailSerializer(TicketListSerializer):
    attachments = TicketAttachmentSerializer(many=True, read_only=True)

    class Meta(TicketListSerializer.Meta):
        fields = TicketListSerializer.Meta.fields + ['attachments']


class TicketAttachmentUploadSerializer(serializers.Serializer):
    image = serializers.ImageField()


class TicketReportProblemSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=3, max_length=1000)

