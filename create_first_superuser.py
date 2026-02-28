import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.contrib.auth.models import User
from api.models import UserProfile

username = os.environ.get('DJANGO_SUPERUSER_USERNAME', 'admin')
password = os.environ.get('DJANGO_SUPERUSER_PASSWORD', 'admin123')
email = os.environ.get('DJANGO_SUPERUSER_EMAIL', 'admin@example.com')

if not User.objects.filter(username=username).exists():
    user = User.objects.create_superuser(username, email, password)
    UserProfile.objects.get_or_create(user=user, defaults={'rol': 'SUPER'})
    print(f"Superusuario '{username}' creado exitosamente mediante variables de entorno.")
else:
    print(f"El usuario '{username}' ya existe.")
