from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .serializers import *
from .models import (
    Community,
    Person,
    Post,
    Comment,
    Channel,
    Message,
    UserActiveDate,
    UserPostView,
)
from django.http import (
    Http404,
    HttpResponseForbidden,
    HttpResponseRedirect,
    HttpResponse,
    JsonResponse,
)
from django.utils import timezone
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
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


"""
This file contains the analytics functions that are used by analytics_views.py.

Each function takes in 4 parameters:
community: a community object
start_date: the date to begin the query (inclusive)
end_date: the date to end the query (inclusive)
step_size: an int representing the number of days each query should be (ex: 7 days for a week)

The function will return a dict with ((end_date - start_date) / step_size) items.
Each item will contain a date (or date range) as the key, and the metric's value as the value.

The one exception is the power_users function, which returns a list of power users.

The format of the dict we need is as follows:
# TODO


"""


def active_users(community):
    """
    Returns a dict containing the number of users who were active.
    """

    # we have 3 date ranges to filter
    # 1) the past 30 days
    # 2) the past 16 weeks
    # 3) the past 12 months

    # querying for the active user events for this community
    # that took place within the past year
    end = datetime.today()
    start = end - timedelta(days=365)

    user_activity_events = UserActiveDate.objects.filter(
        person__community=community, date__range=(start, end)
    )

    # getting the active users for the past 30 days
    data_30_days = []
    for i in range(30):
        # looping over the past 30 days
        date = timezone.now() - timedelta(days=(30 - i))

        # the formatted date string
        date_string = date.strftime("%b %-d")

        # calculating the number of users who were active on this day
        num = user_activity_events.filter(date=date).count()

        # adding this date to the dict
        data_30_days.append({"label": date_string, "Value": num})

    # getting the active users for the past 16 weeks
    data_16_weeks = []
    for i in range(16):
        # looping over the past 16 weeks
        date = timezone.now() - timedelta(weeks=(16 - i))

        # the formatted date string for the week
        # we add 6 days instead of 1 week because the date range is inclusive of both dates
        # adding timedelta(weeks=1) would make each week 8 days long
        date_string = "{}-{}".format(
            date.strftime("%-m/%-d"), (date + timedelta(days=6)).strftime("%-m/%-d")
        )

        # calculating the number of users who were active during this week
        num = user_activity_events.filter(
            date__range=(date, date + timedelta(days=6))
        ).count()

        data_16_weeks.append({"label": date_string, "Value": num})

    data_12_months = []
    for i in range(12):
        # looping over the past 12 months
        # we include the current month even though it isn't complete yet
        date = timezone.now() - relativedelta(months=(11 - i))

        # the month name
        date_string = date.strftime("%b")

        # calculating the number of users who were active during this month
        num = user_activity_events.filter(
            date__year=date.year, date__month=date.month
        ).count()

        data_12_months.append({"label": date_string, "Value": num})

    # returning the dict
    return {
        "data_30_days": data_30_days,
        "data_16_weeks": data_16_weeks,
        "data_12_months": data_12_months,
    }


def new_users(community):
    """
    Returns a dict containing the number of new users in a community.
    """

    # getting all the users in this community
    persons = Person.objects.filter(community=community)

    # getting the new users for the past 30 days
    data_30_days = []
    for i in range(30):
        # looping over the past 30 days
        date = timezone.now() - timedelta(days=(30 - i))

        # the formatted date string
        date_string = date.strftime("%b %-d")

        # calculating the number of users created on this day
        num = persons.filter(created__date=date).count()

        # adding this date to the dict
        data_30_days.append({"label": date_string, "Value": num})
    
    # getting the new users for the past 16 weeks
    data_16_weeks = []
    for i in range(16):
        # looping over the past 16 weeks
        date = timezone.now() - timedelta(weeks=(16 - i))

        # the formatted date string for the week
        # we add 6 days instead of 1 week because the date range is inclusive of both dates
        # adding timedelta(weeks=1) would make each week 8 days long
        date_string = "{}-{}".format(
            date.strftime("%-m/%-d"), (date + timedelta(days=6)).strftime("%-m/%-d")
        )

        # calculating the number of new users created during this week
        num = persons.filter(created__date__range=(date, date + timedelta(days=6))).count()

        data_16_weeks.append({"label": date_string, "Value": num})

    data_12_months = []
    for i in range(12):
        # looping over the past 12 months
        # we include the current month even though it isn't complete yet
        date = timezone.now() - relativedelta(months=(11 - i))

        # the month name
        date_string = date.strftime("%b")

        # calculating the number of new users who were created during this month
        num = persons.filter(created__year=date.year, created__month=date.month).count()

        data_12_months.append({"label": date_string, "Value": num})

    # returning the dict
    return {
        "data_30_days": data_30_days,
        "data_16_weeks": data_16_weeks,
        "data_12_months": data_12_months,
    }


def power_users(community):
    """
    A community's power users.

    There are 4 timeframes:
    1) the past 24 hours
    2) the past 7 days
    3) the past 30 days
    4) the past year

    A user's score is the sum of the number of comments and posts they've created within a set timeframe.
    """

    end = datetime.today()
    start = end - timedelta(days=365)

    # getting all the posts
    posts = Post.objects.filter(community=community, posted__range=(start, end))

    # getting all the comments
    comments = Comment.objects.filter(
        post__community=community, posted__range=(start, end)
    )

    # the dict we will return
    return_dict = {}

    # the past 24 hours
    past_day_posts = posts.filter(posted__date__range=(end - timedelta(days=1), end))
    past_day_comments = comments.filter(posted__date__range=(end - timedelta(days=1), end))

    # a dict containing active users
    past_day_users = {}

    for post in past_day_posts:

        # skipping posts with no owner
        if post.owner is None:
            continue

        # if this user is in the dict of active users, then we increment their post score
        if post.owner.id in past_day_users.keys():
            past_day_users[post.owner.id]["posts"] += 1
            past_day_users[post.owner.id]["score"] += 1
        else:
            # not the dict of active users, so we add them to it
            past_day_users[post.owner.id] = {
                "posts": 1,
                "comments": 0,
                "score": 1,
                "name": post.owner.username,
            }

    for comment in past_day_comments:
        if comment.owner is None:
            # skipping posts with no owner
            continue

        # if this user is in the dict of active users, then we increment their comment score
        if comment.owner.id in past_day_users.keys():
            past_day_users[comment.owner.id]["comments"] += 1
            past_day_users[comment.owner.id]["score"] += 1
        else:
            # not in the dict of active users, so we add them to it
            past_day_users[comment.owner.id] = {
                "posts": 0,
                "comments": 1,
                "score": 1,
                "name": comment.owner.username,
            }

    # turning the dict to a sorted list by score
    day_users = sorted(
        past_day_users.items(), key=lambda x: x[1]["score"], reverse=True
    )

    # only returning at most the top 15 most active users
    return_dict["day"] = day_users[:15]

    # the past week
    past_week_posts = posts.filter(posted__date__range=(end - timedelta(days=7), end))
    past_week_comments = comments.filter(posted__date__range=(end - timedelta(days=7), end))

    # a dict containing active users
    past_week_users = {}

    for post in past_week_posts:

        # skipping posts with no owner
        if post.owner is None:
            continue

        # if this user is in the dict of active users, then we increment their post score
        if post.owner.id in past_week_users.keys():
            past_week_users[post.owner.id]["posts"] += 1
            past_week_users[post.owner.id]["score"] += 1
        else:
            # not the dict of active users, so we add them to it
            past_week_users[post.owner.id] = {
                "posts": 1,
                "comments": 0,
                "score": 1,
                "name": post.owner.username,
            }

    for comment in past_week_comments:
        if comment.owner is None:
            # skipping posts with no owner
            continue

        # if this user is in the dict of active users, then we increment their comment score
        if comment.owner.id in past_week_users.keys():
            past_week_users[comment.owner.id]["comments"] += 1
            past_week_users[comment.owner.id]["score"] += 1
        else:
            # not in the dict of active users, so we add them to it
            past_week_users[comment.owner.id] = {
                "posts": 0,
                "comments": 1,
                "score": 1,
                "name": comment.owner.username,
            }

    # turning the dict to a sorted list by score
    week_users = sorted(
        past_week_users.items(), key=lambda x: x[1]["score"], reverse=True
    )

    # only returning at most the top 15 most active users
    return_dict["week"] = week_users[:15]

    # the past month
    past_month_posts = posts.filter(posted__date__range=(end - timedelta(days=30), end))
    past_month_comments = comments.filter(posted__date__range=(end - timedelta(days=30), end))

    # a dict containing active users
    past_month_users = {}

    for post in past_month_posts:

        # skipping posts with no owner
        if post.owner is None:
            continue

        # if this user is in the dict of active users, then we increment their post score
        if post.owner.id in past_month_users.keys():
            past_month_users[post.owner.id]["posts"] += 1
            past_month_users[post.owner.id]["score"] += 1
        else:
            # not in the dict of active users, so we add them to it
            past_month_users[post.owner.id] = {
                "posts": 1,
                "comments": 0,
                "score": 1,
                "name": post.owner.username,
            }

    for comment in past_month_comments:
        if comment.owner is None:
            # skipping posts with no owner
            continue

        # if this user is in the dict of active users, then we increment their comment score
        if comment.owner.id in past_month_users.keys():
            past_month_users[comment.owner.id]["comments"] += 1
            past_month_users[comment.owner.id]["score"] += 1
        else:
            # not in the dict of active users, so we add them to it
            past_month_users[comment.owner.id] = {
                "posts": 0,
                "comments": 1,
                "score": 1,
                "name": comment.owner.username,
            }

    # turning the dict to a sorted list by score
    month_users = sorted(
        past_month_users.items(), key=lambda x: x[1]["score"], reverse=True
    )

    # only returning at most the top 15 most active users
    return_dict["month"] = month_users[:15]

    # the past year
    past_year_posts = posts.filter(posted__date__range=(end - timedelta(days=365), end))
    past_year_comments = comments.filter(posted__date__range=(end - timedelta(days=365), end))

    # a dict containing active users
    past_year_users = {}

    for post in past_year_posts:

        # skipping posts with no owner
        if post.owner is None:
            continue

        # if this user is in the dict of active users, then we increment their post score
        if post.owner.id in past_year_users.keys():
            past_year_users[post.owner.id]["posts"] += 1
            past_year_users[post.owner.id]["score"] += 1
        else:
            # not the dict of active users, so we add them to it
            past_year_users[post.owner.id] = {
                "posts": 1,
                "comments": 0,
                "score": 1,
                "name": post.owner.username,
            }

    for comment in past_year_comments:
        if comment.owner is None:
            # skipping posts with no owner
            continue

        # if this user is in the dict of active users, then we increment their comment score
        if comment.owner.id in past_year_users.keys():
            past_year_users[comment.owner.id]["comments"] += 1
            past_year_users[comment.owner.id]["score"] += 1
        else:
            # not the dict of active users, so we add them to it
            past_year_users[comment.owner.id] = {
                "posts": 0,
                "comments": 1,
                "score": 1,
                "name": comment.owner.username,
            }

    # turning the dict to a sorted list by score
    year_users = sorted(
        past_year_users.items(), key=lambda x: x[1]["score"], reverse=True
    )

    # only returning at most the top 15 most active users
    return_dict["year"] = year_users[:15]

    return return_dict


def post_views(community):
    # the amount of posts that have been viewed

    end = datetime.today()
    start = end - timedelta(days=365)

    user_post_views = UserPostView.objects.filter(
        person__community=community, date__range=(start, end)
    )

    # getting the number of post views for the past 30 days
    data_30_days = []
    for i in range(30):
        # looping over the past 30 days
        date = timezone.now() - timedelta(days=(30 - i))

        # the formatted date string
        date_string = date.strftime("%b %-d")

        # calculating the number of post views for this day
        num = user_post_views.filter(date=date).count()

        # adding this date to the dict
        data_30_days.append({"label": date_string, "Value": num})

    # getting the active users for the past 16 weeks
    data_16_weeks = []
    for i in range(16):
        # looping over the past 16 weeks
        date = timezone.now() - timedelta(weeks=(16 - i))

        # the formatted date string for the week
        # we add 6 days instead of 1 week because the date range is inclusive of both dates
        # adding timedelta(weeks=1) would make each week 8 days long
        date_string = "{}-{}".format(
            date.strftime("%-m/%-d"), (date + timedelta(days=6)).strftime("%-m/%-d")
        )

        # calculating the number of post views this week
        num = user_post_views.filter(
            date__range=(date, date + timedelta(days=6))
        ).count()

        data_16_weeks.append({"label": date_string, "Value": num})

    data_12_months = []
    for i in range(12):
        # looping over the past 12 months
        # we include the current month even though it isn't complete yet
        date = timezone.now() - relativedelta(months=(11 - i))

        # the month name
        date_string = date.strftime("%b")

        # calculating the number of monthly post views
        num = user_post_views.filter(
            date__year=date.year, date__month=date.month
        ).count()

        data_12_months.append({"label": date_string, "Value": num})

    # returning the dict
    return {
        "data_30_days": data_30_days,
        "data_16_weeks": data_16_weeks,
        "data_12_months": data_12_months,
    }


def posts_created(community):
    # the amount of posts that have been created

    end = datetime.today()
    start = end - timedelta(days=365)

    posts = Post.objects.filter(community=community, posted__range=(start, end))

    # getting the number of created posts for the past 30 days
    data_30_days = []
    for i in range(30):
        # looping over the past 30 days
        date = timezone.now() - timedelta(days=(30 - i))

        # the formatted date string
        date_string = date.strftime("%b %-d")

        # calculating the number of post creations for this day
        num = posts.filter(posted__date=date).count()

        # adding this date to the dict
        data_30_days.append({"label": date_string, "Value": num})

    # getting number for the past 16 weeks
    data_16_weeks = []
    for i in range(16):
        # looping over the past 16 weeks
        date = timezone.now() - timedelta(weeks=(16 - i))

        # the formatted date string for the week
        # we add 6 days instead of 1 week because the date range is inclusive of both dates
        # adding timedelta(weeks=1) would make each week 8 days long
        date_string = "{}-{}".format(
            date.strftime("%-m/%-d"), (date + timedelta(days=6)).strftime("%-m/%-d")
        )

        # calculating the number of post creations this week
        num = posts.filter(posted__date__range=(date, date + timedelta(days=6))).count()

        data_16_weeks.append({"label": date_string, "Value": num})

    data_12_months = []
    for i in range(12):
        # looping over the past 12 months
        # we include the current month even though it isn't complete yet
        date = timezone.now() - relativedelta(months=(11 - i))

        # the month name
        date_string = date.strftime("%b")

        # calculating the number of monthly post creations
        num = posts.filter(posted__year=date.year, posted__month=date.month).count()

        data_12_months.append({"label": date_string, "Value": num})

    # returning the dict
    return {
        "data_30_days": data_30_days,
        "data_16_weeks": data_16_weeks,
        "data_12_months": data_12_months,
    }


def comments_created(community):
    # the number of comments that have been created

    end = datetime.today()
    start = end - timedelta(days=365)

    comments = Comment.objects.filter(
        post__community=community, posted__range=(start, end)
    )

    # getting the number of created comments for the past 30 days
    data_30_days = []
    for i in range(30):
        # looping over the past 30 days
        date = timezone.now() - timedelta(days=(30 - i))

        # the formatted date string
        date_string = date.strftime("%b %-d")

        # calculating the number of comments
        num = comments.filter(posted__date=date).count()

        # adding this date to the dict
        data_30_days.append({"label": date_string, "Value": num})

    # getting number for the past 16 weeks
    data_16_weeks = []
    for i in range(16):
        # looping over the past 16 weeks
        date = timezone.now() - timedelta(weeks=(16 - i))

        # the formatted date string for the week
        # we add 6 days instead of 1 week because the date range is inclusive of both dates
        # adding timedelta(weeks=1) would make each week 8 days long
        date_string = "{}-{}".format(
            date.strftime("%-m/%-d"), (date + timedelta(days=6)).strftime("%-m/%-d")
        )

        # calculating the number of comment creations this week
        num = comments.filter(posted__date__range=(date, date + timedelta(days=6))).count()

        data_16_weeks.append({"label": date_string, "Value": num})

    data_12_months = []
    for i in range(12):
        # looping over the past 12 months
        # we include the current month even though it isn't complete yet
        date = timezone.now() - relativedelta(months=(11 - i))

        # the month name
        date_string = date.strftime("%b")

        # calculating the number of monthly comment creations
        num = comments.filter(posted__year=date.year, posted__month=date.month).count()

        data_12_months.append({"label": date_string, "Value": num})

    # returning the dict
    return {
        "data_30_days": data_30_days,
        "data_16_weeks": data_16_weeks,
        "data_12_months": data_12_months,
    }


def messages_sent(community):
    # the number of chat messages that have been sent

    end = datetime.today()
    start = end - timedelta(days=365)

    messages = Message.objects.filter(
        room__community=community, posted__range=(start, end)
    )

    # getting the number of created comments for the past 30 days
    data_30_days = []
    for i in range(30):
        # looping over the past 30 days
        date = timezone.now() - timedelta(days=(30 - i))

        # the formatted date string
        date_string = date.strftime("%b %-d")

        # calculating the number of messages
        num = messages.filter(posted__date=date).count()

        # adding this date to the dict
        data_30_days.append({"label": date_string, "Value": num})

    # getting number for the past 16 weeks
    data_16_weeks = []
    for i in range(16):
        # looping over the past 16 weeks
        date = timezone.now() - timedelta(weeks=(16 - i))

        # the formatted date string for the week
        # we add 6 days instead of 1 week because the date range is inclusive of both dates
        # adding timedelta(weeks=1) would make each week 8 days long
        date_string = "{}-{}".format(
            date.strftime("%-m/%-d"), (date + timedelta(days=6)).strftime("%-m/%-d")
        )

        # calculating the number of messages
        num = messages.filter(posted__date__range=(date, date + timedelta(days=6))).count()

        data_16_weeks.append({"label": date_string, "Value": num})

    data_12_months = []
    for i in range(12):
        # looping over the past 12 months
        # we include the current month even though it isn't complete yet
        date = timezone.now() - relativedelta(months=(11 - i))

        # the month name
        date_string = date.strftime("%b")

        # calculating the number of monthly messages
        num = messages.filter(posted__year=date.year, posted__month=date.month).count()

        data_12_months.append({"label": date_string, "Value": num})

    # returning the dict
    return {
        "data_30_days": data_30_days,
        "data_16_weeks": data_16_weeks,
        "data_12_months": data_12_months,
    }
