from django_rq import job
from .models import Notification
from django.utils import timezone
from django.db.models import Q, F, Count

from django.utils.html import strip_tags

from forum.models import Comment, Post, partial_update_objs, Community, Person
from datetime import datetime, timedelta
from django.utils import timezone
from django.conf import settings
from sendgrid.helpers.mail import Mail, From, Personalization, Email, To
from sendgrid import SendGridAPIClient
from datetime import datetime, timedelta
from django.utils import timezone


@job
def comment_created(comment):
    parent = comment.parent
    notified_users = []
    while parent:
        if parent.owner != comment.owner and parent.owner.id not in notified_users:
            n = Notification(
                notified_user=parent.owner,
                notification_type=Notification.COMMENT_COMMENT,
                target_comment=comment,
                action_taker=comment.owner,
            )
            n.save()
            notified_users.append(parent.owner.id)
        parent = parent.parent

    if (
        comment.post.owner != comment.owner
        and comment.post.owner.id not in notified_users
    ):
        n = Notification(
            notified_user=comment.post.owner,
            notification_type=Notification.POST_COMMENT,
            target_comment=comment,
            action_taker=comment.owner,
        )
        n.save()


@job
def object_liked(scored_object, obj_type, action_taker):
    if scored_object.owner != action_taker:
        if obj_type == "Comment":
            n, created = Notification.objects.get_or_create(
                notified_user=scored_object.owner,
                target_comment=scored_object,
                notification_type=Notification.COMMENT_LIKE,
            )
        elif obj_type == "Post":
            n, created = Notification.objects.get_or_create(
                notified_user=scored_object.owner,
                target_post=scored_object,
                notification_type=Notification.POST_LIKE,
            )
        n.action_taker = action_taker
        n.read = False
        n.time = timezone.now()
        n.save()


@job
def post_created(post):
    community = post.community

    if community.digest_frequency == Community.IMMEDIATELY:
        domain = community.get_domain()
        content_list = [
            {
                "title": post.channel.get_pretty_name(),
                "posts": [
                    {
                        "title": post.title,
                        "link": domain + "/post/" + str(post.id),
                        "author": post.owner.username,
                        "content": strip_tags(post.content)[:100] + "...",
                    }
                ],
            }
        ]

        dt_data = {
            "subject": community.display_name + ": " + post.title,
            "community": community.display_name,
            "logo": community.photo.url if community.photo else None,
            "domain": community.get_domain(),
            "channels": content_list,
        }
        people = Person.objects.filter(community=community)
        for person in people:
            if post.can_access(person):
                email = person.email
                message = Mail(
                    from_email=From("digest@comradery.io", community.display_name),
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
