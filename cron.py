from lionhearted import settings
import os
import django
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lionhearted.settings")
django.setup()

from forum.models import Comment, Post, partial_update_objs, Community, Person
from datetime import datetime, timedelta
from django.utils import timezone
from newsletter import send_digest
from postmark.core import PMMail


def rescore_posts():
    STOP_SCORING = 30
    scored_objects = list(
        Post.objects.filter(posted__gte=timezone.now() - timedelta(days=STOP_SCORING))
    )
    scored_objects += list(
        Comment.objects.filter(
            posted__gte=timezone.now() - timedelta(days=STOP_SCORING)
        )
    )
    for so in scored_objects:
        if so.should_rescore:
            so.rescore()


def send_newsletter_digests():
    day = timezone.now().today().weekday()
    for c in Community.objects.all():
        if c.digest_frequency == Community.DAILY or (
            c.digest_frequency == Community.WEEKLY and c.digest_day_of_week == day
        ):
            if c.digest_frequency == Community.DAILY:
                filter_days = 1
            else:
                filter_days = 7
            posts = (
                c.post_set.all()
                .order_by("-posted")
                .filter(posted__gte=timezone.now() - timedelta(days=filter_days))
            )
            emails = [person.email for person in c.people.filter(digest_frequency=None)]
            send_digest(c, posts, emails)
    for p in Person.objects.exclude(digest_frequency=None):
        print(p.email)
        if p.digest_frequency == Community.DAILY or (
            p.digest_frequency == Community.WEEKLY and day == 5
        ):
            if p.digest_frequency == Community.DAILY:
                filter_days = 1
            else:
                filter_days = 7
            posts = (
                p.community.post_set.all()
                .order_by("-posted")
                .filter(posted__gte=timezone.now() - timedelta(days=filter_days))
            )
            emails = [
                p.email,
            ]
            c = p.community
            print(posts)
            send_digest(c, posts, emails)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "--rescore-posts":
            rescore_posts()
        elif sys.argv[1] == "--send-newsletter-digests":
            send_newsletter_digests()
        else:
            print("Typo?")
