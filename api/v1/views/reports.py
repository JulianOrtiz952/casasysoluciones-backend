import io

from django.http import HttpResponse
from drf_spectacular.utils import OpenApiParameter, extend_schema
from openpyxl import Workbook
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from api.v1.exceptions import APIError
from api.v1.permissions import IsAdmin
from pot.services.report_service import (
    ReportServiceError,
    busqueda_global,
    exportar_reporte_excel,
    listar_inmuebles_con_tickets_abiertos,
    listar_inquilinos_con_tickets_activos,
    obtener_historial_reparaciones_inmueble,
    obtener_resumen_reportes,
    obtener_semaforo_consolidado,
)


def _handle_report_error(exc):
    status_map = {
        'property_not_found': status.HTTP_404_NOT_FOUND,
        'query_too_short': status.HTTP_400_BAD_REQUEST,
    }
    raise APIError(
        exc.code,
        exc.message,
        status_code=status_map.get(exc.code, status.HTTP_400_BAD_REQUEST),
        details=exc.details,
    ) from exc


def _filter_params(request):
    params = request.query_params
    property_id = params.get('property_id')
    tenant_id = params.get('tenant_id')
    if property_id:
        try:
            property_id = int(property_id)
        except (TypeError, ValueError):
            raise APIError('invalid_property_id', 'property_id debe ser un entero.', status_code=400)
    if tenant_id:
        try:
            tenant_id = int(tenant_id)
        except (TypeError, ValueError):
            raise APIError('invalid_tenant_id', 'tenant_id debe ser un entero.', status_code=400)
    return {
        'property_id': property_id,
        'tenant_id': tenant_id,
        'date_from': params.get('date_from'),
        'date_to': params.get('date_to'),
    }


class ReportFilterMixin:
    def get_report_filters(self):
        return _filter_params(self.request)


class TicketTrafficLightView(ReportFilterMixin, APIView):
    """RF-29: semáforo consolidado y pendientes por resolver."""

    permission_classes = [IsAdmin]

    @extend_schema(
        tags=['Reports'],
        summary='Semáforo de tickets (RF-29)',
        parameters=[
            OpenApiParameter('property_id', int, OpenApiParameter.QUERY, required=False),
            OpenApiParameter('tenant_id', int, OpenApiParameter.QUERY, required=False),
            OpenApiParameter('date_from', str, OpenApiParameter.QUERY, required=False),
            OpenApiParameter('date_to', str, OpenApiParameter.QUERY, required=False),
        ],
    )
    def get(self, request):
        return Response(obtener_semaforo_consolidado(**self.get_report_filters()))


class ReportSummaryView(ReportFilterMixin, APIView):
    permission_classes = [IsAdmin]

    @extend_schema(tags=['Reports'], summary='Resumen de reportes con gráficos')
    def get(self, request):
        return Response(obtener_resumen_reportes(**self.get_report_filters()))


class PropertiesWithOpenTicketsView(ReportFilterMixin, APIView):
    permission_classes = [IsAdmin]

    @extend_schema(tags=['Reports'], summary='Inmuebles arrendados con tickets abiertos (RF-30)')
    def get(self, request):
        return Response(listar_inmuebles_con_tickets_abiertos(**self.get_report_filters()))


class TenantsWithActiveTicketsView(ReportFilterMixin, APIView):
    permission_classes = [IsAdmin]

    @extend_schema(tags=['Reports'], summary='Inquilinos con tickets activos (RF-30)')
    def get(self, request):
        return Response(listar_inquilinos_con_tickets_activos(**self.get_report_filters()))


class PropertyRepairHistoryView(ReportFilterMixin, APIView):
    permission_classes = [IsAdmin]

    @extend_schema(tags=['Reports'], summary='Historial de reparaciones de un inmueble (RF-30)')
    def get(self, request, property_id):
        filters = self.get_report_filters()
        filters.pop('property_id', None)
        try:
            data = obtener_historial_reparaciones_inmueble(property_id, **filters)
        except ReportServiceError as exc:
            _handle_report_error(exc)
        return Response(data)


class ReportsExportExcelView(ReportFilterMixin, APIView):
    permission_classes = [IsAdmin]

    @extend_schema(
        tags=['Reports'],
        summary='Exportar tickets a Excel (RF-30)',
        parameters=[
            OpenApiParameter('property_id', int, OpenApiParameter.QUERY, required=False),
            OpenApiParameter('tenant_id', int, OpenApiParameter.QUERY, required=False),
            OpenApiParameter('date_from', str, OpenApiParameter.QUERY, required=False),
            OpenApiParameter('date_to', str, OpenApiParameter.QUERY, required=False),
        ],
    )
    def get(self, request):
        rows = exportar_reporte_excel(**self.get_report_filters())
        wb = Workbook()
        ws = wb.active
        ws.title = 'Reporte tickets'
        for row in rows:
            ws.append(row)
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        response = HttpResponse(
            buf.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = 'attachment; filename="reporte-tickets.xlsx"'
        return response


class GlobalSearchView(APIView):
    permission_classes = [IsAdmin]

    @extend_schema(
        tags=['Reports'],
        summary='Búsqueda global',
        parameters=[OpenApiParameter('q', str, OpenApiParameter.QUERY, required=True)],
    )
    def get(self, request):
        try:
            data = busqueda_global(request.query_params.get('q', ''))
        except ReportServiceError as exc:
            _handle_report_error(exc)
        return Response(data)
