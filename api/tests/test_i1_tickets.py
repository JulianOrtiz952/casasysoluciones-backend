"""Pruebas i1 creación de tickets — CP-RF-13 a CP-RF-17 (RF-13 a RF-17)."""

import io
from unittest.mock import patch

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from rest_framework import status
from rest_framework.test import APIClient

from pot.models import (
    CustomUser,
    Property,
    PropertyHistory,
    Ticket,
    TicketAttachment,
    UserPropertyAssociation,
)


def _make_test_image(name='photo.jpg'):
    buf = io.BytesIO()
    Image.new('RGB', (40, 40), color='blue').save(buf, format='JPEG')
    buf.seek(0)
    return SimpleUploadedFile(name, buf.read(), content_type='image/jpeg')


def _ticket_payload(**overrides):
    data = {
        'description': 'Fuga de agua en lavamanos del baño principal.',
        'damage_type': Ticket.DamageType.PLUMBING,
        'priority': Ticket.Priority.HIGH,
    }
    data.update(overrides)
    return data


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class TicketCreationAPITests(TestCase):
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
            email='admin-tkt@test.com',
            password='AdminPass123!',
            role=CustomUser.Role.ADMIN,
            password_changed=True,
        )
        self.assistant = CustomUser.objects.create_user(
            email='assistant-tkt@test.com',
            password='AssistPass123!',
            role=CustomUser.Role.ASSISTANT,
            password_changed=True,
        )
        self.tenant = CustomUser.objects.create_user(
            email='tenant-tkt@test.com',
            password='TenantPass123!',
            role=CustomUser.Role.TENANT,
            password_changed=True,
        )
        self.property1 = Property.objects.create(
            code='PRO-TKT01',
            address='Calle Ticket 1',
            type=Property.Type.APARTMENT,
            owner_name='Dueño',
            status=Property.Status.RENTED,
        )
        self.property2 = Property.objects.create(
            code='PRO-TKT02',
            address='Calle Ticket 2',
            type=Property.Type.HOUSE,
            owner_name='Dueño',
            status=Property.Status.RENTED,
        )
        UserPropertyAssociation.objects.create(user=self.tenant, property=self.property1)

    def test_cp_rf_13_create_open_ticket_notify_staff_rf13(self):
        """CP-RF-13: crear ticket OPEN con radicado TK-xxxxx y notificar admin + assistant."""
        self.client.force_authenticate(user=self.tenant)
        r = self.client.post('/api/v1/tickets/mine/', _ticket_payload(), format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data['status'], Ticket.Status.OPEN)
        self.assertTrue(r.data['public_code'].startswith('TK-'))
        self.assertEqual(len(mail.outbox), 2)
        recipients = {m.to[0] for m in mail.outbox}
        self.assertEqual(recipients, {self.admin.email, self.assistant.email})
        ticket = Ticket.objects.get(pk=r.data['id'])
        self.assertTrue(
            PropertyHistory.objects.filter(
                property=self.property1,
                event_type=PropertyHistory.EventType.TICKET_CREATED,
            ).exists()
        )

    def test_create_draft_rf13_draft_endpoint(self):
        self.client.force_authenticate(user=self.tenant)
        r = self.client.post('/api/v1/tickets/mine/draft/', _ticket_payload(), format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data['status'], Ticket.Status.DRAFT)
        self.assertEqual(len(mail.outbox), 0)

    def test_cp_rf_14_property_id_auto_and_required_rf14(self):
        """CP-RF-14: property_id auto con un inmueble; obligatorio si hay varios."""
        self.client.force_authenticate(user=self.tenant)
        r_single = self.client.post('/api/v1/tickets/mine/', _ticket_payload(), format='json')
        self.assertEqual(r_single.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r_single.data['property']['id'], self.property1.id)

        UserPropertyAssociation.objects.create(user=self.tenant, property=self.property2)
        r_missing = self.client.post('/api/v1/tickets/mine/', _ticket_payload(), format='json')
        self.assertEqual(r_missing.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(r_missing.json()['error']['code'], 'property_id_required')

        r_multi = self.client.post(
            '/api/v1/tickets/mine/',
            _ticket_payload(property_id=self.property2.id),
            format='json',
        )
        self.assertEqual(r_multi.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r_multi.data['property']['id'], self.property2.id)

    def test_cp_rf_15_damage_type_catalog_and_other_rf15(self):
        """CP-RF-15: catálogo damage_type; OTHER exige damage_type_other."""
        self.client.force_authenticate(user=self.tenant)
        r = self.client.post(
            '/api/v1/tickets/mine/',
            _ticket_payload(damage_type=Ticket.DamageType.OTHER),
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(r.json()['error']['code'], 'damage_type_other_required')

        r2 = self.client.post(
            '/api/v1/tickets/mine/',
            _ticket_payload(
                damage_type=Ticket.DamageType.OTHER,
                damage_type_other='Daño en persiana motorizada',
            ),
            format='json',
        )
        self.assertEqual(r2.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r2.data['damage_type_other'], 'Daño en persiana motorizada')

    def test_cp_rf_16_priority_required_rf16(self):
        """CP-RF-16: prioridad LOW/MEDIUM/HIGH obligatoria al crear ticket."""
        self.client.force_authenticate(user=self.tenant)
        r = self.client.post(
            '/api/v1/tickets/mine/',
            {
                'description': 'Problema eléctrico en cocina.',
                'damage_type': Ticket.DamageType.ELECTRICITY,
            },
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cp_rf_17_attachments_limit_and_format_rf17(self):
        """CP-RF-17: máx. 10 adjuntos JPG/PNG ≤5 MB; rechaza formatos inválidos."""
        self.client.force_authenticate(user=self.tenant)
        create_r = self.client.post('/api/v1/tickets/mine/', _ticket_payload(), format='json')
        ticket_id = create_r.data['id']
        mail.outbox.clear()

        for i in range(10):
            r = self.client.post(
                f'/api/v1/tickets/mine/{ticket_id}/attachments/',
                {'image': _make_test_image(f'p{i}.jpg')},
                format='multipart',
            )
            self.assertEqual(r.status_code, status.HTTP_201_CREATED, msg=i)

        r6 = self.client.post(
            f'/api/v1/tickets/mine/{ticket_id}/attachments/',
            {'image': _make_test_image('p11.jpg')},
            format='multipart',
        )
        self.assertEqual(r6.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(r6.json()['error']['code'], 'max_attachments')
        self.assertEqual(TicketAttachment.objects.filter(ticket_id=ticket_id).count(), 10)

        bad = SimpleUploadedFile('doc.pdf', b'%PDF', content_type='application/pdf')
        r_bad = self.client.post(
            f'/api/v1/tickets/mine/{ticket_id}/attachments/',
            {'image': bad},
            format='multipart',
        )
        self.assertEqual(r_bad.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(r_bad.json()['error']['code'], ('invalid_image', 'validation_error'))

    def test_list_and_retrieve_mine(self):
        self.client.force_authenticate(user=self.tenant)
        self.client.post('/api/v1/tickets/mine/', _ticket_payload(), format='json')
        r_list = self.client.get('/api/v1/tickets/mine/')
        self.assertEqual(r_list.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(r_list.data['count'], 1)
        ticket_id = r_list.data['results'][0]['id']
        r_detail = self.client.get(f'/api/v1/tickets/mine/{ticket_id}/')
        self.assertEqual(r_detail.status_code, status.HTTP_200_OK)
        self.assertIn('attachments', r_detail.data)

    def test_staff_cannot_create_ticket(self):
        self.client.force_authenticate(user=self.admin)
        r = self.client.post('/api/v1/tickets/mine/', _ticket_payload(), format='json')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_tenant_can_confirm_resolved_ticket(self):
        # Create an in_progress ticket
        ticket = Ticket.objects.create(
            property=self.property1,
            tenant=self.tenant,
            title='Test Ticket',
            status=Ticket.Status.IN_PROGRESS,
        )
        self.client.force_authenticate(user=self.tenant)
        r = self.client.post(f'/api/v1/tickets/mine/{ticket.id}/confirm/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.CLOSED)
        self.assertIsNotNone(ticket.tenant_confirmed_at)
        
        self.assertTrue(
            PropertyHistory.objects.filter(
                property=self.property1,
                event_type=PropertyHistory.EventType.TICKET_CLOSED,
            ).exists()
        )

    def test_tenant_can_report_problem_on_ticket(self):
        # Create an in_progress ticket
        ticket = Ticket.objects.create(
            property=self.property1,
            tenant=self.tenant,
            title='Test Ticket',
            status=Ticket.Status.IN_PROGRESS,
        )
        self.client.force_authenticate(user=self.tenant)
        r = self.client.post(
            f'/api/v1/tickets/mine/{ticket.id}/report-problem/',
            {'reason': 'Sigue goteando un poco por la junta trasera.'},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.IN_PROGRESS)
        self.assertEqual(ticket.rejection_reason, 'Sigue goteando un poco por la junta trasera.')
        
        self.assertTrue(
            PropertyHistory.objects.filter(
                property=self.property1,
                event_type=PropertyHistory.EventType.STATUS_CHANGE,
            ).exists()
        )

    def test_admin_can_reject_client_ticket_with_reason(self):
        ticket = Ticket.objects.create(
            property=self.property1,
            tenant=self.tenant,
            title='Client Ticket',
            status=Ticket.Status.OPEN,
        )
        self.client.force_authenticate(user=self.admin)
        
        r_fail = self.client.post(f'/api/v1/tickets/{ticket.id}/reject/', {'reason': ''}, format='json')
        self.assertEqual(r_fail.status_code, status.HTTP_400_BAD_REQUEST)
        
        r_success = self.client.post(f'/api/v1/tickets/{ticket.id}/reject/', {'reason': 'No es responsabilidad del arrendador.'}, format='json')
        self.assertEqual(r_success.status_code, status.HTTP_200_OK)
        
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.REJECTED)
        self.assertEqual(ticket.rejection_reason, 'No es responsabilidad del arrendador.')

    def test_admin_update_status_to_rejected_requires_reason(self):
        ticket = Ticket.objects.create(
            property=self.property1,
            tenant=self.tenant,
            title='Client Ticket 2',
            status=Ticket.Status.OPEN,
        )
        self.client.force_authenticate(user=self.admin)
        
        r_fail = self.client.post(f'/api/v1/tickets/{ticket.id}/update-status/', {'status': 'REJECTED'}, format='json')
        self.assertEqual(r_fail.status_code, status.HTTP_400_BAD_REQUEST)
        
        r_success = self.client.post(f'/api/v1/tickets/{ticket.id}/update-status/', {
            'status': 'REJECTED',
            'rejection_reason': 'Duplicado.'
        }, format='json')
        self.assertEqual(r_success.status_code, status.HTTP_200_OK)
        
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.REJECTED)
        self.assertEqual(ticket.rejection_reason, 'Duplicado.')

