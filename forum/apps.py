from django.apps import AppConfig
import analytics
from django.conf import settings


class ForumConfig(AppConfig):
    name = "forum"

    def ready(jjd):
        analytics.write_key = settings.SEGMENT_WRITE_KEY