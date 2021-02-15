from django.http import Http404
from django.core.exceptions import (
    PermissionDenied,
    ObjectDoesNotExist,
    SuspiciousOperation,
)
import os
import analytics
import base64
import uuid
from rest_framework.response import Response
from rest_framework import status
from lxml.html.clean import Cleaner  # pylint: disable=no-name-in-module
from lxml import html
from django.core.paginator import Paginator
from django.conf import settings


def in_prod():
    return "IN_HEROKU" in os.environ


def in_staging():
    return "IN_STAGING" in os.environ


def analytics_identify(identifier, user_info):
    if in_prod():
        analytics.identify(identifier, user_info)


def analytics_event(request, event, event_info):
    if in_prod():
        analytics.track(request.user.person.id, event, event_info)


def frontend_url():
    if in_prod():
        return settings.PROD_FRONTEND_URL
    else:
        return settings.DEV_FRONTEND_URL


def _get_object(_cls, obj_id):
    try:
        obj = _cls.objects.get(id=obj_id)
        return obj
    except ObjectDoesNotExist:
        raise Http404()


def get_object(_cls, obj_id, request):
    obj = _get_object(_cls, obj_id)
    if request.user.is_authenticated:
        return viewer_get_object(obj, request.user.person)

    if obj.is_public():
        return obj

    raise Http404()


def edit_object(_cls, obj_id, request):
    return viewer_edit_object(_cls, obj_id, request.user.person)


def get_obj_id_from_trait(_cls, filter_by, trait, request):
    if not request.user.is_authenticated:
        raise PermissionDenied

    try:
        return _cls.objects.get(
            **{filter_by: trait, "community": request.user.person.community}
        ).id
    except ObjectDoesNotExist:
        raise Http404()


def viewer_get_object(obj, viewer):
    if obj.can_access(viewer):
        return obj
    raise Http404()


def viewer_edit_object(_cls, obj_id, viewer):
    obj = get_object(_cls, obj_id, viewer)
    if obj.can_edit(viewer):
        return obj
    raise PermissionDenied


def common_get_object(obj, viewer):
    return obj.community.people.filter(id=viewer.id).exists()


def common_edit_object(obj, viewer):
    if hasattr(obj, "owner") and obj.owner and obj.owner.id == viewer.id:
        return True
    return obj.community.people.filter(id=viewer.id, admin=True).exists()


def serializer_check(serializer):
    if not serializer.is_valid():
        print(serializer.errors)
        raise SuspiciousOperation(serializer.errors)


def person_context(request):
    if request.user.is_authenticated:
        return {"person": request.user.person}
    return {"person": None}


def superadmin_api_check(request):
    if request.user.is_authenticated and request.user.person.superadmin_api_only:
        return True
    raise PermissionDenied


def generate_filter_string(restricted_channels):
    filter_string = ""
    for rc in restricted_channels:
        filter_string += "channel_id:" + str(rc.id) + " OR "
    if len(filter_string) > 0:
        filter_string = " AND (type:person OR " + filter_string[:-4] + ")"
    return filter_string


def django_username(community, email):
    return community.name + "__" + email


def change_email(person, email):
    person.email = email
    person.save()

    person.user.username = django_username(person.community, email)
    person.user.save()


def generate_uuid_base64():
    return base64.urlsafe_b64encode(uuid.uuid4().bytes).decode("ascii").strip("=")


def response_400(error):
    print(error)
    return Response(error, status=status.HTTP_400_BAD_REQUEST)


def uuid_path(instance, filename):
    return os.path.join("media/", uuid.uuid4().hex)


def sanitize_html(_html):
    c = Cleaner(
        add_nofollow=True,
        host_whitelist=[
            "youtube.com",
            "www.youtube.com",
            "player.vimeo.com",
            "fast.wistia.net",
        ],
        safe_attrs=html.defs.safe_attrs | set(["style"]),
    )
    return c.clean_html(_html)


def get_page_info(page, objs, step=10):
    paginator = Paginator(objs, step)
    paged_objs = paginator.get_page(page)
    page_info = {
        "cursor": page,
        "has_next": paged_objs.has_next(),
        "has_previous": paged_objs.has_previous(),
    }
    return (paged_objs, page_info)
