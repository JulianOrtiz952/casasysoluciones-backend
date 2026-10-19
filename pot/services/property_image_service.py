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
ALLOWED_FORMATS = {'JPEG', 'PNG', 'WEBP', 'GIF'}


class PropertyImageValidationError(Exception):
    pass


def optimize_property_image(uploaded_file):
    """Validate and normalize an uploaded property photo for fast web delivery."""
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

    image.thumbnail(
        (MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION),
        Image.Resampling.LANCZOS,
    )
    if image.mode not in ('RGB', 'RGBA'):
        image = image.convert('RGBA' if 'transparency' in image.info else 'RGB')

    output = BytesIO()
    image.save(output, format='WEBP', quality=WEBP_QUALITY, method=4)
    output.seek(0)

    stem = slugify(Path(uploaded_file.name).stem) or 'inmueble'
    return ContentFile(output.read(), name=f'{stem}.webp')


def prepare_property_images(cover_image, gallery_images, *, existing_count=0):
    gallery_images = list(gallery_images or [])
    incoming_count = (1 if cover_image is not None else 0) + len(gallery_images)
    if existing_count + incoming_count > MAX_PROPERTY_IMAGES:
        raise PropertyImageValidationError(
            f'Cada inmueble puede tener máximo {MAX_PROPERTY_IMAGES} imágenes.'
        )

    optimized_cover = optimize_property_image(cover_image) if cover_image is not None else None
    optimized_gallery = [optimize_property_image(image) for image in gallery_images]
    return optimized_cover, optimized_gallery
