import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

import pot.models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.CreateModel(
            name='CustomUser',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('password', models.CharField(max_length=128, verbose_name='password')),
                ('last_login', models.DateTimeField(blank=True, null=True, verbose_name='last login')),
                ('is_superuser', models.BooleanField(default=False, help_text='Designates that this user has all permissions without explicitly assigning them.', verbose_name='superuser status')),
                ('username', models.CharField(blank=True, max_length=150, unique=True)),
                ('first_name', models.CharField(blank=True, max_length=150, verbose_name='first name')),
                ('last_name', models.CharField(blank=True, max_length=150, verbose_name='last name')),
                ('is_staff', models.BooleanField(default=False, help_text='Designates whether the user can log into this admin site.', verbose_name='staff status')),
                ('is_active', models.BooleanField(default=True, help_text='Designates whether this user should be treated as active. Unselect this instead of deleting accounts.', verbose_name='active')),
                ('date_joined', models.DateTimeField(default=django.utils.timezone.now, verbose_name='date joined')),
                ('email', models.EmailField(max_length=254, unique=True)),
                ('phone', models.CharField(default='', max_length=20)),
                ('role', models.CharField(choices=[('ADMIN', 'Administrador'), ('ASSISTANT', 'Asistente Administrativo'), ('TENANT', 'Arrendatario')], default='TENANT', max_length=20)),
                ('password_changed', models.BooleanField(default=False)),
                ('password_reset_token', models.CharField(blank=True, max_length=255, null=True)),
                ('password_reset_expires', models.DateTimeField(blank=True, null=True)),
                ('login_attempts', models.PositiveIntegerField(default=0)),
                ('login_locked_until', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('groups', models.ManyToManyField(blank=True, help_text='The groups this user belongs to. A user will get all permissions granted to each of their groups.', related_name='user_set', related_query_name='user', to='auth.group', verbose_name='groups')),
                ('user_permissions', models.ManyToManyField(blank=True, help_text='Specific permissions for this user.', related_name='user_set', related_query_name='user', to='auth.permission', verbose_name='user permissions')),
            ],
            options={
                'ordering': ['-created_at'],
            },
            managers=[
                ('objects', pot.models.CustomUserManager()),
            ],
        ),
        migrations.CreateModel(
            name='Property',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(max_length=20, unique=True)),
                ('address', models.CharField(max_length=255, unique=True)),
                ('type', models.CharField(choices=[('APARTMENT', 'Apartamento'), ('HOUSE', 'Casa'), ('LOCAL', 'Local comercial'), ('WAREHOUSE', 'Bodega')], max_length=20)),
                ('owner_name', models.CharField(max_length=150)),
                ('status', models.CharField(choices=[('AVAILABLE', 'Disponible'), ('RENTED', 'Arrendado'), ('MAINTENANCE', 'En mantenimiento')], default='AVAILABLE', max_length=20)),
                ('observations', models.TextField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='properties_created', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
                'verbose_name_plural': 'properties',
            },
        ),
        migrations.CreateModel(
            name='Inventory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('inventory_type', models.CharField(choices=[('INITIAL', 'Inicial'), ('FINAL', 'Final')], max_length=10)),
                ('status', models.CharField(choices=[('IN_PROGRESS', 'En registro'), ('PENDING_SIGNATURE', 'Pendiente de firma'), ('OBSERVATIONS_PENDING', 'Observaciones pendientes'), ('ACCEPTED', 'Aceptado'), ('CLOSED', 'Cerrado')], default='IN_PROGRESS', max_length=30)),
                ('delivery_date', models.DateField()),
                ('observations', models.TextField(blank=True, null=True)),
                ('signed_at', models.DateTimeField(blank=True, null=True)),
                ('signature_token', models.CharField(blank=True, max_length=255, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='inventories_created', to=settings.AUTH_USER_MODEL)),
                ('property', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='inventories', to='pot.property')),
                ('signed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='inventories_signed', to=settings.AUTH_USER_MODEL)),
                ('tenant', models.ForeignKey(limit_choices_to={'role': 'TENANT'}, on_delete=django.db.models.deletion.CASCADE, related_name='inventories_as_tenant', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
                'unique_together': {('property', 'tenant', 'inventory_type')},
            },
        ),
        migrations.CreateModel(
            name='InventorySpace',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('space_name', models.CharField(max_length=100)),
                ('condition', models.CharField(choices=[('GOOD', 'Bueno'), ('REGULAR', 'Regular'), ('BAD', 'Malo')], max_length=20)),
                ('observations', models.TextField(blank=True, null=True)),
                ('order', models.IntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('inventory', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='spaces', to='pot.inventory')),
            ],
            options={
                'ordering': ['order', 'space_name'],
            },
        ),
        migrations.CreateModel(
            name='InventorySpacePhoto',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('image', models.ImageField(max_length=255, upload_to=pot.models.inventory_space_photo_upload)),
                ('thumbnail', models.ImageField(blank=True, max_length=255, null=True, upload_to=pot.models.inventory_space_thumb_upload)),
                ('description', models.CharField(blank=True, max_length=255, null=True)),
                ('uploaded_at', models.DateTimeField(auto_now_add=True)),
                ('space', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='photos', to='pot.inventoryspace')),
                ('uploaded_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['uploaded_at'],
            },
        ),
        migrations.CreateModel(
            name='InventorySignature',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('signed_at', models.DateTimeField(auto_now_add=True)),
                ('signature_token', models.CharField(max_length=255)),
                ('ip_address', models.GenericIPAddressField()),
                ('user_agent', models.TextField()),
                ('inventory', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='signatures', to='pot.inventory')),
                ('signed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-signed_at'],
            },
        ),
        migrations.CreateModel(
            name='InventoryTenantObservation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('observation_text', models.TextField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ('inventory', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tenant_observations', to='pot.inventory')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='PropertyHistory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_type', models.CharField(choices=[('CREATED', 'Creación'), ('STATUS_CHANGE', 'Cambio de estado'), ('TENANT_ASSOCIATED', 'Arrendatario asociado'), ('TENANT_DISSOCIATED', 'Arrendatario desasociado'), ('TICKET_CREATED', 'Ticket creado'), ('TICKET_CLOSED', 'Ticket cerrado'), ('INVENTORY_CREATED', 'Inventario creado'), ('INVENTORY_SIGNED', 'Inventario firmado'), ('MAINTENANCE', 'Mantenimiento realizado'), ('TENANT_OBSERVATIONS', 'Observaciones arrendatario')], max_length=30)),
                ('description', models.TextField()),
                ('details', models.JSONField(default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='history_events_created', to=settings.AUTH_USER_MODEL)),
                ('property', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='history', to='pot.property')),
                ('related_user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
                'verbose_name_plural': 'property histories',
            },
        ),
        migrations.CreateModel(
            name='Ticket',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(default='Ticket', max_length=200)),
                ('status', models.CharField(choices=[('OPEN', 'Abierto'), ('CLOSED', 'Cerrado')], default='OPEN', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('property', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tickets', to='pot.property')),
                ('tenant', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='tickets', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='UserAudit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action', models.CharField(max_length=100)),
                ('details', models.JSONField(default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('changed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='audits_created', to=settings.AUTH_USER_MODEL)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='audits', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='UserPropertyAssociation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('associated_at', models.DateTimeField(auto_now_add=True)),
                ('dissociated_at', models.DateTimeField(blank=True, null=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='associations_created', to=settings.AUTH_USER_MODEL)),
                ('property', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tenant_associations', to='pot.property')),
                ('user', models.ForeignKey(limit_choices_to={'role': 'TENANT'}, on_delete=django.db.models.deletion.CASCADE, related_name='property_associations', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-associated_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='userpropertyassociation',
            constraint=models.UniqueConstraint(
                condition=models.Q(dissociated_at__isnull=True),
                fields=('property',),
                name='pot_unique_active_tenant_per_property',
            ),
        ),
    ]
