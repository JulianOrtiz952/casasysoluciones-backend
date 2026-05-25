from rest_framework import serializers

from pot.models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    notification_type_display = serializers.CharField(
        source='get_notification_type_display',
        read_only=True,
    )
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)
    ticket_public_code = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            'id',
            'notification_type',
            'notification_type_display',
            'priority',
            'priority_display',
            'title',
            'body',
            'ticket_id',
            'ticket_public_code',
            'ticket_comment_id',
            'is_read',
            'read_at',
            'created_at',
        ]
        read_only_fields = fields

    def get_ticket_public_code(self, obj):
        if obj.ticket:
            return obj.ticket.public_code
        return None
