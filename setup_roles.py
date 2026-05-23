import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.contrib.auth import get_user_model

User = get_user_model()

for u in User.objects.filter(is_superuser=True).exclude(role=User.Role.ADMIN):
    u.role = User.Role.ADMIN
    u.save(update_fields=['role', 'updated_at'])

print('Roles de superusuarios sincronizados.')
