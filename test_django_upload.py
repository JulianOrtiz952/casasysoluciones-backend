import os
import django
from django.core.files.uploadedfile import SimpleUploadedFile

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from api.models import Inmueble

with open("sample.jpg", "rb") as f:
    sample_data = f.read()

inmueble = Inmueble(
    titulo='Casa en React',
    descripcion='Probando subida a R2 con Django Storages compresión',
    precio='200.00',
    direccion='Sector React',
    estado='en_oferta'
)

inmueble.imagen.save('react.jpg', SimpleUploadedFile('react.jpg', sample_data, content_type='image/jpeg'))
inmueble.save()

print("Inmueble Guardado:")
print("URL:", inmueble.imagen.url)
