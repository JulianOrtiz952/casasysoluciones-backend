import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.contrib.auth.models import User
from api.models import UserProfile

for u in User.objects.all():
    rol = 'SUPER' if u.is_superuser else 'OPERARIO'
    UserProfile.objects.get_or_create(user=u, defaults={'rol': rol})

print("Roles verificados/creados correctamente.")
