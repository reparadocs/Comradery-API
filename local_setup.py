from lionhearted import settings
import os
import django
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lionhearted.settings")
django.setup()

from forum.models import Community, CommunityHost

name = input("Enter your community name: ")
c = Community.objects.create(name=name)
ch = CommunityHost.objects.create(community=c, host="localhost:3000")

print("Community " + name + " created. CommunityHost pointing to localhost:3000 created for local development")