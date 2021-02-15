from .utils import *
import redis

if in_prod() or in_staging():
    re = redis.from_url(os.environ.get("REDIS_URL"))
else:
    re = redis.Redis(host="localhost", port=6379, db=0)


def re_publish(channel, message):
    return re.publish(channel, message)


def re_get(key):
    return re.get(key)


def re_set(key, value):
    return re.set(key, value)


def re_incr(key, amount):
    return re.incr(key, amount)

