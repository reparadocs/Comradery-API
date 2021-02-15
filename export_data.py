from lionhearted import settings
import os
import django
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lionhearted.settings")
django.setup()

from forum.models import Comment, Post, partial_update_objs, Community, Person

def export_data(community):
  ps = community.people.all()
  people_array = []
  for p in ps:
    obj = {
      "email": p.email,
      "bio": p.bio,
      "username": p.username,
      "id": p.id
    }
    people_array.append(obj)
  print(people_array)
  posts = community.post_set.all()
  post_array = []
  for p in posts:
    obj = {
      "author": p.owner.email,
      "content": p.content,
      "title": p.title,
      "id": p.id, 
      "posted": p.posted
    }
    comments = []
    for c in p._comments.all():
      c_obj = {
        "author": c.owner.email,
        "parent": c.parent.id if c.parent else None,
        "content": c.content,
        "posted": c.posted
      }
      comments.append(c_obj)
    obj["comments"] = comments
    post_array.append(obj)
  print(post_array)


if __name__ == "__main__":
    if len(sys.argv) > 1:
      c = Community.objects.get(name=sys.argv[1])
      export_data(c)
