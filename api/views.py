from django.contrib.auth import get_user_model
from rest_framework import permissions, status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import HistorialAlquiler, Inmueble, Inquilino
from .serializers import (
    ChangePasswordSerializer,
    CustomTokenObtainPairSerializer,
    HistorialAlquilerSerializer,
    InmuebleSerializer,
    InquilinoSerializer,
    UserSerializer,
)

User = get_user_model()


class IsSuperUser(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.is_superuser


class IsAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and (request.user.role == 'ADMIN' or request.user.is_superuser)


class IsStaffOperative(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and (request.user.role in ('ADMIN', 'ASSISTANT') or request.user.is_superuser)


class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer


class IsAdminOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user and request.user.is_authenticated


class InmuebleViewSet(viewsets.ModelViewSet):
    queryset = Inmueble.objects.all().order_by('-creado_en')
    serializer_class = InmuebleSerializer
    permission_classes = [permissions.AllowAny]

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
        from .models import ImagenInmueble

        imagenes = request.FILES.getlist('imagenes')

        if request.data.get('reemplazar_imagenes') == 'true':
            inmueble.imagenes.all().delete()

        if imagenes:
            portada_index_str = request.data.get('portada_index', '0')
            portada_index = int(portada_index_str) if portada_index_str.isdigit() else 0

            for idx, img in enumerate(imagenes):
                es_portada = idx == portada_index
                ImagenInmueble.objects.create(
                    inmueble=inmueble,
                    imagen=img,
                    es_portada=es_portada,
                )

            if not inmueble.imagenes.filter(es_portada=True).exists() and inmueble.imagenes.exists():
                first_img = inmueble.imagenes.first()
                first_img.es_portada = True
                first_img.save()


class InquilinoViewSet(viewsets.ModelViewSet):
    queryset = Inquilino.objects.all().order_by('-creado_en')
    serializer_class = InquilinoSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        try:
            from pot.models import CustomUser
            tenant_users = CustomUser.objects.filter(role='TENANT')
            for user in tenant_users:
                nombre = f"{user.first_name} {user.last_name}".strip()
                if not nombre:
                    nombre = user.email.split('@')[0]
                    
                identificacion = user.document_number
                if not identificacion:
                    identificacion = user.public_code or f"USR-{user.pk:05d}"
                
                inquilino = Inquilino.objects.filter(email=user.email).first()
                if inquilino:
                    inquilino.nombre = nombre
                    inquilino.telefono = user.phone or ''
                    if not Inquilino.objects.filter(identificacion=identificacion).exclude(pk=inquilino.pk).exists():
                        inquilino.identificacion = identificacion
                    inquilino.save()
                else:
                    if Inquilino.objects.filter(identificacion=identificacion).exists():
                        identificacion = f"DUP-{user.pk}-{identificacion}"[:50]
                    Inquilino.objects.create(
                        nombre=nombre,
                        email=user.email,
                        telefono=user.phone or '',
                        identificacion=identificacion
                    )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error syncing tenants in get_queryset: {e}", exc_info=True)

        return Inquilino.objects.all().order_by('-creado_en')


class HistorialAlquilerViewSet(viewsets.ModelViewSet):
    queryset = HistorialAlquiler.objects.all().order_by('-fecha_inicio')
    serializer_class = HistorialAlquilerSerializer
    permission_classes = [permissions.AllowAny]


class ChangePasswordView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        ser = ChangePasswordSerializer(data=request.data)
        if not ser.is_valid():
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)
        email = ser.validated_data['email']
        old_password = ser.validated_data['old_password']
        new_password = ser.validated_data['new_password']
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return Response({'error': 'Usuario no encontrado.'}, status=status.HTTP_404_NOT_FOUND)
        if not user.check_password(old_password):
            return Response({'error': 'La contraseña actual es incorrecta.'}, status=status.HTTP_400_BAD_REQUEST)
        user.set_password(new_password)
        user.password_changed = True
        user.save()
        return Response({'message': 'Contraseña actualizada exitosamente.'}, status=status.HTTP_200_OK)


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all().order_by('-date_joined')
    serializer_class = UserSerializer
    permission_classes = [IsStaffOperative]

    def get_queryset(self):
        qs = User.objects.all().order_by('-date_joined')
        role = self.request.query_params.get('role')
        if role:
            qs = qs.filter(role=role)
        return qs
