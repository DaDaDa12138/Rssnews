"""Operational endpoints: container health checks and robots.txt.

These used to live in a separate apps/static app that had no models, no
migrations and no pages of its own. The personal edition has no marketing site,
so the app is gone and its six views live here next to the rest of the profile
endpoints.
"""

import redis
from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest

from apps.rss_feeds.models import Feed


def haproxy_check(request):
    return HttpResponse("OK")


def postgres_check(request):
    feed = Feed.objects.latest("pk").pk
    if feed:
        return HttpResponse(str(feed))
    assert False, "Cannot read from postgres database"


REDIS_POOLS = {
    "main": "REDIS_POOL",
    "story": "REDIS_STORY_HASH_POOL",
    "sessions": "REDIS_SESSION_POOL",
}


def redis_check(request):
    """Report whether one redis pool answers, using the status code as the signal.

    The load balancer only reads the status code, so an unknown or missing pool
    name is a 400. It used to raise UnboundLocalError because r was never bound.
    """
    pool = request.GET.get("pool")
    if pool not in REDIS_POOLS:
        return HttpResponseBadRequest("pool must be one of: %s" % ", ".join(sorted(REDIS_POOLS)))

    r = redis.Redis(connection_pool=getattr(settings, REDIS_POOLS[pool]))
    key = r.randomkey()
    if key:
        return HttpResponse(str(key))
    assert False, "Cannot read from redis-%s database" % pool


def health_check(request):
    return HttpResponse("OK")


def robots_txt(request):
    """Keep crawlers out of a personal, unlisted reader."""
    body = "User-agent: *" + chr(10) + "Disallow: /" + chr(10)
    return HttpResponse(body, content_type="text/plain")
