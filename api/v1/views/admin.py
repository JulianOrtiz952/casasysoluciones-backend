from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from api.v1.exceptions import APIError
from api.v1.permissions import IsAdmin
from pot.services.import_excel_service import ImportExcelError, importar_desde_excel


class ImportExcelView(APIView):
    """Carga inicial de inmuebles y arrendatarios desde plantilla Excel (.xlsx). Solo ADMIN."""

    permission_classes = [IsAdmin]
    parser_classes = [MultiPartParser]

    @extend_schema(
        tags=['Admin'],
        summary='Importar inmuebles y arrendatarios desde Excel',
        description=(
            'Carga masiva inicial (Acta 2). Columnas obligatorias: `direccion`, `propietario`. '
            'Opcionales: `tipo`, `ciudad`, `edificio`, `unidad`, `estado`, `email`, `documento`, '
            '`tipo_documento`, `nombre`, `apellido`, `telefono`.'
        ),
        parameters=[
            OpenApiParameter(
                name='send_credentials',
                type=bool,
                location=OpenApiParameter.QUERY,
                description='Si es true, envía correo con contraseña temporal a arrendatarios nuevos.',
            ),
            OpenApiParameter(
                name='dry_run',
                type=bool,
                location=OpenApiParameter.QUERY,
                description='Valida el archivo sin persistir cambios.',
            ),
        ],
        request={
            'multipart/form-data': {
                'type': 'object',
                'properties': {
                    'file': {'type': 'string', 'format': 'binary'},
                },
                'required': ['file'],
            }
        },
    )
    def post(self, request):
        upload = request.FILES.get('file')
        if not upload:
            raise APIError('file_required', 'Debe enviar el archivo en el campo "file".', status_code=400)

        name = (upload.name or '').lower()
        if not name.endswith('.xlsx'):
            raise APIError(
                'invalid_file_type',
                'Solo se admiten archivos Excel .xlsx.',
                status_code=400,
            )

        send_credentials = request.query_params.get('send_credentials', '').lower() in ('1', 'true', 'yes')
        dry_run = request.query_params.get('dry_run', '').lower() in ('1', 'true', 'yes')

        try:
            summary = importar_desde_excel(
                upload.read(),
                request.user,
                send_credentials=send_credentials,
                request=request,
                dry_run=dry_run,
            )
        except ImportExcelError as exc:
            raise APIError(exc.code, exc.message, status_code=400, details=exc.details) from exc

        status_code = 200 if not summary['errors'] else 207
        return Response(summary, status=status_code)
