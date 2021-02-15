import json
import requests
from lionhearted import settings
import os
import django
import sys
import random

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lionhearted.settings")
django.setup()

from django.core.exceptions import (
    PermissionDenied,
    ObjectDoesNotExist,
    SuspiciousOperation,
)

from forum.models import Comment, Post, Person, Community, Channel


def gen_com(name, json_path):
    f = open("demo_data/authors.json", "r")

    data = json.loads(f.read())

    try:
        c = Community.objects.get(name=name)
        c._channels.all().delete()
        c.post_set.all().delete()
        c.people.filter(user=None).delete()
    except ObjectDoesNotExist:
        c = Community(name=name)
        c.save()
        pass

    people = []
    for a in data:
        p = Person(
            username=a,
            community=c,
            bio="Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim blandit volutpat maecenas volutpat. Diam vulputate ut pharetra sit. Odio ut sem nulla pharetra diam sit amet. Placerat duis ultricies lacus sed turpis tincidunt. Amet facilisis magna etiam tempor orci eu lobortis elementum nibh. Nec dui nunc mattis enim ut tellus. Elit pellentesque habitant morbi tristique. Dolor morbi non arcu risus quis varius quam. ",
        )
        p.save()
        people.append(p)

    f.close()
    f = open(json_path, "r")

    data = json.loads(f.read())

    def create_comment(post, content, parent):
        com = Comment(
            post=post,
            parent=parent,
            owner=random.choice(people),
            content="<div>" + content + "</div>",
        )
        com.save()
        return com

    for p in data:
        ch = Channel.objects.get_or_create(name=p["channel"], community=c, emoji="T")[0]
        po = Post(
            channel=ch,
            owner=random.choice(people),
            community=c,
            title=p["title"],
            content="<div>" + p["content"] + "</div>",
        )
        po.save()

        for co in p["children"]:
            com = Comment(
                post=po,
                owner=random.choice(people),
                content="<div>" + co["content"] + "</div>",
            )
            com.save()

            if "children" in co:
                for child in co["children"]:
                    com1 = create_comment(po, child["content"], com)
                    if "children" in child:
                        for child1 in child["children"]:
                            com2 = create_comment(po, child1["content"], com1)
                            if "children" in child1:
                                for child2 in child1["children"]:
                                    com3 = create_comment(po, child2["content"], com2)
                                    if "children" in child2:
                                        for child3 in child2["children"]:
                                            com4 = create_comment(
                                                po, child3["content"], com3
                                            )

        upvotes = random.randint(4, 25)
        for u in range(upvotes):
            po.upvotes.add(random.choice(people))


if __name__ == "__main__":
    if len(sys.argv) > 2:
        gen_com(sys.argv[1], sys.argv[2])

