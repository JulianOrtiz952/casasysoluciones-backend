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

    def test_login_with_email(self):
        r = self.client.post(
            '/api/v1/auth/login/',
            {'email': 'tenant@test.com', 'password': self.password},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn('access', r.data)
        self.assertIn('refresh', r.data)
        self.assertEqual(r.data['user']['email'], 'tenant@test.com')

    def test_login_with_document_number(self):
        r = self.client.post(
            '/api/v1/auth/login/',
            {'document_number': '1020304050', 'password': self.password},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn('access', r.data)

    def test_login_invalid_locks_after_limit(self):
        for _ in range(3):
            r = self.client.post(
                '/api/v1/auth/login/',
                {'email': 'tenant@test.com', 'password': 'wrong'},
                format='json',
            )
            self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)
        r = self.client.post(
            '/api/v1/auth/login/',
            {'email': 'tenant@test.com', 'password': self.password},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(r.json()['error']['code'], 'account_locked')

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
