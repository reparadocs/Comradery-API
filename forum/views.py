from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .serializers import *
from .models import *
from django.http import (
    Http404,
    HttpResponseForbidden,
    HttpResponseRedirect,
    HttpResponse,
)
from django.utils import timezone
from datetime import datetime, timedelta, date
from rest_framework.permissions import AllowAny
from .utils import *
from knox.models import AuthToken
from knox.views import LoginView as KnoxLoginView
from rest_framework.authentication import BasicAuthentication
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from algoliasearch.search_client import SearchClient
from django.core.exceptions import PermissionDenied, ObjectDoesNotExist
from django.db.models import Q, F, Count, Max
from django.contrib.auth.models import User
import redis
from .css_sanitize import validate_css
import boto3
from django.conf import settings
import io
import uuid
import os
import json
import django_rq
from .jobs import comment_created, object_liked, post_created
from .xredis import re_publish, re_get, re_set
from sentry_sdk import capture_exception
from postmark.core import PMMail
from google.oauth2 import id_token
from google.auth.transport import requests

client = SearchClient.create(settings.ALGOLIA_APPLICATION_ID, settings.ALGOLIA_ADMIN_KEY)


s3_client = boto3.client(
    "s3",
    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
)


class LoginAPI(KnoxLoginView):
    """
    Login endpoint.
    """

    authentication_classes = [
        BasicAuthentication,
    ]
    permission_classes = [
        IsAuthenticated,
    ]


class GoogleAuth(APIView):
    permission_classes = (AllowAny,)

    def post(self, request):
        serializer = GoogleAuthSerializer(data=request.data)
        serializer_check(serializer)
        community = Community.objects.get(name=serializer.validated_data["community"])
        invitation = None

        try:
            # Specify the CLIENT_ID of the app that accesses the backend:
            client_id = (
                settings.GOOGLE_AUTH_PROD 
                if "IN_HEROKU" in os.environ
                else settings.GOOGLE_AUTH_DEV
            )
            idinfo = id_token.verify_oauth2_token(
                serializer.validated_data["google_token"], requests.Request(), client_id
            )

            # Or, if multiple clients access the backend server:
            # idinfo = id_token.verify_oauth2_token(token, requests.Request())
            # if idinfo['aud'] not in [CLIENT_ID_1, CLIENT_ID_2, CLIENT_ID_3]:
            #     raise ValueError('Could not verify audience.')

            if idinfo["iss"] not in [
                "accounts.google.com",
                "https://accounts.google.com",
            ]:
                raise ValueError("Wrong issuer.")

            # ID token is valid. Get the user's Google Account ID from the decoded token.
            userid = idinfo["sub"]
            useremail = idinfo["email"]

            existing = Person.objects.filter(
                community=community, email=useremail
            ).first()

            if existing:
                token = AuthToken.objects.create(existing.user)
                return Response({"token": token[1], "id": existing.id})
            else:
                if community.read_only or not community.is_public():
                    if "invite_code" not in serializer.validated_data:
                        return response_400("Invite code required")

                    invitation = CommunityInvitation.objects.filter(
                        invite_code=serializer.validated_data["invite_code"],
                        community=community,
                    ).first()
                    if (
                        serializer.validated_data["invite_code"]
                        != community.invite_code
                        and not invitation
                    ):
                        return response_400("Invalid invitation to private community")

                user = User.objects.create_user(
                    username=django_username(community, useremail), password=None,
                )
                person = Person(
                    user=user,
                    email=useremail,
                    community=community,
                    username=idinfo["name"],
                    auth=Community.GOOGLE,
                )
                person.save()
                if invitation:
                    invitation.delete()
                analytics_identify(
                    person.id,
                    {
                        "username": person.username,
                        "email": person.email,
                        "community": community.name,
                    },
                )
                token = AuthToken.objects.create(user)
                return Response({"token": token[1], "id": person.id})
        except Exception:
            return response_400("Error with Google Auth")


class RegisterUser(APIView):
    permission_classes = (AllowAny,)

    def post(self, request):
        serializer = RegisterUserSerializer(data=request.data)
        serializer_check(serializer)
        community = Community.objects.get(name=serializer.validated_data["community"])
        invitation = None
        if community.read_only or not community.is_public():
            if "invite_code" not in serializer.validated_data:
                return response_400("Invite code required")

            invitation = CommunityInvitation.objects.filter(
                invite_code=serializer.validated_data["invite_code"],
                community=community,
            ).first()
            if (
                serializer.validated_data["invite_code"] != community.invite_code
                and not invitation
            ):
                return response_400("Invalid invitation to private community")

        if Person.objects.filter(
            community=community, email=serializer.validated_data["email"]
        ).exists():
            return response_400("User with this email already exists")
        if Person.objects.filter(
            community=community, username=serializer.validated_data["displayname"]
        ).exists():
            return response_400("Username already taken")
        user = User.objects.create_user(
            username=django_username(community, serializer.validated_data["email"]),
            password=serializer.validated_data["password"],
        )
        person = Person(
            user=user,
            email=serializer.validated_data["email"],
            community=community,
            username=serializer.validated_data["displayname"],
        )
        person.save()
        if invitation:
            invitation.delete()
        analytics_identify(
            person.id,
            {
                "username": person.username,
                "email": person.email,
                "community": community.name,
            },
        )
        token = AuthToken.objects.create(user)
        return Response({"token": token[1], "id": person.id})


class PasswordReset(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        serializer = PasswordResetSerializer(data=request.data)
        serializer_check(serializer)
        request.user.set_password(serializer.validated_data["password"])
        request.user.save()
        return Response("OK")


class RequestPasswordReset(APIView):
    permission_classes = (AllowAny,)

    def post(self, request, community_url):
        community_id = Community.id_from_host(community_url)
        community = Community.objects.get(id=community_id)
        serializer = RequestPasswordResetSerializer(data=request.data)
        serializer_check(serializer)
        try:
            person = Person.objects.get(
                email=serializer.validated_data["email"], community=community
            )
        except ObjectDoesNotExist:
            return Response("OK")

        if (
            person.last_reset
            and (timezone.now() - timedelta(days=1)) < person.last_reset
        ):
            return response_400("Password reset already sent today")
        token = AuthToken.objects.create(user=person.user)
        try:
            dt_data = {
                "community_name": community.display_name,
                "community_url": community.get_domain(),
                "action_url": community.get_domain()
                + "/password_reset?token="
                + token[1],
            }
            pm = PMMail(
                to=person.email,
                sender=community.display_name
                + " Notifications notifications@comradery.io",
                template_id=settings.POSTMARK_PASSWORD_RESET_TEMPLATE_ID,
                template_model=dt_data,
            )
            pm.send()
            person.last_reset = timezone.now()
            person.save()
            return Response("OK")
        except Exception as e:
            capture_exception(e)
            return response_400("Something went wrong")


class SearchKey(APIView):
    permission_classes = (AllowAny,)

    def get(self, request, community_url):
        community_id = Community.id_from_host(community_url)
        community = get_object(Community, community_id, request)
        if request.user.is_authenticated:
            allowed_channels = community.allowed_channels(request.user.person)
        else:
            allowed_channels = community.allowed_channels(None)
        rc_filter_string = generate_filter_string(allowed_channels)
        print(rc_filter_string)
        key = client.generate_secured_api_key(
            settings.ALGOLIA_SEARCH_KEY,
            {"filters": "community:" + str(community.id) + rc_filter_string},
        )
        return Response({"key": key})


class Self(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        person = request.user.person
        serializer = SelfSerializer(person)
        return Response(serializer.data)


class CommunityList(APIView):
    permission_classes = (AllowAny,)

    def get(self, request):
        communities = Community.objects.filter(private=False)
        serializer = CommunityBasicSerializer(communities, many=True)
        return Response(serializer.data)


class CommunityCreate(APIView):
    permission_classes = (AllowAny,)

    def post(self, request):
        serializer = CreateCommuitySerializer(data=request.data)
        if not serializer.is_valid():
            return response_400(serializer.errors)

        beta = ComraderyBetaInvitation.objects.filter(
            registration_code=serializer.validated_data["registration_code"]
        ).first()
        if not beta:
            return response_400(
                "Registration code incorrect. Contact us for a Comradery invitation (hello@comradery.io)"
            )

        if Community.objects.filter(
            name=serializer.validated_data["community_domain"]
        ).exists():
            return response_400("Domain taken, choose another domain")

        community = Community(
            name=serializer.validated_data["community_domain"],
            nice_name=serializer.validated_data["community_name"],
            private=serializer.validated_data["community_private"],
        )
        community.save()
        beta.delete()

        user = User.objects.create_user(
            username=django_username(community, "hello@comradery.io"),
            password="!dUjEabKTXgJExdK2Uz8",
        )
        person = Person(
            user=user,
            email="hello@comradery.io",
            notification_frequency=Person.NEVER,
            community=community,
            username="Rishab",
            admin=True,
            external_photo_url="https://" + settings.AWS_S3_CUSTOM_DOMAIN + "/media/media/27f4f11838ff4a1e8e317ced3564b7d2",
        )
        person.save()

        gen_channel = Channel.objects.get(community=community, name="General")
        questions_channel = Channel.objects.get(community=community, name="Q & A")

        post = Post(
            owner=person,
            title="1. Setup Your Community",
            channel=gen_channel,
            content='<div><p>First things first, let’s get your community set up the way you like it! Click on your picture in the top right corner ↗﻿and then click “Admin Panel”.</p><p><br></p><p><img src="https://dxgxk48g318ck.cloudfront.net/post_files/cam/18fe30f0-8d41-491b-a5db-c694acf7082c.png" style="" width="192" height="273.70212765957444"></p><p><br></p><p><br></p><p>From here, we’ve broken it down into 4 simple steps.</p><p><br></p><ol><li><strong>Create your Discussion Channels</strong>. These channels serve as guidelines for where you want your members to post and discuss certain topics. Add 2 more that are specific to your community. (We’ve already started you with 3).</li><li><strong>Create your Chatrooms</strong>. These chatrooms are for real time conversation between your members. Add one more chat room that’s relevant to your community.</li><li><strong>Customize your Community</strong>. Head to the Customization tab where you can upload your logo. If you’re part of our Standard plan, adjust your community’s colors to match your brand.</li><li><strong>Invite your members! </strong>Head to the Invite tab to invite members via email or grab your link to share to anyone who wants to join in.</li></ol><p><br></p><p>Now once you have everything set up just the way you like and have invited your members, we suggest creating a few posts and sending a few messages in the chatrooms so that they don’t feel empty! 😃 </p></div>',
        )
        post.save()
        post.rescore()

        post = Post(
            owner=person,
            title="2. Managing Your Community",
            channel=gen_channel,
            content='<div><p>As a community builder, we know that you want your community to have a safe and trusted place online to hang out and we’re dedicated to helping you achieve that goal! </p><p><br></p><p>As an admin, you have full access to everything - you can edit or delete any posts, comments, and user profiles. For example, you probably want to delete this post, so simply hit the edit button up top ☝﻿and then click “Delete Post”!</p><p><img src="https://dxgxk48g318ck.cloudfront.net/post_files/cam/bbe6ca30-81bc-4bcf-9642-c36945c30b8f.png" style="" width="176" height="95.06273062730628"></p><p><br></p><p>We’re in the process of building out more advanced moderation tools and will keep you updated as we release them! If there are any specific requests, please let us know 😊 </p></div>',
        )
        post.save()
        post.posted = timezone.now() - timedelta(days=1)
        post.save()
        post.rescore()

        post = Post(
            owner=person,
            title="3. Support and Feedback",
            channel=questions_channel,
            content='<div><p>Are you running into any problems or have feedback for us? We’d love to hear it and help out! </p><p><br></p><p>Simply send an email to us: <a href="mailto:hello@comradery.io" rel="noopener noreferrer nofollow" target="_blank">hello@comradery.io</a> or you can send us a DM (check your chats <span class="ql-emojiblot">﻿<span><span class="ap ap-point_left">👈</span></span>﻿</span>) and we’ll get back to you ASAP!</p><p><br></p><p>Thanks so much! <span class="ql-emojiblot">﻿<span><span class="ap ap-raised_hands">🙌</span></span>﻿</span> </p></div>',
        )
        post.save()
        post.posted = timezone.now() - timedelta(days=2)
        post.save()
        post.rescore()

        user = User.objects.create_user(
            username=django_username(
                community, serializer.validated_data["account_email"]
            ),
            password=serializer.validated_data["account_password"],
        )
        u_person = Person(
            user=user,
            email=serializer.validated_data["account_email"],
            community=community,
            username=serializer.validated_data["account_username"],
            admin=True,
        )
        u_person.save()

        new_room = ChatRoom(
            private=True, room_type=ChatRoom.DIRECT, community=community,
        )
        new_room.save()
        new_room.private_members.add(person)
        new_room.private_members.add(u_person)

        message = Message.objects.create(
            sender=person,
            room=new_room,
            message="Hi! I’m Rishab from Comradery - thank you so much for trying us out. I’d love to help in anyway I can. Feel free to respond here if you ever have any problems, feedback, questions, feature requests, etc. and we’ll reply as soon as we can 🙂",
        )

        token = AuthToken.objects.create(user)
        return Response(
            {
                "token": token[1],
                "id": person.id,
                "domain": "https://" + community.name + ".comradery.io",
            }
        )


class CommunityPrivacy(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request, community_url):
        community_id = Community.id_from_host(community_url)
        community = get_object(Community, community_id, request)

        if not community.can_edit(request.user.person):
            raise PermissionDenied

        serializer = CommunityPrivacySerializer(community, data=request.data)
        serializer_check(serializer)

        serializer.save()
        return Response(serializer.data)


class CommunityDetail(APIView):
    permission_classes = (IsAuthenticatedOrReadOnly,)

    def get(self, request, community_url):
        community_id = Community.id_from_host(community_url)
        try:
            community = get_object(Community, community_id, request)
            serializer = CommunitySerializer(community, context=person_context(request))
        except Http404:
            community = Community.objects.get(id=community_id)
            serializer = CommunityBasicSerializer(community)
        return Response(serializer.data)

    def post(self, request, community_url):
        community_id = Community.id_from_host(community_url)
        community = get_object(Community, community_id, request)

        if not community.can_edit(request.user.person):
            raise PermissionDenied
        serializer = CommunityEditSerializer(data=request.data)
        serializer_check(serializer)

        if "custom_css" in serializer.validated_data:
            sanitize = validate_css(serializer.validated_data["custom_css"])
            if sanitize[1]:
                return response_400("CSS Error")
            else:
                filename = uuid.uuid4().hex
                uploaded = s3_client.upload_fileobj(
                    io.BytesIO(sanitize[0]),
                    "comradery-assets",
                    filename + ".css",
                    ExtraArgs={"ACL": "public-read", "ContentType": "text/css"},
                )
                community.custom_stylesheet = (
                    "https://" + settings.AWS_S3_CUSTOM_DOMAIN + "/" + filename + ".css"
                )
                community.save()

        new_channels = []
        new_rooms = []
        new_fields = []

        if "logout_redirect" in serializer.validated_data:
            community.logout_redirect = serializer.validated_data["logout_redirect"]
        if "login_redirect" in serializer.validated_data:
            community.login_redirect = serializer.validated_data["login_redirect"]
        if "write_key" in serializer.validated_data:
            community.write_key = serializer.validated_data["write_key"]
        if "track_anonymous" in serializer.validated_data:
            community.track_anonymous = serializer.validated_data["track_anonymous"]
        if "nice_name" in serializer.validated_data:
            community.nice_name = serializer.validated_data["nice_name"]
        if "custom_header" in serializer.validated_data:
            community.custom_header = serializer.validated_data["custom_header"]

        community.save()

        Link.objects.filter(community=community).delete()
        for link in serializer.validated_data["links"]:
            l = Link(**link, community=community)
            l.save()

        for idx, room in enumerate(serializer.validated_data["chatrooms"]):
            if "id" in room:
                if ChatRoom.objects.filter(pk=room["id"], community=community).exists():
                    new_rooms.append(room["id"])
                    ChatRoom.objects.filter(pk=room["id"], community=community).update(
                        **room, community=community
                    )
                else:
                    return response_400("No existing room matches ID")
            else:
                c = ChatRoom(
                    **room, private=False, room_type=ChatRoom.ROOM, community=community
                )
                c.save()
                new_rooms.append(c.id)

        ChatRoom.objects.filter(community=community, room_type=ChatRoom.ROOM).exclude(
            pk__in=new_rooms
        ).delete()

        for idx, channel in enumerate(serializer.validated_data["channels"]):
            channel["sort"] = idx
            if "id" in channel:
                if Channel.objects.filter(
                    pk=channel["id"], community=community
                ).exists():
                    new_channels.append(channel["id"])
                    Channel.objects.filter(
                        pk=channel["id"], community=community
                    ).update(**channel, community=community)
                else:
                    return response_400("No existing channel matches ID")
            else:
                c = Channel(**channel, community=community)
                c.save()
                new_channels.append(c.id)

        Channel.objects.filter(community=community).exclude(
            pk__in=new_channels
        ).delete()

        for idx, field in enumerate(serializer.validated_data["custom_fields"]):
            field["sort"] = idx
            if "id" in field:
                if CustomField.objects.filter(
                    pk=field["id"], community=community
                ).exists():
                    new_fields.append(field["id"])
                    CustomField.objects.filter(
                        pk=field["id"], community=community
                    ).update(**field, community=community)
                else:
                    return response_400("No existing field matches ID")
            else:
                c = CustomField(**field, community=community)
                c.save()
                new_fields.append(c.id)

        CustomField.objects.filter(community=community).exclude(
            pk__in=new_fields
        ).delete()

        analytics_event(request, "Admin_Settings", serializer.validated_data)
        return Response(serializer.data)


class CommunityUploadPhoto(APIView):
    def put(self, request, community_url, format=None):
        community_id = Community.id_from_host(community_url)
        community = get_object(Community, community_id, request)
        if not community.can_edit(request.user.person):
            raise PermissionDenied
        serializer = CommunityUploadPhotoSerializer(community, data=request.data)
        serializer_check(serializer)

        community = serializer.save()
        analytics_event(request, "Admin_Upload_Photo", {"photo": community.photo.url})
        return Response({"photo_url": community.photo.url})


class CommunityUploadFavicon(APIView):
    def put(self, request, community_url, format=None):
        community_id = Community.id_from_host(community_url)
        community = get_object(Community, community_id, request)
        if not community.can_edit(request.user.person):
            raise PermissionDenied
        serializer = CommunityUploadFaviconSerializer(community, data=request.data)
        serializer_check(serializer)

        community = serializer.save()
        analytics_event(
            request, "Admin_Upload_Favicon", {"favicon": community.favicon.url}
        )
        return Response({"favicon_url": community.favicon.url})


class PostCreate(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        serializer = PostCreateEditSerializer(data=request.data)
        serializer_check(serializer)
        channel = serializer.validated_data["channel"]
        channel = get_object(Channel, channel.id, request)
        if request.user.person.admin or not channel.post_admin_only:
            sanitized_content = sanitize_html(serializer.validated_data["content"])
            post = serializer.save(owner=request.user.person, content=sanitized_content)
            post.upvotes.add(request.user.person)
            post.rescore()
            django_rq.enqueue(post_created, post)
            analytics_event(request, "Post_Created", serializer.data)
            return Response(serializer.data)
        else:
            return response_400("Admin only channel")


class PostDetail(APIView):
    permission_classes = (IsAuthenticatedOrReadOnly,)

    def post(self, request, post_id):
        post = edit_object(Post, post_id, request)
        serializer = PostCreateEditSerializer(post, data=request.data)
        serializer_check(serializer)
        sanitized_content = sanitize_html(serializer.validated_data["content"])
        serializer.save(content=sanitized_content)
        analytics_event(request, "Post_Edited", serializer.data)
        return Response(serializer.data)

    def get(self, request, post_id):
        post = get_object(Post, post_id, request)

        if request.user.is_authenticated:
            if not UserPostView.objects.filter(
                person=request.user.person, date=date.today(), post=post
            ).exists():
                upv = UserPostView(person=request.user.person, post=post)
                upv.save()

        post.views = F("views") + 1
        post.save()
        post.refresh_from_db()
        serializer = PostSerializer(post, context=person_context(request))
        return Response(serializer.data)

    def delete(self, request, post_id):
        post = edit_object(Post, post_id, request)
        post.user_delete()
        analytics_event(request, "Post_Deleted", {"id": post.id})
        serializer = PostSerializer(post, context=person_context(request))
        return Response(serializer.data)


class CommentCreate(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request, post_id):
        post = get_object(Post, post_id, request)
        serializer = CommentCreateEditSerializer(data=request.data)
        serializer_check(serializer)
        sanitized_content = sanitize_html(serializer.validated_data["content"])
        comment = serializer.save(
            post=post, owner=request.user.person, content=sanitized_content
        )
        comment.upvotes.add(request.user.person)
        comment.rescore()

        serializer = CommentSerializer(comment, context=person_context(request))
        django_rq.enqueue(comment_created, comment)
        analytics_event(request, "Comment_Created", serializer.data)
        return Response(serializer.data)


class CommentDetail(APIView):
    permission_classes = (IsAuthenticatedOrReadOnly,)

    def post(self, request, comment_id):
        old_comment = edit_object(Comment, comment_id, request)
        serializer = CommentCreateEditSerializer(old_comment, data=request.data)
        serializer_check(serializer)
        sanitized_content = sanitize_html(serializer.validated_data["content"])
        serializer.save(content=sanitized_content)
        analytics_event(request, "Comment_Edited", serializer.data)
        return Response(serializer.data)

    def get(self, request, comment_id):
        comment = get_object(Comment, comment_id, request)
        serializer = CommentSerializer(comment, context=person_context(request))
        return Response(serializer.data)

    def delete(self, request, comment_id):
        comment = edit_object(Comment, comment_id, request)
        analytics_event(request, "Comment_Deleted", {"id": comment.id})

        deleted = comment.user_delete()
        if not deleted:
            serializer = CommentSerializer(comment, context=person_context(request))
            return Response(serializer.data)
        else:
            return Response("OK")


def common_voting(request, obj, obj_type):
    serializer = VoteSerializer(data=request.data)
    serializer_check(serializer)
    if serializer.validated_data["vote"]:
        if not obj.upvotes.filter(pk=request.user.person.id).exists():
            obj.upvotes.add(request.user.person)
            django_rq.enqueue(object_liked, obj, obj_type, request.user.person)
            analytics_event(request, obj_type + "_Vote", {"id": obj.id})
    else:
        if obj.upvotes.filter(pk=request.user.person.id).exists():
            obj.upvotes.remove(request.user.person)
            analytics_event(request, obj_type + "_Unvote", {"id": obj.id})
    obj.rescore()
    return Response({"vote": obj.user_vote(request.user.person), "points": obj.points})


class CommentVote(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request, comment_id):
        comment = get_object(Comment, comment_id, request)
        return common_voting(request, comment, "Comment")


class PostVote(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request, post_id):
        post = get_object(Post, post_id, request)
        return common_voting(request, post, "Post")


def filter_order_posts_by_request(request):
    sort_query = request.query_params.get("sort")
    if sort_query == "new":
        return Post.objects.order_by("-posted")
    if sort_query == "top":
        time = request.query_params.get("time")
        rtn = Post.objects.annotate(u_count=Count("upvotes")).order_by("-u_count")
        if time == "day":
            return rtn.filter(posted__gte=timezone.now() - timedelta(days=1))
        if time == "week":
            return rtn.filter(posted__gte=timezone.now() - timedelta(days=7))
        if time == "month":
            return rtn.filter(posted__gte=timezone.now() - timedelta(days=30))
        if time == "year":
            return rtn.filter(posted__gte=timezone.now() - timedelta(days=365))
        if time == "all":
            return rtn.all()
    return Post.objects.order_by("-pinned", "-score")


class CommunityPostList(APIView):
    permission_classes = (IsAuthenticatedOrReadOnly,)

    def get(self, request, community_url):
        community_id = Community.id_from_host(community_url)
        community = get_object(Community, community_id, request)
        posts = filter_order_posts_by_request(request)
        channel_query = request.query_params.get("channel")
        page = request.query_params.get("page", 1)
        if channel_query:
            channel = int(channel_query)
            posts = posts.filter(channel=channel)
        else:
            posts = posts.filter(
                Q(
                    channel__in=community.allowed_channels(
                        request.user.person if request.user.is_authenticated else None
                    )
                )
                | Q(channel=None),
            )
        posts = posts.filter(active=True, community=community)
        paged_posts, page_info = get_page_info(page, posts)
        serializer = BasicPostSerializer(
            paged_posts, many=True, context=person_context(request)
        )
        page_info.update({"data": serializer.data})
        return Response(page_info)


class ChannelList(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        channels = request.user.person.community.allowed_channels(request.user.person)
        serializer = BasicChannelSerializer(channels, many=True)
        return Response(serializer.data)

    def post(self, request):
        if not request.user.person.admin:
            return response_400("Not an admin")
        serializer = ChannelCreateEditSerializer(data=request.data)
        serializer_check(serializer)

        members = serializer.validated_data["members"]
        channel = serializer.save(community=request.user.person.community)

        for m in members:
            if m.community != request.user.person.community:
                return response_400("Some members don't belong in your community")

        channel.private_members.add(*members)
        serializer = ChannelSerializer(channel)
        return Response(serializer.data)


class ChannelDetail(APIView):
    permission_classes = (IsAuthenticatedOrReadOnly,)

    def get(self, request, channel_id):
        channel = get_object(Channel, channel_id, request)
        serializer = ChannelSerializer(channel)
        return Response(serializer.data)

    def post(self, request, channel_id):
        channel = edit_object(Channel, channel_id, request)
        serializer = ChannelCreateEditSerializer(channel, data=request.data)
        serializer_check(serializer)
        members = serializer.validated_data["members"]

        for m in members:
            if m.community != request.user.person.community:
                return response_400("Some members don't belong in your community")

        channel.private_members.clear()
        channel.private_members.add(*members)

        serializer.save()
        serializer = ChannelSerializer(channel)
        return Response(serializer.data)


def common_channel_members(request):
    serializer = ChannelMembersSerializer(data=request.data)
    serializer_check(serializer)
    emails = serializer.validated_data["emails"]
    members = []

    for e in emails:
        try:
            p = Person.objects.get(email=e, community=request.user.person.community)
            members.append(p)
        except ObjectDoesNotExist:
            return None

    return members


class ChannelAddMembers(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request, channel_id):
        channel = edit_object(Channel, channel_id, request)
        members = common_channel_members(request)
        if not members:
            return response_400("Some members don't exist in your community")

        channel.private_members.add(*members)
        serializer = ChannelSerializer(channel)
        return Response(serializer.data)


class ChannelRemoveMembers(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request, channel_id):
        channel = edit_object(Channel, channel_id, request)
        members = common_channel_members(request)
        if not members:
            return response_400("Some members don't exist in your community")

        channel.private_members.remove(*members)
        serializer = ChannelSerializer(channel)
        return Response(serializer.data)


class CommunityEmailInvite(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request, community_url):
        community_id = Community.id_from_host(community_url)

        community = get_object(Community, community_id, request)
        if not community.can_edit(request.user.person):
            raise PermissionDenied

        serializer = EmailInviteSerializer(data=request.data)
        serializer_check(serializer)

        email_status_dict = {}
        for email in serializer.validated_data["emails"]:
            if Person.objects.filter(community=community, email=email).exists():
                email_status_dict[email] = "Error: User already exists"
            elif CommunityInvitation.objects.filter(
                community=community, email=email
            ).exists():
                email_status_dict[email] = "Error: Invite Sent Previously"
            elif CommunityInvitation.objects.filter(community=community).count() > 1000:
                email_status_dict[email] = "Error: Email Invite Limit Hit!"
            else:
                ci = CommunityInvitation(community=community, email=email)
                ci.save()

                dt_data = {
                    "community_name": community.display_name,
                    "logo": community.photo.url if community.photo else None,
                    "action_url": community.get_domain()
                    + "?invite_code="
                    + ci.invite_code,
                }

                try:
                    pm = PMMail(
                        to=email,
                        sender=community.display_name
                        + " Invitation invitations@comradery.io",
                        template_id=settings.POSTMARK_INVITATION_TEMPLATE_ID,
                        template_model=dt_data,
                    )
                    pm.send()
                    email_status_dict[email] = "Success! Invite Sent"
                except Exception as e:
                    capture_exception(e)
                    ci.delete()
                    email_status_dict[email] = "Error: Couldn't send email"

        return Response(email_status_dict)


class CommunityPersonList(APIView):
    permission_classes = (IsAuthenticatedOrReadOnly,)

    def get(self, request, community_url):
        community_id = Community.id_from_host(community_url)
        community = get_object(Community, community_id, request)
        people = Person.objects.filter(community=community, superadmin_api_only=False)
        serializer = BasicPersonSerializer(people, many=True)
        return Response(serializer.data)


class PersonDetail(APIView):
    permission_classes = (IsAuthenticatedOrReadOnly,)

    def post(self, request, person_id):
        person = edit_object(Person, person_id, request)
        serializer = PersonEditSerializer(person, data=request.data)
        serializer_check(serializer)
        if "custom_fields_dict" in serializer.validated_data:
            for k, v in serializer.validated_data["custom_fields_dict"].items():
                print(k)
                print(v)
                cf = CustomField.objects.get(name=k, community=person.community)
                cfv = CustomFieldValue.objects.filter(field=cf, person=person).first()
                if cfv:
                    cfv.value = v
                else:
                    cfv = CustomFieldValue(field=cf, person=person, value=v)
                cfv.save()
        serializer.save()
        analytics_event(request, "Person_Edited", serializer.data)
        return Response(serializer.data)

    def get(self, request, person_id):
        person = get_object(Person, person_id, request)
        posts = person._posts.filter(
            Q(
                channel__in=person.shared_channels(
                    request.user.person if request.user.is_authenticated else None
                )
            )
            | Q(channel=None)
        )
        comments = person._comments.filter(
            Q(
                post__channel__in=person.shared_channels(
                    request.user.person if request.user.is_authenticated else None
                )
            )
            | Q(post__channel=None)
        ).exclude(post__title="[deleted]")
        serializer = PersonSerializer(
            person,
            context={
                **person_context(request),
                **{"posts": posts, "comments": comments},
            },
        )

        return Response(serializer.data)

    def delete(self, request, person_id):
        if not request.user.person.admin:
            return response_400("Not an admin")

        person = edit_object(Person, person_id, request)
        person.user_delete()
        analytics_event(request, "Person_Deleted", {"id": person.id})
        return Response("Deleted")


class PinPost(APIView):
    def post(self, request, post_id, format=None):
        post = edit_object(Post, post_id, request)
        serializer = PinPostSerializer(data=request.data)
        serializer_check(serializer)
        if not request.user.person.admin:
            raise PermissionDenied
        post.pinned = serializer.validated_data["pinned"]
        post.save()
        return Response("OK")


class PersonUploadPhoto(APIView):
    def put(self, request, person_id, format=None):
        person = edit_object(Person, person_id, request)
        serializer = PersonUploadPhotoSerializer(person, data=request.data)
        serializer_check(serializer)

        person = serializer.save()
        analytics_event(request, "Person_Upload_Photo", {"photo": person.photo_url})
        return Response({"photo_url": person.photo_url})


MAX_UPLOAD_SIZE = 20971520


class PostFileUpload(APIView):
    permission_classes = (IsAuthenticated,)

    def put(self, request, filename, format=None):
        serializer = FileUploadSerializer(data=request.data)
        serializer_check(serializer)
        file_obj = serializer.validated_data["file"]
        if file_obj.size > MAX_UPLOAD_SIZE:
            return response_400("Files must be under 20mb")
        path = "post_files/" + request.user.person.community.name + "/" + filename
        uploaded = s3_client.upload_fileobj(
            file_obj,
            "comradery-assets",
            path,
            ExtraArgs={
                "ACL": "public-read",
                "ContentType": serializer.validated_data["content_type"],
            },
        )
        return Response({"file_url": "https://" + settings.AWS_S3_CUSTOM_DOMAIN + "/" + path})


class ChatRoomList(APIView):
    permission_classes = (IsAuthenticatedOrReadOnly,)

    def get(self, request, community_url):
        community_id = Community.id_from_host(community_url)
        community = get_object(Community, community_id, request)
        rooms = (
            community.allowed_chatrooms(
                request.user.person if request.user.is_authenticated else None
            )
            .annotate(
                msg_count=Count("messages"),
                last_message_posted=Max("messages__posted"),
            )
            .filter(Q(msg_count__gt=0) | Q(private=False))
            .order_by("-last_message_posted")
        )
        serializer = ChatRoomSerializer(
            rooms, many=True, context=person_context(request)
        )
        return Response(serializer.data)

    def post(self, request, community_url):
        community_id = Community.id_from_host(community_url)
        community = get_object(Community, community_id, request)
        if (
            request.user.person.community.id != community.id
            or not request.user.person.admin
        ):
            raise PermissionDenied
        serializer = ChatRoomCreateSerializer(
            data=request.data, context={"community": community}
        )
        serializer_check(serializer)
        members = serializer.validated_data["private_members"]
        for m in members:
            if m.community != request.user.person.community:
                return response_400("Some members don't belong in your community")
        serializer.save(community=community, room_type=ChatRoom.ROOM)
        return Response(serializer.data)


class ChatRoomRead(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request, room_id):
        room = get_object(ChatRoom, room_id, request)
        serializer = ChatRoomReadSerializer(data=request.data)
        serializer_check(serializer)
        metadata = PersonChatRoomMetadata.objects.filter(
            chatroom=room, person=request.user.person
        ).first()
        if metadata:
            metadata.last_read = serializer.validated_data["read"]
        else:
            metadata = PersonChatRoomMetadata(
                chatroom=room,
                person=request.user.person,
                last_read=serializer.validated_data["read"],
            )
        metadata.save()

        return Response("OK")


class ChatRoomDetail(APIView):
    permission_classes = (IsAuthenticatedOrReadOnly,)

    def get(self, request, room_id):
        room = get_object(ChatRoom, room_id, request)
        serializer = ChatRoomSerializer(room, context=person_context(request))
        return Response(serializer.data)


class DirectMessageCreate(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        serializer = DirectMessageCreateSerializer(
            data=request.data, context={"community": request.user.person.community}
        )
        serializer_check(serializer)
        members = serializer.validated_data["private_members"]
        if len(members) <= 1:
            return response_400("Not enough members to chat")
        for m in members:
            if m.community != request.user.person.community:
                return response_400("Some members don't belong in your community")
        candidate_dms = ChatRoom.objects.annotate(c=Count("private_members")).filter(
            c=len(members), community=request.user.person.community
        )
        for member in members:
            candidate_dms = candidate_dms.filter(private_members=member)
        if candidate_dms.exists():
            serializer = ChatRoomSerializer(
                candidate_dms.first(), context=person_context(request)
            )
        else:
            new_room = serializer.save(
                private=True,
                room_type=ChatRoom.DIRECT,
                community=request.user.person.community,
            )
            serializer = ChatRoomSerializer(new_room, context=person_context(request))
        re_publish("system_message", json.dumps(serializer.data))
        return Response(serializer.data)


class ChatRoomMessages(APIView):
    permission_classes = (IsAuthenticatedOrReadOnly,)

    def get(self, request, room_id):
        page = request.query_params.get("page", 1)
        chatroom = get_object(ChatRoom, room_id, request)
        messages = Message.objects.filter(room=chatroom).order_by("-posted")
        paged_messages, page_info = get_page_info(page, messages, 50)
        serializer = MessageSerializer(paged_messages, many=True)
        page_info.update({"data": serializer.data})
        return Response(page_info)


class MessageDetail(APIView):
    permission_classes = (IsAuthenticated,)

    def delete(self, request, message_id):
        message = edit_object(Message, message_id, request)

        re_publish(
            message.room.id, json.dumps({"delete": message.id, "room": message.room.id})
        )
        message.message = "[deleted]"
        message.save()
        return Response("Deleted")


class CreateMessage(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request, room_id):
        chatroom = get_object(ChatRoom, room_id, request)

        serializer = MessageCreateSerializer(data=request.data)
        serializer_check(serializer)

        message = Message.objects.create(
            sender=request.user.person,
            room=chatroom,
            message=serializer.validated_data["message"],
        )
        redis_blob = {"sa_id": serializer.validated_data["sa_id"]}

        serializer = MessageSerializer(message)
        redis_blob.update(serializer.data)
        re_publish(message.room.id, json.dumps(redis_blob))

        if (
            chatroom.room_type == ChatRoom.DIRECT
            and chatroom.private_members.filter(email="hello@comradery.io").exists()
        ):
            pm = PMMail(
                to="hello@comradery.io",
                sender=request.user.person.community.name.capitalize()
                + " Support notifications@comradery.io",
                template_id=settings.POSTMARK_NOTIFICATION_TEMPLATE_ID,
                template_model={
                    "community_name": request.user.person.community.name,
                    "domain": request.user.person.community.get_domain(),
                    "message": message.message,
                },
            )
            pm.send()
        return Response(serializer.data)


class External_CreateUser(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        superadmin_api_check(request)
        serializer = External_CreateUserSerializer(data=request.data)
        serializer_check(serializer)
        if User.objects.filter(
            username=django_username(
                community=request.user.person.community,
                email=serializer.validated_data["email"],
            )
        ).exists():
            return response_400("User with that email already exists")
        if Person.objects.filter(
            community=request.user.person.community,
            username=serializer.validated_data["username"],
        ).exists():
            return response_400("Username already taken")
        user = User.objects.create_user(
            username=django_username(
                community=request.user.person.community,
                email=serializer.validated_data["email"],
            ),
            password=None,
        )
        person = Person(
            user=user,
            email=serializer.validated_data["email"],
            community=request.user.person.community,
            username=serializer.validated_data["username"],
        )
        person.save()
        analytics_identify(
            person.id,
            {
                "username": person.username,
                "email": person.email,
                "community": person.community.name,
            },
        )
        token = AuthToken.objects.create(user)
        serializer = External_PersonSerializer(person)
        return Response({"token": token[1], "person": serializer.data})


class External_LoginUser(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request, person_email):
        person_id = get_obj_id_from_trait(Person, "email", person_email, request)
        person = edit_object(Person, person_id, request)

        superadmin_api_check(request)

        token = AuthToken.objects.create(person.user)
        analytics_event(request, "API_Login", {"id": person.id})
        return Response({"token": token[1]})


class External_PersonDetail(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, person_email):
        person_id = get_obj_id_from_trait(Person, "email", person_email, request)
        person = get_object(Person, person_id, request)

        superadmin_api_check(request)

        serializer = External_PersonSerializer(person)
        return Response(serializer.data)

    def post(self, request, person_email):
        person_id = get_obj_id_from_trait(Person, "email", person_email, request)
        person = edit_object(Person, person_id, request)

        superadmin_api_check(request)

        serializer = External_PersonSerializer(person, data=request.data)
        serializer_check(serializer)
        if "custom_fields_dict" in serializer.validated_data:
            for k, v in serializer.validated_data["custom_fields_dict"].items():
                print(k)
                print(v)
                cf = CustomField.objects.get(name=k, community=person.community)
                cfv = CustomFieldValue.objects.filter(field=cf, person=person).first()
                if cfv:
                    cfv.value = v
                else:
                    cfv = CustomFieldValue(field=cf, person=person, value=v)
                cfv.save()
        serializer.save()

        if "email" in serializer.validated_data:
            change_email(person, serializer.validated_data["email"])

        analytics_event(request, "API_Person_Edited", serializer.data)
        return Response(serializer.data)

    def delete(self, request, person_email):
        person_id = get_obj_id_from_trait(Person, "email", person_email, request)
        person = edit_object(Person, person_id, request)

        superadmin_api_check(request)

        analytics_event(request, "API_Person_Deleted", {"id": person.id})
        person.user_delete()
        return Response("OK")


class Generate_Superadmin_Token(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        if not request.user.person.admin:
            return response_400("Not an admin")

        c = request.user.person.community
        if Person.objects.filter(superadmin_api_only=True, community=c).exists():
            p = Person.objects.get(superadmin_api_only=True, community=c)
            u = p.user
        else:
            u = User.objects.create_user(
                username=c.name + "__superadmin", password=None
            )
            p = Person(
                admin=True,
                superadmin_api_only=True,
                user=u,
                email="superadmin@comradery.io",
                username="superadmin",
                community=c,
            )
            p.save()
        AuthToken.objects.filter(user=u).delete()
        t = AuthToken.objects.create(u, expiry=None)
        return Response({"token": t[1]})


class Notifications(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        page = request.query_params.get("page", 1)

        notifications = (
            Notification.objects.filter(notified_user=request.user.person)
            .order_by("-time")
            .all()
        )
        paged_notifs, page_info = get_page_info(page, notifications)
        serializer = NotificationSerializer(paged_notifs, many=True)
        page_info.update({"data": serializer.data})
        return Response(page_info)

    def post(self, request):
        re_set(request.user.username, 0)
        Notification.objects.filter(notified_user=request.user.person).update(read=True)
        return Response("OK")


class NotificationFrequency(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        serializer = NotificationFrequencySerializer(request.user.person)
        return Response(serializer.data)

    def post(self, request):
        serializer = NotificationFrequencySerializer(
            request.user.person, data=request.data
        )
        serializer_check(serializer)
        serializer.save()
        return Response(serializer.data)


class ReadNotifications(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        return Response({"n": re_get(request.user.username)})


class AcceptWelcome(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        request.user.person.show_welcome = False
        request.user.person.save()
        return Response("OK")


class ActiveUser(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        if not UserActiveDate.objects.filter(
            person=request.user.person, date=date.today()
        ).exists():
            uad = UserActiveDate(person=request.user.person)
            uad.save()

        return Response("OK")
