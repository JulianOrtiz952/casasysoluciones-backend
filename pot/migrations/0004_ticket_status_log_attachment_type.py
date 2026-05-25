from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('pot', '0003_ticket_hu05_fields'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='ticketattachment',
            name='attachment_type',
            field=models.CharField(
                choices=[('TENANT', 'Adjunto arrendatario'), ('REPAIR_EVIDENCE', 'Evidencia reparación')],
                default='TENANT',
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name='TicketStatusLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('from_status', models.CharField(blank=True, choices=[('DRAFT', 'Borrador'), ('OPEN', 'Abierto'), ('ACCEPTED', 'Aceptado'), ('IN_PROGRESS', 'En proceso'), ('REJECTED', 'Rechazado'), ('CLOSED', 'Cerrado')], default='', max_length=20)),
                ('to_status', models.CharField(choices=[('DRAFT', 'Borrador'), ('OPEN', 'Abierto'), ('ACCEPTED', 'Aceptado'), ('IN_PROGRESS', 'En proceso'), ('REJECTED', 'Rechazado'), ('CLOSED', 'Cerrado')], max_length=20)),
                ('action', models.CharField(choices=[('STATUS_CHANGE', 'Cambio de estado'), ('REJECT', 'Rechazo'), ('ASSIGN', 'Asignación maestro'), ('REPAIR_EVIDENCE', 'Evidencia reparación'), ('FORCE_CLOSE', 'Cierre forzado')], default='STATUS_CHANGE', max_length=20)),
                ('note', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('changed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='ticket_status_changes', to=settings.AUTH_USER_MODEL)),
                ('ticket', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='status_logs', to='pot.ticket')),
            ],
            options={
                'ordering': ['created_at'],
            },
        ),
    ]
