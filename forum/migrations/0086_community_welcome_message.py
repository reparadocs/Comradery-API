# Generated by Django 2.2.7 on 2020-05-17 20:19

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('forum', '0085_auto_20200429_0756'),
    ]

    operations = [
        migrations.AddField(
            model_name='community',
            name='welcome_message',
            field=models.CharField(blank=True, max_length=1000, null=True),
        ),
    ]
