from rest_framework import viewsets, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from .models import Inmueble, Inquilino, HistorialAlquiler, ImagenInmueble
from .serializers import InmuebleSerializer, InquilinoSerializer, HistorialAlquilerSerializer
from django.contrib.auth.models import User

class IsAdminOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        # Allow reading to anyone
        if request.method in permissions.SAFE_METHODS:
            return True
        # For writing, user must be authenticated
        return request.user and request.user.is_authenticated

class InmuebleViewSet(viewsets.ModelViewSet):
    queryset = Inmueble.objects.all().order_by('-creado_en')
    serializer_class = InmuebleSerializer
    permission_classes = [permissions.AllowAny] # Temporalmente AllowAny para poder probar sin Token

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        inmueble = Inmueble.objects.get(id=response.data['id'])
        self._handle_images(request, inmueble)
        return Response(InmuebleSerializer(inmueble).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        response = super().update(request, *args, **kwargs)
        inmueble = self.get_object()
        self._handle_images(request, inmueble)
        return Response(InmuebleSerializer(inmueble).data)

    def _handle_images(self, request, inmueble):
        imagenes = request.FILES.getlist('imagenes')
        
        # Eliminar las anteriores si se marca el flag
        if request.data.get('reemplazar_imagenes') == 'true':
            inmueble.imagenes.all().delete()

        # Solo si vienen imagenes nuevas las procesamos
        if imagenes:
            # Obtener indice de la portada
            portada_index_str = request.data.get('portada_index', '0')
            portada_index = int(portada_index_str) if portada_index_str.isdigit() else 0

            for idx, img in enumerate(imagenes):
                es_portada = (idx == portada_index)
                
                # Para evitar error de compresión con InMemoryUploadedFile si se intenta re-guardar
                ImagenInmueble.objects.create(
                    inmueble=inmueble,
                    imagen=img,
                    es_portada=es_portada
                )
            
            # Verificamos si existe portada. Si no existe, seteamos la recien subida o alguna.
            if not inmueble.imagenes.filter(es_portada=True).exists() and inmueble.imagenes.exists():
                first_img = inmueble.imagenes.first()
                first_img.es_portada = True
                first_img.save()

class InquilinoViewSet(viewsets.ModelViewSet):
    queryset = Inquilino.objects.all().order_by('-creado_en')
    serializer_class = InquilinoSerializer
    permission_classes = [permissions.AllowAny]

class HistorialAlquilerViewSet(viewsets.ModelViewSet):
    queryset = HistorialAlquiler.objects.all().order_by('-fecha_inicio')
    serializer_class = HistorialAlquilerSerializer
    permission_classes = [permissions.AllowAny]


class ChangePasswordView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        username = request.data.get("username", "admin")
        old_password = request.data.get("old_password")
        new_password = request.data.get("new_password")
        
        try:
            user = User.objects.get(username=username)
            if not user.check_password(old_password):
                return Response({"error": "La contraseña actual es incorrecta."}, status=status.HTTP_400_BAD_REQUEST)
            user.set_password(new_password)
            user.save()
            return Response({"message": "Contraseña actualizada exitosamente."}, status=status.HTTP_200_OK)
        except User.DoesNotExist:
            return Response({"error": "Usuario no encontrado."}, status=status.HTTP_404_NOT_FOUND)
