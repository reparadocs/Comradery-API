from lionhearted import settings
import os
import django
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lionhearted.settings")
django.setup()

from django.utils.html import strip_tags

from forum.models import (
    Comment,
    Post,
    partial_update_objs,
    Community,
    CommunityInvitation,
)
from datetime import datetime, timedelta
from django.utils import timezone
from django.conf import settings
from sendgrid.helpers.mail import Mail, From, Personalization, Email, To
from sendgrid import SendGridAPIClient
from datetime import datetime, timedelta
from django.utils import timezone
from postmark.core import PMMail


def send_invitations(community, emails):
    for email in emails:
        ci = CommunityInvitation(community=community)
        ci.save()
        dt_data = {
            "community_name": community.display_name,
            "logo": community.photo.url if community.photo else None,
            "action_url": community.get_domain() + "?invite_code=" + ci.invite_code,
        }

        pm = PMMail(
            to=email,
            sender=community.display_name + " Invitation invitations@comradery.io",
            template_id=settings.POSTMARK_INVITATION_TEMPLATE_ID,
            template_model=dt_data,
        )
        pm.send()


if __name__ == "__main__":
    if len(sys.argv) > 2:
        c = Community.objects.get(name=sys.argv[1])
        emails = sys.argv[2:]
        send_invitations(c, emails)
    else:
        print("Need community name and email arg")
