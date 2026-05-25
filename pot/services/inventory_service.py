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
    LeaseContract,
    Property,
    PropertyHistory,
    UserPropertyAssociation,
)
from pot.services.contract_service import obtener_o_crear_contrato_activo, tickets_del_contrato
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
        data_tabla.append(
            [
                str(i),
                escape(space.space_name),
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
        sub = f'<b>{escape(space.space_name)}</b> — {space.get_condition_display()}'
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
    return user.role == CustomUser.Role.TENANT and inventory.tenant_id == user.pk


def _validar_editable(inventory):
    if not inventory.is_editable():
        raise InventoryServiceError('not_editable', 'El inventario no está en edición.')


def crear_inventario_inicial(created_by, *, property_id, tenant_id, delivery_date, observations=None):
    prop = Property.objects.filter(pk=property_id).first()
    if not prop:
        raise InventoryServiceError('property_not_found', 'Inmueble no encontrado.')
    tenant = CustomUser.objects.filter(pk=tenant_id, role=CustomUser.Role.TENANT).first()
    if not tenant:
        raise InventoryServiceError('tenant_not_found', 'Arrendatario no encontrado.')
    if Inventory.objects.filter(
        property=prop,
        inventory_type=Inventory.Type.INITIAL,
        status=Inventory.Status.ACCEPTED,
    ).exists():
        raise InventoryServiceError(
            'initial_already_accepted',
            'Ya existe un inventario inicial aceptado para este inmueble.',
        )
    if not UserPropertyAssociation.objects.filter(
        user=tenant,
        property=prop,
        dissociated_at__isnull=True,
    ).exists():
        raise InventoryServiceError(
            'tenant_not_associated',
            'El arrendatario no está asociado activamente a este inmueble.',
        )
    try:
        inv = Inventory.objects.create(
            property=prop,
            tenant=tenant,
            inventory_type=Inventory.Type.INITIAL,
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
        f'Inventario inicial #{inv.pk}',
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


def agregar_espacio(inventory, *, space_name, condition, observations=None):
    _validar_editable(inventory)
    if condition not in dict(InventorySpace.Condition.choices):
        raise InventoryServiceError('invalid_condition', 'Condición de espacio no válida.')
    space_name = (space_name or '').strip()
    if not space_name:
        raise InventoryServiceError('space_name_required', 'El nombre del espacio es obligatorio.')
    return InventorySpace.objects.create(
        inventory=inventory,
        space_name=space_name,
        condition=condition,
        observations=observations or '',
        order=inventory.spaces.count(),
    )


@transaction.atomic
def reemplazar_espacios(inventory, spaces_data):
    _validar_editable(inventory)
    if not isinstance(spaces_data, list):
        raise InventoryServiceError('invalid_spaces', 'Se esperaba una lista de espacios.')
    inventory.spaces.all().delete()
    created = []
    for idx, item in enumerate(spaces_data):
        space_name = (item.get('space_name') or '').strip()
        condition = item.get('condition')
        if not space_name:
            raise InventoryServiceError('space_name_required', f'Espacio #{idx + 1}: nombre obligatorio.')
        if condition not in dict(InventorySpace.Condition.choices):
            raise InventoryServiceError('invalid_condition', f'Espacio "{space_name}": condición no válida.')
        created.append(
            InventorySpace.objects.create(
                inventory=inventory,
                space_name=space_name,
                condition=condition,
                observations=item.get('observations') or '',
                order=item.get('order', idx),
            )
        )
    return created


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
    if inventory.status != Inventory.Status.IN_PROGRESS:
        raise InventoryServiceError('invalid_status', 'Solo se puede finalizar un inventario en registro.')
    if inventory.spaces.count() < 1:
        raise InventoryServiceError('spaces_required', 'Agrega al menos un espacio antes de finalizar.')
    inventory.status = Inventory.Status.PENDING_SIGNATURE
    inventory.save(update_fields=['status', 'updated_at'])
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


CONDITION_RANK = {
    InventorySpace.Condition.GOOD: 0,
    InventorySpace.Condition.REGULAR: 1,
    InventorySpace.Condition.BAD: 2,
}

CONDITION_LABELS = dict(InventorySpace.Condition.choices)


def _normalize_space_name(name):
    return (name or '').strip().lower()


def obtener_inventario_inicial_aceptado(property_obj, tenant):
    return (
        Inventory.objects.filter(
            property=property_obj,
            tenant=tenant,
            inventory_type=Inventory.Type.INITIAL,
            status=Inventory.Status.ACCEPTED,
        )
        .order_by('-signed_at', '-created_at')
        .first()
    )


@transaction.atomic
def crear_inventario_final(created_by, *, property_id, tenant_id, delivery_date, observations=None):
    prop = Property.objects.filter(pk=property_id).first()
    if not prop:
        raise InventoryServiceError('property_not_found', 'Inmueble no encontrado.')
    tenant = CustomUser.objects.filter(pk=tenant_id, role=CustomUser.Role.TENANT).first()
    if not tenant:
        raise InventoryServiceError('tenant_not_found', 'Arrendatario no encontrado.')
    if not UserPropertyAssociation.objects.filter(
        user=tenant,
        property=prop,
        dissociated_at__isnull=True,
    ).exists():
        raise InventoryServiceError(
            'tenant_not_associated',
            'El arrendatario no está asociado activamente a este inmueble.',
        )

    initial = obtener_inventario_inicial_aceptado(prop, tenant)
    if not initial:
        raise InventoryServiceError(
            'initial_not_accepted',
            'Se requiere un inventario inicial aceptado para este inmueble y arrendatario.',
        )

    if Inventory.objects.filter(
        property=prop,
        tenant=tenant,
        inventory_type=Inventory.Type.FINAL,
    ).exists():
        raise InventoryServiceError(
            'final_already_exists',
            'Ya existe un inventario final para este inmueble y arrendatario.',
        )

    try:
        inv = Inventory.objects.create(
            property=prop,
            tenant=tenant,
            inventory_type=Inventory.Type.FINAL,
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

    initial_spaces = list(initial.spaces.order_by('order', 'space_name'))
    for space in initial_spaces:
        InventorySpace.objects.create(
            inventory=inv,
            space_name=space.space_name,
            condition=space.condition,
            observations=space.observations or '',
            order=space.order,
        )

    obtener_o_crear_contrato_activo(prop, tenant, final_inventory=inv)

    registrar_evento_propiedad(
        prop,
        PropertyHistory.EventType.INVENTORY_CREATED,
        f'Inventario final #{inv.pk} (precargado desde inicial #{initial.pk})',
        created_by=created_by,
        related_user=tenant,
        details={
            'inventory_id': inv.pk,
            'inventory_type': inv.inventory_type,
            'initial_inventory_id': initial.pk,
            'spaces_preloaded': len(initial_spaces),
        },
    )
    return inv


def _clasificar_cambio_condicion(initial_condition, final_condition):
    if not initial_condition:
        return 'ONLY_FINAL', False
    if not final_condition:
        return 'ONLY_INITIAL', False
    initial_rank = CONDITION_RANK.get(initial_condition, 0)
    final_rank = CONDITION_RANK.get(final_condition, 0)
    if final_rank > initial_rank:
        return 'DETERIORATED', True
    if final_rank < initial_rank:
        return 'IMPROVED', False
    return 'UNCHANGED', False


def comparar_inventario_final(final_inventory):
    if final_inventory.inventory_type != Inventory.Type.FINAL:
        raise InventoryServiceError(
            'not_final_inventory',
            'La comparación solo aplica a inventarios finales.',
        )

    initial = obtener_inventario_inicial_aceptado(final_inventory.property, final_inventory.tenant)
    if not initial:
        raise InventoryServiceError(
            'initial_not_accepted',
            'No hay inventario inicial aceptado para comparar.',
        )

    initial_by_name = {
        _normalize_space_name(s.space_name): s
        for s in initial.spaces.order_by('order', 'space_name')
    }
    final_by_name = {
        _normalize_space_name(s.space_name): s
        for s in final_inventory.spaces.order_by('order', 'space_name')
    }

    all_names = sorted(set(initial_by_name) | set(final_by_name))
    rows = []
    summary = {
        'total_spaces_compared': 0,
        'deteriorated_count': 0,
        'unchanged_count': 0,
        'improved_count': 0,
        'only_in_initial_count': 0,
        'only_in_final_count': 0,
    }

    for key in all_names:
        initial_space = initial_by_name.get(key)
        final_space = final_by_name.get(key)
        initial_condition = initial_space.condition if initial_space else None
        final_condition = final_space.condition if final_space else None
        change_type, highlight = _clasificar_cambio_condicion(initial_condition, final_condition)

        if change_type == 'ONLY_INITIAL':
            summary['only_in_initial_count'] += 1
        elif change_type == 'ONLY_FINAL':
            summary['only_in_final_count'] += 1
        else:
            summary['total_spaces_compared'] += 1
            if change_type == 'DETERIORATED':
                summary['deteriorated_count'] += 1
            elif change_type == 'IMPROVED':
                summary['improved_count'] += 1
            else:
                summary['unchanged_count'] += 1

        display_name = (
            (final_space.space_name if final_space else None)
            or (initial_space.space_name if initial_space else key)
        )
        rows.append(
            {
                'space_name': display_name,
                'initial_condition': initial_condition,
                'final_condition': final_condition,
                'initial_condition_display': CONDITION_LABELS.get(initial_condition) if initial_condition else None,
                'final_condition_display': CONDITION_LABELS.get(final_condition) if final_condition else None,
                'change_type': change_type,
                'highlight': highlight,
                'initial_observations': (initial_space.observations or '') if initial_space else '',
                'final_observations': (final_space.observations or '') if final_space else '',
            }
        )

    contract = LeaseContract.objects.filter(final_inventory=final_inventory).first()
    if not contract:
        contract = LeaseContract.objects.filter(
            property=final_inventory.property,
            tenant=final_inventory.tenant,
            status=LeaseContract.Status.ACTIVE,
        ).first()
    if not contract:
        contract = obtener_o_crear_contrato_activo(
            final_inventory.property,
            final_inventory.tenant,
            final_inventory=final_inventory,
        )

    return {
        'final_inventory_id': final_inventory.pk,
        'initial_inventory_id': initial.pk,
        'contract_id': contract.pk,
        'property': {
            'id': final_inventory.property_id,
            'code': final_inventory.property.code,
            'address': final_inventory.property.address,
        },
        'tenant': {
            'id': final_inventory.tenant_id,
            'email': final_inventory.tenant.email,
            'full_name': final_inventory.tenant.get_full_name(),
        },
        'summary': summary,
        'rows': rows,
    }


def generar_pdf_paz_y_salvo(final_inventory, user):
    if final_inventory.inventory_type != Inventory.Type.FINAL:
        raise InventoryServiceError(
            'not_final_inventory',
            'El documento de paz y salvo solo aplica a inventarios finales.',
        )
    comparison = comparar_inventario_final(final_inventory)
    contract = LeaseContract.objects.filter(
        property=final_inventory.property,
        tenant=final_inventory.tenant,
        status=LeaseContract.Status.ACTIVE,
    ).first()
    if not contract:
        contract = obtener_o_crear_contrato_activo(
            final_inventory.property,
            final_inventory.tenant,
            final_inventory=final_inventory,
        )
    tickets = list(tickets_del_contrato(contract))

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
        name='ClosureTitle',
        parent=styles['Heading1'],
        fontSize=15,
        leading=18,
        alignment=TA_CENTER,
        spaceAfter=6,
        textColor=colors.HexColor('#1a1a2e'),
    )
    subtitle = ParagraphStyle(
        name='ClosureSub',
        parent=styles['Normal'],
        fontSize=10,
        alignment=TA_CENTER,
        textColor=colors.HexColor('#444444'),
        spaceAfter=14,
    )
    h2 = ParagraphStyle(
        name='ClosureH2',
        parent=styles['Heading2'],
        fontSize=12,
        leading=15,
        spaceBefore=10,
        spaceAfter=8,
        textColor=colors.HexColor('#16213e'),
    )
    body = ParagraphStyle(
        name='ClosureBody',
        parent=styles['Normal'],
        fontSize=10,
        leading=14,
        alignment=TA_JUSTIFY,
    )
    small = ParagraphStyle(
        name='ClosureSmall',
        parent=styles['Normal'],
        fontSize=8,
        leading=10,
        textColor=colors.HexColor('#555555'),
        alignment=TA_CENTER,
    )

    doc_id = f'PYS-{final_inventory.property.code}-{final_inventory.pk}'
    elements.append(Paragraph('PAZ Y SALVO — ACTA DE ENTREGA FINAL', title))
    elements.append(Paragraph(f'{doc_id} &nbsp;·&nbsp; Contrato #{contract.pk}', subtitle))
    elements.append(HRFlowable(width='100%', thickness=1, color=colors.HexColor('#1a1a2e')))
    elements.append(Spacer(1, 0.15 * inch))

    prop = final_inventory.property
    tenant = final_inventory.tenant
    elements.append(Paragraph('<b>I. Datos del arriendo</b>', h2))
    bloque = f"""
    <b>Inmueble:</b> {escape(prop.address)} (código {escape(prop.code)})<br/>
    <b>Arrendatario:</b> {escape(tenant.get_full_name() or tenant.email)}<br/>
    <b>Email:</b> {escape(tenant.email)}<br/>
    <b>Periodo contrato:</b> {contract.start_date.strftime('%d/%m/%Y')}
    — {contract.end_date.strftime('%d/%m/%Y') if contract.end_date else 'vigente'}<br/>
    <b>Fecha entrega final:</b> {final_inventory.delivery_date.strftime('%d/%m/%Y')}<br/>
    <b>Inventario inicial ID:</b> {comparison['initial_inventory_id']} &nbsp;|&nbsp;
    <b>Inventario final ID:</b> {comparison['final_inventory_id']}
    """
    if final_inventory.observations:
        bloque += f'<br/><b>Observaciones:</b> {escape(final_inventory.observations)}'
    elements.append(Paragraph(bloque, body))
    elements.append(Spacer(1, 0.2 * inch))

    elements.append(Paragraph('<b>II. Comparativo inicial vs final</b>', h2))
    sum_txt = (
        f"Espacios comparados: {comparison['summary']['total_spaces_compared']} &nbsp;|&nbsp; "
        f"Deterioro: {comparison['summary']['deteriorated_count']} &nbsp;|&nbsp; "
        f"Sin cambio: {comparison['summary']['unchanged_count']} &nbsp;|&nbsp; "
        f"Mejora: {comparison['summary']['improved_count']}"
    )
    elements.append(Paragraph(sum_txt, body))
    elements.append(Spacer(1, 0.1 * inch))

    data_tabla = [['Espacio', 'Inicial', 'Final', 'Cambio']]
    for row in comparison['rows']:
        change_label = {
            'DETERIORATED': 'Deterioro',
            'UNCHANGED': 'Sin cambio',
            'IMPROVED': 'Mejora',
            'ONLY_INITIAL': 'Solo en inicial',
            'ONLY_FINAL': 'Solo en final',
        }.get(row['change_type'], row['change_type'])
        data_tabla.append(
            [
                escape(row['space_name']),
                row['initial_condition_display'] or '—',
                row['final_condition_display'] or '—',
                change_label,
            ]
        )
    tabla = Table(data_tabla, repeatRows=1, colWidths=[1.8 * inch, 1.2 * inch, 1.2 * inch, 1.8 * inch])
    style_commands = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a1a2e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]
    for i, row in enumerate(comparison['rows'], start=1):
        if row['highlight']:
            style_commands.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#fde8e8')))
    tabla.setStyle(TableStyle(style_commands))
    elements.append(tabla)
    elements.append(Spacer(1, 0.2 * inch))

    elements.append(Paragraph('<b>III. Resumen de tickets del contrato</b>', h2))
    if tickets:
        ticket_data = [['Radicado', 'Tipo', 'Prioridad', 'Estado', 'Fecha']]
        for t in tickets:
            ticket_data.append(
                [
                    escape(t.public_code or str(t.pk)),
                    t.get_damage_type_display(),
                    t.get_priority_display(),
                    t.get_status_display(),
                    t.created_at.strftime('%d/%m/%Y'),
                ]
            )
        ttabla = Table(ticket_data, repeatRows=1, colWidths=[1.1 * inch, 1.5 * inch, 1.0 * inch, 1.2 * inch, 0.9 * inch])
        ttabla.setStyle(
            TableStyle(
                [
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#16213e')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 8),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ]
            )
        )
        elements.append(ttabla)
    else:
        elements.append(Paragraph('<i>No se registraron tickets durante el periodo del contrato.</i>', body))

    elements.append(Spacer(1, 0.25 * inch))
    elements.append(Paragraph('<b>IV. Declaración</b>', h2))
    elements.append(
        Paragraph(
            'Con la firma de las partes, se deja constancia del estado del inmueble al momento de la entrega final, '
            'del comparativo frente al inventario inicial y del resumen de solicitudes de mantenimiento atendidas '
            'durante la vigencia del contrato, en los términos del reglamento de arrendamiento de Casas y Soluciones.',
            body,
        )
    )
    elements.append(Spacer(1, 0.4 * inch))
    firma_tabla = Table(
        [
            ['_________________________', '_________________________'],
            ['Representante inmobiliaria', 'Arrendatario'],
            ['', escape(tenant.get_full_name() or tenant.email)],
        ],
        colWidths=[2.6 * inch, 2.6 * inch],
    )
    firma_tabla.setStyle(
        TableStyle(
            [
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('TOPPADDING', (0, 2), (-1, 2), 12),
            ]
        )
    )
    elements.append(firma_tabla)
    elements.append(Spacer(1, 0.3 * inch))
    elements.append(
        Paragraph(
            f'<b>Documento:</b> {doc_id} &nbsp;|&nbsp; <b>Generado:</b> '
            f'{timezone.now().strftime("%d/%m/%Y %H:%M")} &nbsp;|&nbsp; <b>Por:</b> {escape(user.email)}',
            small,
        )
    )

    doc.build(elements)
    buffer.seek(0)
    return buffer


def registrar_log_paz_y_salvo(final_inventory, user):
    registrar_evento_propiedad(
        final_inventory.property,
        PropertyHistory.EventType.INVENTORY_CREATED,
        f'Paz y salvo (inventario final #{final_inventory.pk}) generado',
        created_by=user,
        related_user=final_inventory.tenant,
        details={
            'inventory_id': final_inventory.pk,
            'document': 'closure_clearance_pdf',
            'inventory_type': final_inventory.inventory_type,
        },
    )
