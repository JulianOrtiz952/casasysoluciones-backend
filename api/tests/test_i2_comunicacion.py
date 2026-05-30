"""Pruebas i2 comunicación — HU-08 (CP-RF-24, CP-RF-25 / RF-24, RF-25)."""

from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from pot.models import (
    CustomUser,
    Notification,
    Property,
    Ticket,
    TicketComment,
    UserPropertyAssociation,
)


def _open_ticket(tenant, prop, **kwargs):
    defaults = {
        'property': prop,
        'tenant': tenant,
        'description': 'Daño en cocina requiere revisión por personal.',
        'damage_type': Ticket.DamageType.PLUMBING,
        'priority': Ticket.Priority.MEDIUM,
        'status': Ticket.Status.OPEN,
        'title': 'Fuga cocina',
    }
    defaults.update(kwargs)
    return Ticket.objects.create(**defaults)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class TicketComunicacionAPITests(TestCase):
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
            email='admin-com@test.com',
            password='AdminPass123!',
            role=CustomUser.Role.ADMIN,
            password_changed=True,
        )
        self.tenant = CustomUser.objects.create_user(
            email='tenant-com@test.com',
            password='TenantPass123!',
            role=CustomUser.Role.TENANT,
            password_changed=True,
        )
        self.property = Property.objects.create(
            code='PRO-COM-01',
            address='Calle Comunicación 1',
            type=Property.Type.APARTMENT,
            owner_name='Dueño',
            status=Property.Status.RENTED,
        )
        UserPropertyAssociation.objects.create(user=self.tenant, property=self.property)

    def test_cp_rf_24_comments_thread_chronological_rf24(self):
        """CP-RF-24: hilo de comentarios cronológico; staff y arrendatario pueden participar."""
        ticket = _open_ticket(self.tenant, self.property)
        self.client.force_authenticate(user=self.admin)
        r1 = self.client.post(
            f'/api/v1/tickets/{ticket.id}/comments/',
            {'body': 'Revisaremos el daño reportado en la visita.'},
            format='json',
        )
        self.assertEqual(r1.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r1.data['message_type'], 'NORMAL')

        self.client.force_authenticate(user=self.tenant)
        r2 = self.client.post(
            f'/api/v1/tickets/mine/{ticket.id}/comments/',
            {'body': 'Quedo atento a la visita del técnico.'},
            format='json',
        )
        self.assertEqual(r2.status_code, status.HTTP_201_CREATED)

        r_list = self.client.get(f'/api/v1/tickets/mine/{ticket.id}/comments/')
        self.assertEqual(r_list.status_code, status.HTTP_200_OK)
        self.assertEqual(len(r_list.data), 2)
        self.assertLess(
            r_list.data[0]['created_at'],
            r_list.data[1]['created_at'],
        )
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.tenant,
                notification_type=Notification.NotificationType.TICKET_COMMENT,
            ).exists(),
        )

    def test_cp_rf_24_blocks_comments_on_closed_ticket_rf24(self):
        """CP-RF-24 flujo alterno: no se pueden enviar mensajes en ticket cerrado."""
        ticket = _open_ticket(self.tenant, self.property, status=Ticket.Status.CLOSED)
        self.client.force_authenticate(user=self.tenant)
        r = self.client.post(
            f'/api/v1/tickets/mine/{ticket.id}/comments/',
            {'body': 'Intento de mensaje en ticket ya cerrado.'},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(r.json()['error']['code'], 'ticket_closed')

    def test_cp_rf_25_request_info_staff_only_rf25(self):
        """CP-RF-25: solicitud de información por staff; notificación alta y correo."""
        ticket = _open_ticket(self.tenant, self.property)
        self.client.force_authenticate(user=self.tenant)
        r_forbidden = self.client.post(
            f'/api/v1/tickets/mine/{ticket.id}/request-info/',
            {'message': 'El arrendatario no puede solicitar info así.'},
            format='json',
        )
        self.assertEqual(r_forbidden.status_code, status.HTTP_404_NOT_FOUND)

        self.client.force_authenticate(user=self.admin)
        mail.outbox.clear()
        message = 'Por favor envíe fotos adicionales del daño en la pared del baño.'
        r = self.client.post(
            f'/api/v1/tickets/{ticket.id}/request-info/',
            {'message': message},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data['message_type'], 'INFO_REQUEST')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.tenant.email, mail.outbox[0].to)
        notif = Notification.objects.filter(
            recipient=self.tenant,
            notification_type=Notification.NotificationType.TICKET_INFO_REQUEST,
            priority=Notification.Priority.HIGH,
        ).first()
        self.assertIsNotNone(notif)
        self.assertTrue(TicketComment.objects.filter(ticket=ticket, message_type='INFO_REQUEST').exists())

    def test_cp_rf_25_request_info_min_length_rf25(self):
        """CP-RF-25 flujo alterno: mensaje de solicitud con longitud mínima."""
        ticket = _open_ticket(self.tenant, self.property)
        self.client.force_authenticate(user=self.admin)
        r = self.client.post(
            f'/api/v1/tickets/{ticket.id}/request-info/',
            {'message': 'corto'},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_notifications_unread_and_mark_read(self):
        """Notificaciones in-app: listado, contador y marcar leída."""
        ticket = _open_ticket(self.tenant, self.property)
        Notification.objects.create(
            recipient=self.tenant,
            notification_type=Notification.NotificationType.TICKET_OPENED,
            title='Ticket abierto',
            body=f'Ticket {ticket.public_code}',
            ticket=ticket,
        )
        self.client.force_authenticate(user=self.tenant)
        r_count = self.client.get('/api/v1/notifications/unread-count/')
        self.assertEqual(r_count.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(r_count.data['unread_count'], 1)

        r_list = self.client.get('/api/v1/notifications/?unread=1')
        self.assertEqual(r_list.status_code, status.HTTP_200_OK)
        notif_id = r_list.data['results'][0]['id']
        r_read = self.client.patch(f'/api/v1/notifications/{notif_id}/read/')
        self.assertEqual(r_read.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(r_read.data['read_at'])
