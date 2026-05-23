"""Pruebas despliegue parcial i1 — OpenAPI, legacy, import Excel."""

import json
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from openpyxl import Workbook
from rest_framework import status
from rest_framework.test import APIClient

from pot.models import CustomUser, Property, UserPropertyAssociation


def _build_import_xlsx(rows):
    wb = Workbook()
    ws = wb.active
    ws.append(
        [
            'direccion',
            'tipo',
            'propietario',
            'ciudad',
            'email',
            'documento',
            'nombre',
            'apellido',
        ]
    )
    for row in rows:
        ws.append(row)
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class OpenApiSchemaTests(TestCase):
    def test_schema_i1_includes_core_paths(self):
        r = APIClient().get('/api/v1/schema/', HTTP_ACCEPT='application/json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        schema = json.loads(r.content)
        paths = schema.get('paths', {})
        self.assertIn('/api/v1/auth/login/', paths)
        self.assertIn('/api/v1/properties/', paths)
        self.assertIn('/api/v1/tickets/mine/', paths)
        self.assertIn('/api/v1/admin/import/excel/', paths)
        self.assertIn('/api/v1/legacy/inmuebles/', paths)

    def test_schema_endpoint_registered(self):
        from django.urls import resolve

        match = resolve('/api/v1/schema/')
        self.assertEqual(match.url_name, 'schema-i1')


class LegacyRoutingExtendedTests(TestCase):
    def test_legacy_and_compat_inmuebles_list(self):
        c = APIClient()
        legacy = c.get('/api/v1/legacy/inmuebles/')
        compat = c.get('/api/v1/inmuebles/')
        self.assertEqual(legacy.status_code, status.HTTP_200_OK)
        self.assertEqual(compat.status_code, status.HTTP_200_OK)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class ImportExcelTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = CustomUser.objects.create_user(
            email='admin-import@test.com',
            password='AdminPass123!',
            role=CustomUser.Role.ADMIN,
            password_changed=True,
        )
        self.tenant = CustomUser.objects.create_user(
            email='assistant-import@test.com',
            password='AssistPass123!',
            role=CustomUser.Role.ASSISTANT,
            password_changed=True,
        )

    def test_import_requires_admin(self):
        self.client.force_authenticate(user=self.tenant)
        content = _build_import_xlsx([['Calle 1', 'Apartamento', 'Dueño 1', 'Bogota', '', '', '', '']])
        upload = SimpleUploadedFile(
            'carga.xlsx',
            content,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        r = self.client.post(
            '/api/v1/admin/import/excel/',
            {'file': upload},
            format='multipart',
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_import_creates_property_and_tenant(self):
        self.client.force_authenticate(user=self.admin)
        content = _build_import_xlsx(
            [
                [
                    'Carrera 10 # 20-30',
                    'Casa',
                    'Juan Pérez',
                    'Medellín',
                    'inquilino@import.test',
                    '99887766',
                    'Ana',
                    'García',
                ],
            ]
        )
        upload = SimpleUploadedFile(
            'carga.xlsx',
            content,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        r = self.client.post(
            '/api/v1/admin/import/excel/',
            {'file': upload},
            format='multipart',
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['properties_created'], 1)
        self.assertEqual(r.data['tenants_created'], 1)
        self.assertTrue(Property.objects.filter(address__iexact='Carrera 10 # 20-30').exists())
        tenant = CustomUser.objects.get(email='inquilino@import.test')
        self.assertEqual(tenant.role, CustomUser.Role.TENANT)
        self.assertTrue(
            UserPropertyAssociation.objects.filter(
                user=tenant,
                property__address__iexact='Carrera 10 # 20-30',
                dissociated_at__isnull=True,
            ).exists()
        )

    def test_import_dry_run_does_not_persist(self):
        self.client.force_authenticate(user=self.admin)
        content = _build_import_xlsx([['Calle Dry Run', 'Local', 'Owner', 'Cali', '', '', '', '']])
        upload = SimpleUploadedFile(
            'carga.xlsx',
            content,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        r = self.client.post(
            '/api/v1/admin/import/excel/?dry_run=true',
            {'file': upload},
            format='multipart',
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertTrue(r.data['dry_run'])
        self.assertFalse(Property.objects.filter(address__iexact='Calle Dry Run').exists())
