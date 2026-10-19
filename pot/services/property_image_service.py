from io import BytesIO
from pathlib import Path

from django.core.files.base import ContentFile
from django.utils.text import slugify
from PIL import Image, ImageOps, UnidentifiedImageError


MAX_PROPERTY_IMAGES = 20
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_IMAGE_PIXELS = 50_000_000
MAX_IMAGE_DIMENSION = 1920
WEBP_QUALITY = 82
THUMBNAIL_DIMENSION = 96
THUMBNAIL_QUALITY = 35
ALLOWED_FORMATS = {'JPEG', 'PNG', 'WEBP', 'GIF'}


class PropertyImageValidationError(Exception):
    pass


def optimize_property_image_variants(uploaded_file):
    """Return a web-sized photo and a tiny preview decoded from the upload once."""
    if not uploaded_file:
        return None

    size = getattr(uploaded_file, 'size', 0) or 0
    if size > MAX_UPLOAD_BYTES:
        raise PropertyImageValidationError(
            f'La imagen "{uploaded_file.name}" supera el límite de 12 MB.'
        )

    try:
        uploaded_file.seek(0)
        with Image.open(uploaded_file) as source:
            if source.format not in ALLOWED_FORMATS:
                raise PropertyImageValidationError(
                    f'La imagen "{uploaded_file.name}" debe ser JPG, PNG, WebP o GIF.'
                )
            if source.width * source.height > MAX_IMAGE_PIXELS:
                raise PropertyImageValidationError(
                    f'La imagen "{uploaded_file.name}" tiene una resolución demasiado alta.'
                )

            # GIFs are intentionally flattened to their first frame: property photos
            # do not need animation and this avoids transferring very large files.
            source.seek(0)
            image = ImageOps.exif_transpose(source).copy()
    except PropertyImageValidationError:
        raise
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError) as exc:
        raise PropertyImageValidationError(
            f'El archivo "{uploaded_file.name}" no es una imagen válida.'
        ) from exc
    finally:
        try:
            uploaded_file.seek(0)
        except (AttributeError, OSError):
            pass

    if image.mode not in ('RGB', 'RGBA'):
        image = image.convert('RGBA' if 'transparency' in image.info else 'RGB')

    preview = image.copy()
    preview.thumbnail(
        (THUMBNAIL_DIMENSION, THUMBNAIL_DIMENSION),
        Image.Resampling.LANCZOS,
    )
    image.thumbnail(
        (MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION),
        Image.Resampling.LANCZOS,
    )
    stem = slugify(Path(uploaded_file.name).stem) or 'inmueble'
    output = BytesIO()
    image.save(output, format='WEBP', quality=WEBP_QUALITY, method=4)
    preview_output = BytesIO()
    preview.save(preview_output, format='WEBP', quality=THUMBNAIL_QUALITY, method=4)

    return (
        ContentFile(output.getvalue(), name=f'{stem}.webp'),
        ContentFile(preview_output.getvalue(), name=f'{stem}-preview.webp'),
    )


def optimize_property_image(uploaded_file):
    """Compatibility helper for callers that only need the main variant."""
    variants = optimize_property_image_variants(uploaded_file)
    return variants[0] if variants else None


def prepare_property_images(cover_image, gallery_images, *, existing_count=0):
    gallery_images = list(gallery_images or [])
    incoming_count = (1 if cover_image is not None else 0) + len(gallery_images)
    if existing_count + incoming_count > MAX_PROPERTY_IMAGES:
        raise PropertyImageValidationError(
            f'Cada inmueble puede tener máximo {MAX_PROPERTY_IMAGES} imágenes.'
        )

    optimized_cover = optimize_property_image_variants(cover_image) if cover_image is not None else None
    optimized_gallery = [optimize_property_image_variants(image) for image in gallery_images]
    return optimized_cover, optimized_gallery
