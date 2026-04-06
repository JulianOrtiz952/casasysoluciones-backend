from django.db import models
from PIL import Image
from io import BytesIO
from django.core.files.uploadedfile import InMemoryUploadedFile
import sys
import os
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
import urllib.request
import urllib.parse

class UserProfile(models.Model):
    ROLES_CHOICES = [
        ('SUPER', 'Super'),
        ('ADMIN', 'Administrador'),
        ('OPERARIO', 'Operario'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    rol = models.CharField(max_length=20, choices=ROLES_CHOICES, default='OPERARIO')

    def __str__(self):
        return f"{self.user.username} - {self.rol}"

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        rol = 'SUPER' if instance.is_superuser else 'OPERARIO'
        UserProfile.objects.create(user=instance, rol=rol)

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
    
    # Nuevos campos
    habitaciones = models.IntegerField(null=True, blank=True)
    banos = models.IntegerField(null=True, blank=True)
    salas = models.IntegerField(null=True, blank=True)
    cocinas = models.IntegerField(null=True, blank=True)
    garajes = models.IntegerField(null=True, blank=True)
    es_comercial = models.BooleanField(default=False)
    
    # Nuevos campos de conjunto
    en_conjunto = models.BooleanField(default=False)
    administracion_incluida = models.BooleanField(default=False)
    valor_administracion = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    enlace_google_maps = models.CharField(max_length=1000, null=True, blank=True)
    
    imagen = models.ImageField(upload_to='inmuebles/', blank=True, null=True)
    estado = models.CharField(max_length=20, choices=ESTADOS_CHOICES, default='en_oferta')
    creado_en = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.direccion == 'Ver enlace de Google Maps adjunto' and self.enlace_google_maps:
            try:
                import re
                import html as html_lib
                req = urllib.request.Request(self.enlace_google_maps, headers={'User-Agent': 'Mozilla/5.0'})
                res = urllib.request.urlopen(req, timeout=10)
                html_content = res.read().decode('utf-8', errors='ignore')
                
                titulo_maps = ""
                subtitulo_maps = ""
                
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
                    # Eliminar " · Google Maps" del subtítulo si existe
                    if " · Google Maps" in subtitulo_maps:
                        subtitulo_maps = subtitulo_maps.replace(" · Google Maps", "")
                    
                    # Lógica para elegir entre título y subtítulo
                    starts_with_num = lambda s: (s[0].isdigit() or s[0] in ['-', '+']) if s else False
                    
                    if starts_with_num(titulo_maps):
                        if starts_with_num(subtitulo_maps):
                            self.direccion = titulo_maps
                        else:
                            # Si el subtitulo tiene algo, lo tomamos
                            self.direccion = subtitulo_maps if subtitulo_maps else titulo_maps
                    else:
                        self.direccion = titulo_maps
                else:
                    # Fallback original
                    final_url = res.geturl()
                    if '/search/' in final_url:
                        query = final_url.split('/search/')[1].split('?')[0].split('/')[0]
                        self.direccion = urllib.parse.unquote_plus(query)
                    elif '/place/' in final_url:
                        query = final_url.split('/place/')[1].split('/')[0]
                        self.direccion = urllib.parse.unquote_plus(query)
            except Exception as e:
                print(f"Error resolviendo enlace de maps: {e}")

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
