from django.core.management.base import BaseCommand

from pot.models import PropertyImage
from pot.services.property_image_service import (
    PropertyImageValidationError,
    optimize_property_image_variants,
)


class Command(BaseCommand):
    help = 'Genera previews livianos para fotografías de inmuebles existentes.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=None)
        parser.add_argument('--force', action='store_true')

    def handle(self, *args, **options):
        images = PropertyImage.objects.exclude(image='').order_by('id')
        if not options['force']:
            images = images.filter(thumbnail__isnull=True)
        if options['limit'] is not None:
            images = images[:max(options['limit'], 0)]

        generated = 0
        skipped = 0
        for property_image in images.iterator():
            try:
                with property_image.image.open('rb') as source:
                    _, thumbnail = optimize_property_image_variants(source)
                property_image.thumbnail.save(thumbnail.name, thumbnail, save=True)
                generated += 1
            except (PropertyImageValidationError, OSError, ValueError) as exc:
                skipped += 1
                self.stderr.write(
                    self.style.WARNING(f'Imagen {property_image.pk} omitida: {exc}')
                )

        self.stdout.write(
            self.style.SUCCESS(
                f'Previews generados: {generated}. Imágenes omitidas: {skipped}.'
            )
        )
