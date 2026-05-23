import io
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from rest_framework import status
from rest_framework.test import APIClient

from pot.models import (
    CustomUser,
    Inventory,
    InventorySpace,
    InventoryTenantObservation,
    Property,
    PropertyHistory,
    UserPropertyAssociation,
)


def _make_test_image(name='photo.jpg'):
    buf = io.BytesIO()
    Image.new('RGB', (40, 40), color='red').save(buf, format='JPEG')
    buf.seek(0)
    return SimpleUploadedFile(name, buf.read(), content_type='image/jpeg')


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class InventoryInitialAPITests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.render_patch = patch(
            'pot.services.email_service.render_to_string',
            return_value='<p>test</p>',
        )
        cls.render_patch.start()

    @classmethod
    def tearDownClass(cls):
        cls.render_patch.stop()
        super().tearDownClass()

    def setUp(self):
        self.client = APIClient()
        self.admin = CustomUser.objects.create_user(
            email='admin-inv@test.com',
            password='AdminPass123!',
            role=CustomUser.Role.ADMIN,
            password_changed=True,
        )
        self.assistant = CustomUser.objects.create_user(
            email='assistant-inv@test.com',
            password='AssistPass123!',
            role=CustomUser.Role.ASSISTANT,
            password_changed=True,
        )
        self.tenant = CustomUser.objects.create_user(
            email='tenant-inv@test.com',
            password='TenantPass123!',
            role=CustomUser.Role.TENANT,
            password_changed=True,
        )
        self.property = Property.objects.create(
            code='PRO-INV01',
            address='Calle Inventario 1',
            type=Property.Type.APARTMENT,
            owner_name='Dueño',
            status=Property.Status.RENTED,
        )
        UserPropertyAssociation.objects.create(user=self.tenant, property=self.property)

    def _create_inventory(self):
        self.client.force_authenticate(user=self.admin)
        return self.client.post(
            '/api/v1/inventories/',
            {
                'property_id': self.property.id,
                'tenant_id': self.tenant.id,
                'delivery_date': '2026-05-01',
                'observations': 'Entrega inicial',
            },
            format='json',
        )

    def test_create_initial_inventory_rf08(self):
        r = self._create_inventory()
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data['status'], Inventory.Status.IN_PROGRESS)
        self.assertEqual(r.data['inventory_type'], Inventory.Type.INITIAL)
        inv = Inventory.objects.get(pk=r.data['id'])
        self.assertTrue(
            PropertyHistory.objects.filter(
                property=self.property,
                event_type=PropertyHistory.EventType.INVENTORY_CREATED,
            ).exists()
        )

    def test_create_rejects_unassociated_tenant(self):
        other_tenant = CustomUser.objects.create_user(
            email='other-tenant@test.com',
            password='TenantPass123!',
            role=CustomUser.Role.TENANT,
            password_changed=True,
        )
        self.client.force_authenticate(user=self.admin)
        r = self.client.post(
            '/api/v1/inventories/',
            {
                'property_id': self.property.id,
                'tenant_id': other_tenant.id,
                'delivery_date': '2026-05-01',
            },
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(r.json()['error']['code'], 'tenant_not_associated')

    def test_space_templates_rf09(self):
        self.client.force_authenticate(user=self.assistant)
        r = self.client.get('/api/v1/inventories/space-templates/?property_type=APARTMENT')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(r.data['spaces']), 5)
        self.assertEqual(r.data['spaces'][0]['space_name'], 'Sala')

    def test_dynamic_spaces_and_photos_rf09_rf10(self):
        create_r = self._create_inventory()
        inv_id = create_r.data['id']
        self.client.force_authenticate(user=self.assistant)
        r = self.client.post(
            f'/api/v1/inventories/{inv_id}/spaces/',
            {
                'space_name': 'Sala',
                'condition': InventorySpace.Condition.GOOD,
                'observations': 'Piso en buen estado',
            },
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        space_id = r.data['created_space_id']
        photo = _make_test_image()
        r_photo = self.client.post(
            f'/api/v1/inventories/{inv_id}/spaces/{space_id}/photos/',
            {'image': photo, 'description': 'Vista general'},
            format='multipart',
        )
        self.assertEqual(r_photo.status_code, status.HTTP_201_CREATED)
        r_del = self.client.delete(f'/api/v1/inventories/{inv_id}/spaces/{space_id}/')
        self.assertEqual(r_del.status_code, status.HTTP_204_NO_CONTENT)

    def test_bulk_spaces_step2(self):
        create_r = self._create_inventory()
        inv_id = create_r.data['id']
        self.client.force_authenticate(user=self.admin)
        r = self.client.put(
            f'/api/v1/inventories/{inv_id}/step/2/spaces/',
            {
                'spaces': [
                    {'space_name': 'Cocina', 'condition': 'REGULAR', 'order': 0},
                    {'space_name': 'Baño', 'condition': 'GOOD', 'order': 1},
                ],
            },
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(len(r.data['spaces']), 2)

    def test_finalize_and_mine_rf11_flow(self):
        create_r = self._create_inventory()
        inv_id = create_r.data['id']
        self.client.force_authenticate(user=self.admin)
        self.client.post(
            f'/api/v1/inventories/{inv_id}/spaces/',
            {'space_name': 'Sala', 'condition': 'GOOD'},
            format='json',
        )
        r_fin = self.client.post(f'/api/v1/inventories/{inv_id}/finalize/')
        self.assertEqual(r_fin.status_code, status.HTTP_200_OK)
        self.assertEqual(r_fin.data['status'], Inventory.Status.PENDING_SIGNATURE)

        self.client.force_authenticate(user=self.tenant)
        r_mine = self.client.get('/api/v1/inventories/mine/')
        self.assertEqual(r_mine.status_code, status.HTTP_200_OK)
        self.assertEqual(len(r_mine.data), 1)

    def test_sign_inventory_rf11(self):
        create_r = self._create_inventory()
        inv_id = create_r.data['id']
        self.client.force_authenticate(user=self.admin)
        self.client.post(
            f'/api/v1/inventories/{inv_id}/spaces/',
            {'space_name': 'Sala', 'condition': 'GOOD'},
            format='json',
        )
        self.client.post(f'/api/v1/inventories/{inv_id}/finalize/')
        self.client.force_authenticate(user=self.tenant)
        r = self.client.post(f'/api/v1/inventories/{inv_id}/sign/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['status'], Inventory.Status.ACCEPTED)
        self.assertIsNotNone(r.data['signed_at'])

    def test_tenant_observations_alternate_flow(self):
        create_r = self._create_inventory()
        inv_id = create_r.data['id']
        self.client.force_authenticate(user=self.admin)
        self.client.post(
            f'/api/v1/inventories/{inv_id}/spaces/',
            {'space_name': 'Sala', 'condition': 'GOOD'},
            format='json',
        )
        self.client.post(f'/api/v1/inventories/{inv_id}/finalize/')
        self.client.force_authenticate(user=self.tenant)
        r = self.client.post(
            f'/api/v1/inventories/{inv_id}/observations/',
            {'observation_text': 'Hay rayón en la puerta principal del apartamento.'},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['status'], Inventory.Status.OBSERVATIONS_PENDING)
        self.assertTrue(InventoryTenantObservation.objects.filter(inventory_id=inv_id).exists())

    def test_pdf_generation_rf12(self):
        create_r = self._create_inventory()
        inv_id = create_r.data['id']
        self.client.force_authenticate(user=self.admin)
        self.client.post(
            f'/api/v1/inventories/{inv_id}/spaces/',
            {'space_name': 'Sala', 'condition': 'GOOD'},
            format='json',
        )
        r = self.client.get(f'/api/v1/inventories/{inv_id}/pdf/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(
            PropertyHistory.objects.filter(
                property=self.property,
                details__document='inventory_pdf',
            ).exists()
        )

    def test_invalid_image_rejected_rf10(self):
        create_r = self._create_inventory()
        inv_id = create_r.data['id']
        self.client.force_authenticate(user=self.admin)
        r_space = self.client.post(
            f'/api/v1/inventories/{inv_id}/spaces/',
            {'space_name': 'Sala', 'condition': 'GOOD'},
            format='json',
        )
        space_id = r_space.data['created_space_id']
        bad = SimpleUploadedFile(
            'big.jpg',
            b'x' * (5 * 1024 * 1024 + 1),
            content_type='image/jpeg',
        )
        r = self.client.post(
            f'/api/v1/inventories/{inv_id}/spaces/{space_id}/photos/',
            {'image': bad},
            format='multipart',
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(r.json()['error']['code'], ('invalid_image', 'validation_error'))

    def test_tenant_cannot_create_inventory(self):
        self.client.force_authenticate(user=self.tenant)
        r = self.client.post(
            '/api/v1/inventories/',
            {
                'property_id': self.property.id,
                'tenant_id': self.tenant.id,
                'delivery_date': '2026-05-01',
            },
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)
