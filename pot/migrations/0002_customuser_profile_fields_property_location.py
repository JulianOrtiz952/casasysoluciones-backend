from django.db import migrations, models


def populate_public_codes(apps, schema_editor):
    CustomUser = apps.get_model('pot', 'CustomUser')
    for user in CustomUser.objects.filter(public_code__isnull=True).iterator():
        user.public_code = f'USR-{user.pk:05d}'
        user.save(update_fields=['public_code'])


class Migration(migrations.Migration):

    dependencies = [
        ('pot', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='customuser',
            name='avatar',
            field=models.ImageField(blank=True, max_length=255, null=True, upload_to='avatars/%Y/%m/'),
        ),
        migrations.AddField(
            model_name='customuser',
            name='document_number',
            field=models.CharField(blank=True, max_length=30, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='customuser',
            name='document_type',
            field=models.CharField(
                blank=True,
                choices=[
                    ('CC', 'Cédula de ciudadanía'),
                    ('CE', 'Cédula de extranjería'),
                    ('PASSPORT', 'Pasaporte'),
                    ('NIT', 'NIT'),
                ],
                default='',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='customuser',
            name='public_code',
            field=models.CharField(blank=True, max_length=20, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='property',
            name='building_name',
            field=models.CharField(blank=True, default='', max_length=150),
        ),
        migrations.AddField(
            model_name='property',
            name='city',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
        migrations.AddField(
            model_name='property',
            name='cover_image',
            field=models.ImageField(blank=True, max_length=255, null=True, upload_to='properties/covers/%Y/%m/'),
        ),
        migrations.AddField(
            model_name='property',
            name='unit_label',
            field=models.CharField(blank=True, default='', max_length=50),
        ),
        migrations.RunPython(populate_public_codes, migrations.RunPython.noop),
    ]
