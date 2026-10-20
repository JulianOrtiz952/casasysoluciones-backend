from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pot', '0016_propertyimage_thumbnail'),
    ]

    operations = [
        migrations.CreateModel(
            name='LoginThrottle',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('scope_hash', models.CharField(max_length=64, unique=True)),
                ('failed_attempts', models.PositiveSmallIntegerField(default=0)),
                ('locked_until', models.DateTimeField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True, db_index=True)),
            ],
            options={
                'ordering': ['-updated_at'],
            },
        ),
    ]
