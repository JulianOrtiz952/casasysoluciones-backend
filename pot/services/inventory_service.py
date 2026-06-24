import os
from io import BytesIO

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone
from django.utils.html import escape
from PIL import Image, ImageOps
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image as RLImage
from reportlab.platypus import HRFlowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from django.db import transaction

from pot.models import (
    CustomUser,
    Inventory,
    InventorySpace,
    InventorySpacePhoto,
    InventoryTenantObservation,
    Property,
    PropertyHistory,
    UserPropertyAssociation,
)
from pot.services.property_service import registrar_evento_propiedad


class InventoryServiceError(Exception):
    def __init__(self, code, message, details=None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


SPACE_TEMPLATES_BY_PROPERTY_TYPE = {
    Property.Type.APARTMENT: [
        'Sala',
        'Cocina',
        'Baño principal',
        'Baño auxiliar',
        'Alcoba principal',
        'Alcoba secundaria',
        'Balcón',
        'Zona de ropas',
    ],
    Property.Type.HOUSE: [
        'Sala',
        'Comedor',
        'Cocina',
        'Baño principal',
        'Habitación 1',
        'Habitación 2',
        'Patio',
        'Garaje',
    ],
    Property.Type.LOCAL: [
        'Área principal',
        'Baño',
        'Bodega',
        'Fachada',
        'Cocineta',
    ],
    Property.Type.WAREHOUSE: [
        'Bodega principal',
        'Oficina',
        'Baño',
        'Parqueadero',
        'Mezzanine',
    ],
}


def _read_fieldfile_bytes(fieldfile):
    """Lee bytes desde storage (R2/S3/disco); evita estado roto del FieldFile."""
    if not fieldfile:
        return None
    name = getattr(fieldfile, 'name', None) or ''
    if name:
        try:
            with default_storage.open(name, 'rb') as fh:
                return fh.read()
        except Exception:
            pass
    try:
        fieldfile.open('rb')
        try:
            return fieldfile.read()
        finally:
            fieldfile.close()
    except Exception:
        return None


def _pil_to_rgb(pil_img):
    """RGBA / P+transparencia / LA → RGB sobre blanco (evita fallos al guardar JPEG)."""
    pil_img = pil_img.copy()
    pil_img.load()
    pil_img = ImageOps.exif_transpose(pil_img)
    if pil_img.mode == 'CMYK':
        pil_img = pil_img.convert('RGB')
    if pil_img.mode == 'P':
        if 'transparency' in pil_img.info:
            pil_img = pil_img.convert('RGBA')
        else:
            return pil_img.convert('RGB')
    if pil_img.mode in ('RGBA', 'LA'):
        rgba = pil_img if pil_img.mode == 'RGBA' else pil_img.convert('RGBA')
        bg = Image.new('RGB', rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[3])
        return bg
    if pil_img.mode != 'RGB':
        return pil_img.convert('RGB')
    return pil_img


def _rl_image_from_fieldfile(fieldfile, max_width, max_height):
    """
    Incrusta imagen en PDF vía JPEG en memoria (PNG/JPEG/R2/local).
    Mantiene proporción dentro de max_width x max_height.
    """
    raw = _read_fieldfile_bytes(fieldfile)
    if not raw:
        return None

    def _from_pil(pil_img):
        rgb = _pil_to_rgb(pil_img)
        iw, ih = rgb.size
        if iw < 1 or ih < 1:
            return None
        scale = min(float(max_width) / iw, float(max_height) / ih, 1.0)
        w_pt = iw * scale
        h_pt = ih * scale
        out = BytesIO()
        rgb.save(out, format='JPEG', quality=88)
        jpeg_bytes = out.getvalue()
        return RLImage(ImageReader(BytesIO(jpeg_bytes)), width=w_pt, height=h_pt)

    try:
        pil = Image.open(BytesIO(raw))
        pil.load()
        return _from_pil(pil)
    except Exception:
        pass

    try:
        pil = Image.open(BytesIO(raw))
        return _from_pil(pil)
    except Exception:
        pass

    try:
        bio = BytesIO(raw)
        bio.seek(0)
        ir = ImageReader(bio)
        iw, ih = ir.getSize()
        if iw < 1 or ih < 1:
            return None
        scale = min(float(max_width) / iw, float(max_height) / ih, 1.0)
        return RLImage(ir, width=iw * scale, height=ih * scale)
    except Exception:
        return None


def _foto_bloque(photo, max_w, max_h, small_style, numero):
    rl = _rl_image_from_fieldfile(photo.image, max_w, max_h)
    cap = escape(photo.description) if photo.description else f'Evidencia fotográfica {numero}'
    if rl:
        return KeepTogether([rl, Spacer(1, 0.06 * inch), Paragraph(cap, small_style)])
    return Paragraph(f'<i>{cap}</i> — <b>imagen no disponible</b> en el PDF.', small_style)


def generar_pdf_inventario(inventory_obj):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=0.65 * inch,
        leftMargin=0.65 * inch,
        topMargin=0.65 * inch,
        bottomMargin=0.65 * inch,
    )
    elements = []
    styles = getSampleStyleSheet()

    title = ParagraphStyle(
        name='ConstTitle',
        parent=styles['Heading1'],
        fontSize=15,
        leading=18,
        alignment=TA_CENTER,
        spaceAfter=6,
        textColor=colors.HexColor('#1a1a2e'),
    )
    subtitle = ParagraphStyle(
        name='ConstSub',
        parent=styles['Normal'],
        fontSize=10,
        alignment=TA_CENTER,
        textColor=colors.HexColor('#444444'),
        spaceAfter=14,
    )
    h2 = ParagraphStyle(
        name='ConstH2',
        parent=styles['Heading2'],
        fontSize=12,
        leading=15,
        spaceBefore=10,
        spaceAfter=8,
        textColor=colors.HexColor('#16213e'),
    )
    small = ParagraphStyle(
        name='ConstSmall',
        parent=styles['Normal'],
        fontSize=8,
        leading=10,
        textColor=colors.HexColor('#555555'),
        alignment=TA_CENTER,
    )
    body = ParagraphStyle(
        name='ConstBody',
        parent=styles['Normal'],
        fontSize=10,
        leading=14,
        alignment=TA_JUSTIFY,
    )

    inv_label = inventory_obj.get_inventory_type_display().upper()
    doc_id = f'INV-{inventory_obj.property.code}-{inventory_obj.pk}'
    elements.append(Paragraph('CONSTANCIA DE INVENTARIO', title))
    elements.append(Paragraph(f'{inv_label} &nbsp;·&nbsp; {doc_id}', subtitle))
    elements.append(HRFlowable(width='100%', thickness=1, color=colors.HexColor('#1a1a2e')))
    elements.append(Spacer(1, 0.15 * inch))

    elements.append(Paragraph('<b>I. Datos generales</b>', h2))
    bloque = f"""
    <b>Inmueble:</b> {escape(inventory_obj.property.address)} (código {escape(inventory_obj.property.code)})<br/>
    <b>Tipo:</b> {inventory_obj.property.get_type_display()}<br/>
    <b>Propietario registral:</b> {escape(inventory_obj.property.owner_name)}<br/>
    <b>Arrendatario:</b> {escape(inventory_obj.tenant.get_full_name() or inventory_obj.tenant.email)}<br/>
    <b>Email:</b> {escape(inventory_obj.tenant.email)} &nbsp;|&nbsp; <b>Teléfono:</b> {escape(inventory_obj.tenant.phone or '—')}<br/>
    <b>Fecha de entrega declarada:</b> {inventory_obj.delivery_date.strftime('%d/%m/%Y')}<br/>
    <b>Estado del expediente:</b> {inventory_obj.get_status_display()}
    """
    if inventory_obj.observations:
        bloque += f'<br/><b>Observaciones generales:</b> {escape(inventory_obj.observations)}'
    elements.append(Paragraph(bloque, body))
    elements.append(Spacer(1, 0.2 * inch))

    elements.append(Paragraph('<b>II. Estado de ambientes (resumen)</b>', h2))
    data_tabla = [['#', 'Espacio', 'Estado', 'Observaciones']]
    spaces = list(inventory_obj.spaces.prefetch_related('photos').order_by('order', 'space_name'))
    for i, space in enumerate(spaces, 1):
        name_str = f"{space.space_name} (x{space.quantity})" if getattr(space, 'quantity', 1) > 1 else space.space_name
        data_tabla.append(
            [
                str(i),
                escape(name_str),
                space.get_condition_display(),
                escape((space.observations or '—')[:200] + ('…' if space.observations and len(space.observations) > 200 else '')),
            ]
        )
    tabla = Table(data_tabla, repeatRows=1, colWidths=[0.45 * inch, 1.55 * inch, 1.0 * inch, 3.0 * inch])
    tabla.setStyle(
        TableStyle(
            [
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a1a2e')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 9),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                ('TOPPADDING', (0, 0), (-1, -1), 5),
                ('BOTTOMPADDING', (0, 1), (-1, -1), 5),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#f8f9fa'), colors.white]),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc')),
            ]
        )
    )
    elements.append(tabla)
    elements.append(Spacer(1, 0.25 * inch))

    elements.append(Paragraph('<b>III. Registro fotográfico (evidencias por ambiente)</b>', h2))
    elements.append(
        Paragraph(
            'Las imágenes siguientes forman parte de esta constancia y corresponden al estado registrado '
            'en el momento de elaboración del inventario.',
            body,
        )
    )
    elements.append(Spacer(1, 0.12 * inch))

    max_single_w = 5.0 * inch
    max_single_h = 3.4 * inch
    max_pair_w = 2.45 * inch
    max_pair_h = 2.15 * inch

    for space in spaces:
        photos = list(space.photos.all())
        qty_str = f" (x{space.quantity})" if getattr(space, 'quantity', 1) > 1 else ""
        sub = f'<b>{escape(space.space_name)}</b>{qty_str} — {space.get_condition_display()}'
        if space.observations:
            sub += f'<br/><i>Obs.:</i> {escape(space.observations)}'
        elements.append(Spacer(1, 0.08 * inch))
        elements.append(Paragraph(sub, h2))

        if not photos:
            elements.append(Paragraph('<i>(Sin fotografías adjuntas para este ambiente.)</i>', body))
            continue

        idx = 0
        while idx < len(photos):
            photo_a = photos[idx]
            photo_b = photos[idx + 1] if idx + 1 < len(photos) else None
            if photo_b is not None:
                left = _foto_bloque(photo_a, max_pair_w, max_pair_h, small, idx + 1)
                right = _foto_bloque(photo_b, max_pair_w, max_pair_h, small, idx + 2)
                t = Table([[left, right]], colWidths=[2.55 * inch, 2.55 * inch])
                t.setStyle(
                    TableStyle(
                        [
                            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                            ('LEFTPADDING', (0, 0), (-1, -1), 4),
                            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                        ]
                    )
                )
                elements.append(t)
                elements.append(Spacer(1, 0.14 * inch))
                idx += 2
            else:
                rl_big = _rl_image_from_fieldfile(photo_a.image, max_single_w, max_single_h)
                cap = escape(photo_a.description) if photo_a.description else f'Evidencia fotográfica {idx + 1}'
                if rl_big:
                    elements.append(KeepTogether([rl_big, Spacer(1, 0.06 * inch), Paragraph(cap, small)]))
                else:
                    elements.append(
                        Paragraph(f'<i>{cap}</i> — <b>imagen no disponible</b> en el PDF.', small)
                    )
                elements.append(Spacer(1, 0.14 * inch))
                idx += 1

    if inventory_obj.status == inventory_obj.Status.ACCEPTED and inventory_obj.signed_at:
        elements.append(Spacer(1, 0.15 * inch))
        elements.append(HRFlowable(width='100%', thickness=0.5, color=colors.grey))
        elements.append(
            Paragraph(
                f'<b>Firma digital del arrendatario:</b> aceptado el '
                f'{inventory_obj.signed_at.strftime("%d/%m/%Y a las %H:%M")} (registro en sistema).',
                body,
            )
        )

    elements.append(Spacer(1, 0.35 * inch))
    pie = (
        f'<b>Documento:</b> {doc_id} &nbsp;|&nbsp; <b>Generado:</b> '
        f'{timezone.now().strftime("%d/%m/%Y %H:%M")} &nbsp;|&nbsp; <b>Inventario ID:</b> {inventory_obj.pk}'
    )
    elements.append(Paragraph(pie, small))

    doc.build(elements)
    buffer.seek(0)
    return buffer


def validar_archivo_imagen(archivo):
    name = getattr(archivo, 'name', '') or ''
    ext = name.split('.')[-1].lower() if '.' in name else ''
    if ext not in ('jpg', 'jpeg', 'png'):
        return False, 'Solo JPG o PNG'
    if getattr(archivo, 'size', 0) > 5 * 1024 * 1024:
        return False, 'Máximo 5 MB'
    return True, None


def guardar_thumbnail_foto(photo_instance):
    if not photo_instance.image:
        return
    path = getattr(photo_instance.image, 'path', None)
    if not path:
        return
    try:
        img = Image.open(path)
        img = img.convert('RGB')
        img.thumbnail((320, 320), Image.Resampling.LANCZOS)
        buf = BytesIO()
        img.save(buf, format='JPEG', quality=70)
        buf.seek(0)
        photo_instance.thumbnail.save(
            f'thumb_{os.path.basename(photo_instance.image.name)}',
            ContentFile(buf.read()),
            save=False,
        )
        photo_instance.save(update_fields=['thumbnail'])
    except (OSError, ValueError):
        pass


def notificar_inventario_pendiente_firma(inventory_obj, request):
    from pot.services.email_service import enviar_inventario_pendiente_firma

    enviar_inventario_pendiente_firma(inventory_obj, request)


def registrar_evento_firma_en_propiedad(inventory_obj):
    registrar_evento_propiedad(
        property_obj=inventory_obj.property,
        event_type=PropertyHistory.EventType.INVENTORY_SIGNED,
        description=f'Inventario {inventory_obj.get_inventory_type_display()} firmado por arrendatario',
        created_by=inventory_obj.signed_by,
        related_user=inventory_obj.tenant,
        details={
            'inventory_id': inventory_obj.id,
            'inventory_type': inventory_obj.inventory_type,
            'signed_date': inventory_obj.signed_at.isoformat() if inventory_obj.signed_at else None,
        },
    )


def obtener_plantillas_espacios(property_type):
    if property_type not in dict(Property.Type.choices):
        raise InventoryServiceError('invalid_property_type', 'Tipo de inmueble no válido.')
    names = SPACE_TEMPLATES_BY_PROPERTY_TYPE.get(property_type, [])
    return [
        {
            'space_name': name,
            'suggested_condition': InventorySpace.Condition.GOOD,
            'order': idx,
        }
        for idx, name in enumerate(names)
    ]


def usuario_puede_acceder_inventario(user, inventory):
    if not user or not user.is_authenticated:
        return False
    if user.is_staff_operative():
        return True
    if user.role == CustomUser.Role.TECHNICIAN:
        return True
    return (
        user.role == CustomUser.Role.TENANT
        and inventory.tenant_id == user.pk
        and inventory.property_association is not None
        and inventory.property_association.dissociated_at is None
    )


def _validar_editable(inventory):
    if not inventory.is_editable():
        raise InventoryServiceError('not_editable', 'El inventario no está en edición.')


def crear_inventario_inicial(created_by, *, property_id, tenant_id, delivery_date, observations=None, inventory_type=Inventory.Type.INITIAL):
    prop = Property.objects.filter(pk=property_id).first()
    if not prop:
        raise InventoryServiceError('property_not_found', 'Inmueble no encontrado.')
    tenant = CustomUser.objects.filter(pk=tenant_id, role=CustomUser.Role.TENANT).first()
    if not tenant:
        raise InventoryServiceError('tenant_not_found', 'Arrendatario no encontrado.')

    active_assoc = UserPropertyAssociation.objects.filter(
        property=prop,
        dissociated_at__isnull=True,
    ).first()

    if inventory_type == Inventory.Type.INITIAL:
        if active_assoc and active_assoc.user == tenant:
            if Inventory.objects.filter(
                property_association=active_assoc,
                inventory_type=Inventory.Type.INITIAL,
            ).exists():
                raise InventoryServiceError(
                    'initial_already_exists',
                    'Ya existe un inventario inicial para este inmueble y este arrendatario en la ocupación actual.',
                )

        # Si es inicial, entonces debería asociar al inquilino que se seleccione
        if active_assoc:
            if active_assoc.user != tenant:
                # Desasociar el inquilino anterior
                from django.utils import timezone
                active_assoc.dissociated_at = timezone.now()
                active_assoc.save(update_fields=['dissociated_at'])
                registrar_evento_propiedad(
                    prop,
                    PropertyHistory.EventType.TENANT_DISSOCIATED,
                    f'Desasociado {active_assoc.user.email} por nuevo inventario inicial',
                    created_by=created_by,
                    related_user=active_assoc.user,
                )
                # Asociar al nuevo inquilino
                active_assoc = UserPropertyAssociation.objects.create(
                    user=tenant,
                    property=prop,
                    created_by=created_by,
                )
        else:
            active_assoc = UserPropertyAssociation.objects.create(
                user=tenant,
                property=prop,
                created_by=created_by,
            )
        prop.status = Property.Status.RENTED
        prop.save(update_fields=['status', 'updated_at'])
        assoc_to_link = active_assoc
    elif inventory_type == Inventory.Type.FINAL:
        from pot.services import user_service
        try:
            user_service.desasociar_inmueble_arrendatario(tenant, prop, created_by)
        except Exception:
            pass

        assoc_to_link = UserPropertyAssociation.objects.filter(
            property=prop,
            user=tenant
        ).order_by('-associated_at').first()

        if assoc_to_link:
            if Inventory.objects.filter(
                property_association=assoc_to_link,
                inventory_type=Inventory.Type.FINAL,
            ).exists():
                raise InventoryServiceError(
                    'final_already_exists',
                    'Ya existe un inventario final para este inmueble y este arrendatario en la ocupación actual.',
                )

    try:
        inv = Inventory.objects.create(
            property=prop,
            tenant=tenant,
            property_association=assoc_to_link,
            inventory_type=inventory_type,
            status=Inventory.Status.IN_PROGRESS,
            delivery_date=delivery_date,
            observations=observations or '',
            created_by=created_by,
        )
    except Exception as exc:
        raise InventoryServiceError(
            'duplicate_inventory',
            'Ya existe un inventario para esta combinación inmueble/arrendatario/tipo.',
        ) from exc
    registrar_evento_propiedad(
        prop,
        PropertyHistory.EventType.INVENTORY_CREATED,
        f'Inventario {inv.get_inventory_type_display()} #{inv.pk}',
        created_by=created_by,
        related_user=tenant,
        details={'inventory_id': inv.pk},
    )
    return inv


def actualizar_paso_1(inventory, *, delivery_date=None, observations=None):
    _validar_editable(inventory)
    fields = []
    if delivery_date is not None:
        inventory.delivery_date = delivery_date
        fields.append('delivery_date')
    if observations is not None:
        inventory.observations = observations
        fields.append('observations')
    if fields:
        fields.append('updated_at')
        inventory.save(update_fields=fields)
    return inventory


def agregar_espacio(inventory, *, space_name, condition, observations=None, quantity=1):
    _validar_editable(inventory)
    if condition not in dict(InventorySpace.Condition.choices):
        raise InventoryServiceError('invalid_condition', 'Condición de espacio no válida.')
    space_name = (space_name or '').strip()
    if not space_name:
        raise InventoryServiceError('space_name_required', 'El nombre del espacio es obligatorio.')
    if quantity < 1:
        raise InventoryServiceError('invalid_quantity', 'La cantidad debe ser un número entero positivo.')
    return InventorySpace.objects.create(
        inventory=inventory,
        space_name=space_name,
        condition=condition,
    )


@transaction.atomic
def reemplazar_espacios(inventory, spaces_data):
    _validar_editable(inventory)
    if not isinstance(spaces_data, list):
        raise InventoryServiceError('invalid_spaces', 'Se esperaba una lista de espacios.')
    
    # 1. Map existing spaces by ID for easy lookup
    existing_spaces = {s.id: s for s in inventory.spaces.all()}
    
    # 2. Track IDs of spaces that we should keep/update
    incoming_ids = set()
    for item in spaces_data:
        sp_id = item.get('id')
        if sp_id and sp_id in existing_spaces:
            incoming_ids.add(sp_id)
            
    # 3. Delete spaces that are NOT in the incoming data
    for sp_id, space in list(existing_spaces.items()):
        if sp_id not in incoming_ids:
            space.delete()
            
    # 4. Create or update spaces
    result = []
    for idx, item in enumerate(spaces_data):
        space_name = (item.get('space_name') or '').strip()
        condition = item.get('condition')
        quantity = item.get('quantity', 1)
        sp_id = item.get('id')
        
        if not space_name:
            raise InventoryServiceError('space_name_required', f'Espacio #{idx + 1}: nombre obligatorio.')
        if condition not in dict(InventorySpace.Condition.choices):
            raise InventoryServiceError('invalid_condition', f'Espacio "{space_name}": condición no válida.')
        if quantity < 1:
            raise InventoryServiceError('invalid_quantity', f'Espacio "{space_name}": cantidad debe ser un número entero positivo.')
            
        if sp_id and sp_id in existing_spaces:
            # Update existing space (preserving photos)
            space = existing_spaces[sp_id]
            space.space_name = space_name
            space.condition = condition
            space.observations = item.get('observations') or ''
            space.quantity = quantity
            space.order = item.get('order', idx)
            space.save()
            result.append(space)
        else:
            # Create new space
            space = InventorySpace.objects.create(
                inventory=inventory,
                space_name=space_name,
                condition=condition,
                observations=item.get('observations') or '',
                quantity=quantity,
                order=item.get('order', idx),
            )
            result.append(space)
            
    return result
def eliminar_espacio(space):
    inventory = space.inventory
    _validar_editable(inventory)
    space.delete()


def subir_foto_espacio(space, *, image, description=None, uploaded_by=None):
    _validar_editable(space.inventory)
    ok, err = validar_archivo_imagen(image)
    if not ok:
        raise InventoryServiceError('invalid_image', err)
    photo = InventorySpacePhoto.objects.create(
        space=space,
        image=image,
        description=description or '',
        uploaded_by=uploaded_by,
    )
    try:
        guardar_thumbnail_foto(photo)
    except Exception:
        pass
    return photo


def eliminar_foto(photo):
    _validar_editable(photo.space.inventory)
    photo.delete()


def guardar_borrador(inventory):
    _validar_editable(inventory)
    inventory.save(update_fields=['updated_at'])
    return inventory


def finalizar_inventario(inventory, request):
    if not inventory.is_editable():
        raise InventoryServiceError('invalid_status', 'Solo se puede finalizar un inventario en registro.')
    if inventory.spaces.count() < 1:
        raise InventoryServiceError('spaces_required', 'Agrega al menos un espacio antes de finalizar.')
    
    if inventory.inventory_type == Inventory.Type.FINAL:
        inventory.status = Inventory.Status.PENDING_APPROVAL
    else:
        inventory.status = Inventory.Status.PENDING_SIGNATURE

    inventory.save(update_fields=['status', 'updated_at'])
    if inventory.status == Inventory.Status.PENDING_SIGNATURE:
        notificar_inventario_pendiente_firma(inventory, request)
    return inventory


def firmar_inventario(inventory, tenant, request):
    if inventory.tenant_id != tenant.pk:
        raise InventoryServiceError('not_owner', 'No es el arrendatario de este inventario.')
    if inventory.status != Inventory.Status.PENDING_SIGNATURE:
        raise InventoryServiceError('invalid_status', 'El inventario no está pendiente de firma.')
    if inventory.spaces.count() < 1:
        raise InventoryServiceError('incomplete_review', 'Debe revisar todos los espacios antes de firmar.')
    from pot.services.signature_service import completar_flujo_firma

    completar_flujo_firma(inventory, tenant, request)
    return inventory


def registrar_observaciones_arrendatario(inventory, tenant, observation_text):
    if inventory.tenant_id != tenant.pk:
        raise InventoryServiceError('not_owner', 'No es el arrendatario de este inventario.')
    if inventory.status != Inventory.Status.PENDING_SIGNATURE:
        raise InventoryServiceError('invalid_status', 'El inventario no está pendiente de firma.')
    text = (observation_text or '').strip()
    if not text:
        raise InventoryServiceError('observation_required', 'Las observaciones son obligatorias.')
    InventoryTenantObservation.objects.create(
        inventory=inventory,
        observation_text=text,
        created_by=tenant,
    )
    inventory.status = Inventory.Status.OBSERVATIONS_PENDING
    inventory.save(update_fields=['status', 'updated_at'])
    registrar_evento_propiedad(
        inventory.property,
        PropertyHistory.EventType.TENANT_OBSERVATIONS,
        'Arrendatario registró observaciones',
        created_by=tenant,
        related_user=tenant,
        details={'inventory_id': inventory.pk},
    )
    from pot.services.email_service import enviar_observaciones_inventario_admin

    enviar_observaciones_inventario_admin(inventory, text)
    return inventory


def resolver_observaciones(inventory, request):
    if inventory.status != Inventory.Status.OBSERVATIONS_PENDING:
        raise InventoryServiceError('invalid_status', 'El inventario no tiene observaciones pendientes.')
    inventory.status = Inventory.Status.PENDING_SIGNATURE
    inventory.save(update_fields=['status', 'updated_at'])
    notificar_inventario_pendiente_firma(inventory, request)
    return inventory


def registrar_log_generacion_pdf(inventory, user):
    registrar_evento_propiedad(
        inventory.property,
        PropertyHistory.EventType.INVENTORY_CREATED,
        f'PDF de inventario #{inventory.pk} generado',
        created_by=user,
        related_user=inventory.tenant,
        details={
            'inventory_id': inventory.pk,
            'document': 'inventory_pdf',
            'inventory_type': inventory.inventory_type,
        },
    )
