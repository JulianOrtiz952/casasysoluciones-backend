"""Pruebas base i1 — CP-RF-01 (RF-01 autenticación)."""

from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from pot.models import CustomUser, Property, UserPropertyAssociation


@override_settings(
    LOGIN_ATTEMPT_LIMIT=3,
    LOGIN_COOLDOWN=3600,
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
)
class V1AuthAndCatalogTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.password = 'TestPass123!'
        self.user = CustomUser.objects.create_user(
            email='tenant@test.com',
            password=self.password,
            role=CustomUser.Role.TENANT,
            document_number='1020304050',
            document_type=CustomUser.DocumentType.CC,
            password_changed=True,
        )

    def test_catalogs_public_returns_expected_keys(self):
        r = self.client.get('/api/v1/catalogs/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        for key in (
            'roles',
            'property_types',
            'inventory_conditions',
            'ticket_damage_types',
            'ticket_priorities',
        ):
            self.assertIn(key, r.data)

    def test_cp_rf_01_login_email_cedula_lockout_rf01(self):
        """CP-RF-01: login con email o cédula, error claro y bloqueo por intentos fallidos."""
        r_email = self.client.post(
            '/api/v1/auth/login/',
            {'email': 'tenant@test.com', 'password': self.password},
            format='json',
        )
        self.assertEqual(r_email.status_code, status.HTTP_200_OK)
        self.assertIn('access', r_email.data)
        self.assertIn('refresh', r_email.data)
        self.assertEqual(r_email.data['user']['email'], 'tenant@test.com')

        r_doc = self.client.post(
            '/api/v1/auth/login/',
            {'document_number': '1020304050', 'password': self.password},
            format='json',
        )
        self.assertEqual(r_doc.status_code, status.HTTP_200_OK)
        self.assertIn('access', r_doc.data)

        r_bad = self.client.post(
            '/api/v1/auth/login/',
            {'email': 'tenant@test.com', 'password': 'wrong'},
            format='json',
        )
        self.assertEqual(r_bad.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(r_bad.json()['error']['code'], 'invalid_credentials')

        for _ in range(2):
            r = self.client.post(
                '/api/v1/auth/login/',
                {'email': 'tenant@test.com', 'password': 'wrong'},
                format='json',
            )
            self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)
        r_locked = self.client.post(
            '/api/v1/auth/login/',
            {'email': 'tenant@test.com', 'password': self.password},
            format='json',
        )
        self.assertEqual(r_locked.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(r_locked.json()['error']['code'], 'account_locked')

    def test_me_requires_auth(self):
        r = self.client.get('/api/v1/auth/me/')
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_returns_properties_for_tenant(self):
        prop = Property.objects.create(
            code='PRO-00001',
            address='Calle 123',
            type=Property.Type.APARTMENT,
            owner_name='Dueño',
        )
        UserPropertyAssociation.objects.create(user=self.user, property=prop)

        self.client.force_authenticate(user=self.user)
        r = self.client.get('/api/v1/auth/me/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(r.data['properties']), 1)


class LegacyRoutingTests(TestCase):
    def test_legacy_inmuebles_list(self):
        c = APIClient()
        r = c.get('/api/v1/legacy/inmuebles/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
