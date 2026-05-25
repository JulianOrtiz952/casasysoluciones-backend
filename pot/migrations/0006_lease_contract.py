import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pot', '0005_ticket_confirmation_reminder_sent'),
    ]

    operations = [
        migrations.CreateModel(
            name='LeaseContract',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('start_date', models.DateField()),
                ('end_date', models.DateField(blank=True, null=True)),
                ('status', models.CharField(
                    choices=[('ACTIVE', 'Activo'), ('CLOSED', 'Cerrado'), ('CANCELLED', 'Cancelado')],
                    default='ACTIVE',
                    max_length=20,
                )),
                ('closed_at', models.DateTimeField(blank=True, null=True)),
                ('notes', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                (
                    'closed_by',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='lease_contracts_closed',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    'final_inventory',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='lease_contract',
                        to='pot.inventory',
                    ),
                ),
                (
                    'property',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='lease_contracts',
                        to='pot.property',
                    ),
                ),
                (
                    'tenant',
                    models.ForeignKey(
                        limit_choices_to={'role': 'TENANT'},
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='lease_contracts',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='leasecontract',
            constraint=models.UniqueConstraint(
                condition=models.Q(('status', 'ACTIVE')),
                fields=('property', 'tenant'),
                name='unique_active_lease_per_property_tenant',
            ),
        ),
    ]
