from rest_framework import serializers
from .models import (
    Community,
    Person,
    Post,
    Comment,
    Channel,
    Link,
    Notification,
    Message,
    ChatRoom,
    CustomField,
    CustomFieldValue,
)
from django.core.exceptions import ObjectDoesNotExist
from django.contrib.auth.models import User
from rest_framework_recursive.fields import RecursiveField
from django.utils.html import strip_tags


def _get_vote(self, obj):
    person = self.context.get("person", False)
    return obj.user_vote(person) if person else False


def _get_editable(self, obj):
    person = self.context.get("person", False)
    return obj.can_edit(person) if person else False


def _validate_content(self, value):
    if len(strip_tags(value).strip()) <= 0:
        raise serializers.ValidationError("Content must not be blank")
    return value


class CommunityBasicSerializer(serializers.ModelSerializer):
    name = serializers.CharField(min_length=4, max_length=100)

    class Meta:
        model = Community
        fields = (
            "name",
            "private",
            "id",
            "welcome_message",
            "login_redirect",
            "auth_enabled",
        )


class BasicChannelSerializer(serializers.ModelSerializer):
    name = serializers.CharField(min_length=2, max_length=25)
    id = serializers.IntegerField(required=False)

    class Meta:
        model = Channel
        fields = ("id", "name", "private", "emoji", "post_admin_only")


class BasicPersonSerializer(serializers.ModelSerializer):
    photo_url = serializers.CharField()

    class Meta:
        model = Person
        fields = ("username", "id", "photo_url")
        read_only_fields = ("username", "id", "photo_url")


class ChannelSerializer(serializers.ModelSerializer):
    private_members = BasicPersonSerializer(many=True)

    class Meta:
        model = Channel
        fields = ("id", "name", "private", "emoji", "private_members")


class ChannelCreateEditSerializer(serializers.ModelSerializer):
    members = serializers.PrimaryKeyRelatedField(many=True, queryset=Person.objects)

    class Meta:
        model = Channel
        fields = ("name", "private", "emoji", "members")

    def create(self, validated_data):
        validated_data.pop("members", None)
        return super().create(validated_data)


class LinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = Link
        fields = ("label", "url")


class BasicChatRoomSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)

    class Meta:
        model = ChatRoom
        fields = ("id", "name")


class CustomFieldSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)

    class Meta:
        model = CustomField
        fields = ("id", "name")


class CommunitySerializer(serializers.ModelSerializer):
    channels = serializers.SerializerMethodField()
    name = serializers.CharField(min_length=4, max_length=100)
    admins = BasicPersonSerializer(many=True)
    links = LinkSerializer(many=True)
    chatrooms = BasicChatRoomSerializer(many=True)
    custom_fields = CustomFieldSerializer(many=True)

    def get_channels(self, obj):
        viewer = self.context.get("person", None)
        return BasicChannelSerializer(
            obj.allowed_channels(viewer).order_by("sort"), many=True
        ).data

    class Meta:
        model = Community
        fields = (
            "name",
            "private",
            "channels",
            "chatrooms",
            "id",
            "custom_stylesheet",
            "free",
            "display_name",
            "favicon",
            "links",
            "write_key",
            "custom_header",
            "auth_enabled",
            "track_anonymous",
            "welcome_message",
            "trusted",
            "admins",
            "invite_code",
            "photo",
            "custom_fields",
            "login_redirect",
            "logout_redirect",
        )
        read_only_fields = (
            "name",
            "private",
            "channels",
            "display_name",
            "custom_header",
            "chatrooms",
            "id",
            "favicon",
            "trusted",
            "auth_enabled",
            "free",
            "custom_stylesheet",
            "write_key",
            "welcome_message",
            "track_anonymous",
            "links",
            "admins",
            "invite_code",
            "photo",
            "custom_fields",
            "login_redirect",
            "logout_redirect",
        )


class CommunityEditSerializer(serializers.Serializer):
    channels = BasicChannelSerializer(many=True)
    links = LinkSerializer(many=True)
    chatrooms = BasicChatRoomSerializer(many=True)
    custom_fields = CustomFieldSerializer(many=True)

    logout_redirect = serializers.URLField(
        required=False, allow_blank=True, allow_null=True
    )
    login_redirect = serializers.URLField(
        required=False, allow_blank=True, allow_null=True
    )
    custom_css = serializers.CharField(
        max_length=25000, required=False, allow_blank=True, allow_null=True
    )
    write_key = serializers.CharField(
        max_length=40, required=False, allow_blank=True, allow_null=True
    )
    nice_name = serializers.CharField(
        max_length=100, required=False, allow_blank=True, allow_null=True
    )
    custom_header = serializers.CharField(
        max_length=5000, required=False, allow_blank=True, allow_null=True
    )

    track_anonymous = serializers.BooleanField(required=False)


class CustomFieldValueSerializer(serializers.ModelSerializer):
    field_name = serializers.CharField()

    class Meta:
        model = CustomFieldValue
        fields = ("field_name", "value")
        read_only_fields = ("field_name", "value")


class PersonSerializer(serializers.ModelSerializer):
    posts = serializers.SerializerMethodField()
    comments = serializers.SerializerMethodField()
    photo_url = serializers.CharField()
    editable = serializers.SerializerMethodField()
    edit_profile_redirect = serializers.URLField()
    custom_field_values = CustomFieldValueSerializer(many=True)

    def get_editable(self, obj):
        return _get_editable(self, obj)

    def get_posts(self, obj):
        return BasicPostSerializer(self.context.get("posts", []), many=True).data

    def get_comments(self, obj):
        return BasicCommentSerializer(self.context.get("comments", []), many=True).data

    class Meta:
        model = Person
        fields = (
            "username",
            "id",
            "posts",
            "comments",
            "photo_url",
            "custom_field_values",
            "admin",
            "bio",
            "editable",
            "edit_profile_redirect",
        )
        read_only_fields = (
            "username",
            "id",
            "posts",
            "custom_field_values",
            "photo_url",
            "admin",
            "comments",
            "bio",
            "editable",
            "edit_profile_redirect",
        )


class PersonEditSerializer(serializers.ModelSerializer):
    username = serializers.CharField(min_length=4, max_length=150)
    custom_fields_dict = serializers.DictField(
        required=False,
        allow_empty=True,
        child=serializers.CharField(allow_blank=True, allow_null=True),
    )

    class Meta:
        model = Person
        fields = ("username", "bio", "custom_fields_dict")


class NotificationCommentSerializer(serializers.ModelSerializer):
    points = serializers.IntegerField(read_only=True)

    class Meta:
        model = Comment
        fields = ("id", "post", "points")


class CommentSerializer(serializers.ModelSerializer):
    owner = BasicPersonSerializer()
    points = serializers.IntegerField(read_only=True)
    vote = serializers.SerializerMethodField()
    editable = serializers.SerializerMethodField()
    children = RecursiveField(many=True, required=False)

    def get_vote(self, obj):
        return _get_vote(self, obj)

    def get_editable(self, obj):
        return _get_editable(self, obj)

    class Meta:
        model = Comment
        fields = (
            "id",
            "owner",
            "points",
            "vote",
            "editable",
            "children",
            "posted",
            "content",
        )


class BasicPostSerializer(serializers.ModelSerializer):
    owner = BasicPersonSerializer()
    num_comments = serializers.IntegerField(read_only=True)
    points = serializers.IntegerField(read_only=True)
    vote = serializers.SerializerMethodField()
    editable = serializers.SerializerMethodField()
    channel = BasicChannelSerializer()

    def get_vote(self, obj):
        return _get_vote(self, obj)

    def get_editable(self, obj):
        return _get_editable(self, obj)

    class Meta:
        model = Post
        fields = (
            "id",
            "owner",
            "num_comments",
            "points",
            "content",
            "vote",
            "editable",
            "title",
            "views",
            "pinned",
            "posted",
            "channel",
        )
        read_only_fields = (
            "id",
            "owner",
            "num_comments",
            "points",
            "pinned",
            "vote",
            "content",
            "editable",
            "title",
            "views",
            "posted",
            "channel",
        )


class MinimalPostSerializer(serializers.ModelSerializer):
    class Meta:
        model = Post
        fields = ("title", "id")


class BasicCommentSerializer(serializers.ModelSerializer):
    post = MinimalPostSerializer()

    class Meta:
        model = Comment
        fields = ("id", "post", "content", "posted")


class PostSerializer(serializers.ModelSerializer):
    owner = BasicPersonSerializer()
    comments = CommentSerializer(many=True)
    points = serializers.IntegerField(read_only=True)
    vote = serializers.SerializerMethodField()
    editable = serializers.SerializerMethodField()
    channel = BasicChannelSerializer()

    def get_vote(self, obj):
        return _get_vote(self, obj)

    def get_editable(self, obj):
        return _get_editable(self, obj)

    class Meta:
        model = Post
        fields = (
            "id",
            "owner",
            "comments",
            "points",
            "vote",
            "pinned",
            "views",
            "editable",
            "title",
            "content",
            "posted",
            "channel",
        )
        read_only_fields = (
            "id",
            "owner",
            "comments",
            "pinned",
            "points",
            "vote",
            "views",
            "editable",
            "title",
            "content",
            "posted",
            "channel",
        )


class PostCreateEditSerializer(serializers.ModelSerializer):
    title = serializers.CharField(min_length=5, max_length=100)

    class Meta:
        model = Post
        fields = ("content", "title", "channel", "id")


class CommentCreateEditSerializer(serializers.ModelSerializer):
    def validate_content(self, value):
        return _validate_content(self, value)

    class Meta:
        model = Comment
        fields = ("content", "id", "parent")


class CreateCommuitySerializer(serializers.Serializer):
    registration_code = serializers.CharField(allow_blank=True)
    community_name = serializers.CharField(min_length=5, max_length=50)
    community_domain = serializers.CharField(min_length=5, max_length=50)
    community_private = serializers.BooleanField()

    account_username = serializers.CharField(min_length=4, max_length=50)
    account_email = serializers.EmailField()
    account_password = serializers.CharField(min_length=5)


class RegisterUserSerializer(serializers.ModelSerializer):
    community = serializers.CharField()
    displayname = serializers.CharField(min_length=4, max_length=150)
    invite_code = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )

    class Meta:
        model = User
        fields = ("displayname", "password", "email", "community", "invite_code")
        write_only_fields = ("password",)


class GoogleAuthSerializer(serializers.Serializer):
    community = serializers.CharField()
    google_token = serializers.CharField(max_length=5000)
    invite_code = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )


class PasswordResetSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("password",)
        write_only_fields = ("password",)


class RequestPasswordResetSerializer(serializers.Serializer):
    email = serializers.EmailField()


class BasicUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("username",)
        read_only_fields = ("username",)


class SelfSerializer(serializers.ModelSerializer):
    username = serializers.CharField()
    private_channels = BasicChannelSerializer(many=True)
    photo_url = serializers.CharField()
    edit_profile_redirect = serializers.URLField()

    class Meta:
        model = Person
        fields = (
            "username",
            "community",
            "email",
            "segment_user_id",
            "admin",
            "private_channels",
            "id",
            "edit_profile_redirect",
            "photo_url",
            "show_welcome",
        )
        read_only_fields = (
            "username",
            "community",
            "private_channels",
            "id",
            "email",
            "segment_user_id",
            "admin",
            "edit_profile_redirect",
            "photo_url",
            "show_welcome",
        )


class VoteSerializer(serializers.Serializer):
    vote = serializers.BooleanField()


class PinPostSerializer(serializers.Serializer):
    pinned = serializers.BooleanField()


class PersonUploadPhotoSerializer(serializers.ModelSerializer):
    photo = serializers.FileField(required=True)

    class Meta:
        model = Person
        fields = ("photo",)


class FileUploadSerializer(serializers.Serializer):
    file = serializers.FileField(required=True)
    content_type = serializers.CharField(max_length=200, required=True)


class CommunityUploadPhotoSerializer(serializers.ModelSerializer):
    photo = serializers.FileField(required=True)

    class Meta:
        model = Community
        fields = ("photo",)


class DirectMessageCreateSerializer(serializers.ModelSerializer):
    private_members = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Person.objects
    )

    class Meta:
        model = ChatRoom
        fields = ("id", "private_members")


class MessageCreateSerializer(serializers.ModelSerializer):
    sa_id = serializers.CharField(write_only=True)

    class Meta:
        model = Message
        fields = ("message", "sa_id")


class MessageSerializer(serializers.ModelSerializer):
    sender = BasicPersonSerializer()

    class Meta:
        model = Message
        fields = ("id", "message", "sender", "posted", "room")
        read_only_fields = ("id", "message", "sender", "posted", "room")


class ChatRoomSerializer(serializers.ModelSerializer):
    members = serializers.SerializerMethodField()
    last_message = MessageSerializer()
    unread = serializers.SerializerMethodField()

    def get_unread(self, obj):
        viewer = self.context.get("person", None)
        if not obj.last_message:
            return False
        if viewer:
            metadata = obj.persons_metadata.filter(person=viewer).first()
            if metadata and metadata.last_read:
                return (
                    obj.last_message.sender.id != viewer.id
                    and obj.last_message.id != metadata.last_read.id
                )
            else:
                return True

        return False

    def get_members(self, obj):
        if obj.room_type == ChatRoom.DIRECT:
            return BasicPersonSerializer(obj.private_members.all(), many=True).data
        else:
            return None

    class Meta:
        model = ChatRoom
        fields = (
            "id",
            "private",
            "name",
            "room_type",
            "members",
            "last_message",
            "unread",
        )
        read_only_fields = (
            "id",
            "private",
            "name",
            "room_type",
            "members",
            "last_message",
            "unread",
        )


class ChatRoomReadSerializer(serializers.Serializer):
    read = serializers.PrimaryKeyRelatedField(queryset=Message.objects)


class EmailInviteSerializer(serializers.Serializer):
    emails = serializers.ListField(child=serializers.CharField())


class ChannelMembersSerializer(serializers.Serializer):
    emails = serializers.ListField(child=serializers.EmailField())


class ChatRoomCreateSerializer(serializers.ModelSerializer):
    private_members = serializers.PrimaryKeyRelatedField(
        queryset=Person.objects, many=True
    )
    name = serializers.CharField(
        max_length=100, required=True, allow_blank=False, allow_null=False
    )

    class Meta:
        model = ChatRoom
        fields = ("id", "private_members", "private", "name")


class NotificationSerializer(serializers.ModelSerializer):
    action_taker = BasicPersonSerializer()
    target_post = BasicPostSerializer()
    target_comment = NotificationCommentSerializer()
    notification_type = serializers.SerializerMethodField()

    def get_notification_type(self, obj):
        return obj.get_notification_type_display()

    class Meta:
        model = Notification
        fields = (
            "read",
            "action_taker",
            "target_post",
            "target_comment",
            "time",
            "notification_type",
        )
        read_only_fields = (
            "read",
            "action_taker",
            "target_post",
            "target_comment",
            "time",
            "notification_type",
        )


class NotificationFrequencySerializer(serializers.ModelSerializer):
    class Meta:
        model = Person
        fields = ("notification_frequency", "digest_frequency")


class CommunityUploadFaviconSerializer(serializers.ModelSerializer):
    favicon = serializers.FileField(required=True)

    class Meta:
        model = Community
        fields = ("favicon",)


class CommunityPrivacySerializer(serializers.ModelSerializer):
    class Meta:
        model = Community
        fields = ("private",)


class External_CreateUserSerializer(serializers.Serializer):
    email = serializers.EmailField()
    username = serializers.CharField(min_length=4, max_length=150)


class External_PersonSerializer(serializers.ModelSerializer):
    username = serializers.CharField(min_length=4, max_length=150, required=False)
    bio = serializers.CharField(max_length=1000, required=False)
    email = serializers.EmailField(required=False)
    external_photo_url = serializers.URLField(max_length=300, required=False)
    edit_profile_redirect_url = serializers.URLField(max_length=100, required=False)
    segment_user_id = serializers.CharField(max_length=50, required=False)
    custom_fields_dict = serializers.DictField(
        required=False,
        allow_empty=True,
        child=serializers.CharField(allow_blank=True, allow_null=True),
    )

    class Meta:
        model = Person
        fields = (
            "id",
            "username",
            "bio",
            "email",
            "external_photo_url",
            "edit_profile_redirect_url",
            "segment_user_id",
            "custom_fields_dict",
        )
