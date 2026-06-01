from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from api.v1.exceptions import APIError
from api.v1.serializers.auth import (
    FirstPasswordChangeSerializer,
    LoginSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    UserMeSerializer,
)
from pot.models import CustomUser
from pot.services.auth_service import (
    buscar_usuario_por_credencial,
    generar_reset_token,
    limpiar_intentos_fallidos,
    registrar_intento_fallido,
    verificar_intento_login,
)
from pot.services.email_service import enviar_reset_password


def _issue_tokens(user):
    refresh = RefreshToken.for_user(user)
    refresh['email'] = user.email
    refresh['role'] = user.role
    refresh['public_code'] = user.public_code or ''
    access = refresh.access_token
    access['email'] = user.email
    access['role'] = user.role
    access['public_code'] = user.public_code or ''
    return {
        'access': str(access),
        'refresh': str(refresh),
    }


class LoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identifier = serializer.validated_data['identifier']
        password = serializer.validated_data['password']

        user = buscar_usuario_por_credencial(identifier)
        if not user:
            raise APIError(
                'invalid_credentials',
                'Credenciales incorrectas.',
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        ok, locked_until = verificar_intento_login(user)
        if not ok:
            raise APIError(
                'account_locked',
                f'Cuenta bloqueada por intentos fallidos. Intenta después de {locked_until:%H:%M}.',
                status_code=status.HTTP_403_FORBIDDEN,
                details={'locked_until': locked_until.isoformat()},
            )

        if not user.is_active:
            raise APIError(
                'account_inactive',
                'Usuario desactivado.',
                status_code=status.HTTP_403_FORBIDDEN,
            )

        authenticated = authenticate(request, username=user.email, password=password)
        if not authenticated:
            attempts = registrar_intento_fallido(user)
            limit = getattr(settings, 'LOGIN_ATTEMPT_LIMIT', 5)
            remaining = max(0, limit - attempts)
            raise APIError(
                'invalid_credentials',
                'Credenciales incorrectas.',
                status_code=status.HTTP_401_UNAUTHORIZED,
                details={'remaining_attempts': remaining},
            )

        limpiar_intentos_fallidos(user)
        tokens = _issue_tokens(user)
        return Response(
            {
                **tokens,
                'user': UserMeSerializer(user).data,
            },
            status=status.HTTP_200_OK,
        )


class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get('refresh')
        if refresh_token:
            try:
                token = RefreshToken(refresh_token)
                token.blacklist()
            except Exception:
                pass
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(UserMeSerializer(request.user).data)

    def patch(self, request):
        user = request.user
        
        first_name = request.data.get('first_name')
        last_name = request.data.get('last_name')
        phone = request.data.get('phone')
        document_type = request.data.get('document_type')
        document_number = request.data.get('document_number')
        password = request.data.get('password')
        
        import re
        name_regex = re.compile(r'^[a-zA-ZáéíóúÁÉÍÓÚñÑüÜ\s]*$')
        
        if first_name is not None:
            first_name = first_name.strip()
            if not name_regex.match(first_name):
                raise APIError(
                    'invalid_name',
                    'El nombre no debe contener caracteres especiales, solo letras, espacios y tildes.',
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
                
        if last_name is not None:
            last_name = last_name.strip()
            if not name_regex.match(last_name):
                raise APIError(
                    'invalid_lastname',
                    'El apellido no debe contener caracteres especiales, solo letras, espacios y tildes.',
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
                
        if phone is not None:
            phone = phone.strip()
            if phone and not re.match(r'^\d{10}$', phone):
                raise APIError(
                    'invalid_phone',
                    'El teléfono celular debe tener exactamente 10 dígitos numéricos.',
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
                
        if document_number is not None:
            document_number = document_number.strip()
            if document_number and not re.match(r'^\d{8,11}$', document_number):
                raise APIError(
                    'invalid_document',
                    'El número de identificación debe tener entre 8 y 11 dígitos numéricos.',
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
                
            if document_number and CustomUser.objects.filter(document_number=document_number).exclude(pk=user.pk).exists():
                raise APIError(
                    'document_exists',
                    'Este número de documento ya está registrado.',
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

        if first_name is not None:
            user.first_name = first_name
        if last_name is not None:
            user.last_name = last_name
        if phone is not None:
            user.phone = phone
        if document_type is not None:
            user.document_type = document_type
        if document_number is not None:
            user.document_number = document_number
            
        if password:
            try:
                validate_password(password, user=user)
            except DjangoValidationError as exc:
                raise APIError(
                    'weak_password',
                    'La contraseña no cumple los requisitos de seguridad.',
                    status_code=status.HTTP_400_BAD_REQUEST,
                    details={'messages': exc.messages},
                ) from exc
            user.set_password(password)
            user.password_changed = True
            
        user.save()
        return Response(UserMeSerializer(user).data)


class PasswordResetRequestView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']
        user = CustomUser.objects.filter(email__iexact=email).first()
        if user:
            user.password_reset_token = generar_reset_token()
            user.password_reset_expires = timezone.now() + timedelta(hours=24)
            user.save(update_fields=['password_reset_token', 'password_reset_expires'])
            enviar_reset_password(user, user.password_reset_token, request)
        return Response(
            {'message': 'Si el correo existe, recibirás instrucciones para restablecer la contraseña.'},
            status=status.HTTP_200_OK,
        )


class PasswordResetConfirmView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = serializer.validated_data['token']
        new_password = serializer.validated_data['new_password']

        user = CustomUser.objects.filter(password_reset_token=token).first()
        if not user or not user.password_reset_expires or user.password_reset_expires < timezone.now():
            raise APIError(
                'invalid_reset_token',
                'El enlace de recuperación es inválido o ha expirado.',
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            validate_password(new_password, user=user)
        except DjangoValidationError as exc:
            raise APIError(
                'weak_password',
                'La contraseña no cumple los requisitos de seguridad.',
                status_code=status.HTTP_400_BAD_REQUEST,
                details={'messages': exc.messages},
            ) from exc

        user.set_password(new_password)
        user.password_reset_token = None
        user.password_reset_expires = None
        user.password_changed = True
        user.save(update_fields=['password', 'password_reset_token', 'password_reset_expires', 'password_changed'])
        return Response({'message': 'Contraseña actualizada correctamente.'}, status=status.HTTP_200_OK)


class FirstPasswordChangeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if request.user.password_changed:
            raise APIError(
                'password_already_changed',
                'La contraseña ya fue cambiada anteriormente.',
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        serializer = FirstPasswordChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_password = serializer.validated_data['new_password']
        try:
            validate_password(new_password, user=request.user)
        except DjangoValidationError as exc:
            raise APIError(
                'weak_password',
                'La contraseña no cumple los requisitos de seguridad.',
                status_code=status.HTTP_400_BAD_REQUEST,
                details={'messages': exc.messages},
            ) from exc

        request.user.set_password(new_password)
        request.user.password_changed = True
        request.user.save(update_fields=['password', 'password_changed'])
        return Response({'message': 'Contraseña actualizada correctamente.'}, status=status.HTTP_200_OK)


class RefreshView(TokenRefreshView):
    permission_classes = [permissions.AllowAny]
