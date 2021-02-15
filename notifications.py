from lionhearted import settings
import os
import django
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lionhearted.settings")
django.setup()

from postmark.core import PMMail
from django.utils import timezone
from datetime import timedelta
from forum.models import *
from django.db.models import Max
from django.conf import settings
from sentry_sdk import capture_exception


def generate_notif_dict(notification):
    return {
        "author": notification.action_taker.username,
        "author_link": notification.action_taker.get_link(),
        "post_link": notification.target_comment.post.get_link(),
        "post_title": notification.target_comment.post.title,
        "link": notification.target_comment.post.get_link(),
        "content": notification.target_comment.content,
    }


def generate_chat_dict(chatroom, name):
    return {"room_name": name, "room_link": chatroom.get_link()}


def send_notifications(community, email_dict):
    for email, vals in email_dict.items():
        n_dict_list = []
        c_dict_list = []
        for n in vals[1]:
            n_dict_list.append(generate_notif_dict(n))

        for c in vals[0]:
            c_dict_list.append(
                generate_chat_dict(c.chatroom, c.chatroom.descriptive_name(c.person))
            )

        subject = "[" + community.display_name + "] "
        if len(n_dict_list) > 0:
            subject += "New Comment on " + n_dict_list[0]["post_title"]
        elif len(c_dict_list) > 0:
            subject += "New Messages from " + c_dict_list[0]["room_name"]
        else:
            raise Exception("how?")

        template_model = {
            "community": community.display_name,
            "subject": subject,
            "logo": community.photo.url if community.photo else None,
            "domain": community.get_domain(),
            "notifications": n_dict_list,
            "chats": c_dict_list,
        }

        try:
            pm = PMMail(
                to=email,
                sender=community.display_name
                + " Notifications notifications@comradery.io",
                template_id=settings.POSTMARK_NOTIFICATION_TEMPLATE_ID,
                template_model=template_model,
            )
            pm.send()
        except Exception as e:
            capture_exception(e)

        for n in vals[1]:
            n.should_send_email = False
            n.save()

        for pcrm in vals[0]:
            pcrm.last_email = pcrm.chatroom.last_message
            pcrm.save()


def user_chat_map(community, frequency):
    possible_chats = ChatRoom.objects.annotate(
        last_posted=Max("messages__posted")
    ).filter(
        room_type=ChatRoom.DIRECT,
        community=community,
        last_posted__gte=timezone.now() - timedelta(days=32),
    )
    user_chat_dict = {}
    for room in possible_chats:
        for person in room.private_members.all():
            if (
                person.email
                and room.last_message
                and person.id != room.last_message.sender.id
                and person.notification_frequency == frequency
            ):
                pcrm = PersonChatRoomMetadata.objects.filter(
                    person=person, chatroom=room
                ).first()
                if not pcrm:
                    pcrm = PersonChatRoomMetadata(person=person, chatroom=room)
                    pcrm.save()

                if (
                    not pcrm.last_read or pcrm.last_read.id != room.last_message.id
                ) and (
                    not pcrm.last_email or pcrm.last_email.id != room.last_message.id
                ):
                    if person.id in user_chat_dict:
                        user_chat_dict[person.email].append(pcrm)
                    else:
                        user_chat_dict[person.email] = [
                            pcrm,
                        ]

    return user_chat_dict


if __name__ == "__main__":
    if len(sys.argv) > 1:
        for c in Community.objects.all():
            if sys.argv[1] == "hourly":
                notifications = Notification.objects.filter(
                    notified_user__community=c,
                    should_send_email=True,
                    notified_user__notification_frequency=Person.HOURLY,
                    read=False,
                )
                chat_email_dict = user_chat_map(c, Person.HOURLY)

            elif sys.argv[1] == "daily":
                notifications = Notification.objects.filter(
                    notified_user__community=c,
                    should_send_email=True,
                    notified_user__notification_frequency=Person.DAILY,
                    read=False,
                )
                chat_email_dict = user_chat_map(c, Person.DAILY)

            else:
                print("Typo?")
                raise Exception()

            email_chat_notif_dict = {}
            print(chat_email_dict)
            for email in chat_email_dict:
                email_chat_notif_dict[email] = [chat_email_dict[email], []]

            for n in notifications:
                email = n.notified_user.email
                if not email:
                    pass
                if email in email_chat_notif_dict:
                    email_chat_notif_dict[email][1].append(n)
                else:
                    email_chat_notif_dict[email] = [[], [n,]]

            if len(email_chat_notif_dict) > 0:
                send_notifications(c, email_chat_notif_dict)
