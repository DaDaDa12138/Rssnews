"""Google Reader API compatibility for third party clients.

Only the endpoints a reader app needs are implemented: login, token,
subscriptions, unread counts, tags, stream contents and edit-tag. The item id is
the NewsBlur story hash, which is stable and already used by the web reader.

Auth accepts either the signed token this module issues (Authorization:
GoogleLogin auth=<token>) or an existing Django session, so a browser and a
native client can both use the same account.
"""

from ._base import *  # noqa: F401,F403

import json as jsonlib
import time
from urllib.parse import unquote

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.core import signing
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt

from apps.reader.models import UserSubscription, UserSubscriptionFolders
from apps.rss_feeds.models import Feed, MStarredStory, MStarredStoryCounts, MStory

__all__ = [
    "greader_login",
    "greader_token",
    "greader_subscription_list",
    "greader_tag_list",
    "greader_unread_count",
    "greader_stream_contents",
    "greader_edit_tag",
    "greader_mark_all_as_read",
    "greader_user_info",
]

SALT = "greader-api"
TOKEN_MAX_AGE = 60 * 60 * 24 * 30
READ_TAG = "user/-/state/com.google/read"
STAR_TAG = "user/-/state/com.google/starred"
READING_LIST = "user/-/state/com.google/reading-list"


def issue_token(user):
    return signing.dumps({"u": user.pk, "t": int(time.time())}, salt=SALT)


def token_user(request):
    """Resolves the caller from the Authorization header, a query arg or the session."""
    header = request.META.get("HTTP_AUTHORIZATION", "") or ""
    token = ""

    if header.startswith("GoogleLogin auth="):
        token = header.split("=", 1)[1].strip()
    elif header.startswith("Bearer "):
        token = header.split(" ", 1)[1].strip()
    token = token or request.GET.get("auth") or request.POST.get("auth") or ""

    if token:
        try:
            data = signing.loads(token, salt=SALT, max_age=TOKEN_MAX_AGE)
        except signing.BadSignature:
            return None
        return User.objects.filter(pk=data.get("u")).first()

    if request.user.is_authenticated:
        return request.user

    return None


def require_user(request):
    user = token_user(request)
    if not user:
        return None, HttpResponse("Unauthorized", status=401, content_type="text/plain")
    return user, None


def json_out(data):
    return HttpResponse(jsonlib.dumps(data), content_type="application/json; charset=utf-8")


def text_response(body, status=200):
    return HttpResponse(body, status=status, content_type="text/plain; charset=utf-8")


@csrf_exempt
def greader_login(request):
    """ClientLogin: a reader app posts Email/Passwd and keeps the Auth token.

    POST only: the password must not end up in a URL, an access log or a proxy
    cache. Every Google Reader client sends this as a form POST.
    """
    if request.method != "POST":
        return text_response("Error=BadMethod", status=405)

    email = request.POST.get("Email") or ""
    password = request.POST.get("Passwd") or ""
    user = authenticate(username=email, password=password)

    if user is None:
        user = User.objects.filter(email__iexact=email).first()
        if user is not None:
            user = authenticate(username=user.username, password=password)

    if user is None:
        return text_response("Error=BadAuthentication", status=401)

    return text_response("SID=%s\nLSID=%s\nAuth=%s" % (user.pk, user.pk, issue_token(user)))


def greader_token(request):
    user, error = require_user(request)
    if error:
        return error
    return text_response(issue_token(user))


def parse_stream(stream_id):
    """feed/34, user/-/state/com.google/reading-list, .../starred, user/-/label/Fresh."""
    stream_id = unquote(stream_id or "")

    if stream_id.startswith("feed/"):
        try:
            return "feed", int(stream_id.split("/", 1)[1])
        except (TypeError, ValueError):
            return "unknown", None
    if "/label/" in stream_id:
        return "label", stream_id.split("/label/", 1)[1]
    if stream_id.endswith("/starred"):
        return "starred", None
    if stream_id.endswith("/reading-list"):
        return "reading-list", None

    return "unknown", None


def folder_feeds(user, label):
    """Feed ids inside one folder, using the same flattening the sidebar uses."""
    mapping = UserSubscriptionFolders.get_feed_folder_mapping(user)
    return [feed_id for feed_id, folder in mapping.items() if folder == label]


def subscription_ids(user):
    return list(
        UserSubscription.objects.filter(user=user).values_list("feed_id", flat=True)
    )


def query_for_tags(request):
    """it/xt are the include and exclude tag lists; only read and starred map to SQL."""
    include = request.GET.getlist("it")
    exclude = request.GET.getlist("xt")
    clauses = []

    if READ_TAG in exclude:
        clauses.append("read:no")
    if READ_TAG in include:
        clauses.append("read:yes")
    if STAR_TAG in exclude:
        clauses.append("star:no")
    if STAR_TAG in include:
        clauses.append("star:yes")

    return " ".join(clauses)


def story_to_item(story, folder=""):
    published = story.get("story_date")
    published_ts = int(published.timestamp()) if hasattr(published, "timestamp") else int(time.time())
    content = story.get("story_content") or ""
    item_id = story.get("story_hash") or story.get("story_guid") or ""

    return {
        "id": item_id,
        "crawlTimeMsec": str(published_ts * 1000),
        "timestampUsec": str(published_ts * 1000000),
        "published": published_ts,
        "updated": published_ts,
        "title": story.get("story_title") or "",
        "canonical": [{"href": story.get("story_permalink") or ""}],
        "alternate": [
            {"href": story.get("story_permalink") or "", "type": "text/html"}
        ],
        "summary": {"content": content},
        "content": {"content": content, "direction": "ltr"},
        "author": story.get("story_author_name") or "",
        "origin": {
            "streamId": "feed/%s" % story.get("story_feed_id"),
            "title": story.get("feed_title") or "",
            "htmlUrl": story.get("feed_link") or "",
        },
        "categories": ["user/-/state/com.google/reading-list"]
        + (["user/-/label/%s" % folder] if folder else []),
    }


def load_items(user, stream_id, request):
    kind, value = parse_stream(stream_id)
    limit = min(int_or_default(request.GET.get("n"), 20), 100)
    offset = int_or_default(request.GET.get("c"), 0)
    order = "oldest" if request.GET.get("r") == "o" else "newest"
    query = query_for_tags(request)
    folder_map = UserSubscriptionFolders.get_feed_folder_mapping(user)

    if kind == "feed":
        stories = Feed.find_feed_stories([value], query, order=order, offset=offset, limit=limit, user=user)
    elif kind == "label":
        feed_ids = folder_feeds(user, value)
        stories = Feed.find_feed_stories(feed_ids, query, order=order, offset=offset, limit=limit, user=user) if feed_ids else []
    elif kind == "starred":
        stories_db = list(
            MStarredStory.objects.filter(user_id=user.pk).order_by("-starred_date")[offset : offset + limit]
        )
        stories = Feed.format_stories(stories_db)
    elif kind == "reading-list":
        feed_ids = subscription_ids(user)
        stories = Feed.find_feed_stories(feed_ids, query, order=order, offset=offset, limit=limit, user=user) if feed_ids else []
    else:
        stories = []

    items = []
    for story in stories:
        folder = folder_map.get(story.get("story_feed_id"), "")
        item = story_to_item(story, folder)
        if kind == "starred":
            item["categories"].append(STAR_TAG)
        items.append(item)

    return kind, value, items, limit, offset


@csrf_exempt
def greader_subscription_list(request):
    user, error = require_user(request)
    if error:
        return error

    folder_map = UserSubscriptionFolders.get_feed_folder_mapping(user)
    subscriptions = []

    for sub in UserSubscription.objects.filter(user=user).select_related("feed").order_by("feed__feed_title"):
        # get_feed_folder_mapping returns a list of folder titles; top-level
        # feeds sit in a list containing one empty string, which is not a label.
        folders = [folder for folder in (folder_map.get(sub.feed_id) or []) if folder]
        categories = [{"id": "user/-/label/%s" % folder, "label": folder} for folder in folders]
        subscriptions.append(
            {
                "id": "feed/%s" % sub.feed_id,
                "title": sub.feed.feed_title,
                "htmlUrl": sub.feed.feed_link or sub.feed.feed_address,
                "categories": categories,
                "sortid": str(sub.feed_id),
                "firstitemmsec": str(int(sub.unread_count_updated.timestamp() * 1000))
                if sub.unread_count_updated
                else "0",
            }
        )

    return json_out({"subscriptions": subscriptions})


@csrf_exempt
def greader_tag_list(request):
    user, error = require_user(request)
    if error:
        return error

    tags = [{"id": READ_TAG}, {"id": STAR_TAG}, {"id": READING_LIST}]
    folder_map = UserSubscriptionFolders.get_feed_folder_mapping(user)
    labels = sorted(set(folder for folder in folder_map.values() if folder))

    for label in labels:
        tags.append({"id": "user/-/label/%s" % label, "label": label})

    return json_out({"tags": tags})


@csrf_exempt
def greader_unread_count(request):
    user, error = require_user(request)
    if error:
        return error

    counts = []
    total = 0

    for sub in UserSubscription.objects.filter(user=user).select_related("feed"):
        count = (sub.unread_count_positive or 0) + (sub.unread_count_neutral or 0)
        total += count
        counts.append(
            {
                "id": "feed/%s" % sub.feed_id,
                "count": count,
                "newestItemTimestampUsec": str(int(sub.unread_count_updated.timestamp() * 1000000)),
            }
        )

    counts.append({"id": READING_LIST, "count": total, "newestItemTimestampUsec": "0"})

    return json_out({"max": total, "unreadcounts": counts})


@csrf_exempt
def greader_stream_contents(request, stream_id=""):
    user, error = require_user(request)
    if error:
        return error

    kind, value, items, limit, offset = load_items(user, stream_id, request)

    return json_out(
        {
            "id": stream_id,
            "updated": int(time.time()),
            "continuation": str(offset + limit) if len(items) >= limit else None,
            "items": items,
        }
    )


def story_hash_from_item(item_id):
    return (item_id or "").strip()


def mark_read(user, story_hashes, read=True):
    """Marks hashes read or unread per feed, using the subscription helper the web reader uses."""
    by_feed = {}

    for story_hash in story_hashes:
        feed_id = str(story_hash).split(":")[0]
        if feed_id.isdigit():
            by_feed.setdefault(int(feed_id), []).append(story_hash)

    for feed_id, hashes in by_feed.items():
        sub = UserSubscription.objects.filter(user=user, feed_id=feed_id).first()
        if not sub:
            continue
        if read:
            sub.mark_story_ids_as_read(hashes, aggregated=True)
        elif hasattr(sub, "mark_story_ids_as_unread"):
            sub.mark_story_ids_as_unread(hashes)


def star(user, story_hashes, starred=True):
    from apps.rss_feeds.filters import star_story_for_user

    for story_hash in story_hashes:
        if starred:
            story = MStory.objects.filter(story_hash=story_hash).first()
            if story is not None:
                star_story_for_user(user.pk, story)
        else:
            for row in MStarredStory.objects.filter(user_id=user.pk, story_hash=story_hash):
                MStarredStoryCounts.adjust_count(user.pk, feed_id=row.story_feed_id, amount=-1)
                row.delete()


@csrf_exempt
def greader_edit_tag(request):
    """a/r carry tag names, i carries the story hashes."""
    user, error = require_user(request)
    if error:
        return error

    add = request.POST.getlist("a")
    remove = request.POST.getlist("r")
    items = [story_hash_from_item(item) for item in request.POST.getlist("i") if item]

    if READ_TAG in add:
        mark_read(user, items, read=True)
    if READ_TAG in remove:
        mark_read(user, items, read=False)
    if STAR_TAG in add:
        star(user, items, starred=True)
    if STAR_TAG in remove:
        star(user, items, starred=False)

    return text_response("OK")


@csrf_exempt
def greader_mark_all_as_read(request):
    user, error = require_user(request)
    if error:
        return error

    stream_id = request.POST.get("s") or request.GET.get("s") or READING_LIST
    kind, value = parse_stream(stream_id)

    if kind == "feed":
        feed_ids = [value]
    elif kind == "label":
        feed_ids = folder_feeds(user, value)
    else:
        feed_ids = subscription_ids(user)

    stories = Feed.find_feed_stories(feed_ids, "read:no", order="newest", offset=0, limit=500, user=user)
    mark_read(user, [story.get("story_hash") for story in stories], read=True)

    return text_response("OK")


@csrf_exempt
def greader_user_info(request):
    user, error = require_user(request)
    if error:
        return error

    return json_out(
        {
            "userId": str(user.pk),
            "userName": user.username,
            "userEmail": user.email,
            "userProfileId": str(user.pk),
            "isBloggerUser": False,
            "signupTimeSec": int(user.date_joined.timestamp()) if user.date_joined else 0,
        }
    )
