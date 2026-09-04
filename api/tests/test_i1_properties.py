"""Pruebas i1 inmuebles — CP-RF-06 y CP-RF-07 (RF-06, RF-07)."""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from pot.models import CustomUser, Property, PropertyHistory, PropertyImage, UserPropertyAssociation


class PropertyManagementAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = CustomUser.objects.create_user(
            email='admin-prop@test.com',
            password='AdminPass123!',
            role=CustomUser.Role.ADMIN,
            password_changed=True,
        )
        self.assistant = CustomUser.objects.create_user(
            email='assistant-prop@test.com',
            password='AssistPass123!',
            role=CustomUser.Role.ASSISTANT,
            password_changed=True,
        )
        self.tenant = CustomUser.objects.create_user(
            email='tenant-prop@test.com',
            password='TenantPass123!',
            role=CustomUser.Role.TENANT,
            password_changed=True,
        )

    def test_tenant_cannot_access_properties(self):
        self.client.force_authenticate(user=self.tenant)
        r = self.client.get('/api/v1/properties/')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_cp_rf_06_create_property_unique_code_rf06(self):
        """CP-RF-06: crear inmueble con dirección única, código autogenerado y estado AVAILABLE."""
        self.client.force_authenticate(user=self.admin)
        r = self.client.post(
            '/api/v1/properties/',
            {
                'address': 'Carrera 7 #45-10',
                'type': Property.Type.APARTMENT,
                'owner_name': 'Propietario Uno',
                'city': 'Bogotá',
                'building_name': 'Torre Norte',
                'unit_label': '501',
            },
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertTrue(r.data['code'].startswith('PRO-'))
        self.assertEqual(r.data['status'], Property.Status.AVAILABLE)
        self.assertEqual(r.data['address'], 'Carrera 7 #45-10')

        prop = Property.objects.get(pk=r.data['id'])
        self.assertTrue(
            PropertyHistory.objects.filter(
                property=prop,
                event_type=PropertyHistory.EventType.CREATED,
            ).exists()
        )

    def test_cp_rf_06_rejects_duplicate_address_rf06(self):
        """CP-RF-06 flujo alterno: rechaza dirección duplicada."""
        Property.objects.create(
            code='PRO-00099',
            address='Av. Siempre Viva 742',
            type=Property.Type.HOUSE,
            owner_name='Dueño',
            status=Property.Status.AVAILABLE,
        )
        self.client.force_authenticate(user=self.assistant)
        r = self.client.post(
            '/api/v1/properties/',
            {
                'address': 'av. siempre viva 742',
                'type': Property.Type.HOUSE,
                'owner_name': 'Otro',
            },
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(r.json()['error']['code'], 'address_exists')

    def test_assistant_can_update_property(self):
        prop = Property.objects.create(
            code='PRO-00100',
            address='Calle 10 #1-1',
            type=Property.Type.LOCAL,
            owner_name='Dueño Local',
            status=Property.Status.AVAILABLE,
        )
        self.client.force_authenticate(user=self.assistant)
        r = self.client.patch(
            f'/api/v1/properties/{prop.id}/',
            {'status': Property.Status.MAINTENANCE, 'observations': 'Pintura pendiente'},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        prop.refresh_from_db()
        self.assertEqual(prop.status, Property.Status.MAINTENANCE)
        self.assertTrue(
            PropertyHistory.objects.filter(
                property=prop,
                event_type=PropertyHistory.EventType.STATUS_CHANGE,
            ).exists()
        )

    def test_list_properties_with_filters(self):
        Property.objects.create(
            code='PRO-00200',
            address='Filtro A',
            type=Property.Type.APARTMENT,
            owner_name='A',
            status=Property.Status.RENTED,
            city='Medellín',
        )
        Property.objects.create(
            code='PRO-00201',
            address='Filtro B',
            type=Property.Type.HOUSE,
            owner_name='B',
            status=Property.Status.AVAILABLE,
            city='Bogotá',
        )
        self.client.force_authenticate(user=self.admin)
        r = self.client.get('/api/v1/properties/', {'status': Property.Status.RENTED})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        codes = [p['code'] for p in r.data['results']]
        self.assertIn('PRO-00200', codes)
        self.assertNotIn('PRO-00201', codes)

        r2 = self.client.get('/api/v1/properties/', {'search': 'Filtro B'})
        self.assertEqual(r2.status_code, status.HTTP_200_OK)
        self.assertEqual(r2.data['count'], 1)

    def test_properties_stats(self):
        Property.objects.create(
            code='PRO-00300',
            address='Stats 1',
            type=Property.Type.APARTMENT,
            owner_name='S',
            status=Property.Status.AVAILABLE,
        )
        self.client.force_authenticate(user=self.admin)
        r = self.client.get('/api/v1/properties/stats/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn('total', r.data)
        self.assertIn('by_status', r.data)
        self.assertIn('by_type', r.data)

    def test_cp_rf_07_property_history_chronological_rf07(self):
        """CP-RF-07: historial cronológico del inmueble (tickets, inventarios, arrendatarios)."""
        prop = Property.objects.create(
            code='PRO-00400',
            address='Historial 1',
            type=Property.Type.HOUSE,
            owner_name='Hist',
            status=Property.Status.RENTED,
        )
        tenant = CustomUser.objects.create_user(
            email='hist-tenant@test.com',
            password='x',
            role=CustomUser.Role.TENANT,
        )
        UserPropertyAssociation.objects.create(user=tenant, property=prop, created_by=self.admin)
        PropertyHistory.objects.create(
            property=prop,
            event_type=PropertyHistory.EventType.TENANT_ASSOCIATED,
            description=f'Asociado {tenant.email}',
            related_user=tenant,
            created_by=self.admin,
        )
        PropertyHistory.objects.create(
            property=prop,
            event_type=PropertyHistory.EventType.TICKET_CREATED,
            description='Ticket de prueba',
            created_by=self.admin,
        )

        self.client.force_authenticate(user=self.admin)
        r = self.client.get(f'/api/v1/properties/{prop.id}/history/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        event_types = {e['event_type'] for e in r.data['results']}
        self.assertIn(PropertyHistory.EventType.TENANT_ASSOCIATED, event_types)
        self.assertIn(PropertyHistory.EventType.TICKET_CREATED, event_types)

        r2 = self.client.get(
            f'/api/v1/properties/{prop.id}/history/',
            {'tenant_id': tenant.id},
        )
        self.assertEqual(r2.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(r2.data['count'], 1)

    def test_retrieve_includes_active_tenant(self):
        prop = Property.objects.create(
            code='PRO-00500',
            address='Con arrendatario',
            type=Property.Type.APARTMENT,
            owner_name='Dueño',
            status=Property.Status.RENTED,
        )
        tenant = CustomUser.objects.create_user(
            email='active-tenant@test.com',
            password='x',
            role=CustomUser.Role.TENANT,
            document_number='9988776655',
        )
        UserPropertyAssociation.objects.create(user=tenant, property=prop, created_by=self.admin)

        self.client.force_authenticate(user=self.admin)
        r = self.client.get(f'/api/v1/properties/{prop.id}/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(r.data['active_tenant'])
        self.assertEqual(r.data['active_tenant']['email'], 'active-tenant@test.com')

    def test_deactivate_property_without_tenant(self):
        prop = Property.objects.create(
            code='PRO-00600',
            address='Calle Desactivada 1',
            type=Property.Type.HOUSE,
            owner_name='Dueño',
            status=Property.Status.AVAILABLE,
            is_active=True,
        )
        self.client.force_authenticate(user=self.admin)
        r = self.client.patch(
            f'/api/v1/properties/{prop.id}/',
            {'is_active': False},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        prop.refresh_from_db()
        self.assertFalse(prop.is_active)

    def test_deactivate_property_with_active_tenant_fails(self):
        prop = Property.objects.create(
            code='PRO-00601',
            address='Calle Desactivada Rented',
            type=Property.Type.HOUSE,
            owner_name='Dueño',
            status=Property.Status.RENTED,
            is_active=True,
        )
        tenant = CustomUser.objects.create_user(
            email='tenant-deact@test.com',
            password='x',
            role=CustomUser.Role.TENANT,
        )
        UserPropertyAssociation.objects.create(user=tenant, property=prop, created_by=self.admin)

        self.client.force_authenticate(user=self.admin)
        r = self.client.patch(
            f'/api/v1/properties/{prop.id}/',
            {'is_active': False},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(r.json()['error']['code'], 'cannot_deactivate_rented_property')
        prop.refresh_from_db()
        self.assertTrue(prop.is_active)

    def test_property_list_excludes_inactive_by_default(self):
        Property.objects.create(
            code='PRO-00602',
            address='Calle Activa',
            type=Property.Type.HOUSE,
            owner_name='Dueño',
            status=Property.Status.AVAILABLE,
            is_active=True,
        )
        Property.objects.create(
            code='PRO-00603',
            address='Calle Inactiva',
            type=Property.Type.HOUSE,
            owner_name='Dueño',
            status=Property.Status.AVAILABLE,
            is_active=False,
        )

        self.client.force_authenticate(user=self.admin)
        r = self.client.get('/api/v1/properties/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        codes = [p['code'] for p in r.data['results']]
        self.assertIn('PRO-00602', codes)
        self.assertNotIn('PRO-00603', codes)

    def test_property_list_includes_inactive_if_param_passed(self):
        Property.objects.create(
            code='PRO-00604',
            address='Calle Activa 2',
            type=Property.Type.HOUSE,
            owner_name='Dueño',
            status=Property.Status.AVAILABLE,
            is_active=True,
        )
        Property.objects.create(
            code='PRO-00605',
            address='Calle Inactiva 2',
            type=Property.Type.HOUSE,
            owner_name='Dueño',
            status=Property.Status.AVAILABLE,
            is_active=False,
        )

        self.client.force_authenticate(user=self.admin)
        r = self.client.get('/api/v1/properties/', {'include_inactive': 'true'})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        codes = [p['code'] for p in r.data['results']]
        self.assertIn('PRO-00604', codes)
        self.assertIn('PRO-00605', codes)

    def test_anonymous_user_never_sees_inactive_properties(self):
        Property.objects.create(
            code='PRO-00606',
            address='Calle Activa Anon',
            type=Property.Type.HOUSE,
            owner_name='Dueño',
            status=Property.Status.AVAILABLE,
            is_active=True,
        )
        Property.objects.create(
            code='PRO-00607',
            address='Calle Inactiva Anon',
            type=Property.Type.HOUSE,
            owner_name='Dueño',
            status=Property.Status.AVAILABLE,
            is_active=False,
        )

        r = self.client.get('/api/v1/properties/', {'include_inactive': 'true'})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results') or r.data
        codes = [p['code'] for p in results]
        self.assertIn('PRO-00606', codes)
        self.assertNotIn('PRO-00607', codes)

    def test_create_property_with_multiple_images(self):
        """Prueba registro de propiedad con portada y múltiples fotos de galería."""
        self.client.force_authenticate(user=self.admin)
        gif_bytes = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
        cover = SimpleUploadedFile("cover.gif", gif_bytes, content_type="image/gif")
        img1 = SimpleUploadedFile("img1.gif", gif_bytes, content_type="image/gif")
        img2 = SimpleUploadedFile("img2.gif", gif_bytes, content_type="image/gif")

        r = self.client.post(
            '/api/v1/properties/',
            {
                'address': 'Calle Galeria 123',
                'type': Property.Type.APARTMENT,
                'owner_name': 'Galeria Owner',
                'cover_image': cover,
                'images': [img1, img2],
            },
            format='multipart',
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        prop_id = r.data['id']
        prop = Property.objects.get(id=prop_id)
        
        self.assertIsNotNone(prop.cover_image)
        # Deberían existir 3 instancias en PropertyImage (1 portada + 2 galería)
        self.assertEqual(PropertyImage.objects.filter(property=prop).count(), 3)
        self.assertEqual(len(r.data['images']), 3)

    def test_update_property_delete_and_add_images(self):
        """Prueba actualización de propiedad añadiendo nuevas fotos y eliminando existentes."""
        self.client.force_authenticate(user=self.admin)
        prop = Property.objects.create(
            code='PRO-00800',
            address='Calle Edicion 456',
            type=Property.Type.HOUSE,
            owner_name='Edit Owner',
            status=Property.Status.AVAILABLE,
        )
        p_img1 = PropertyImage.objects.create(property=prop, image='properties/gallery/1.jpg', is_cover=True)
        p_img2 = PropertyImage.objects.create(property=prop, image='properties/gallery/2.jpg', is_cover=False)

        new_img = SimpleUploadedFile("new3.jpg", b"fake_new3", content_type="image/jpeg")

        r = self.client.patch(
            f'/api/v1/properties/{prop.id}/',
            {
                'deleted_image_ids': [p_img2.id],
                'images': [new_img],
            },
            format='multipart',
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        # p_img2 debe ser borrada y new_img agregada
        self.assertFalse(PropertyImage.objects.filter(id=p_img2.id).exists())
        self.assertTrue(PropertyImage.objects.filter(id=p_img1.id).exists())
        self.assertEqual(PropertyImage.objects.filter(property=prop).count(), 2)

