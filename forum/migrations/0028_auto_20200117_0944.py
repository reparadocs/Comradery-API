# Generated by Django 2.2.7 on 2020-01-17 09:44

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('forum', '0027_community_custom_stylesheet'),
    ]

    operations = [
        migrations.AlterField(
            model_name='channel',
            name='name',
            field=models.CharField(max_length=13),
        ),
    ]
