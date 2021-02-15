from django.db import models
from django.contrib.auth.models import User
from .utils import (
    common_edit_object,
    common_get_object,
    generate_uuid_base64,
    uuid_path,
)
from django.conf import settings
from django.contrib.postgres.fields import JSONField
import math
from datetime import datetime
import pytz
from django.db.models.signals import post_save, pre_delete
import os
from algoliasearch.search_client import SearchClient
from django.utils.html import strip_tags
from model_utils import FieldTracker
from django.http import Http404
from django.core.exceptions import (
    PermissionDenied,
    ObjectDoesNotExist,
    SuspiciousOperation,
)
from .xredis import re_set, re_incr


client = SearchClient.create(settings.ALGOLIA_APPLICATION_ID, settings.ALGOLIA_ADMIN_KEY)
index = client.init_index(
    ("prod" if "IN_HEROKU" in os.environ else "dev") + "_post_index"
)

index.set_settings(
    {
        "searchableAttributes": ["title,content"],
        "attributesForFaceting": ["community", "channel_id", "type"],
        "attributesToSnippet": ["content:20",],
        "snippetEllipsisText": "...",
    }
)

person_index = client.init_index(
    ("prod" if "IN_HEROKU" in os.environ else "dev") + "_person_index"
)

person_index.set_settings(
    {
        "searchableAttributes": ["username,bio"],
        "attributesForFaceting": ["community", "type"],
        "attributesToSnippet": ["bio:10",],
        "snippetEllipsisText": "...",
    }
)


class Community(models.Model):
    NEVER = "never"
    DAILY = "daily"
    WEEKLY = "weekly"
    IMMEDIATELY = "immediate"

    DIGEST_SCHEDULER = [
        (IMMEDIATELY, IMMEDIATELY),
        (NEVER, NEVER),
        (DAILY, DAILY),
        (WEEKLY, WEEKLY),
    ]

    DAYS_OF_WEEK = (
        (0, "Monday"),
        (1, "Tuesday"),
        (2, "Wednesday"),
        (3, "Thursday"),
        (4, "Friday"),
        (5, "Saturday"),
        (6, "Sunday"),
    )

    SLACK = "slack"
    GOOGLE = "google"

    AUTH_OPTIONS = [(SLACK, SLACK), (GOOGLE, GOOGLE)]

    name = models.CharField(max_length=100, unique=True)
    nice_name = models.CharField(max_length=100, blank=True, null=True)
    private = models.BooleanField(default=False)
    read_only = models.BooleanField(default=False)
    photo = models.FileField(null=True, blank=True, upload_to=uuid_path)
    favicon = models.FileField(null=True, blank=True)
    logout_redirect = models.URLField(null=True, blank=True)
    login_redirect = models.URLField(null=True, blank=True)
    custom_stylesheet = models.URLField(null=True, blank=True)
    invite_code = models.CharField(max_length=40, null=True, blank=True)
    write_key = models.CharField(max_length=40, null=True, blank=True)
    track_anonymous = models.BooleanField(default=False)
    custom_header = models.CharField(max_length=5000, null=True, blank=True)
    digest_frequency = models.CharField(
        choices=DIGEST_SCHEDULER, max_length=10, default=NEVER
    )
    welcome_message = models.CharField(max_length=10000, blank=True, null=True)
    trusted = models.BooleanField(default=False)
    auth_enabled = models.CharField(
        choices=AUTH_OPTIONS, max_length=10, blank=True, null=True
    )
    free = models.BooleanField(default=False)
    digest_day_of_week = models.IntegerField(choices=DAYS_OF_WEEK, default=0)

    def __str__(self):
        return self.name

    @property
    def display_name(self):
        if self.nice_name:
            return self.nice_name
        else:
            return self.name.capitalize()

    @property
    def channels(self):
        return self._channels.filter(private=False)

    @property
    def custom_fields(self):
        return self._custom_fields.all().order_by("sort")

    def allowed_channels(self, viewer):
        if viewer:
            if viewer.admin:
                return self._channels.all()
            return self.channels | viewer.private_channels.all()
        else:
            return self.channels

    @property
    def chatrooms(self):
        return self._chatrooms.filter(private=False)

    def allowed_chatrooms(self, viewer):
        if viewer:
            if viewer.superadmin_api_only:
                return self.chatrooms
            return self.chatrooms | viewer.private_chatrooms.all()
        else:
            return self.chatrooms

    @property
    def admins(self):
        return self.people.filter(admin=True)

    def is_public(self):
        return not self.private

    def can_access(self, viewer):
        return self.people.filter(id=viewer.id).exists()

    def can_edit(self, viewer):
        return self.people.filter(id=viewer.id, admin=True).exists()

    @classmethod
    def id_from_host(cls, url):
        try:
            host = CommunityHost.objects.get(host=url)
        except ObjectDoesNotExist:
            raise Http404()

        return host.community.id

    def get_domain(self):
        host = self.hosts.filter(primary=True)
        if len(host) > 0:
            host = host[0].host
        elif len(self.hosts.all()) > 0:
            host = self.hosts.all()[0].host
        else:
            host = self.name + ".comradery.io"
        return "https://" + host

    def save(self, *args, **kwargs):
        if not self.invite_code:
            self.invite_code = generate_uuid_base64()

        super().save(*args, **kwargs)

    @classmethod
    def post_save(cls, sender, instance, created, *args, **kwargs):
        if created:
            chatroom = ChatRoom(
                community=instance,
                name="General",
                private=False,
                room_type=ChatRoom.ROOM,
            )
            chatroom.save()
            chatroom = ChatRoom(
                community=instance,
                name="Ideas",
                private=False,
                room_type=ChatRoom.ROOM,
            )
            chatroom.save()
            channel = Channel(community=instance, name="General", emoji="🌟")
            channel.save()
            channel = Channel(community=instance, name="Events", emoji="📅")
            channel.save()
            channel = Channel(community=instance, name="Q & A", emoji="❓")
            channel.save()
            host = CommunityHost(
                community=instance, host=(instance.name + ".comradery.io")
            )
            host.save()


class ComraderyBetaInvitation(models.Model):
    registration_code = models.CharField(max_length=40)

    def save(self, *args, **kwargs):
        if not self.registration_code:
            self.registration_code = generate_uuid_base64()

        super().save(*args, **kwargs)


class CommunityInvitation(models.Model):
    invite_code = models.CharField(max_length=40)
    community = models.ForeignKey(Community, on_delete=models.CASCADE)
    email = models.EmailField(blank=True, null=True)

    def save(self, *args, **kwargs):
        if not self.invite_code:
            self.invite_code = generate_uuid_base64()

        super().save(*args, **kwargs)


class CommunityHost(models.Model):
    community = models.ForeignKey(
        Community, on_delete=models.CASCADE, related_name="hosts"
    )
    host = models.CharField(max_length=100, unique=True)
    primary = models.BooleanField(default=False)

    def __str__(self):
        return self.host


class Link(models.Model):
    community = models.ForeignKey(
        Community, on_delete=models.CASCADE, related_name="links"
    )
    url = models.URLField(max_length=100)
    label = models.CharField(max_length=15)


class Person(models.Model):
    NEVER = "never"
    DAILY = "daily"
    HOURLY = "hourly"

    NOTIFICATION_FREQUENCIES = [(NEVER, NEVER), (DAILY, DAILY), (HOURLY, HOURLY)]

    user = models.OneToOneField(User, null=True, on_delete=models.SET_NULL)
    community = models.ForeignKey(
        Community, on_delete=models.CASCADE, related_name="people"
    )
    auth = models.CharField(
        choices=Community.AUTH_OPTIONS, max_length=10, blank=True, null=True
    )
    created = models.DateTimeField(auto_now_add=True)
    admin = models.BooleanField(default=False)
    email = models.EmailField()
    superadmin_api_only = models.BooleanField(default=False)  # MUST ALSO BE AN ADMIN
    bio = models.CharField(max_length=1000, blank=True, default="")
    username = models.CharField(max_length=150)
    photo = models.FileField(null=True, blank=True, upload_to=uuid_path)
    segment_user_id = models.CharField(max_length=50, blank=True, null=True)
    external_photo_url = models.URLField(max_length=300, blank=True, null=True)
    show_welcome = models.BooleanField(default=True)
    last_reset = models.DateTimeField(blank=True, null=True)
    digest_frequency = models.CharField(
        choices=Community.DIGEST_SCHEDULER, max_length=10, blank=True, null=True
    )

    notification_frequency = models.CharField(
        max_length=10, default="hourly", choices=NOTIFICATION_FREQUENCIES
    )

    tracker = FieldTracker()

    ## Feature Flag Enabled
    edit_profile_redirect_url = models.URLField(max_length=100, blank=True, null=True)

    @classmethod
    def index_obj(cls, instance):
        if not instance.superadmin_api_only:
            obj = {
                "objectID": "person_" + str(instance.id),
                "community": instance.community.id,
                "id": instance.id,
                "photo_url": instance.photo_url,
                "admin": instance.admin,
                "username": instance.username,
                "bio": instance.bio,
                "type": "person",
            }
            person_index.save_object(obj)

    def __str__(self):
        return self.community.name + "__" + self.email + ":" + self.username

    def user_delete(self):
        if self.user:
            self.user.delete()
        index.delete_object("person_" + str(self.id))
        self.delete()

    def is_public(self):
        return self.community.is_public()

    def can_access(self, viewer):
        return common_get_object(self, viewer)

    def can_edit(self, viewer):
        return (
            viewer.id == self.id
            or self.community.people.filter(id=viewer.id, admin=True).exists()
        )

    def get_link(self):
        return self.community.get_domain() + "/profile/" + str(self.id)

    @property
    def custom_field_values(self):
        return self._custom_field_values.all().order_by("field__sort")

    @property
    def edit_profile_redirect(self):
        return self.edit_profile_redirect_url

    @property
    def photo_url(self):
        if bool(self.photo):
            return self.photo.url
        else:
            return self.external_photo_url

    def shared_channels(self, viewer):
        channels = self.community.channels
        if viewer:
            channels = channels | viewer.private_channels.filter(
                private_members__in=[self]
            )
        return channels

    def restricted_channels(self):
        return Channel.objects.exclude(private=False).exclude(
            private_members__in=[self]
        )

    @classmethod
    def post_save(cls, sender, instance, created, *args, **kwargs):
        changed = instance.tracker.changed()
        if any(
            key in changed
            for key in [
                "id",
                "community",
                "photo",
                "admin",
                "username",
                "bio",
                "external_photo_url",
            ]
        ):
            cls.index_obj(instance)

    @classmethod
    def pre_delete(cls, sender, instance, using, *args, **kwargs):
        index.delete_object("person_" + str(instance.id))


class CustomField(models.Model):
    community = models.ForeignKey(
        Community, on_delete=models.CASCADE, related_name="_custom_fields"
    )
    name = models.CharField(max_length=100)
    sort = models.IntegerField(default=100)


class CustomFieldValue(models.Model):
    field = models.ForeignKey(
        CustomField, on_delete=models.CASCADE, related_name="values"
    )
    person = models.ForeignKey(
        Person, on_delete=models.CASCADE, related_name="_custom_field_values"
    )
    value = models.CharField(max_length=1000, blank=True, null=True)

    @property
    def field_name(self):
        return self.field.name


class Channel(models.Model):
    name = models.CharField(max_length=25)
    emoji = models.CharField(max_length=5)
    private = models.BooleanField(default=False)
    sort = models.IntegerField(default=100)
    community = models.ForeignKey(
        Community, on_delete=models.CASCADE, related_name="_channels"
    )
    private_members = models.ManyToManyField(Person, related_name="private_channels")
    post_admin_only = models.BooleanField(default=False)

    def get_pretty_name(self):
        return self.emoji + " " + self.name

    def __str__(self):
        return self.community.name + "__" + self.name

    def is_public(self):
        return self.community.is_public() and not self.private

    def can_access(self, viewer):
        if self.private:
            return (
                self.private_members.filter(id=viewer.id).exists()
                or self.community.people.filter(id=viewer.id, admin=True).exists()
            )
        return common_get_object(self, viewer)

    def can_edit(self, viewer):
        return common_edit_object(self, viewer)


class ScoredObject(models.Model):
    upvotes = models.ManyToManyField(Person, related_name="%(class)s_upvoted")
    score = models.FloatField(default=0)
    posted = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True

    @property
    def points(self):
        return self.upvotes.count()

    @property
    def should_rescore(self):
        return True

    def user_vote(self, person):
        return self.upvotes.filter(pk=person.id).exists()

    def rescore(self):
        basis = math.log(self.points + 1, 10)
        t = self.posted - datetime(2019, 1, 1, 0, 0, 0, 0, pytz.UTC)
        t = t.total_seconds() / 60000.0
        self.score = basis + t
        self.save()


class Post(ScoredObject):
    community = models.ForeignKey(Community, on_delete=models.CASCADE)
    owner = models.ForeignKey(
        Person, null=True, on_delete=models.SET_NULL, related_name="_posts"
    )

    active = models.BooleanField(default=True)
    pinned = models.BooleanField(default=False)
    views = models.IntegerField(default=0)
    content = models.CharField(max_length=9500)
    title = models.CharField(max_length=200)
    channel = models.ForeignKey(Channel, null=True, on_delete=models.SET_NULL)

    tracker = FieldTracker()

    def __str__(self):
        return self.community.name + "__" + self.title

    def save(self, *args, **kwargs):
        if not self.pk:  # Just Created
            self.community = self.owner.community

        super().save(*args, **kwargs)

    def user_delete(self):
        self.owner = None
        self.content = "<div>[deleted]</div>"
        self.channel = None
        self.title = "[deleted]"
        self.active = False
        index.delete_object("post_" + str(self.id))
        self.save()

    def get_link(self):
        return self.community.get_domain() + "/post/" + str(self.id)

    def is_public(self):
        return self.channel.is_public() if self.channel else self.community.is_public()

    def can_access(self, viewer):
        return (
            self.channel.can_access(viewer)
            if self.channel
            else common_get_object(self, viewer)
        )

    def can_edit(self, viewer):
        return common_edit_object(self, viewer)

    @property
    def num_comments(self):
        return self._comments.count()

    @property
    def comments(self):
        return self._comments.filter(parent=None).order_by("-score")

    @classmethod
    def index_obj(cls, instance):
        if not instance.active:
            return

        owner_obj = None
        if instance.owner:
            owner_obj = {
                "id": instance.owner.id,
                "username": instance.owner.username,
                "photo": instance.owner.photo.url if instance.owner.photo else None,
            }
        obj = {
            "objectID": "post_" + str(instance.id),
            "community": instance.community.id,
            "channel": {"name": instance.channel.name} if instance.channel else None,
            "channel_id": instance.channel.id if instance.channel else None,
            "id": instance.id,
            "posted": instance.posted.isoformat(),
            "owner": owner_obj,
            "title": instance.title,
            "content": strip_tags(instance.content),
            "num_comments": instance.num_comments,
            "type": "post",
        }
        index.save_object(obj)

    @classmethod
    def post_save(cls, sender, instance, created, *args, **kwargs):
        changed = instance.tracker.changed()
        if any(
            key in changed
            for key in [
                "id",
                "owner",
                "community",
                "channel",
                "posted",
                "owner",
                "title",
                "content",
            ]
        ):
            cls.index_obj(instance)

    @classmethod
    def pre_delete(cls, sender, instance, using, *args, **kwargs):
        index.delete_object("post_" + str(instance.id))


class Comment(ScoredObject):
    content = models.CharField(max_length=25000)
    owner = models.ForeignKey(
        Person, null=True, on_delete=models.SET_NULL, related_name="_comments"
    )
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="_comments")
    parent = models.ForeignKey(
        "Comment",
        related_name="_children",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )

    def is_public(self):
        return self.post.is_public()

    def can_access(self, viewer):
        return self.post.can_access(viewer)

    def can_edit(self, viewer):
        if self.owner and self.owner.id == viewer.id:
            return True
        return self.post.community.people.filter(id=viewer.id, admin=True).exists()

    @property
    def children(self):
        return self._children.order_by("-score")

    @property
    def should_rescore(self):
        return False

    def rescore(self):
        self.score = self.points
        self.save()

    def user_delete(self):
        if self._children.count() > 0:
            self.owner = None
            self.content = "<div>[deleted]</div>"
            self.save()
            return False
        else:
            self.delete()
            return True

    @classmethod
    def post_save(cls, sender, instance, created, *args, **kwargs):
        if created:
            index.partial_update_object(
                {
                    "objectID": "post_" + str(instance.post.id),
                    "num_comments": instance.post.num_comments,
                }
            )


class Notification(models.Model):
    COMMENT_LIKE = "CL"
    POST_LIKE = "PL"
    POST_COMMENT = "PC"
    COMMENT_COMMENT = "CC"

    NOTIFICATION_TYPES = [
        (COMMENT_LIKE, "comment_like"),
        (POST_LIKE, "post_like"),
        (POST_COMMENT, "post_comment"),
        (COMMENT_COMMENT, "comment_comment"),
    ]

    read = models.BooleanField(default=False)
    notified_user = models.ForeignKey(
        Person, on_delete=models.CASCADE, related_name="notifications"
    )
    action_taker = models.ForeignKey(
        Person, on_delete=models.CASCADE, null=True, blank=True
    )
    target_post = models.ForeignKey(
        Post, null=True, blank=True, on_delete=models.CASCADE
    )
    target_comment = models.ForeignKey(
        Comment, null=True, blank=True, on_delete=models.CASCADE
    )
    time = models.DateTimeField(auto_now_add=True)
    should_send_email = models.BooleanField(default=False)
    notification_type = models.CharField(max_length=5, choices=NOTIFICATION_TYPES)

    def save(self, *args, **kwargs):
        if not self.pk:
            re_incr(self.notified_user.user.username, 1)

            if (
                self.notification_type
                in [Notification.POST_COMMENT, Notification.COMMENT_COMMENT,]
                and self.notified_user.notification_frequency != Person.NEVER
            ):
                self.should_send_email = True

        super().save(*args, **kwargs)


class ChatRoom(models.Model):
    ROOM = "room"
    DIRECT = "direct"

    ROOM_TYPES = [(ROOM, ROOM), (DIRECT, DIRECT)]

    community = models.ForeignKey(
        Community, on_delete=models.CASCADE, related_name="_chatrooms"
    )
    private_members = models.ManyToManyField(Person, related_name="private_chatrooms")
    name = models.CharField(max_length=100, null=True, blank=True)
    private = models.BooleanField(default=True)
    room_type = models.CharField(max_length=10, choices=ROOM_TYPES)

    @property
    def last_message(self):
        return self.messages.order_by("-posted").first()

    def is_public(self):
        return self.community.is_public() and not self.private

    def can_access(self, viewer):
        return (
            self.private_members.filter(id=viewer.id).exists()
            if self.private
            else common_get_object(self, viewer)
        )

    def descriptive_name(self, requester):
        if self.name:
            return self.name

        pms = self.private_members.exclude(id=requester.id)
        name = ""
        for p in pms:
            name += p.username + ", "
        name = name[:-2]
        return name

    def get_link(self):
        return self.community.get_domain() + "/chat?room=" + str(self.id)

    def can_edit(self, viewer):
        return common_edit_object(self, viewer)

    def save(self, *args, **kwargs):
        if self.room_type == ChatRoom.DIRECT:
            self.private = True

        super().save(*args, **kwargs)


class Message(models.Model):
    sender = models.ForeignKey(
        Person, on_delete=models.CASCADE, related_name="_messages"
    )
    message = models.CharField(max_length=2000)
    room = models.ForeignKey(
        ChatRoom, on_delete=models.CASCADE, related_name="messages"
    )
    posted = models.DateTimeField(auto_now_add=True)

    def is_public(self):
        return self.room.is_public()

    def can_access(self, viewer):
        return self.room.can_access(viewer)

    def can_edit(self, viewer):
        if self.sender.id == viewer.id:
            return True
        return common_edit_object(self.room, viewer)


class PersonChatRoomMetadata(models.Model):
    person = models.ForeignKey(
        Person, on_delete=models.CASCADE, related_name="chatrooms_metadata"
    )
    chatroom = models.ForeignKey(
        ChatRoom, on_delete=models.CASCADE, related_name="persons_metadata"
    )
    last_read = models.ForeignKey(
        Message, on_delete=models.CASCADE, null=True, blank=True
    )
    last_email = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name="md_emails",
        null=True,
        blank=True,
    )


class UserActiveDate(models.Model):
    person = models.ForeignKey(Person, on_delete=models.CASCADE)
    date = models.DateField(auto_now_add=True)


class UserPostView(models.Model):
    person = models.ForeignKey(Person, on_delete=models.CASCADE)
    date = models.DateField(auto_now_add=True)
    post = models.ForeignKey(Post, on_delete=models.CASCADE)


post_save.connect(Post.post_save, sender=Post)
pre_delete.connect(Post.pre_delete, sender=Post)
post_save.connect(Comment.post_save, sender=Comment)
post_save.connect(Person.post_save, sender=Person)
pre_delete.connect(Person.pre_delete, sender=Person)
post_save.connect(Community.post_save, sender=Community)


def clear_index():
    index.clear_objects()
    person_index.clear_objects()


def partial_update_objs(objs):
    index.partial_update_objects(objs)
