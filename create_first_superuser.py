import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.contrib.auth import get_user_model

User = get_user_model()

email = os.environ.get('DJANGO_SUPERUSER_EMAIL', 'admin@example.com')
password = os.environ.get('DJANGO_SUPERUSER_PASSWORD', 'admin123')

if not User.objects.filter(email__iexact=email).exists():
    User.objects.create_superuser(email=email, password=password, role=User.Role.ADMIN, phone='0', password_changed=True)
    print(f'Superusuario {email} creado.')
else:
    print(f'Ya existe usuario con email {email}.')
