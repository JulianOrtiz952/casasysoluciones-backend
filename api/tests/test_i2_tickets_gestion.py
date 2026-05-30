"""Pruebas i2 gestión de tickets — HU-06 (CP-RF-18 a CP-RF-21, CP-RF-29 parcial)."""

import io
from unittest.mock import patch

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework import status
from rest_framework.test import APIClient

from pot.models import (
    CustomUser,
    Property,
    Ticket,
    TicketAttachment,
    TicketStatusLog,
    UserPropertyAssociation,
)


def _make_test_image(name='photo.jpg'):
    buf = io.BytesIO()
    Image.new('RGB', (40, 40), color='red').save(buf, format='JPEG')
    buf.seek(0)
    return SimpleUploadedFile(name, buf.read(), content_type='image/jpeg')


def _open_ticket(tenant, prop, **kwargs):
    defaults = {
        'property': prop,
        'tenant': tenant,
        'description': 'Daño en cocina requiere revisión urgente.',
        'damage_type': Ticket.DamageType.PLUMBING,
        'priority': Ticket.Priority.HIGH,
        'status': Ticket.Status.OPEN,
        'title': 'Fuga cocina',
    }
    defaults.update(kwargs)
    return Ticket.objects.create(**defaults)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class TicketManagementAPITests(TestCase):
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
            email='admin-i2@test.com',
            password='AdminPass123!',
            role=CustomUser.Role.ADMIN,
            password_changed=True,
        )
        self.assistant = CustomUser.objects.create_user(
            email='assistant-i2@test.com',
            password='AssistPass123!',
            role=CustomUser.Role.ASSISTANT,
            password_changed=True,
        )
        self.tenant = CustomUser.objects.create_user(
            email='tenant-i2@test.com',
            password='TenantPass123!',
            role=CustomUser.Role.TENANT,
            password_changed=True,
        )
        self.property = Property.objects.create(
            code='PRO-I2-01',
            address='Calle Gestión 1',
            type=Property.Type.APARTMENT,
            owner_name='Dueño',
            status=Property.Status.RENTED,
        )
        UserPropertyAssociation.objects.create(user=self.tenant, property=self.property)

    def _staff_auth(self, user=None):
        self.client.force_authenticate(user=user or self.admin)

    def test_cp_rf_18_staff_list_filters_status_transitions_rf18(self):
        """CP-RF-18: listado staff, filtros y transiciones de estado con TicketStatusLog."""
        _open_ticket(self.tenant, self.property)
        _open_ticket(
            self.tenant,
            self.property,
            status=Ticket.Status.ACCEPTED,
            priority=Ticket.Priority.LOW,
        )
        self._staff_auth()
        r = self.client.get('/api/v1/tickets/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['count'], 2)

        r_status = self.client.get('/api/v1/tickets/?status=ACCEPTED')
        self.assertEqual(r_status.data['count'], 1)

    def test_tenant_cannot_access_staff_tickets(self):
        self.client.force_authenticate(user=self.tenant)
        r = self.client.get('/api/v1/tickets/')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_cp_rf_19_reject_reason_min_length_and_notify_rf19(self):
        """CP-RF-19: rechazo con motivo mínimo 20 caracteres y notificación al arrendatario."""
        self._staff_auth(self.assistant)
        ticket2 = _open_ticket(self.tenant, self.property, title='Otro daño')
        r_short = self.client.post(
            f'/api/v1/tickets/{ticket2.id}/reject/',
            {'reason': 'corto'},
            format='json',
        )
        self.assertEqual(r_short.status_code, status.HTTP_400_BAD_REQUEST)

        reason = 'El daño reportado no corresponde a responsabilidad de arrendamiento según contrato.'
        mail.outbox.clear()
        r_reject = self.client.post(
            f'/api/v1/tickets/{ticket2.id}/reject/',
            {'reason': reason},
            format='json',
        )
        self.assertEqual(r_reject.status_code, status.HTTP_200_OK)
        self.assertEqual(r_reject.data['status'], 'REJECTED')
        self.assertEqual(r_reject.data['rejection_reason'], reason)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.tenant.email, mail.outbox[0].to)

    def test_cp_rf_18_accept_status_transition_logs_rf18(self):
        """CP-RF-18: aceptar ticket OPEN → ACCEPTED registra historial."""
        ticket = _open_ticket(self.tenant, self.property)
        self._staff_auth(self.assistant)
        r_accept = self.client.post(
            f'/api/v1/tickets/{ticket.id}/status/',
            {'status': 'ACCEPTED'},
            format='json',
        )
        self.assertEqual(r_accept.status_code, status.HTTP_200_OK)
        self.assertEqual(r_accept.data['status'], 'ACCEPTED')
        self.assertTrue(
            TicketStatusLog.objects.filter(
                ticket=ticket,
                to_status=Ticket.Status.ACCEPTED,
            ).exists(),
        )

    def test_cp_rf_20_assign_contractor_moves_in_progress_rf20(self):
        """CP-RF-20: asignar maestro subcontratado y pasar a IN_PROGRESS."""
        ticket = _open_ticket(self.tenant, self.property, status=Ticket.Status.ACCEPTED)
        self._staff_auth()
        r = self.client.post(
            f'/api/v1/tickets/{ticket.id}/assign/',
            {
                'contractor_name': 'Juan Pérez Plomería',
                'visit_note': 'Visita martes 10:00',
            },
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['status'], 'IN_PROGRESS')
        self.assertEqual(r.data['assigned_contractor_name'], 'Juan Pérez Plomería')
        log = TicketStatusLog.objects.filter(ticket=ticket, action=TicketStatusLog.Action.ASSIGN).first()
        self.assertIsNotNone(log)
        self.assertIn('Juan Pérez', log.note)

    def test_cp_rf_21_repair_evidence_required_to_close_rf21(self):
        """CP-RF-21: evidencia de reparación obligatoria para cerrar ticket."""
        ticket = _open_ticket(self.tenant, self.property, status=Ticket.Status.IN_PROGRESS)
        self._staff_auth()

        r_close = self.client.post(
            f'/api/v1/tickets/{ticket.id}/status/',
            {'status': 'CLOSED'},
            format='json',
        )
        self.assertEqual(r_close.status_code, status.HTTP_400_BAD_REQUEST)

        r_ev = self.client.post(
            f'/api/v1/tickets/{ticket.id}/repair-evidence/',
            {'image': _make_test_image()},
            format='multipart',
        )
        self.assertEqual(r_ev.status_code, status.HTTP_201_CREATED)
        self.assertTrue(r_ev.data['ticket']['has_repair_evidence'])
        ticket.refresh_from_db()
        self.assertIsNotNone(ticket.confirmation_deadline_at)

        r_close_ok = self.client.post(
            f'/api/v1/tickets/{ticket.id}/status/',
            {'status': 'CLOSED'},
            format='json',
        )
        self.assertEqual(r_close_ok.status_code, status.HTTP_200_OK)
        self.assertEqual(r_close_ok.data['status'], 'CLOSED')
        self.assertEqual(
            TicketAttachment.objects.filter(
                ticket=ticket,
                attachment_type=TicketAttachment.AttachmentType.REPAIR_EVIDENCE,
            ).count(),
            1,
        )

    def test_force_close_with_justification(self):
        ticket = _open_ticket(self.tenant, self.property, status=Ticket.Status.IN_PROGRESS)
        self._staff_auth()
        justification = 'Cierre administrativo acordado con arrendatario por teléfono.'
        r = self.client.post(
            f'/api/v1/tickets/{ticket.id}/status/',
            {
                'status': 'CLOSED',
                'force_close': True,
                'justification': justification,
            },
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['status'], 'CLOSED')
        log = TicketStatusLog.objects.filter(
            ticket=ticket,
            action=TicketStatusLog.Action.FORCE_CLOSE,
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.note, justification)

    def test_cp_rf_29_ticket_stats_pending_resolution_rf29(self):
        """CP-RF-29: estadísticas con pending_resolution y semáforo en /tickets/stats/."""
        _open_ticket(self.tenant, self.property, priority=Ticket.Priority.HIGH)
        _open_ticket(
            self.tenant,
            self.property,
            priority=Ticket.Priority.MEDIUM,
            status=Ticket.Status.ACCEPTED,
        )
        _open_ticket(
            self.tenant,
            self.property,
            priority=Ticket.Priority.LOW,
            status=Ticket.Status.IN_PROGRESS,
        )
        Ticket.objects.filter(status=Ticket.Status.CLOSED).delete()
        self._staff_auth()
        r = self.client.get('/api/v1/tickets/stats/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['pending_resolution'], 3)
        self.assertEqual(r.data['urgent'], 1)
        self.assertIn('traffic_light', r.data)
        self.assertEqual(
            r.data['traffic_light']['red']
            + r.data['traffic_light']['yellow']
            + r.data['traffic_light']['green']
            + r.data['traffic_light']['grey'],
            3,
        )

    def test_cp_rf_18_staff_export_csv_rf18(self):
        """CP-RF-18: exportación CSV del listado de tickets para staff."""
        _open_ticket(self.tenant, self.property)
        self._staff_auth()
        r = self.client.get('/api/v1/tickets/export/?export_format=csv')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn('text/csv', r['Content-Type'])
        self.assertIn(b'Radicado', r.content)

    def test_regression_i1_mine_routes_not_shadowed_by_staff_router(self):
        """Regresión i1: /tickets/mine/ no debe resolverse como staff pk=mine."""
        self.client.force_authenticate(user=self.tenant)
        r = self.client.get('/api/v1/tickets/mine/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
