from django.db import models
from PIL import Image
from io import BytesIO
from django.core.files.uploadedfile import InMemoryUploadedFile
import sys
import os

class Inmueble(models.Model):
    ESTADOS_CHOICES = [
        ('arrendada', 'Arrendada'),
        ('en_oferta', 'En oferta'),
        ('en_mantenimiento', 'En mantenimiento'),
        ('inactiva', 'Inactiva'),
    ]

    titulo = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True)
    precio = models.DecimalField(max_digits=12, decimal_places=2)
    direccion = models.CharField(max_length=255)
    imagen = models.ImageField(upload_to='inmuebles/', blank=True, null=True)
    estado = models.CharField(max_length=20, choices=ESTADOS_CHOICES, default='en_oferta')
    creado_en = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        # Mantenemos esto si hay una imagen principal legacy
        if self.imagen and not getattr(self, '_image_compressed', False):
            if hasattr(self.imagen, 'file') and not hasattr(self.imagen.file, 'url'):
                try:
                    img = Image.open(self.imagen)
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                    output = BytesIO()
                    img.save(output, format='JPEG', quality=65, optimize=True)
                    output.seek(0)
                    filename = os.path.splitext(self.imagen.name)[0] + '.jpg'
                    self.imagen = InMemoryUploadedFile(
                        output, 'ImageField', filename, 'image/jpeg', len(output.getvalue()), None
                    )
                    self._image_compressed = True
                except Exception as e:
                    print(f"Error comprimiendo la imagen principal: {e}")
        
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.titulo} - {self.direccion}"

class ImagenInmueble(models.Model):
    inmueble = models.ForeignKey(Inmueble, on_delete=models.CASCADE, related_name='imagenes')
    imagen = models.ImageField(upload_to='inmuebles_galeria/')
    es_portada = models.BooleanField(default=False)
    creado_en = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.imagen and not getattr(self, '_image_compressed', False):
            if hasattr(self.imagen, 'file') and not hasattr(self.imagen.file, 'url'):
                try:
                    img = Image.open(self.imagen)
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                    output = BytesIO()
                    img.save(output, format='JPEG', quality=65, optimize=True)
                    output.seek(0)
                    filename = os.path.splitext(self.imagen.name)[0] + '.jpg'
                    self.imagen = InMemoryUploadedFile(
                        output, 'ImageField', filename, 'image/jpeg', len(output.getvalue()), None
                    )
                    self._image_compressed = True
                except Exception as e:
                    print(f"Error comprimiendo imagen galería: {e}")
        
        # Si esta es portada, quitar el flag a las demás del mismo inmueble
        if self.es_portada:
            ImagenInmueble.objects.filter(inmueble=self.inmueble, es_portada=True).update(es_portada=False)
            
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Imagen de {self.inmueble.titulo} - {'Portada' if self.es_portada else 'Galería'}"

class Inquilino(models.Model):
    nombre = models.CharField(max_length=200)
    email = models.EmailField(unique=True)
    telefono = models.CharField(max_length=20)
    identificacion = models.CharField(max_length=50, unique=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nombre

class HistorialAlquiler(models.Model):
    inmueble = models.ForeignKey(Inmueble, on_delete=models.CASCADE, related_name='historiales')
    inquilino = models.ForeignKey(Inquilino, on_delete=models.CASCADE, related_name='historiales')
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField(null=True, blank=True)
    esta_activo = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.inquilino.nombre} en {self.inmueble.titulo}"
