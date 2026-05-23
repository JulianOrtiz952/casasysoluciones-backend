from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from pot.models import CustomUser, Property, Ticket, UserPropertyAssociation


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class UserManagementAPITests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.render_patch = patch(
            'pot.services.email_service.render_to_string',
            return_value='<html></html>',
        )
        cls.render_patch.start()

    @classmethod
    def tearDownClass(cls):
        cls.render_patch.stop()
        super().tearDownClass()
    def setUp(self):
        self.client = APIClient()
        self.admin = CustomUser.objects.create_user(
            email='admin@test.com',
            password='AdminPass123!',
            role=CustomUser.Role.ADMIN,
            password_changed=True,
        )
        self.assistant = CustomUser.objects.create_user(
            email='assistant@test.com',
            password='AssistPass123!',
            role=CustomUser.Role.ASSISTANT,
            password_changed=True,
        )
        self.prop1 = Property.objects.create(
            code='PRO-00001',
            address='Calle 1 #10-20',
            type=Property.Type.APARTMENT,
            owner_name='Dueño 1',
            status=Property.Status.AVAILABLE,
        )
        self.prop2 = Property.objects.create(
            code='PRO-00002',
            address='Calle 2 #20-30',
            type=Property.Type.HOUSE,
            owner_name='Dueño 2',
            status=Property.Status.AVAILABLE,
        )

    def test_non_admin_cannot_create_user(self):
        self.client.force_authenticate(user=self.assistant)
        r = self.client.post(
            '/api/v1/users/',
            {
                'email': 'nuevo@tenant.com',
                'first_name': 'Nuevo',
                'property_ids': [self.prop1.id],
            },
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_creates_tenant_and_sends_email(self):
        self.client.force_authenticate(user=self.admin)
        r = self.client.post(
            '/api/v1/users/',
            {
                'email': 'tenant.new@test.com',
                'first_name': 'Ana',
                'last_name': 'Pérez',
                'phone': '3001234567',
                'document_type': 'CC',
                'document_number': '1234567890',
                'property_ids': [self.prop1.id, self.prop2.id],
            },
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        user = CustomUser.objects.get(email='tenant.new@test.com')
        self.assertEqual(user.role, CustomUser.Role.TENANT)
        self.assertFalse(user.password_changed)
        self.assertEqual(user.property_associations.filter(dissociated_at__isnull=True).count(), 2)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('tenant.new@test.com', mail.outbox[0].to)

    def test_cannot_associate_property_with_active_tenant(self):
        tenant = CustomUser.objects.create_user(
            email='ocupado@test.com',
            password='x',
            role=CustomUser.Role.TENANT,
        )
        UserPropertyAssociation.objects.create(user=tenant, property=self.prop1, created_by=self.admin)
        self.prop1.status = Property.Status.RENTED
        self.prop1.save()

        self.client.force_authenticate(user=self.admin)
        r = self.client.post(
            '/api/v1/users/',
            {
                'email': 'otro@test.com',
                'property_ids': [self.prop1.id],
            },
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(r.json()['error']['code'], 'property_already_rented')

    def test_associate_tenant_property_rf04(self):
        tenant = CustomUser.objects.create_user(
            email='multi@test.com',
            password='x',
            role=CustomUser.Role.TENANT,
        )
        self.client.force_authenticate(user=self.admin)
        r = self.client.post(
            f'/api/v1/tenants/{tenant.id}/properties/',
            {'property_id': self.prop1.id},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertTrue(
            UserPropertyAssociation.objects.filter(
                user=tenant, property=self.prop1, dissociated_at__isnull=True
            ).exists()
        )

    def test_dissociate_tenant_property(self):
        tenant = CustomUser.objects.create_user(
            email='dissoc@test.com',
            password='x',
            role=CustomUser.Role.TENANT,
        )
        UserPropertyAssociation.objects.create(user=tenant, property=self.prop1, created_by=self.admin)
        self.client.force_authenticate(user=self.admin)
        r = self.client.delete(f'/api/v1/tenants/{tenant.id}/properties/{self.prop1.id}/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        assoc = UserPropertyAssociation.objects.get(user=tenant, property=self.prop1)
        self.assertIsNotNone(assoc.dissociated_at)

    def test_deactivate_preserves_user_and_history_rf05(self):
        tenant = CustomUser.objects.create_user(
            email='desact@test.com',
            password='x',
            role=CustomUser.Role.TENANT,
            is_active=True,
        )
        UserPropertyAssociation.objects.create(user=tenant, property=self.prop1, created_by=self.admin)
        self.client.force_authenticate(user=self.admin)
        r = self.client.post(f'/api/v1/users/{tenant.id}/deactivate/', {}, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        tenant.refresh_from_db()
        self.assertFalse(tenant.is_active)
        self.assertTrue(CustomUser.objects.filter(pk=tenant.pk).exists())
        self.assertFalse(
            UserPropertyAssociation.objects.filter(user=tenant, dissociated_at__isnull=True).exists()
        )

    def test_deactivate_warns_on_open_tickets_without_confirm(self):
        tenant = CustomUser.objects.create_user(
            email='tickets@test.com',
            password='x',
            role=CustomUser.Role.TENANT,
        )
        Ticket.objects.create(property=self.prop1, tenant=tenant, status=Ticket.Status.OPEN)
        self.client.force_authenticate(user=self.admin)
        r = self.client.post(f'/api/v1/users/{tenant.id}/deactivate/', {}, format='json')
        self.assertEqual(r.status_code, status.HTTP_409_CONFLICT)
        self.assertTrue(r.json()['requires_confirm'])

        r2 = self.client.post(
            f'/api/v1/users/{tenant.id}/deactivate/',
            {'confirm': True},
            format='json',
        )
        self.assertEqual(r2.status_code, status.HTTP_200_OK)

    def test_role_change_warns_on_open_tickets_rf03(self):
        tenant = CustomUser.objects.create_user(
            email='rol@test.com',
            password='x',
            role=CustomUser.Role.TENANT,
        )
        Ticket.objects.create(property=self.prop1, tenant=tenant, status=Ticket.Status.OPEN)
        self.client.force_authenticate(user=self.admin)
        r = self.client.patch(
            f'/api/v1/users/{tenant.id}/role/',
            {'role': CustomUser.Role.ASSISTANT},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_409_CONFLICT)

        r2 = self.client.patch(
            f'/api/v1/users/{tenant.id}/role/',
            {'role': CustomUser.Role.ASSISTANT, 'confirm': True},
            format='json',
        )
        self.assertEqual(r2.status_code, status.HTTP_200_OK)
        tenant.refresh_from_db()
        self.assertEqual(tenant.role, CustomUser.Role.ASSISTANT)

    def test_users_stats(self):
        self.client.force_authenticate(user=self.admin)
        r = self.client.get('/api/v1/users/stats/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn('total', r.data)
        self.assertIn('by_role', r.data)

    def test_list_tenants_admin_only(self):
        CustomUser.objects.create_user(email='t1@test.com', password='x', role=CustomUser.Role.TENANT)
        self.client.force_authenticate(user=self.admin)
        r = self.client.get('/api/v1/tenants/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(r.data['count'], 1)

    def test_list_users_with_filters(self):
        self.client.force_authenticate(user=self.admin)
        r = self.client.get('/api/v1/users/', {'role': 'ADMIN'})
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_patch_user_profile(self):
        tenant = CustomUser.objects.create_user(
            email='patch@test.com',
            password='x',
            role=CustomUser.Role.TENANT,
        )
        self.client.force_authenticate(user=self.admin)
        r = self.client.patch(
            f'/api/v1/users/{tenant.id}/',
            {'first_name': 'Actualizado', 'phone': '3100000000'},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        tenant.refresh_from_db()
        self.assertEqual(tenant.first_name, 'Actualizado')
