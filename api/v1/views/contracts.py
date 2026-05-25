from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from api.v1.exceptions import APIError
from api.v1.permissions import IsStaffOperative
from api.v1.serializers.contracts import ContractCloseSerializer, LeaseContractSerializer
from pot.models import LeaseContract
from pot.services.contract_service import ContractServiceError, cerrar_contrato


def _handle_contract_error(exc):
    status_map = {
        'contract_not_found': status.HTTP_404_NOT_FOUND,
        'contract_not_active': status.HTTP_400_BAD_REQUEST,
        'invalid_end_date': status.HTTP_400_BAD_REQUEST,
        'open_tickets': status.HTTP_409_CONFLICT,
        'association_not_found': status.HTTP_404_NOT_FOUND,
    }
    raise APIError(
        exc.code,
        exc.message,
        status_code=status_map.get(exc.code, status.HTTP_400_BAD_REQUEST),
        details=exc.details,
    ) from exc


class ContractViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, IsStaffOperative]
    serializer_class = LeaseContractSerializer

    def get_queryset(self):
        return LeaseContract.objects.select_related('property', 'tenant', 'final_inventory').order_by(
            '-created_at',
        )

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        contract = self.get_object()
        serializer = ContractCloseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            contract = cerrar_contrato(
                request.user,
                contract.pk,
                end_date=data.get('end_date'),
                deactivate_tenant=data.get('deactivate_tenant', False),
                notes=data.get('notes', ''),
            )
        except ContractServiceError as exc:
            _handle_contract_error(exc)
        return Response(LeaseContractSerializer(contract).data)
