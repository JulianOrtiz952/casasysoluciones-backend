from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import pot.models


def populate_ticket_public_codes(apps, schema_editor):
    Ticket = apps.get_model('pot', 'Ticket')
    for ticket in Ticket.objects.filter(public_code__isnull=True).iterator():
        ticket.public_code = f'TK-{ticket.pk:05d}'
        ticket.save(update_fields=['public_code'])


class Migration(migrations.Migration):

    dependencies = [
        ('pot', '0002_customuser_profile_fields_property_location'),
    ]

    operations = [
        migrations.AddField(
            model_name='ticket',
            name='assigned_contractor_name',
            field=models.CharField(blank=True, default='', max_length=200),
        ),
        migrations.AddField(
            model_name='ticket',
            name='closed_automatically',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='ticket',
            name='confirmation_deadline_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='ticket',
            name='damage_type',
            field=models.CharField(
                choices=[
                    ('PLUMBING', 'Plomería / Hidráulico'),
                    ('ELECTRICITY', 'Electricidad'),
                    ('LOCKSMITH', 'Cerrajería'),
                    ('STRUCTURE', 'Estructura'),
                    ('PAINTING', 'Pintura'),
                    ('CARPENTRY', 'Carpintería'),
                    ('OTHER', 'Otro'),
                ],
                default='OTHER',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='ticket',
            name='damage_type_other',
            field=models.CharField(blank=True, default='', max_length=200),
        ),
        migrations.AddField(
            model_name='ticket',
            name='description',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='ticket',
            name='priority',
            field=models.CharField(
                choices=[('LOW', 'Leve'), ('MEDIUM', 'Importante'), ('HIGH', 'Urgente')],
                default='MEDIUM',
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name='ticket',
            name='public_code',
            field=models.CharField(blank=True, max_length=20, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='ticket',
            name='rejection_reason',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='ticket',
            name='tenant_confirmed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='ticket',
            name='status',
            field=models.CharField(
                choices=[
                    ('DRAFT', 'Borrador'),
                    ('OPEN', 'Abierto'),
                    ('ACCEPTED', 'Aceptado'),
                    ('IN_PROGRESS', 'En proceso'),
                    ('REJECTED', 'Rechazado'),
                    ('CLOSED', 'Cerrado'),
                ],
                default='OPEN',
                max_length=20,
            ),
        ),
        migrations.RunPython(populate_ticket_public_codes, migrations.RunPython.noop),
        migrations.CreateModel(
            name='TicketAttachment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('image', models.ImageField(max_length=500, upload_to=pot.models.ticket_attachment_upload)),
                ('uploaded_at', models.DateTimeField(auto_now_add=True)),
                (
                    'ticket',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='attachments',
                        to='pot.ticket',
                    ),
                ),
                (
                    'uploaded_by',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='ticket_attachments_uploaded',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                'ordering': ['uploaded_at'],
            },
        ),
    ]
