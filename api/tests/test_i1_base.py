"""Pruebas base i1 — CP-RF-01 (RF-01 autenticación)."""

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from api.models import Inmueble
from pot.models import CustomUser, LoginThrottle, Property, UserPropertyAssociation
from pot.services.auth_service import _device_lock_seconds


@override_settings(
    LOGIN_LOCKOUT_SCHEDULE=((3, 30), (5, 60), (7, 300), (9, 600), (11, 1800)),
    LOGIN_NETWORK_ATTEMPT_LIMIT=20,
    LOGIN_NETWORK_COOLDOWN=1800,
    LOGIN_ATTEMPT_RESET_WINDOW=86400,
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
            HTTP_X_DEVICE_ID='11111111-1111-4111-8111-111111111111',
        )
        self.assertEqual(r_bad.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(r_bad.json()['error']['code'], 'invalid_credentials')

        r = self.client.post(
            '/api/v1/auth/login/',
            {'email': 'tenant@test.com', 'password': 'wrong'},
            format='json',
            HTTP_X_DEVICE_ID='11111111-1111-4111-8111-111111111111',
        )
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

        r_locked = self.client.post(
            '/api/v1/auth/login/',
            {'email': 'tenant@test.com', 'password': 'wrong'},
            format='json',
            HTTP_X_DEVICE_ID='11111111-1111-4111-8111-111111111111',
        )
        self.assertEqual(r_locked.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(r_locked.json()['error']['code'], 'login_temporarily_blocked')
        self.assertIn('Retry-After', r_locked)
        self.assertLessEqual(int(r_locked['Retry-After']), 30)
        self.assertGreater(int(r_locked['Retry-After']), 0)

        still_locked = self.client.post(
            '/api/v1/auth/login/',
            {'email': 'tenant@test.com', 'password': self.password},
            format='json',
            HTTP_X_DEVICE_ID='11111111-1111-4111-8111-111111111111',
        )
        self.assertEqual(still_locked.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

        other_device = self.client.post(
            '/api/v1/auth/login/',
            {'email': 'tenant@test.com', 'password': self.password},
            format='json',
            HTTP_X_DEVICE_ID='22222222-2222-4222-8222-222222222222',
        )
        self.assertEqual(other_device.status_code, status.HTTP_200_OK)

    def test_legacy_token_alias_uses_protected_login(self):
        response = self.client.post(
            '/api/v1/token/',
            {'email': 'tenant@test.com', 'password': self.password},
            format='json',
            HTTP_X_DEVICE_ID='33333333-3333-4333-8333-333333333333',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)

    def test_progressive_lockout_keeps_attempt_history_between_waits(self):
        device_id = '44444444-4444-4444-8444-444444444444'

        for expected_status in (401, 401, 429):
            response = self.client.post(
                '/api/v1/auth/login/',
                {'email': 'tenant@test.com', 'password': 'wrong'},
                format='json',
                HTTP_X_DEVICE_ID=device_id,
            )
            self.assertEqual(response.status_code, expected_status)

        first_wait = int(response['Retry-After'])
        self.assertGreater(first_wait, 0)
        self.assertLessEqual(first_wait, 30)

        LoginThrottle.objects.filter(locked_until__isnull=False).update(
            locked_until=timezone.now() - timedelta(seconds=1),
        )

        fourth_attempt = self.client.post(
            '/api/v1/auth/login/',
            {'email': 'tenant@test.com', 'password': 'wrong'},
            format='json',
            HTTP_X_DEVICE_ID=device_id,
        )
        self.assertEqual(fourth_attempt.status_code, status.HTTP_401_UNAUTHORIZED)

        fifth_attempt = self.client.post(
            '/api/v1/auth/login/',
            {'email': 'tenant@test.com', 'password': 'wrong'},
            format='json',
            HTTP_X_DEVICE_ID=device_id,
        )
        self.assertEqual(fifth_attempt.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        second_wait = int(fifth_attempt['Retry-After'])
        self.assertGreater(second_wait, 30)
        self.assertLessEqual(second_wait, 60)

    @override_settings(
        LOGIN_LOCKOUT_SCHEDULE=((5, 30), (7, 60), (9, 300), (11, 600), (13, 1800)),
    )
    def test_production_lockout_schedule(self):
        expected = {
            4: None,
            5: 30,
            6: None,
            7: 60,
            8: None,
            9: 300,
            10: None,
            11: 600,
            12: None,
            13: 1800,
            14: 1800,
        }
        self.assertEqual(
            {attempts: _device_lock_seconds(attempts) for attempts in expected},
            expected,
        )

    def test_login_cors_preflight_allows_device_header(self):
        response = self.client.options(
            '/api/v1/auth/login/',
            HTTP_ORIGIN='http://localhost:3000',
            HTTP_ACCESS_CONTROL_REQUEST_METHOD='POST',
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS='content-type,x-device-id',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        allowed_headers = response.headers.get('access-control-allow-headers', '').lower()
        self.assertIn('x-device-id', allowed_headers)

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
    def test_legacy_inmuebles_list_requires_authentication(self):
        c = APIClient()
        r = c.get('/api/v1/legacy/inmuebles/')
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

        compatibility = c.get('/api/v1/inmuebles/')
        self.assertEqual(compatibility.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_legacy_model_does_not_request_google_maps(self):
        with patch('urllib.request.urlopen') as urlopen:
            Inmueble.objects.create(
                titulo='Inmueble sin SSRF',
                precio=100000,
                direccion='Ver enlace de Google Maps adjunto',
                enlace_google_maps='http://127.0.0.1/private',
            )
        urlopen.assert_not_called()
