import django.db.models.deletion
from django.conf import settings
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0008_inmueble_enlace_google_maps'),
        ('pot', '0001_initial'),
    ]

    operations = [
        migrations.DeleteModel(name='UserProfile'),
    ]
