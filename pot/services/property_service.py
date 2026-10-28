from uuid import uuid4

from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.db.models import Count

from pot.models import Property, PropertyHistory, PropertyImage, UserPropertyAssociation
from pot.services.property_image_service import (
    PropertyImageValidationError,
    prepare_property_images,
)


class PropertyServiceError(Exception):
    def __init__(self, code, message, details=None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


def generar_codigo_propiedad():
    last = Property.objects.order_by('-id').first()
    n = (last.id + 1) if last else 1
    return f'PRO-{n:05d}'


def _prepare_images(cover_image, gallery_images, *, existing_count=0):
    try:
        return prepare_property_images(
            cover_image,
            gallery_images,
            existing_count=existing_count,
        )
    except PropertyImageValidationError as exc:
        raise PropertyServiceError('invalid_property_image', str(exc)) from exc


def _delete_uploaded_files(file_names):
    """Best-effort cleanup for object storage writes not covered by DB rollback."""
    for file_name in file_names:
        try:
            default_storage.delete(file_name)
        except Exception:
            # Preserve the original creation error. An isolated orphan can be
            # cleaned later, while masking the root failure makes diagnosis hard.
            pass


def registrar_evento_propiedad(
    property_obj,
    event_type,
    description,
    created_by=None,
    related_user=None,
    details=None,
):
    PropertyHistory.objects.create(
        property=property_obj,
        event_type=event_type,
        description=description,
        created_by=created_by,
        related_user=related_user,
        details=details or {},
    )


def obtener_historial_filtrado(property_obj, fecha_desde=None, fecha_hasta=None, tipo_evento=None, tenant_id=None):
    qs = property_obj.history.all()
    if fecha_desde:
        qs = qs.filter(created_at__date__gte=fecha_desde)
    if fecha_hasta:
        qs = qs.filter(created_at__date__lte=fecha_hasta)
    if tipo_evento:
        qs = qs.filter(event_type=tipo_evento)
    if tenant_id:
        qs = qs.filter(related_user_id=tenant_id)
    return qs.order_by('-created_at')


def obtener_arrendatario_actual(property_obj):
    assoc = UserPropertyAssociation.objects.filter(property=property_obj, dissociated_at__isnull=True).first()
    return assoc.user if assoc else None


def validar_direccion_unica(address, *, exclude_pk=None):
    address = (address or '').strip()
    if not address:
        raise PropertyServiceError('address_required', 'La dirección es obligatoria.')
    qs = Property.objects.filter(address__iexact=address)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    if qs.exists():
        raise PropertyServiceError('address_exists', 'Ya existe un inmueble con esta dirección.')


def crear_propiedad(created_by, **data):
    address = (data.pop('address', '') or '').strip()
    if not address and not data.get('google_maps_link'):
        raise PropertyServiceError('address_required', 'La dirección o el enlace de Google Maps es obligatorio.')
    address_is_pending = not address or address == 'Ver enlace de Google Maps adjunto'
    if not address_is_pending:
        validar_direccion_unica(address)
    cover_image = data.pop('cover_image', None)
    gallery_images = data.pop('images', [])
    cover_image, gallery_images = _prepare_images(cover_image, gallery_images)

    temporary_suffix = uuid4().hex[:12]
    temporary_code = f'TMP-{temporary_suffix}'
    safe_address = address if not address_is_pending else f'Ubicación por confirmar ({temporary_suffix})'

    uploaded_file_names = []
    try:
        with transaction.atomic():
            prop = Property.objects.create(
                code=temporary_code,
                address=safe_address,
                status=Property.Status.AVAILABLE,
                created_by=created_by,
                **data,
            )
            prop.code = f'PRO-{prop.pk:05d}'
            if address_is_pending:
                prop.address = f'Ubicación por confirmar ({prop.code})'
            prop.save(update_fields=['code', 'address', 'updated_at'])

            all_images = ([cover_image] if cover_image is not None else []) + gallery_images
            for index, (img_file, thumbnail_file) in enumerate(all_images):
                image = PropertyImage.objects.create(
                    property=prop,
                    image=img_file,
                    thumbnail=thumbnail_file,
                    is_cover=index == 0,
                )
                uploaded_file_names.append(image.image.name)
                uploaded_file_names.append(image.thumbnail.name)
                if index == 0:
                    # Reuse the gallery object's storage key. The previous code uploaded
                    # the cover twice (once per ImageField), doubling R2 work and storage.
                    prop.cover_image = image.image
                    prop.save(update_fields=['cover_image', 'updated_at'])

            registrar_evento_propiedad(
                prop,
                PropertyHistory.EventType.CREATED,
                f'Inmueble creado {prop.code}',
                created_by=created_by,
                details={'address': prop.address, 'type': prop.type},
            )
            return prop
    except IntegrityError as exc:
        _delete_uploaded_files(uploaded_file_names)
        if not address_is_pending and Property.objects.filter(address__iexact=address).exists():
            raise PropertyServiceError('address_exists', 'Ya existe un inmueble con esta dirección.') from exc
        raise PropertyServiceError(
            'property_creation_conflict',
            'No fue posible generar un código único para el inmueble. Intenta nuevamente.',
        ) from exc
    except Exception:
        _delete_uploaded_files(uploaded_file_names)
        raise


def actualizar_propiedad(prop, updated_by, **data):
    old_status = prop.status
    if 'address' in data or 'google_maps_link' in data:
        address = (data.get('address', prop.address) or '').strip()
        maps_link = (data.get('google_maps_link', prop.google_maps_link) or '').strip()
        pending_address = (
            not address
            or address in ('Google Maps', 'Ver enlace de Google Maps adjunto')
            or address.startswith('Ubicación por confirmar (')
        )
        if pending_address:
            if not maps_link:
                raise PropertyServiceError('address_required', 'La dirección o el enlace de Google Maps es obligatorio.')
            data['address'] = f'Ubicación por confirmar ({prop.code})'
        else:
            validar_direccion_unica(address, exclude_pk=prop.pk)
            data['address'] = address

    cover_image = data.pop('cover_image', None)
    new_images = data.pop('images', [])
    deleted_image_ids = data.pop('deleted_image_ids', [])
    set_cover_image_id = data.pop('set_cover_image_id', None)

    existing_count = prop.images.exclude(id__in=deleted_image_ids).count()
    cover_image, new_images = _prepare_images(
        cover_image,
        new_images,
        existing_count=existing_count,
    )

    with transaction.atomic():
        return _actualizar_propiedad(
            prop,
            updated_by,
            data,
            cover_image,
            new_images,
            deleted_image_ids,
            set_cover_image_id,
            old_status,
        )


def _actualizar_propiedad(
    prop,
    updated_by,
    data,
    cover_image,
    new_images,
    deleted_image_ids,
    set_cover_image_id,
    old_status,
):

    # 1. Handle deleted images
    if deleted_image_ids:
        PropertyImage.objects.filter(property=prop, id__in=deleted_image_ids).delete()

    # 2. Handle set cover image from existing
    if set_cover_image_id:
        target_img = PropertyImage.objects.filter(property=prop, id=set_cover_image_id).first()
        if target_img:
            PropertyImage.objects.filter(property=prop, is_cover=True).update(is_cover=False)
            target_img.is_cover = True
            target_img.save()
            prop.cover_image = target_img.image

    # 3. Handle new cover image upload
    if cover_image is not None:
        PropertyImage.objects.filter(property=prop, is_cover=True).update(is_cover=False)
        cover = PropertyImage.objects.create(
            property=prop,
            image=cover_image[0],
            thumbnail=cover_image[1],
            is_cover=True,
        )
        prop.cover_image = cover.image

    # 4. Handle new gallery images upload
    for img_file, thumbnail_file in new_images:
        is_first_no_cover = not prop.images.filter(is_cover=True).exists()
        new_pi = PropertyImage.objects.create(
            property=prop,
            image=img_file,
            thumbnail=thumbnail_file,
            is_cover=is_first_no_cover,
        )
        if is_first_no_cover and not prop.cover_image:
            prop.cover_image = new_pi.image

    for field, value in data.items():
        setattr(prop, field, value)
    prop.save()

    if 'status' in data and old_status != prop.status:
        registrar_evento_propiedad(
            prop,
            PropertyHistory.EventType.STATUS_CHANGE,
            f'Estado {old_status} → {prop.status}',
            created_by=updated_by,
            details={'old': old_status, 'new': prop.status},
        )
    return prop


def agregar_imagenes(prop, images):
    _, images = _prepare_images(None, images, existing_count=prop.images.count())
    with transaction.atomic():
        for img_file, thumbnail_file in images:
            is_first_no_cover = not prop.images.filter(is_cover=True).exists()
            new_pi = PropertyImage.objects.create(
                property=prop,
                image=img_file,
                thumbnail=thumbnail_file,
                is_cover=is_first_no_cover,
            )
            if is_first_no_cover and not prop.cover_image:
                prop.cover_image = new_pi.image
                prop.save(update_fields=['cover_image', 'updated_at'])


def eliminar_imagen(prop, image_id):
    img = PropertyImage.objects.filter(property=prop, id=image_id).first()
    if not img:
        raise PropertyServiceError('image_not_found', 'Imagen no encontrada.')
    was_cover = img.is_cover
    img.delete()
    if was_cover:
        next_img = PropertyImage.objects.filter(property=prop).first()
        if next_img:
            next_img.is_cover = True
            next_img.save()
            prop.cover_image = next_img.image
        else:
            prop.cover_image = None
        prop.save()


def establecer_portada(prop, image_id):
    img = PropertyImage.objects.filter(property=prop, id=image_id).first()
    if not img:
        raise PropertyServiceError('image_not_found', 'Imagen no encontrada.')
    PropertyImage.objects.filter(property=prop, is_cover=True).update(is_cover=False)
    img.is_cover = True
    img.save()
    prop.cover_image = img.image
    prop.save()


def estadisticas_propiedades():
    by_status = {
        row['status']: row['count']
        for row in Property.objects.values('status').annotate(count=Count('id'))
    }
    by_type = {
        row['type']: row['count']
        for row in Property.objects.values('type').annotate(count=Count('id'))
    }
    return {
        'total': Property.objects.count(),
        'available': by_status.get(Property.Status.AVAILABLE, 0),
        'rented': by_status.get(Property.Status.RENTED, 0),
        'maintenance': by_status.get(Property.Status.MAINTENANCE, 0),
        'by_status': by_status,
        'by_type': by_type,
    }
