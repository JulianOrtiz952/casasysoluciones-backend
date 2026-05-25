from django.core.management.base import BaseCommand

from pot.services import ticket_service


class Command(BaseCommand):
    help = (
        'RF-23: envía recordatorios de confirmación (~24 h antes) y cierra tickets '
        'IN_PROGRESS sin respuesta del arrendatario tras el plazo hábil.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--skip-reminders',
            action='store_true',
            help='Solo ejecutar cierre automático, sin recordatorios por correo.',
        )

    def handle(self, *args, **options):
        reminders = 0
        if not options['skip_reminders']:
            reminders = ticket_service.enviar_recordatorios_confirmacion_ticket()
        closed = ticket_service.cerrar_tickets_confirmacion_vencida()
        self.stdout.write(
            self.style.SUCCESS(
                f'Recordatorios enviados: {reminders}. Tickets cerrados automáticamente: {closed}.',
            ),
        )
