from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .serializers import *
from .models import Community, Person, Post, Comment, Channel, PersonChatRoomMetadata
from django.http import (
    Http404,
    HttpResponseForbidden,
    HttpResponseRedirect,
    HttpResponse,
    JsonResponse,
)
from django.utils import timezone
from datetime import datetime, timedelta
from rest_framework.permissions import AllowAny
from .utils import *
from knox.models import AuthToken
from knox.views import LoginView as KnoxLoginView
from rest_framework.authentication import BasicAuthentication
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from algoliasearch.search_client import SearchClient
from django.core.exceptions import PermissionDenied
from django.db.models import Q, F, Count, Max
from django.contrib.auth.models import User
import redis
from .css_sanitize import validate_css
import boto3
from django.conf import settings
import io
import uuid
import json
import django_rq
from .jobs import comment_created, object_liked
from .xredis import re_publish, re_get, re_set
from .analytics_utils import *


"""
Views for the admin dashboard relating to community analytics.
"""

# This is a mapping between metric names and their corresponding functions.
# Each metric maps to a function in analytics_utils.py.
METRIC_TYPES = {
    "ACTIVE_USERS": active_users,
    "NEW_USERS": new_users,
    "POWER_USERS": power_users,
    "POST_VIEWS": post_views,
    "POSTS_CREATED": posts_created,
    "COMMENTS_CREATED": comments_created,
    "MESSAGES_SENT": messages_sent,
}


class AnalyticsUsers(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        if not request.user.person.admin:
            return response_400("Not an admin")

        # the community for this metric
        community = request.user.person.community

        # getting the metric type from the POST dict
        metric = request.data["metric"]

        # if the requested metric type is unsupported
        if metric not in METRIC_TYPES.keys():
            return response_400("Unsupported metric type")

        # calling the relevant function for this metric type
        data = METRIC_TYPES[metric](community=community)

        # returning the data
        return JsonResponse(data)
