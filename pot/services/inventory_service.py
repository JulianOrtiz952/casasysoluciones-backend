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

from pot.models import PropertyHistory
from pot.services.property_service import registrar_evento_propiedad


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
