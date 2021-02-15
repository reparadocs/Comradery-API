from lionhearted import settings
import os
import django
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lionhearted.settings")
django.setup()

from django.utils.html import strip_tags

from forum.models import Comment, Post, partial_update_objs, Community
from datetime import datetime, timedelta
from django.utils import timezone
from django.conf import settings
from sendgrid.helpers.mail import Mail, From, Personalization, Email, To
from sendgrid import SendGridAPIClient
from datetime import datetime, timedelta
from django.utils import timezone


def send_digest(community, _posts, emails):
    posts = []
    for p in _posts:
        if p.channel and not p.channel.private:
            posts.append(p)

    if len(posts) <= 0:
        return

    domain = community.get_domain()
    channel_dict = {}
    channel_list = []
    for p in posts:
        if p.channel.get_pretty_name() not in channel_dict:
            channel_dict[p.channel.get_pretty_name()] = []
            channel_list.append(p.channel)
        if len(channel_dict[p.channel.get_pretty_name()]) < 4:
            channel_dict[p.channel.get_pretty_name()].append(p)

    channel_list.sort(key=lambda x: x.sort)
    content_list = []
    for channel in channel_list:
        ch = channel.get_pretty_name()
        post_list = []
        for p in channel_dict[ch]:
            post_list.append(
                {
                    "title": p.title,
                    "link": domain + "/post/" + str(p.id),
                    "author": p.owner.username,
                    "content": strip_tags(p.content)[:100] + "...",
                }
            )
        content_list.append({"title": ch, "posts": post_list})

    dt_data = {
        "subject": community.display_name
        + " Community "
        + community.digest_frequency.capitalize()
        + " Digest",
        "community": community.display_name,
        "logo": community.photo.url if community.photo else None,
        "domain": community.get_domain(),
        "channels": content_list,
    }

    for email in emails:
        message = Mail(
            from_email=From(
                "digest@comradery.io", community.display_name + " Community Digest"
            ),
        )
        message.to = To(email)
        message.template_id = settings.SENDGRID_NEWSLETTER_TEMPLATE_ID
        message.dynamic_template_data = dt_data
        try:
            sg = SendGridAPIClient(settings.SENDGRID_API_KEY)
            response = sg.send(message)
            print(email)
            print(response.status_code)
            print(response.body)
            print(response.headers)
        except Exception as e:
            print(str(e))


if __name__ == "__main__":
    if len(sys.argv) > 2:
        c = Community.objects.get(name=sys.argv[1])
        posts = c.post_set.all().order_by("-posted")
        if sys.argv[2] == "--all":
            emails = [person.email for person in c.people.all()]
        else:
            emails = sys.argv[2:]
        send_digest(c, posts, emails)
    else:
        print("Need community name and email arg")
