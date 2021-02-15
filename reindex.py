from lionhearted import settings
import os
import datetime
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lionhearted.settings")
django.setup()

from forum.models import Post, Comment, clear_index, Person

clear_index()

for post in Post.objects.all():
    post.index_obj(post)

for person in Person.objects.all():
    person.index_obj(person)
