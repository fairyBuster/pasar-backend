from django.db import migrations


def create_default_settings(apps, schema_editor):
    """Buat satu baris konfigurasi default (fitur OFF sampai admin atur tarif)."""
    GoldSettings = apps.get_model('gold', 'GoldSettings')
    if not GoldSettings.objects.exists():
        GoldSettings.objects.create()


class Migration(migrations.Migration):

    dependencies = [
        ('gold', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(create_default_settings, migrations.RunPython.noop),
    ]
