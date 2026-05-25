from rest_framework import serializers

from pot.models import CustomUser, Property, Ticket, TicketAttachment, TicketComment, TicketStatusLog


class TicketPropertyBriefSerializer(serializers.ModelSerializer):
    type_display = serializers.CharField(source='get_type_display', read_only=True)

    class Meta:
        model = Property
        fields = ['id', 'code', 'address', 'city', 'type', 'type_display', 'status']


class TicketAttachmentSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    attachment_type_display = serializers.CharField(
        source='get_attachment_type_display',
        read_only=True,
    )

    class Meta:
        model = TicketAttachment
        fields = ['id', 'image_url', 'attachment_type', 'attachment_type_display', 'uploaded_at']

    def get_image_url(self, obj):
        return obj.image.url if obj.image else None


class TicketTenantBriefSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = ['id', 'email', 'full_name', 'document_number', 'public_code']

    def get_full_name(self, obj):
        return obj.get_full_name() or obj.email


class TicketStatusLogSerializer(serializers.ModelSerializer):
    from_status_display = serializers.SerializerMethodField()
    to_status_display = serializers.CharField(source='get_to_status_display', read_only=True)
    action_display = serializers.CharField(source='get_action_display', read_only=True)
    changed_by_email = serializers.SerializerMethodField()

    class Meta:
        model = TicketStatusLog
        fields = [
            'id',
            'from_status',
            'from_status_display',
            'to_status',
            'to_status_display',
            'action',
            'action_display',
            'note',
            'changed_by_email',
            'created_at',
        ]

    def get_from_status_display(self, obj):
        if not obj.from_status:
            return ''
        try:
            return Ticket.Status(obj.from_status).label
        except ValueError:
            return obj.from_status

    def get_changed_by_email(self, obj):
        return obj.changed_by.email if obj.changed_by else None


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
    has_repair_evidence = serializers.SerializerMethodField()
    awaits_tenant_confirmation = serializers.SerializerMethodField()
    status_logs = TicketStatusLogSerializer(many=True, read_only=True)

    class Meta(TicketListSerializer.Meta):
        fields = TicketListSerializer.Meta.fields + [
            'attachments',
            'has_repair_evidence',
            'confirmation_deadline_at',
            'tenant_confirmed_at',
            'closed_automatically',
            'awaits_tenant_confirmation',
            'status_logs',
        ]

    def get_has_repair_evidence(self, obj):
        return obj.has_repair_evidence()

    def get_awaits_tenant_confirmation(self, obj):
        return obj.awaits_tenant_confirmation()


class StaffTicketListSerializer(TicketListSerializer):
    tenant = TicketTenantBriefSerializer(read_only=True)
    assigned_contractor_name = serializers.CharField(read_only=True)
    has_repair_evidence = serializers.SerializerMethodField()

    class Meta(TicketListSerializer.Meta):
        fields = TicketListSerializer.Meta.fields + [
            'tenant',
            'assigned_contractor_name',
            'has_repair_evidence',
            'confirmation_deadline_at',
        ]

    def get_has_repair_evidence(self, obj):
        return obj.has_repair_evidence()


class StaffTicketDetailSerializer(StaffTicketListSerializer):
    rejection_reason = serializers.CharField(read_only=True)
    status_logs = TicketStatusLogSerializer(many=True, read_only=True)
    repair_evidence = serializers.SerializerMethodField()

    class Meta(StaffTicketListSerializer.Meta):
        fields = StaffTicketListSerializer.Meta.fields + [
            'rejection_reason',
            'status_logs',
            'repair_evidence',
            'tenant_confirmed_at',
            'closed_automatically',
        ]

    def get_repair_evidence(self, obj):
        qs = obj.attachments.filter(
            attachment_type=TicketAttachment.AttachmentType.REPAIR_EVIDENCE,
        )
        return TicketAttachmentSerializer(qs, many=True).data


class TicketStatusChangeSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Ticket.Status.choices)
    note = serializers.CharField(required=False, allow_blank=True, default='')
    force_close = serializers.BooleanField(required=False, default=False)
    justification = serializers.CharField(required=False, allow_blank=True, default='')


class TicketRejectSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=20)


class TicketAssignSerializer(serializers.Serializer):
    contractor_name = serializers.CharField(min_length=2, max_length=200)
    visit_note = serializers.CharField(required=False, allow_blank=True, default='', max_length=500)


class TicketRepairEvidenceUploadSerializer(serializers.Serializer):
    image = serializers.ImageField()


class TicketAttachmentUploadSerializer(serializers.Serializer):
    image = serializers.ImageField()


class TicketDisputeSerializer(serializers.Serializer):
    note = serializers.CharField(min_length=10)


class TicketCommentSerializer(serializers.ModelSerializer):
    message_type_display = serializers.CharField(source='get_message_type_display', read_only=True)
    author_name = serializers.SerializerMethodField()
    author_role = serializers.SerializerMethodField()

    class Meta:
        model = TicketComment
        fields = [
            'id',
            'body',
            'message_type',
            'message_type_display',
            'author_id',
            'author_name',
            'author_role',
            'created_at',
        ]
        read_only_fields = fields

    def get_author_name(self, obj):
        if not obj.author:
            return ''
        return obj.author.get_full_name() or obj.author.email

    def get_author_role(self, obj):
        return obj.author.role if obj.author else ''


class TicketCommentCreateSerializer(serializers.Serializer):
    body = serializers.CharField(min_length=1)


class TicketInfoRequestSerializer(serializers.Serializer):
    message = serializers.CharField(min_length=10)
