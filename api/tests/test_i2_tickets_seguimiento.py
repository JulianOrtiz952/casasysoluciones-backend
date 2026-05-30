"""Pruebas i2 seguimiento tickets — HU-06 (CP-RF-22, CP-RF-23)."""

import io
from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
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
from pot.services import ticket_service


def _make_test_image(name='photo.jpg'):
    buf = io.BytesIO()
    Image.new('RGB', (40, 40), color='blue').save(buf, format='JPEG')
    buf.seek(0)
    return SimpleUploadedFile(name, buf.read(), content_type='image/jpeg')


def _ticket_en_confirmacion(tenant, prop):
    ticket = Ticket.objects.create(
        property=prop,
        tenant=tenant,
        description='Daño en baño con evidencia de reparación adjunta.',
        damage_type=Ticket.DamageType.PLUMBING,
        priority=Ticket.Priority.MEDIUM,
        status=Ticket.Status.IN_PROGRESS,
        assigned_contractor_name='Maestro Test',
        confirmation_deadline_at=timezone.now() + timedelta(days=1),
    )
    TicketAttachment.objects.create(
        ticket=ticket,
        image=_make_test_image(),
        attachment_type=TicketAttachment.AttachmentType.REPAIR_EVIDENCE,
        uploaded_by=tenant,
    )
    return ticket


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class TicketSeguimientoAPITests(TestCase):
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
            email='admin-seg@test.com',
            password='AdminPass123!',
            role=CustomUser.Role.ADMIN,
            password_changed=True,
        )
        self.tenant = CustomUser.objects.create_user(
            email='tenant-seg@test.com',
            password='TenantPass123!',
            role=CustomUser.Role.TENANT,
            password_changed=True,
        )
        self.property = Property.objects.create(
            code='PRO-SEG-01',
            address='Calle Seguimiento 1',
            type=Property.Type.APARTMENT,
            owner_name='Dueño',
            status=Property.Status.RENTED,
        )
        UserPropertyAssociation.objects.create(user=self.tenant, property=self.property)

    def test_cp_rf_22_tenant_confirm_closes_ticket_rf22(self):
        """CP-RF-22: arrendatario confirma reparación y cierra el ticket."""
        ticket = _ticket_en_confirmacion(self.tenant, self.property)
        self.client.force_authenticate(user=self.tenant)
        r = self.client.post(f'/api/v1/tickets/mine/{ticket.id}/confirm/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['status'], 'CLOSED')
        self.assertIsNotNone(r.data['tenant_confirmed_at'])
        self.assertFalse(r.data['closed_automatically'])
        log = TicketStatusLog.objects.filter(
            ticket=ticket,
            action=TicketStatusLog.Action.TENANT_CONFIRM,
        ).first()
        self.assertIsNotNone(log)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.CLOSED)

    def test_cp_rf_22_tenant_dispute_returns_accepted_rf22(self):
        """CP-RF-22 flujo alterno: inconformidad devuelve ticket a ACCEPTED."""
        ticket = _ticket_en_confirmacion(self.tenant, self.property)
        self.client.force_authenticate(user=self.tenant)
        note = 'La reparación no solucionó la fuga reportada en el baño.'
        r = self.client.post(
            f'/api/v1/tickets/mine/{ticket.id}/dispute/',
            {'note': note},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['status'], 'ACCEPTED')
        ticket.refresh_from_db()
        self.assertEqual(ticket.assigned_contractor_name, '')
        self.assertIsNone(ticket.confirmation_deadline_at)
        log = TicketStatusLog.objects.filter(
            ticket=ticket,
            action=TicketStatusLog.Action.TENANT_DISPUTE,
        ).first()
        self.assertEqual(log.note, note)

    def test_confirm_requires_repair_evidence(self):
        ticket = Ticket.objects.create(
            property=self.property,
            tenant=self.tenant,
            description='Ticket en proceso sin evidencia aún cargada.',
            damage_type=Ticket.DamageType.OTHER,
            priority=Ticket.Priority.LOW,
            status=Ticket.Status.IN_PROGRESS,
            confirmation_deadline_at=timezone.now() + timedelta(days=1),
        )
        self.client.force_authenticate(user=self.tenant)
        r = self.client.post(f'/api/v1/tickets/mine/{ticket.id}/confirm/')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cp_rf_23_staff_timeline_rf23(self):
        """CP-RF-23: timeline de estados y acciones del ticket."""
        ticket = _ticket_en_confirmacion(self.tenant, self.property)
        TicketStatusLog.objects.create(
            ticket=ticket,
            from_status=Ticket.Status.ACCEPTED,
            to_status=Ticket.Status.IN_PROGRESS,
            action=TicketStatusLog.Action.ASSIGN,
            note='Asignación previa',
            changed_by=self.admin,
        )
        self.client.force_authenticate(user=self.admin)
        r = self.client.get(f'/api/v1/tickets/{ticket.id}/timeline/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(r.data), 1)
        self.assertIn('action_display', r.data[0])

    def test_cp_rf_23_auto_close_expired_confirmation_rf23(self):
        """CP-RF-23: cierre automático si vence confirmation_deadline_at."""
        ticket = _ticket_en_confirmacion(self.tenant, self.property)
        ticket.confirmation_deadline_at = timezone.now() - timedelta(hours=1)
        ticket.save(update_fields=['confirmation_deadline_at'])
        closed = ticket_service.cerrar_tickets_confirmacion_vencida()
        self.assertEqual(closed, 1)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.CLOSED)
        self.assertTrue(ticket.closed_automatically)
        self.assertTrue(
            TicketStatusLog.objects.filter(
                ticket=ticket,
                action=TicketStatusLog.Action.AUTO_CLOSE,
            ).exists(),
        )

    def test_management_command_runs_reminders_and_close(self):
        ticket = _ticket_en_confirmacion(self.tenant, self.property)
        ticket.confirmation_deadline_at = timezone.now() + timedelta(hours=24)
        ticket.save(update_fields=['confirmation_deadline_at'])
        mail.outbox.clear()
        call_command('close_expired_tickets')
        self.assertEqual(len(mail.outbox), 1)
        ticket.refresh_from_db()
        self.assertIsNotNone(ticket.confirmation_reminder_sent_at)

        ticket.confirmation_deadline_at = timezone.now() - timedelta(minutes=5)
        ticket.save(update_fields=['confirmation_deadline_at'])
        call_command('close_expired_tickets', skip_reminders=True)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.CLOSED)

    def test_tenant_cannot_access_staff_timeline(self):
        ticket = _ticket_en_confirmacion(self.tenant, self.property)
        self.client.force_authenticate(user=self.tenant)
        r = self.client.get(f'/api/v1/tickets/{ticket.id}/timeline/')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)
