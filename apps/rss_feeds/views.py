"""RSS feed views: feed CRUD, story detail, feed statistics, and exception handling.

API endpoints for adding/removing/moving feeds, loading individual stories,
fetching original page content, viewing feed statistics, and managing feed
exceptions (address changes, duplicate detection).
"""

import base64
import datetime
import hashlib
import ipaddress
import re
import socket
from urllib.parse import urljoin, urlparse

import redis
import requests
import urllib3
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import Http404, HttpResponse, HttpResponseForbidden, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils.translation import gettext
from django.views.decorators.http import condition, require_POST

from apps.analyzer.models import get_classifiers_for_user
from apps.reader.models import UserSubscription
from apps.rss_feeds.models import Feed, MFeedIcon, MFetchHistory, MStory
from utils import json_functions as json
from utils import log as logging
from utils.feed_functions import relative_timesince, relative_timeuntil
from utils.ratelimit import ratelimit
from utils.url_safety import BLOCKED_PRIVATE_URL_MESSAGE, UnsafeUrlError, validate_public_url
from utils.user_functions import ajax_login_required, get_user
from utils.view_functions import get_argument_or_404, int_argument, is_true, required_params

# Address fragments that never make sense in feed autocomplete results.
IGNORE_AUTOCOMPLETE = (
    "facebook.com/feeds/notifications.php",
    "inbox",
    "secret",
    "password",
    "latitude",
)


def normalize_feed_id(feed_id):
    """Clients sometimes send the DOM element id ('feed:123') instead of the bare feed id."""
    if not feed_id:
        return None

    feed_id = str(feed_id)
    if feed_id.startswith("feed:"):
        feed_id = feed_id[len("feed:") :]
    if not feed_id.isdigit():
        return None

    return int(feed_id)


@json.json_view
def load_single_feed(request, feed_id):
    user = get_user(request)
    feed = get_object_or_404(Feed, pk=feed_id)
    classifiers = get_classifiers_for_user(user, feed_id=feed.pk)

    payload = feed.canonical(full=True)
    payload["classifiers"] = classifiers

    return payload


def feed_favicon_etag(request, feed_id):
    try:
        feed_icon = MFeedIcon.objects.get(feed_id=feed_id)
    except MFeedIcon.DoesNotExist:
        return

    etag_source = "%s:%s:%s:%s" % (
        feed_icon.color or "",
        feed_icon.icon_url or "",
        feed_icon.not_found or False,
        feed_icon.data or "",
    )
    return hashlib.md5(etag_source.encode("utf-8")).hexdigest()


@condition(etag_func=feed_favicon_etag)
def load_feed_favicon(request, feed_id):
    not_found = False
    try:
        feed_icon = MFeedIcon.objects.get(feed_id=feed_id)
    except MFeedIcon.DoesNotExist:
        logging.user(request, "~FBNo feed icon found: %s" % feed_id)
        not_found = True

    if not_found or not feed_icon.data:
        return HttpResponseRedirect(settings.MEDIA_URL + "img/icons/nouns/world.svg")

    icon_data = base64.b64decode(feed_icon.data)
    return HttpResponse(icon_data, content_type="image/png")


@json.json_view
def feed_autocomplete(request):
    query = request.GET.get("term") or request.GET.get("query")
    version = int_argument(request.GET, "v", 1)
    autocomplete_format = request.GET.get("format", "autocomplete")
    limit = int_argument(request.GET, "limit", 5)

    if not query:
        return dict(code=-1, message=gettext("Specify a search 'term'."), feeds=[], term=query)

    if "." in query:
        try:
            parts = urlparse(query)
            if not parts.hostname and not re.match(r"https?://", query):
                parts = urlparse("http://%s" % re.sub(r"^https?:", "", query))
            if parts.hostname:
                query = [parts.hostname]
                query.extend([p for p in parts.path.split("/") if p])
                query = " ".join(query)
        except:
            logging.user(request, "~FGAdd search, could not parse url in ~FR%s" % query)

    query_params = query.split(" ")
    tries_left = 5
    while len(query_params) and tries_left:
        tries_left -= 1
        feed_ids = Feed.autocomplete(" ".join(query_params), limit=limit)
        if feed_ids:
            break
        else:
            query_params = query_params[:-1]

    feeds = list(set([Feed.get_by_id(feed_id) for feed_id in feed_ids]))
    feeds = [feed for feed in feeds if feed and not feed.branch_from_feed]
    feeds = [feed for feed in feeds if all([x not in feed.feed_address for x in IGNORE_AUTOCOMPLETE])]

    if autocomplete_format == "autocomplete":
        feeds = [
            {
                "id": feed.pk,
                "value": feed.feed_address,
                "label": feed.feed_title,
                "tagline": feed.data and feed.data.feed_tagline,
                "num_subscribers": feed.num_subscribers,
            }
            for feed in feeds
        ]
    else:
        feeds = [feed.canonical(full=True) for feed in feeds]
    feeds = sorted(feeds, key=lambda f: -1 * f["num_subscribers"])

    feed_ids = [f["id"] for f in feeds]
    feed_icons = dict((icon.feed_id, icon) for icon in MFeedIcon.objects.filter(feed_id__in=feed_ids))

    for feed in feeds:
        if feed["id"] in feed_icons:
            feed_icon = feed_icons[feed["id"]]
            if feed_icon.data:
                feed["favicon_color"] = feed_icon.color
                feed["favicon"] = feed_icon.data

    logging.user(
        request,
        "~FGAdd Search: ~SB%s ~SN(%s matches)"
        % (
            query,
            len(feeds),
        ),
    )

    if version > 1:
        return {
            "feeds": feeds,
            "term": query,
        }
    else:
        return feeds


@ratelimit(minutes=1, requests=30)
@json.json_view
def load_feed_statistics(request, feed_id):
    user = get_user(request)
    feed = get_object_or_404(Feed, pk=feed_id)
    stats = assemble_statistics(user, feed_id)

    logging.user(request, "~FBStatistics: ~SB%s" % (feed))

    return stats


def load_feed_statistics_embedded(request, feed_id):
    user = get_user(request)
    feed = get_object_or_404(Feed, pk=feed_id)
    stats = assemble_statistics(user, feed_id)

    logging.user(request, "~FBStatistics (~FCembedded~FB): ~SB%s" % (feed))

    return render(
        request,
        "rss_feeds/statistics.xhtml",
        {
            "stats": stats,
            "feed_json": feed.canonical(),
            "feed": feed,
        },
    )


def assemble_statistics(user, feed_id):
    user_timezone = user.profile.timezone
    stats = dict()
    feed = get_object_or_404(Feed, pk=feed_id)
    feed.update_all_statistics()
    feed.set_next_scheduled_update(verbose=True, skip_scheduling=True)
    feed.save_feed_story_history_statistics()
    feed.save_classifier_counts()

    # Dates of last and next update
    stats["active"] = feed.active
    stats["last_update"] = relative_timesince(feed.last_update)
    stats["next_update"] = relative_timeuntil(feed.next_scheduled_update)
    stats["push"] = feed.is_push
    stats["fs_size_bytes"] = feed.fs_size_bytes
    stats["archive_count"] = feed.archive_count

    # Minutes between updates
    update_interval_minutes = feed.get_next_scheduled_update(force=True, verbose=False)
    stats["update_interval_minutes"] = update_interval_minutes
    original_active_premium_subscribers = feed.active_premium_subscribers
    original_premium_subscribers = feed.premium_subscribers
    feed.active_premium_subscribers = max(feed.active_premium_subscribers + 1, 1)
    feed.premium_subscribers += 1
    premium_update_interval_minutes = feed.get_next_scheduled_update(
        force=True, verbose=False, premium_speed=True
    )
    feed.active_premium_subscribers = original_active_premium_subscribers
    feed.premium_subscribers = original_premium_subscribers
    stats["premium_update_interval_minutes"] = premium_update_interval_minutes
    stats["errors_since_good"] = feed.errors_since_good

    # Stories per month - average and month-by-month breakout
    average_stories_per_month, story_count_history = (
        feed.average_stories_per_month,
        feed.data.story_count_history,
    )
    stats["average_stories_per_month"] = average_stories_per_month
    story_count_history = story_count_history and json.decode(story_count_history)
    if story_count_history and isinstance(story_count_history, dict):
        stats["story_count_history"] = story_count_history["months"]
        stats["story_days_history"] = story_count_history["days"]
        stats["story_hours_history"] = story_count_history["hours"]
    else:
        stats["story_count_history"] = story_count_history

    # Rotate hours to match user's timezone offset
    localoffset = user_timezone.utcoffset(datetime.datetime.utcnow())
    hours_offset = int(localoffset.total_seconds() / 3600)
    rotated_hours = {}
    for hour, value in list(stats["story_hours_history"].items()):
        rotated_hours[str(int(hour) + hours_offset)] = value
    stats["story_hours_history"] = rotated_hours

    # Subscribers
    stats["subscriber_count"] = feed.num_subscribers
    stats["num_subscribers"] = feed.num_subscribers
    stats["stories_last_month"] = feed.stories_last_month
    stats["last_load_time"] = feed.last_load_time
    stats["premium_subscribers"] = feed.premium_subscribers
    stats["active_subscribers"] = feed.active_subscribers
    stats["active_premium_subscribers"] = feed.active_premium_subscribers

    # Classifier counts
    stats["classifier_counts"] = json.decode(feed.data.feed_classifier_counts)

    # Fetch histories
    fetch_history = MFetchHistory.feed(feed_id, timezone=user_timezone)
    stats["feed_fetch_history"] = fetch_history["feed_fetch_history"]
    stats["page_fetch_history"] = fetch_history["page_fetch_history"]
    stats["feed_push_history"] = fetch_history["push_history"]

    return stats


@json.json_view
def load_feed_settings(request, feed_id):
    stats = dict()
    feed = get_object_or_404(Feed, pk=feed_id)
    user = get_user(request)
    timezone = user.profile.timezone

    fetch_history = MFetchHistory.feed(feed_id, timezone=timezone)
    stats["feed_fetch_history"] = fetch_history["feed_fetch_history"]
    stats["page_fetch_history"] = fetch_history["page_fetch_history"]
    stats["feed_push_history"] = fetch_history["push_history"]
    stats["duplicate_addresses"] = feed.duplicate_addresses.all()

    return stats


@ajax_login_required
@require_POST
@json.json_view
def save_feed_fetch_interval(request):
    """Store the reader's fetch interval for one feed and reschedule it.

    An empty fetch_interval puts the feed back on the reader-wide preference.
    """
    feed_id = int(request.POST.get("feed_id") or 0)
    raw_interval = (request.POST.get("fetch_interval") or "").strip()
    interval = None
    if raw_interval and raw_interval != "auto":
        try:
            interval = int(raw_interval)
        except (TypeError, ValueError):
            return dict(code=-1, message=gettext("Invalid fetch interval"))
        if interval < 1 or interval > 60 * 24 * 7:
            return dict(code=-1, message=gettext("Fetch interval out of range"))

    feed = Feed.get_by_id(feed_id)
    if not feed:
        raise Http404

    feed.fetch_interval = interval
    feed.save(update_fields=["fetch_interval"])
    feed.set_next_scheduled_update(verbose=False)
    logging.user(
        request,
        "~FRSetting fetch interval for ~SB%s~SN to %s min"
        % (feed, interval if interval else "the global preference"),
    )

    return dict(
        code=1,
        feed_id=feed.pk,
        fetch_interval=interval,
        next_scheduled_update=feed.next_scheduled_update.strftime("%s"),
    )


@ajax_login_required
@ratelimit(minutes=1, requests=30)
@json.json_view
def exception_retry(request):
    user = get_user(request)
    feed_id = get_argument_or_404(request, "feed_id")
    reset_fetch = json.decode(request.POST["reset_fetch"])
    feed = Feed.get_by_id(feed_id)
    original_feed = feed

    if not feed:
        raise Http404

    feed.schedule_feed_fetch_immediately()
    changed = False
    if feed.has_page_exception:
        changed = True
        feed.has_page_exception = False
    if feed.has_feed_exception:
        changed = True
        feed.has_feed_exception = False
    if not feed.active:
        changed = True
        feed.active = True
    if changed:
        feed.save(update_fields=["has_page_exception", "has_feed_exception", "active"])

    original_fetched_once = feed.fetched_once
    if reset_fetch:
        logging.user(request, "~FRRefreshing exception feed: ~SB%s" % (feed))
        feed.fetched_once = False
    else:
        logging.user(request, "~FRForcing refreshing feed: ~SB%s" % (feed))

        feed.fetched_once = True
    if feed.fetched_once != original_fetched_once:
        feed.save(update_fields=["fetched_once"])

    feed = feed.update(force=True, compute_scores=False, verbose=True)
    feed = Feed.get_by_id(feed.pk)

    try:
        usersub = UserSubscription.objects.get(user=user, feed=feed)
    except UserSubscription.DoesNotExist:
        usersubs = UserSubscription.objects.filter(user=user, feed=original_feed)
        if usersubs:
            usersub = usersubs[0]
            usersub.switch_feed(feed, original_feed)
        else:
            return {"code": -1}
    usersub.calculate_feed_scores(silent=False)

    feeds = {feed.pk: usersub and usersub.canonical(full=True), feed_id: usersub.canonical(full=True)}
    return {"code": 1, "feeds": feeds}


def find_or_create_feed_for_branch(original_feed, feed_address, feed_link):
    """The feed a reader leaving original_feed for this address and link moves onto, whether
    this call created it (only then do the Change Feed Address views make it a branch), and
    whether nothing holds the address at all, in which case the reader stays on
    original_feed. A feed that already holds the address has readers of its own and is never
    re-parented under the reader's feed (forum #13860). Feed.save folds a new row into a feed
    another request created at this address meanwhile and leaves the instance without an id,
    so the id is what says the row is ours (Feed.save handles the IntegrityError itself).
    apps/rss_feeds/views.py
    """
    hash_address_and_link = Feed.generate_hash_address_and_link(feed_address, feed_link)
    try:
        return Feed.objects.get(hash_address_and_link=hash_address_and_link), False, False
    except Feed.DoesNotExist:
        pass
    new_feed = Feed.objects.create(feed_address=feed_address, feed_link=feed_link)
    if new_feed.pk is not None:
        return new_feed, True, False
    existing_feed = Feed.objects.filter(hash_address_and_link=hash_address_and_link).first()
    if existing_feed:
        return existing_feed, False, False
    return original_feed, False, True


@ajax_login_required
@json.json_view
def exception_change_feed_address(request):
    feed_id = normalize_feed_id(request.POST.get("feed_id"))
    if not feed_id:
        return {"code": -1, "message": gettext("Missing or invalid feed id.")}

    feed = get_object_or_404(Feed, pk=feed_id)
    original_feed = feed
    feed_address = request.POST["feed_address"]
    timezone = request.user.profile.timezone
    code = -1

    try:
        validate_public_url(feed_address)
    except UnsafeUrlError:
        return {"code": -1, "message": BLOCKED_PRIVATE_URL_MESSAGE}

    # Branch to the feed at this address, broken or not. The old "fix broken feed"
    # path mutated the reader's current feed instead of moving them onto a working one.
    logging.user(
        request, "~FRBranching feed by address: ~SB%s~SN to ~SB%s" % (feed.feed_address, feed_address)
    )
    feed, created_branch, left_in_place = find_or_create_feed_for_branch(
        original_feed, feed_address, feed.feed_link
    )
    code = -1 if left_in_place else 1
    # Only a feed made here for this reader becomes a branch. A feed that already holds the
    # address has readers of its own: re-parenting it under this one hid it from search and
    # let it lose a merge to this feed, moving all of them (forum #13860). The reader is
    # switched onto it below either way. apps/rss_feeds/views.py
    if created_branch and feed.pk != original_feed.pk:
        try:
            feed.branch_from_feed = original_feed.branch_from_feed or original_feed
        except Feed.DoesNotExist:
            feed.branch_from_feed = original_feed
        feed.feed_address_locked = True
        feed = feed.save()

    feed = feed.update()
    feed = Feed.get_by_id(feed.pk)
    try:
        usersub = UserSubscription.objects.get(user=request.user, feed=feed)
    except UserSubscription.DoesNotExist:
        usersubs = UserSubscription.objects.filter(user=request.user, feed=original_feed)
        if usersubs:
            usersub = usersubs[0]
            usersub.switch_feed(feed, original_feed)
        else:
            fetch_history = MFetchHistory.feed(feed_id, timezone=timezone)
            return {
                "code": -1,
                "feed_fetch_history": fetch_history["feed_fetch_history"],
                "page_fetch_history": fetch_history["page_fetch_history"],
                "push_history": fetch_history["push_history"],
            }

    usersub.calculate_feed_scores(silent=False)

    feed.update_all_statistics()
    classifiers = get_classifiers_for_user(usersub.user, feed_id=usersub.feed_id)

    feeds = {
        original_feed.pk: usersub and usersub.canonical(full=True, classifiers=classifiers),
    }

    if feed and feed.has_feed_exception:
        code = -1

    fetch_history = MFetchHistory.feed(feed_id, timezone=timezone)
    return {
        "code": code,
        "feeds": feeds,
        "new_feed_id": usersub.feed_id,
        "feed_fetch_history": fetch_history["feed_fetch_history"],
        "page_fetch_history": fetch_history["page_fetch_history"],
        "push_history": fetch_history["push_history"],
    }


@ajax_login_required
@json.json_view
def exception_change_feed_link(request):
    feed_id = normalize_feed_id(request.POST.get("feed_id"))
    if not feed_id:
        return {"code": -1, "message": gettext("Missing or invalid feed id.")}

    feed = get_object_or_404(Feed, pk=feed_id)
    original_feed = feed
    feed_link = request.POST["feed_link"]
    timezone = request.user.profile.timezone
    code = -1

    try:
        validate_public_url(feed_link)
    except UnsafeUrlError:
        return {"code": -1, "message": BLOCKED_PRIVATE_URL_MESSAGE}

    # Branch to the feed at this link, broken or not (see exception_change_feed_address).
    logging.user(request, "~FRBranching feed by link: ~SB%s~SN to ~SB%s" % (feed.feed_link, feed_link))
    feed, created_branch, left_in_place = find_or_create_feed_for_branch(
        original_feed, feed.feed_address, feed_link
    )
    code = -1 if left_in_place else 1
    # As in exception_change_feed_address: an existing feed at this link is never
    # re-parented or locked, only switched to (forum #13860). apps/rss_feeds/views.py
    if created_branch and feed.pk != original_feed.pk:
        try:
            feed.branch_from_feed = original_feed.branch_from_feed or original_feed
        except Feed.DoesNotExist:
            feed.branch_from_feed = original_feed
        feed.feed_link_locked = True
        feed.save()

    feed = feed.update()
    feed = Feed.get_by_id(feed.pk)

    try:
        usersub = UserSubscription.objects.get(user=request.user, feed=feed)
    except UserSubscription.DoesNotExist:
        usersubs = UserSubscription.objects.filter(user=request.user, feed=original_feed)
        if usersubs:
            usersub = usersubs[0]
            usersub.switch_feed(feed, original_feed)
        else:
            fetch_history = MFetchHistory.feed(feed_id, timezone=timezone)
            return {
                "code": -1,
                "feed_fetch_history": fetch_history["feed_fetch_history"],
                "page_fetch_history": fetch_history["page_fetch_history"],
                "push_history": fetch_history["push_history"],
            }

    usersub.calculate_feed_scores(silent=False)

    feed.update_all_statistics()
    classifiers = get_classifiers_for_user(usersub.user, feed_id=usersub.feed_id)

    if feed and feed.has_feed_exception:
        code = -1

    feeds = {
        original_feed.pk: usersub.canonical(full=True, classifiers=classifiers),
    }
    fetch_history = MFetchHistory.feed(feed_id, timezone=timezone)
    return {
        "code": code,
        "feeds": feeds,
        "new_feed_id": usersub.feed_id,
        "feed_fetch_history": fetch_history["feed_fetch_history"],
        "page_fetch_history": fetch_history["page_fetch_history"],
        "push_history": fetch_history["push_history"],
    }


@login_required
def status(request):
    if not request.user.is_staff and not settings.DEBUG:
        logging.user(request, "~SKNON-STAFF VIEWING RSS FEEDS STATUS!")
        assert False
        return HttpResponseForbidden()
    minutes = int_argument(request.GET, "minutes", 1)
    now = datetime.datetime.now()
    hour_ago = now + datetime.timedelta(minutes=minutes)
    username = request.GET.get("user", "") or request.GET.get("username", "")
    if username == "all":
        feeds = Feed.objects.filter(next_scheduled_update__lte=hour_ago).order_by("next_scheduled_update")
    else:
        if username:
            user = User.objects.get(username=username)
        else:
            user = request.user
        usersubs = UserSubscription.objects.filter(user=user)
        feed_ids = usersubs.values("feed_id")
        if minutes > 0:
            feeds = Feed.objects.filter(pk__in=feed_ids, next_scheduled_update__lte=hour_ago).order_by(
                "next_scheduled_update"
            )
        else:
            feeds = Feed.objects.filter(pk__in=feed_ids, last_update__gte=hour_ago).order_by("-last_update")

    r = redis.Redis(connection_pool=settings.REDIS_FEED_UPDATE_POOL)
    queues = {
        "tasked_feeds": r.zcard("tasked_feeds"),
        "queued_feeds": r.scard("queued_feeds"),
        "scheduled_updates": r.zcard("scheduled_updates"),
    }
    return render(request, "rss_feeds/status.xhtml", {"feeds": feeds, "queues": queues})


@ratelimit(minutes=1, requests=30)
@json.json_view
def original_text(request):
    # iOS sends a POST, web sends a GET
    GET_POST = getattr(request, request.method)
    story_id = GET_POST.get("story_id")
    feed_id = GET_POST.get("feed_id")
    story_hash = GET_POST.get("story_hash", None)
    force = GET_POST.get("force", False)
    debug = GET_POST.get("debug", False)

    if not story_hash and not story_id:
        return {"code": -1, "message": gettext("Missing story_hash."), "original_text": None, "failed": True}

    if story_hash:
        story, _ = MStory.find_story(story_hash=story_hash)
    else:
        story, _ = MStory.find_story(story_id=story_id, story_feed_id=feed_id)

    if not story:
        logging.user(request, "~FYFetching ~FGoriginal~FY story text: ~FRstory not found")
        return {"code": -1, "message": gettext("Story not found."), "original_text": None, "failed": True}

    original_text = story.fetch_original_text(force=force, request=request, debug=debug)

    return {
        "feed_id": story.story_feed_id,
        "story_hash": story.story_hash,
        "story_id": story.story_guid,
        "image_urls": story.image_urls,
        "secure_image_urls": Feed.secure_image_urls(story.image_urls),
        "original_text": original_text,
        "failed": not original_text or len(original_text) < 100,
    }


@required_params("story_hash", method="GET")
def original_story(request):
    story_hash = request.GET.get("story_hash")
    force = request.GET.get("force", False)
    debug = request.GET.get("debug", False)

    story, _ = MStory.find_story(story_hash=story_hash)

    if not story:
        logging.user(request, "~FYFetching ~FGoriginal~FY story page: ~FRstory not found")
        # return {'code': -1, 'message': 'Story not found.', 'original_page': None, 'failed': True}
        raise Http404

    original_page = story.fetch_original_page(force=force, request=request, debug=debug)

    return HttpResponse(original_page or "")


@required_params("story_hash", method="GET")
@json.json_view
def story_changes(request):
    story_hash = request.GET.get("story_hash", None)
    show_changes = is_true(request.GET.get("show_changes", True))
    story, _ = MStory.find_story(story_hash=story_hash)
    if not story:
        logging.user(request, "~FYFetching ~FGoriginal~FY story page: ~FRstory not found")
        return {"code": -1, "message": gettext("Story not found."), "original_page": None, "failed": True}

    return {"story": Feed.format_story(story, show_changes=show_changes)}


# --- Image proxy --------------------------------------------------------------
#
# Story images load straight from the publisher's CDN (IMAGES_URL is empty in the
# personal edition), and many CDNs refuse hotlinked requests: they answer 403/418
# unless the Referer is missing or points at their own origin. The browser always
# sends this app's origin, so those images never render. The frontend retries a
# failed <img> through GET /imageproxy?url=<encoded>; this view re-fetches the
# image server side with no Referer first and, when the CDN still refuses, with
# the image's own origin as the Referer.
#
# Two upstream failure modes are tolerated on purpose. A body shorter than its
# Content-Length: the bytes that did arrive are still a valid partial image, so
# they are served as they are. And a dead /media/ twin: the Telegram-to-RSS
# bridge stores every attachment at both /media/<id>/<index> and /thumb/<id>/<index>,
# and /media/ expires long before /thumb/, so the thumb twin is tried when the
# media URL fails. apps/rss_feeds/views.py

IMAGE_PROXY_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36"
)
IMAGE_PROXY_ACCEPT = "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"
IMAGE_PROXY_TIMEOUT = 20
IMAGE_PROXY_MAX_BYTES = 16 * 1024 * 1024
IMAGE_PROXY_MIN_BYTES = 1024
IMAGE_PROXY_MAX_REDIRECTS = 5
IMAGE_PROXY_REFERER_RETRY_STATUSES = (401, 403, 418, 451)
# 198.18.0.0/15 is allowed on purpose: this host runs a Clash-style fake-ip
# resolver, so public sites resolve into that benchmarking range and a guard
# there would reject exactly the images the proxy exists to rescue.
IMAGE_PROXY_ALLOWED_NETWORK = ipaddress.ip_network("198.18.0.0/15")
IMAGE_PROXY_MEDIA_TWIN = re.compile(r"^(.*)/media/(\d+)/(\d+)$")


def _image_proxy_validate(target):
    try:
        parsed = urlparse(target)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as e:
        raise UnsafeUrlError("Invalid URL.") from e
    if parsed.scheme not in ("http", "https"):
        raise UnsafeUrlError("Only http and https URLs are allowed.")
    if not parsed.hostname:
        raise UnsafeUrlError("URL must include a hostname.")
    try:
        infos = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as e:
        raise UnsafeUrlError("Could not resolve URL hostname.") from e
    for info in infos:
        try:
            address = ipaddress.ip_address(info[4][0])
        except ValueError as e:
            raise UnsafeUrlError("URL resolved to an invalid IP address.") from e
        if isinstance(address, ipaddress.IPv4Address) and address in IMAGE_PROXY_ALLOWED_NETWORK:
            continue
        if (
            not address.is_global
            or address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            raise UnsafeUrlError("%s %s" % (BLOCKED_PRIVATE_URL_MESSAGE, address))
    return parsed


def _image_proxy_thumb_twin(target):
    try:
        parsed = urlparse(target)
    except ValueError:
        return None
    match = IMAGE_PROXY_MEDIA_TWIN.match(parsed.path)
    if not match:
        return None
    twin = parsed._replace(path="%s/thumb/%s/%s" % (match.group(1), match.group(2), match.group(3)))
    return twin.geturl()


def _image_proxy_get(target, referer=None):
    headers = {"User-Agent": IMAGE_PROXY_USER_AGENT, "Accept": IMAGE_PROXY_ACCEPT}
    if referer:
        headers["Referer"] = referer
    url = target
    for _ in range(IMAGE_PROXY_MAX_REDIRECTS + 1):
        _image_proxy_validate(url)
        response = requests.get(
            url, headers=headers, timeout=IMAGE_PROXY_TIMEOUT, stream=True, allow_redirects=False
        )
        location = response.headers.get("Location")
        if response.is_redirect and location:
            response.close()
            url = urljoin(url, location)
            continue
        return response
    raise requests.TooManyRedirects("Exceeded %s redirects for %s" % (IMAGE_PROXY_MAX_REDIRECTS, target))


def _image_proxy_read_body(response):
    chunks = []
    total = 0
    truncated = False
    try:
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            chunks.append(chunk)
            total += len(chunk)
            if total > IMAGE_PROXY_MAX_BYTES:
                truncated = True
                break
    except (requests.RequestException, urllib3.exceptions.HTTPError):
        # A connection that dies mid-transfer still leaves valid partial pixels.
        truncated = True
    finally:
        response.close()
    return b"".join(chunks), truncated


def _image_proxy_attempt(target):
    try:
        parsed = _image_proxy_validate(target)
    except UnsafeUrlError as e:
        return {"ok": False, "status": 403, "reason": str(e)}

    response = None
    try:
        response = _image_proxy_get(target)
        if response.status_code in IMAGE_PROXY_REFERER_RETRY_STATUSES:
            logging.debug(
                "[imageproxy] %s for %s, retrying with its own referer"
                % (response.status_code, parsed.netloc)
            )
            response.close()
            response = _image_proxy_get(target, referer="%s://%s/" % (parsed.scheme, parsed.netloc))
    except (UnsafeUrlError, requests.RequestException, OSError, ValueError) as e:
        if response is not None:
            response.close()
        return {"ok": False, "status": 403, "reason": str(e)}

    try:
        if response.status_code >= 400:
            status = 404 if response.status_code == 404 else 502
            return {"ok": False, "status": status, "reason": "upstream %s" % response.status_code}

        content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if not content_type.startswith("image/"):
            return {"ok": False, "status": 502, "reason": "not an image (%s)" % (content_type or "no content-type")}

        body, truncated = _image_proxy_read_body(response)
        if len(body) < IMAGE_PROXY_MIN_BYTES:
            reason = "truncated before any pixels" if truncated else "empty response"
            return {"ok": False, "status": 502, "reason": reason}
        return {
            "ok": True,
            "body": body,
            "content_type": content_type,
            "truncated": truncated,
            "host": parsed.netloc,
        }
    finally:
        response.close()


def _image_proxy_error(status, message):
    response = JsonResponse({"error": message}, status=status)
    response["Cache-Control"] = "no-store"
    return response


def image_proxy(request):
    target = (request.GET.get("url") or "").strip()
    if not target:
        return _image_proxy_error(400, "missing url")

    candidates = [target]
    twin = _image_proxy_thumb_twin(target)
    if twin and twin != target:
        candidates.append(twin)

    failure = None
    for candidate in candidates:
        result = _image_proxy_attempt(candidate)
        if result["ok"]:
            response = HttpResponse(result["body"], content_type=result["content_type"])
            response["Content-Length"] = str(len(result["body"]))
            response["Cache-Control"] = "public, max-age=86400"
            response["X-Imageproxy-Host"] = result["host"]
            if candidate != target:
                response["X-Imageproxy-Fallback"] = "thumb"
            if result["truncated"]:
                response["X-Imageproxy-Partial"] = "1"
            return response
        logging.debug("[imageproxy] %s for %s" % (result["reason"], candidate))
        failure = result

    if failure is None:
        failure = {"status": 502, "reason": "fetch failed"}
    return _image_proxy_error(failure["status"], failure["reason"])
