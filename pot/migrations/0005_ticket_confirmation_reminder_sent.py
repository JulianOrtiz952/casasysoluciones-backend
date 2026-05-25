from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pot', '0004_ticket_status_log_attachment_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='ticket',
            name='confirmation_reminder_sent_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
