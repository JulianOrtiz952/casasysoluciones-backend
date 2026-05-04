import secrets
from datetime import timedelta

from django.conf import settings
from django.utils import timezone


def generar_password_temporal():
    return secrets.token_urlsafe(12)


def generar_reset_token():
    return secrets.token_urlsafe(32)


def _limit():
    return getattr(settings, 'LOGIN_ATTEMPT_LIMIT', 5)


def _cooldown():
    return timedelta(seconds=getattr(settings, 'LOGIN_COOLDOWN', 900))


def verificar_intento_login(user):
    if user.login_locked_until and timezone.now() < user.login_locked_until:
        return False, user.login_locked_until
    if user.login_locked_until and timezone.now() >= user.login_locked_until:
        user.login_attempts = 0
        user.login_locked_until = None
        user.save(update_fields=['login_attempts', 'login_locked_until'])
    return True, None


def registrar_intento_fallido(user):
    user.login_attempts = (user.login_attempts or 0) + 1
    if user.login_attempts >= _limit():
        user.login_locked_until = timezone.now() + _cooldown()
    user.save(update_fields=['login_attempts', 'login_locked_until'])
    return user.login_attempts


def limpiar_intentos_fallidos(user):
    user.login_attempts = 0
    user.login_locked_until = None
    user.save(update_fields=['login_attempts', 'login_locked_until'])
