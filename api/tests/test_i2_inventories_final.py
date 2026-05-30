"""Pruebas i2 inventario final — HU-07 (CP-RF-26 a CP-RF-28)."""

from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from pot.models import (
    CustomUser,
    Inventory,
    InventorySpace,
    LeaseContract,
    Property,
    PropertyHistory,
    Ticket,
    UserPropertyAssociation,
)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class InventoryFinalAPITests(TestCase):
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
            email='admin-final@test.com',
            password='AdminPass123!',
            role=CustomUser.Role.ADMIN,
            password_changed=True,
        )
        self.tenant = CustomUser.objects.create_user(
            email='tenant-final@test.com',
            password='TenantPass123!',
            role=CustomUser.Role.TENANT,
            password_changed=True,
        )
        self.property = Property.objects.create(
            code='PRO-FINAL01',
            address='Calle Final 1',
            type=Property.Type.APARTMENT,
            owner_name='Dueño',
            status=Property.Status.RENTED,
        )
        UserPropertyAssociation.objects.create(user=self.tenant, property=self.property)

    def _create_accepted_initial(self):
        initial = Inventory.objects.create(
            property=self.property,
            tenant=self.tenant,
            inventory_type=Inventory.Type.INITIAL,
            status=Inventory.Status.ACCEPTED,
            delivery_date='2026-01-01',
            created_by=self.admin,
        )
        InventorySpace.objects.create(
            inventory=initial,
            space_name='Sala',
            condition=InventorySpace.Condition.GOOD,
            order=0,
        )
        InventorySpace.objects.create(
            inventory=initial,
            space_name='Cocina',
            condition=InventorySpace.Condition.REGULAR,
            order=1,
        )
        return initial

    def test_cp_rf_26_create_final_preloads_spaces_rf26(self):
        """CP-RF-26: staff crea inventario FINAL precargado desde inicial aceptado."""
        self._create_accepted_initial()
        self.client.force_authenticate(user=self.admin)
        r = self.client.post(
            '/api/v1/inventories/',
            {
                'property_id': self.property.id,
                'tenant_id': self.tenant.id,
                'delivery_date': '2026-12-01',
                'inventory_type': 'FINAL',
                'observations': 'Entrega final',
            },
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data['inventory_type'], Inventory.Type.FINAL)
        self.assertEqual(r.data['status'], Inventory.Status.IN_PROGRESS)
        self.assertEqual(len(r.data['spaces']), 2)
        self.assertEqual(r.data['spaces'][0]['space_name'], 'Sala')
        self.assertTrue(LeaseContract.objects.filter(property=self.property, tenant=self.tenant).exists())

    def test_tenant_cannot_create_final_inventory(self):
        self._create_accepted_initial()
        self.client.force_authenticate(user=self.tenant)
        r = self.client.post(
            '/api/v1/inventories/',
            {
                'property_id': self.property.id,
                'tenant_id': self.tenant.id,
                'delivery_date': '2026-12-01',
                'inventory_type': 'FINAL',
            },
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_final_requires_accepted_initial(self):
        self.client.force_authenticate(user=self.admin)
        r = self.client.post(
            '/api/v1/inventories/',
            {
                'property_id': self.property.id,
                'tenant_id': self.tenant.id,
                'delivery_date': '2026-12-01',
                'inventory_type': 'FINAL',
            },
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(r.json()['error']['code'], 'initial_not_accepted')

    def test_cp_rf_27_comparison_highlights_deterioration_rf27(self):
        """CP-RF-27: comparación inicial vs final resalta deterioro."""
        initial = self._create_accepted_initial()
        self.client.force_authenticate(user=self.admin)
        create_r = self.client.post(
            '/api/v1/inventories/',
            {
                'property_id': self.property.id,
                'tenant_id': self.tenant.id,
                'delivery_date': '2026-12-01',
                'inventory_type': 'FINAL',
            },
            format='json',
        )
        final_id = create_r.data['id']
        final = Inventory.objects.get(pk=final_id)
        sala = final.spaces.get(space_name='Sala')
        sala.condition = InventorySpace.Condition.BAD
        sala.save(update_fields=['condition'])

        r = self.client.get(f'/api/v1/inventories/{final_id}/comparison/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['initial_inventory_id'], initial.pk)
        deteriorated = [row for row in r.data['rows'] if row['change_type'] == 'DETERIORATED']
        self.assertEqual(len(deteriorated), 1)
        self.assertTrue(deteriorated[0]['highlight'])
        self.assertEqual(r.data['summary']['deteriorated_count'], 1)

    def test_cp_rf_28_closure_document_pdf_rf28(self):
        """CP-RF-28: PDF paz y salvo con comparativo y registro en historial."""
        self._create_accepted_initial()
        self.client.force_authenticate(user=self.admin)
        create_r = self.client.post(
            '/api/v1/inventories/',
            {
                'property_id': self.property.id,
                'tenant_id': self.tenant.id,
                'delivery_date': '2026-12-01',
                'inventory_type': 'FINAL',
            },
            format='json',
        )
        final_id = create_r.data['id']
        r = self.client.get(f'/api/v1/inventories/{final_id}/closure-document/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(
            PropertyHistory.objects.filter(
                property=self.property,
                details__document='closure_clearance_pdf',
            ).exists()
        )

    def test_close_contract_dissociates_tenant(self):
        """Cierre de contrato: desvincula inquilino y marca contrato cerrado."""
        self._create_accepted_initial()
        self.client.force_authenticate(user=self.admin)
        self.client.post(
            '/api/v1/inventories/',
            {
                'property_id': self.property.id,
                'tenant_id': self.tenant.id,
                'delivery_date': '2026-12-01',
                'inventory_type': 'FINAL',
            },
            format='json',
        )
        contract = LeaseContract.objects.get(property=self.property, tenant=self.tenant)
        r = self.client.post(
            f'/api/v1/contracts/{contract.id}/close/',
            {'end_date': '2026-12-15', 'deactivate_tenant': True},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['status'], LeaseContract.Status.CLOSED)
        contract.refresh_from_db()
        self.assertEqual(str(contract.end_date), '2026-12-15')
        self.property.refresh_from_db()
        self.assertEqual(self.property.status, Property.Status.AVAILABLE)
        self.tenant.refresh_from_db()
        self.assertFalse(self.tenant.is_active)
        self.assertFalse(
            UserPropertyAssociation.objects.filter(
                user=self.tenant,
                property=self.property,
                dissociated_at__isnull=True,
            ).exists()
        )

    def test_close_contract_blocks_open_tickets(self):
        self._create_accepted_initial()
        Ticket.objects.create(
            property=self.property,
            tenant=self.tenant,
            description='Daño pendiente en cocina del inmueble arrendado.',
            damage_type=Ticket.DamageType.PLUMBING,
            priority=Ticket.Priority.MEDIUM,
            status=Ticket.Status.OPEN,
        )
        contract = LeaseContract.objects.create(
            property=self.property,
            tenant=self.tenant,
            start_date='2026-01-01',
            status=LeaseContract.Status.ACTIVE,
        )
        self.client.force_authenticate(user=self.admin)
        r = self.client.post(f'/api/v1/contracts/{contract.id}/close/', {}, format='json')
        self.assertEqual(r.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(r.json()['error']['code'], 'open_tickets')
