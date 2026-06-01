from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone
import re
import html as html_lib
import urllib.request
import urllib.parse


class CustomUserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError('Email obligatorio')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', CustomUser.Role.ADMIN)
        extra_fields.setdefault('password_changed', True)
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser debe tener is_staff=True')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser debe tener is_superuser=True')
        return self._create_user(email, password, **extra_fields)


class CustomUser(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = 'ADMIN', 'Administrador'
        ASSISTANT = 'ASSISTANT', 'Asistente Administrativo'
        TENANT = 'TENANT', 'Arrendatario'

    class DocumentType(models.TextChoices):
        CC = 'CC', 'Cédula de ciudadanía'
        CE = 'CE', 'Cédula de extranjería'
        PASSPORT = 'PASSPORT', 'Pasaporte'
        NIT = 'NIT', 'NIT'

    username = models.CharField(max_length=150, unique=True, blank=True)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20, default='')
    public_code = models.CharField(max_length=20, unique=True, blank=True, null=True)
    document_type = models.CharField(
        max_length=20,
        choices=DocumentType.choices,
        blank=True,
        default='',
    )
    document_number = models.CharField(max_length=30, unique=True, blank=True, null=True)
    avatar = models.ImageField(upload_to='avatars/%Y/%m/', blank=True, null=True, max_length=255)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.TENANT)
    password_changed = models.BooleanField(default=False)
    password_reset_token = models.CharField(max_length=255, null=True, blank=True)
    password_reset_expires = models.DateTimeField(null=True, blank=True)
    login_attempts = models.PositiveIntegerField(default=0)
    login_locked_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects = CustomUserManager()

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.username:
            self.username = self.email
        super().save(*args, **kwargs)
        if not self.public_code:
            self.public_code = f'USR-{self.pk:05d}'
            super().save(update_fields=['public_code'])

        if self.role == 'TENANT':
            try:
                from api.models import Inquilino
                nombre = f"{self.first_name} {self.last_name}".strip()
                if not nombre:
                    nombre = self.email.split('@')[0]
                    
                identificacion = self.document_number
                if not identificacion:
                    identificacion = self.public_code or f"USR-{self.pk:05d}"
                
                inquilino = Inquilino.objects.filter(email=self.email).first()
                if inquilino:
                    inquilino.nombre = nombre
                    inquilino.telefono = self.phone or ''
                    if not Inquilino.objects.filter(identificacion=identificacion).exclude(pk=inquilino.pk).exists():
                        inquilino.identificacion = identificacion
                    inquilino.save()
                else:
                    if Inquilino.objects.filter(identificacion=identificacion).exists():
                        identificacion = f"DUP-{self.pk}-{identificacion}"[:50]
                    Inquilino.objects.create(
                        nombre=nombre,
                        email=self.email,
                        telefono=self.phone or '',
                        identificacion=identificacion
                    )
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Error syncing tenant on save: {e}", exc_info=True)


    def __str__(self):
        return f'{self.email} ({self.get_role_display()})'

    def is_admin_role(self):
        return self.role == self.Role.ADMIN

    def is_staff_operative(self):
        return self.role in (self.Role.ADMIN, self.Role.ASSISTANT)


class UserPropertyAssociation(models.Model):
    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='property_associations',
        limit_choices_to={'role': CustomUser.Role.TENANT},
    )
    property = models.ForeignKey('Property', on_delete=models.CASCADE, related_name='tenant_associations')
    associated_at = models.DateTimeField(auto_now_add=True)
    dissociated_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='associations_created',
    )

    class Meta:
        ordering = ['-associated_at']
        constraints = [
            models.UniqueConstraint(
                fields=['property'],
                condition=models.Q(dissociated_at__isnull=True),
                name='pot_unique_active_tenant_per_property',
            ),
        ]

    def is_association_active(self):
        return self.dissociated_at is None

    def __str__(self):
        return f'{self.user.email} → {self.property.address}'


class UserAudit(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='audits')
    action = models.CharField(max_length=100)
    details = models.JSONField(default=dict)
    changed_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audits_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.action} - {self.user.email} - {self.created_at}'


class Property(models.Model):
    class Type(models.TextChoices):
        APARTMENT = 'APARTMENT', 'Apartamento'
        HOUSE = 'HOUSE', 'Casa'
        LOCAL = 'LOCAL', 'Local comercial'
        WAREHOUSE = 'WAREHOUSE', 'Bodega'

    class Status(models.TextChoices):
        AVAILABLE = 'AVAILABLE', 'Disponible'
        RENTED = 'RENTED', 'Arrendado'
        MAINTENANCE = 'MAINTENANCE', 'En mantenimiento'

    code = models.CharField(max_length=20, unique=True)
    address = models.CharField(max_length=255, unique=True)
    city = models.CharField(max_length=100, blank=True, default='')
    building_name = models.CharField(max_length=150, blank=True, default='')
    unit_label = models.CharField(max_length=50, blank=True, default='')
    cover_image = models.ImageField(upload_to='properties/covers/%Y/%m/', blank=True, null=True, max_length=255)
    type = models.CharField(max_length=20, choices=Type.choices)
    owner_name = models.CharField(max_length=150)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.AVAILABLE)
    
    # New fields migrated from Inmueble
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    rooms = models.IntegerField(null=True, blank=True)
    bathrooms = models.IntegerField(null=True, blank=True)
    living_rooms = models.IntegerField(null=True, blank=True)
    kitchens = models.IntegerField(null=True, blank=True)
    garages = models.IntegerField(null=True, blank=True)
    is_commercial = models.BooleanField(default=False)
    in_complex = models.BooleanField(default=False)
    admin_included = models.BooleanField(default=False)
    admin_value = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    google_maps_link = models.CharField(max_length=1000, null=True, blank=True)
    description = models.TextField(blank=True, null=True)

    observations = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='properties_created',
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'properties'

    def __str__(self):
        return f'{self.code} - {self.address}'

    def save(self, *args, **kwargs):
        if self.google_maps_link and (not self.address or self.address == 'Ver enlace de Google Maps adjunto'):
            try:
                req = urllib.request.Request(self.google_maps_link, headers={'User-Agent': 'Mozilla/5.0'})
                res = urllib.request.urlopen(req, timeout=10)
                html_content = res.read().decode('utf-8', errors='ignore')

                titulo_maps = ''
                subtitulo_maps = ''

                for meta_match in re.finditer(r'<meta\s+([^>]+)>', html_content):
                    attrs = meta_match.group(1)
                    if 'property="og:title"' in attrs:
                        c_match = re.search(r'content="([^"]+)"', attrs)
                        if c_match:
                            titulo_maps = c_match.group(1)
                    elif 'property="og:description"' in attrs:
                        c_match = re.search(r'content="([^"]+)"', attrs)
                        if c_match:
                            subtitulo_maps = c_match.group(1)

                titulo_maps = html_lib.unescape(titulo_maps).strip()
                subtitulo_maps = html_lib.unescape(subtitulo_maps).strip()

                if titulo_maps:
                    def starts_with_num(s):
                        return (s[0].isdigit() or s[0] in ['-', '+']) if s else False

                    if ' · Google Maps' in subtitulo_maps:
                        subtitulo_maps = subtitulo_maps.replace(' · Google Maps', '')

                    if starts_with_num(titulo_maps):
                        if starts_with_num(subtitulo_maps):
                            self.address = titulo_maps
                        else:
                            self.address = subtitulo_maps if subtitulo_maps else titulo_maps
                    else:
                        self.address = titulo_maps
                else:
                    final_url = res.geturl()
                    if '/search/' in final_url:
                        query = final_url.split('/search/')[1].split('?')[0].split('/')[0]
                        self.address = urllib.parse.unquote_plus(query)
                    elif '/place/' in final_url:
                        query = final_url.split('/place/')[1].split('/')[0]
                        self.address = urllib.parse.unquote_plus(query)
            except Exception as e:
                print(f'Error resolving maps link in Property: {e}')

        super().save(*args, **kwargs)

    def get_active_tenant(self):
        assoc = (
            self.tenant_associations.filter(dissociated_at__isnull=True)
            .select_related('user')
            .first()
        )
        return assoc.user if assoc else None


class PropertyImage(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='properties/gallery/%Y/%m/', max_length=255)
    is_cover = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_cover', 'created_at']

    def __str__(self):
        return f'Imagen de {self.property.code} - {"Portada" if self.is_cover else "Galería"}'

    def save(self, *args, **kwargs):
        if self.is_cover:
            PropertyImage.objects.filter(property=self.property, is_cover=True).update(is_cover=False)
        super().save(*args, **kwargs)


class PropertyHistory(models.Model):
    class EventType(models.TextChoices):
        CREATED = 'CREATED', 'Creación'
        STATUS_CHANGE = 'STATUS_CHANGE', 'Cambio de estado'
        TENANT_ASSOCIATED = 'TENANT_ASSOCIATED', 'Arrendatario asociado'
        TENANT_DISSOCIATED = 'TENANT_DISSOCIATED', 'Arrendatario desasociado'
        TICKET_CREATED = 'TICKET_CREATED', 'Ticket creado'
        TICKET_CLOSED = 'TICKET_CLOSED', 'Ticket cerrado'
        INVENTORY_CREATED = 'INVENTORY_CREATED', 'Inventario creado'
        INVENTORY_SIGNED = 'INVENTORY_SIGNED', 'Inventario firmado'
        MAINTENANCE = 'MAINTENANCE', 'Mantenimiento realizado'
        TENANT_OBSERVATIONS = 'TENANT_OBSERVATIONS', 'Observaciones arrendatario'

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='history')
    event_type = models.CharField(max_length=30, choices=EventType.choices)
    description = models.TextField()
    details = models.JSONField(default=dict)
    related_user = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='history_events_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'property histories'

    def __str__(self):
        return f'{self.property.code} - {self.event_type} - {self.created_at}'


class Ticket(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Borrador'
        OPEN = 'OPEN', 'Abierto'
        ACCEPTED = 'ACCEPTED', 'Aceptado'
        IN_PROGRESS = 'IN_PROGRESS', 'En proceso'
        REJECTED = 'REJECTED', 'Rechazado'
        CLOSED = 'CLOSED', 'Cerrado'

    class DamageType(models.TextChoices):
        PLUMBING = 'PLUMBING', 'Plomería / Hidráulico'
        ELECTRICITY = 'ELECTRICITY', 'Electricidad'
        LOCKSMITH = 'LOCKSMITH', 'Cerrajería'
        STRUCTURE = 'STRUCTURE', 'Estructura'
        PAINTING = 'PAINTING', 'Pintura'
        CARPENTRY = 'CARPENTRY', 'Carpintería'
        APPLIANCE = 'APPLIANCE', 'Electrodoméstico'
        OTHER = 'OTHER', 'Otro'

    class Priority(models.TextChoices):
        LOW = 'LOW', 'Leve'
        MEDIUM = 'MEDIUM', 'Importante'
        HIGH = 'HIGH', 'Urgente'

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='tickets')
    tenant = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tickets',
    )
    public_code = models.CharField(max_length=20, unique=True, blank=True, null=True)
    title = models.CharField(max_length=200, default='Ticket')
    description = models.TextField(blank=True, default='')
    damage_type = models.CharField(
        max_length=20,
        choices=DamageType.choices,
        default=DamageType.OTHER,
    )
    damage_type_other = models.CharField(max_length=200, blank=True, default='')
    priority = models.CharField(
        max_length=10,
        choices=Priority.choices,
        default=Priority.MEDIUM,
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    assigned_contractor_name = models.CharField(max_length=200, blank=True, default='')
    rejection_reason = models.TextField(blank=True, default='')
    confirmation_deadline_at = models.DateTimeField(null=True, blank=True)
    closed_automatically = models.BooleanField(default=False)
    tenant_confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new and not self.public_code:
            self.public_code = f'TK-{self.pk:05d}'
            super().save(update_fields=['public_code'])

    def __str__(self):
        return f'{self.public_code or self.pk} - {self.property.code} - {self.title}'

    def is_editable_by_tenant(self):
        return self.status in (self.Status.DRAFT, self.Status.OPEN)


def ticket_attachment_upload(instance, filename):
    code = instance.ticket.public_code or f'id-{instance.ticket_id}'
    return f'tickets/{code}/{timezone.now().timestamp()}_{filename}'


class TicketAttachment(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='attachments')
    image = models.ImageField(upload_to=ticket_attachment_upload, max_length=500)
    uploaded_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ticket_attachments_uploaded',
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['uploaded_at']

    def __str__(self):
        return f'{self.ticket.public_code} - adjunto {self.pk}'


class Inventory(models.Model):
    class Type(models.TextChoices):
        INITIAL = 'INITIAL', 'Inicial'
        FINAL = 'FINAL', 'Final'

    class Status(models.TextChoices):
        IN_PROGRESS = 'IN_PROGRESS', 'En registro'
        PENDING_SIGNATURE = 'PENDING_SIGNATURE', 'Pendiente de firma'
        OBSERVATIONS_PENDING = 'OBSERVATIONS_PENDING', 'Observaciones pendientes'
        ACCEPTED = 'ACCEPTED', 'Aceptado'
        CLOSED = 'CLOSED', 'Cerrado'

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='inventories')
    tenant = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='inventories_as_tenant',
        limit_choices_to={'role': CustomUser.Role.TENANT},
    )
    inventory_type = models.CharField(max_length=10, choices=Type.choices)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.IN_PROGRESS)
    delivery_date = models.DateField()
    observations = models.TextField(blank=True, null=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    signed_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inventories_signed',
    )
    signature_token = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inventories_created',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ('property', 'tenant', 'inventory_type')

    def __str__(self):
        return f'{self.property.code} - {self.get_inventory_type_display()} - {self.tenant.email}'

    def is_editable(self):
        return self.status == self.Status.IN_PROGRESS


class InventorySpace(models.Model):
    class Condition(models.TextChoices):
        GOOD = 'GOOD', 'Bueno'
        REGULAR = 'REGULAR', 'Regular'
        BAD = 'BAD', 'Malo'

    inventory = models.ForeignKey(Inventory, on_delete=models.CASCADE, related_name='spaces')
    space_name = models.CharField(max_length=100)
    condition = models.CharField(max_length=20, choices=Condition.choices)
    observations = models.TextField(blank=True, null=True)
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'space_name']

    def __str__(self):
        return f'{self.inventory.property.code} - {self.space_name}'


def _inventory_photo_dir(instance):
    inv = instance.space.inventory
    return f'inventories/{inv.property.code}/{inv.id}/{instance.space.id}'


def inventory_space_photo_upload(instance, filename):
    return f'{_inventory_photo_dir(instance)}/{timezone.now().timestamp()}_{filename}'


def inventory_space_thumb_upload(instance, filename):
    return f'{_inventory_photo_dir(instance)}/thumb_{timezone.now().timestamp()}_{filename}'


class InventorySpacePhoto(models.Model):
    space = models.ForeignKey(InventorySpace, on_delete=models.CASCADE, related_name='photos')
    image = models.ImageField(upload_to=inventory_space_photo_upload, max_length=255)
    thumbnail = models.ImageField(upload_to=inventory_space_thumb_upload, max_length=255, blank=True, null=True)
    description = models.CharField(max_length=255, blank=True, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['uploaded_at']

    def __str__(self):
        return f'Foto - {self.space.space_name}'

    def get_thumbnail_url(self):
        if self.thumbnail:
            return self.thumbnail.url
        return self.image.url if self.image else ''


class InventorySignature(models.Model):
    inventory = models.ForeignKey(Inventory, on_delete=models.CASCADE, related_name='signatures')
    signed_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True)
    signed_at = models.DateTimeField(auto_now_add=True)
    signature_token = models.CharField(max_length=255)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField()

    class Meta:
        ordering = ['-signed_at']

    def __str__(self):
        return f'Firma - {self.inventory.property.code}'


class InventoryTenantObservation(models.Model):
    inventory = models.ForeignKey(Inventory, on_delete=models.CASCADE, related_name='tenant_observations')
    observation_text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
