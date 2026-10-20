import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac

from pot.models import LoginThrottle


def generar_password_temporal():
    return secrets.token_urlsafe(12)


def generar_reset_token():
    return secrets.token_urlsafe(32)


def _lockout_schedule():
    return getattr(
        settings,
        'LOGIN_LOCKOUT_SCHEDULE',
        ((5, 30), (7, 60), (9, 300), (11, 600), (13, 1800)),
    )


def _network_limit():
    return getattr(settings, 'LOGIN_NETWORK_ATTEMPT_LIMIT', 25)


def _network_cooldown():
    return timedelta(seconds=getattr(settings, 'LOGIN_NETWORK_COOLDOWN', 1800))


def _reset_window():
    return timedelta(seconds=getattr(settings, 'LOGIN_ATTEMPT_RESET_WINDOW', 86400))


def _device_lock_seconds(attempts):
    schedule = _lockout_schedule()
    for threshold, seconds in schedule:
        if attempts == threshold:
            return seconds
    final_threshold, final_seconds = schedule[-1]
    return final_seconds if attempts > final_threshold else None


def _device_remaining_attempts(attempts):
    for threshold, _ in _lockout_schedule():
        if threshold > attempts:
            return threshold - attempts
    return 0


def _scopes(identifier, request, include_network=True):
    """Crea ámbitos opacos por dispositivo e IP sin persistir sus valores reales."""
    normalized_identifier = (identifier or '').strip().casefold()[:254]
    raw_device_id = (request.headers.get('X-Device-ID') or '').strip()
    remote_ip = (request.META.get('REMOTE_ADDR') or 'unknown-ip').strip()[:64]
    try:
        device_id = str(uuid.UUID(raw_device_id))
    except (ValueError, AttributeError):
        device_id = f'fallback:{remote_ip}'

    values = [(f'device:{device_id}', 'device')]
    if include_network:
        values.append((f'network:{remote_ip}:{normalized_identifier}', 'network'))
    return tuple(
        (
            salted_hmac('casasysoluciones.login-throttle', value, secret=settings.SECRET_KEY).hexdigest(),
            scope_type,
        )
        for value, scope_type in values
    )


def verificar_bloqueo_login(identifier, request, include_network=True):
    now = timezone.now()
    locked_until = (
        LoginThrottle.objects.filter(
            scope_hash__in=[
                scope_hash for scope_hash, _ in _scopes(identifier, request, include_network)
            ],
            locked_until__gt=now,
        )
        .order_by('-locked_until')
        .values_list('locked_until', flat=True)
        .first()
    )
    return locked_until is None, locked_until


def registrar_fallo_login(identifier, request, include_network=True):
    now = timezone.now()
    remaining_attempts = []
    latest_lock = None

    with transaction.atomic():
        LoginThrottle.objects.filter(updated_at__lt=now - timedelta(days=1)).delete()
        for scope_hash, scope_type in _scopes(identifier, request, include_network):
            throttle, _ = LoginThrottle.objects.select_for_update().get_or_create(
                scope_hash=scope_hash,
            )
            if throttle.locked_until and throttle.locked_until > now:
                latest_lock = max(latest_lock or throttle.locked_until, throttle.locked_until)
                remaining_attempts.append(0)
                continue

            if throttle.updated_at and throttle.updated_at <= now - _reset_window():
                throttle.failed_attempts = 0

            throttle.failed_attempts += 1
            if scope_type == 'device':
                lock_seconds = _device_lock_seconds(throttle.failed_attempts)
                remaining = _device_remaining_attempts(throttle.failed_attempts)
            else:
                lock_seconds = (
                    int(_network_cooldown().total_seconds())
                    if throttle.failed_attempts >= _network_limit()
                    else None
                )
                remaining = max(0, _network_limit() - throttle.failed_attempts)

            throttle.locked_until = now + timedelta(seconds=lock_seconds) if lock_seconds else None
            throttle.updated_at = now
            throttle.save(update_fields=['failed_attempts', 'locked_until', 'updated_at'])
            remaining_attempts.append(remaining)
            if throttle.locked_until:
                latest_lock = max(latest_lock or throttle.locked_until, throttle.locked_until)

    return min(remaining_attempts), latest_lock


def limpiar_fallos_login(identifier, request, include_network=True):
    LoginThrottle.objects.filter(
        scope_hash__in=[
            scope_hash for scope_hash, _ in _scopes(identifier, request, include_network)
        ]
    ).delete()


def buscar_usuario_por_credencial(identifier):
    """Busca usuario por email (case-insensitive) o número de documento."""
    from pot.models import CustomUser

    value = (identifier or '').strip()
    if not value:
        return None
    user = CustomUser.objects.filter(email__iexact=value).first()
    if user:
        return user
    return CustomUser.objects.filter(document_number=value).first()
