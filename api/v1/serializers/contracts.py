from rest_framework import serializers

from pot.models import LeaseContract


class ContractCloseSerializer(serializers.Serializer):
    end_date = serializers.DateField(required=False)
    deactivate_tenant = serializers.BooleanField(default=False)
    notes = serializers.CharField(required=False, allow_blank=True, default='')


class LeaseContractSerializer(serializers.ModelSerializer):
    property_code = serializers.CharField(source='property.code', read_only=True)
    tenant_email = serializers.EmailField(source='tenant.email', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = LeaseContract
        fields = [
            'id',
            'property',
            'property_code',
            'tenant',
            'tenant_email',
            'start_date',
            'end_date',
            'status',
            'status_display',
            'final_inventory',
            'closed_at',
            'notes',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields
