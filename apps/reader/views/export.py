"""Settings export: one JSON bundle of everything a reader has configured.

Moving to another instance or backing up before an experiment should not need a
database dump, so this collects subscriptions, folders, view settings, filters,
saved searches and tags in one document. It is read only.
"""

from ._base import *  # noqa: F401,F403

import json as jsonlib

from django.http import HttpResponse

from apps.reader.models import (
    SavedSearch,
    StoryTag,
    UserSubscription,
    UserSubscriptionFolders,
)
from apps.rss_feeds.models import Feed, StoryFilter


def export_settings(request):
    user = request.user

    if not user or not user.is_authenticated:
        return HttpResponse("Unauthorized", status=401, content_type="text/plain")

    subscriptions = []

    for sub in UserSubscription.objects.filter(user=user).select_related("feed"):
        subscriptions.append(
            {
                "feed_id": sub.feed_id,
                "feed_address": sub.feed.feed_address,
                "feed_title": sub.feed.feed_title,
                "feed_link": sub.feed.feed_link,
                "fetch_interval": sub.feed.get_configured_fetch_interval() or 0,
            }
        )

    folders_row = UserSubscriptionFolders.objects.filter(user=user).first()
    profile = getattr(user, "profile", None)
    # Profile.view_settings is a JSON string, so hand the export a real object.
    view_settings = {}

    if profile and profile.view_settings:
        try:
            view_settings = jsonlib.loads(profile.view_settings)
        except ValueError:
            view_settings = {}

    payload = {
        "version": 1,
        "exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "user": {"username": user.username, "email": user.email},
        "folders": folders_row.folders if folders_row else [],
        "subscriptions": subscriptions,
        "view_settings": view_settings,
        "preferences": {
            "feed_pane_size": profile.feed_pane_size if profile else None,
        },
        "filters": [
            {
                "scope": rule.scope,
                "feed_id": rule.feed_id,
                "folder": rule.folder,
                "field": rule.field,
                "pattern": rule.pattern,
                "is_regex": rule.is_regex,
                "case_sensitive": rule.case_sensitive,
                "action": rule.action,
                "tag": rule.tag,
                "enabled": rule.enabled,
            }
            for rule in StoryFilter.objects.filter(user=user)
        ],
        "saved_searches": [
            {"name": saved.name, "query": saved.query, "order": saved.order}
            for saved in SavedSearch.objects.filter(user=user)
        ],
        "tags": [row["tag"] for row in StoryTag.counts(user.pk)],
    }

    response = HttpResponse(
        jsonlib.dumps(payload), content_type="application/json; charset=utf-8"
    )
    response["Content-Disposition"] = 'attachment; filename="newsblur-settings.json"'

    return response


def import_settings(request):
    """Merge a previously exported bundle back into this reader's settings.

    Additive on purpose: nothing is deleted, existing folders are never pruned
    (imported feeds are parked at the top level so the sidebar can show them),
    and feeds that this instance has never seen are skipped and counted, so
    importing a stale bundle cannot unsubscribe or prune a reader. Story tags
    are exported for reference but are not recreated here.
    """
    user = request.user

    if not user or not user.is_authenticated:
        return HttpResponse("Unauthorized", status=401, content_type="text/plain")

    if request.method != "POST":
        return HttpResponse("POST required", status=405, content_type="text/plain")

    # There is no CsrfViewMiddleware in this deployment, so a cross-site form
    # post could otherwise reach this view. Custom headers are not available to
    # cross-origin forms, and jQuery sends this one on every ajax request.
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        return HttpResponse("Missing X-Requested-With", status=403, content_type="text/plain")

    upload = request.FILES.get("file")
    raw = None

    if upload:
        raw = upload.read().decode("utf-8", "replace")
    elif request.body:
        raw = request.body.decode("utf-8", "replace")

    if not raw:
        return HttpResponse("Empty payload", status=400, content_type="text/plain")

    try:
        payload = jsonlib.loads(raw)
    except ValueError:
        return HttpResponse("Invalid JSON", status=400, content_type="text/plain")

    if not isinstance(payload, dict) or payload.get("version") != 1:
        return HttpResponse("Unsupported settings version", status=400, content_type="text/plain")

    counts = {
        "subscriptions_added": 0,
        "skipped_subscriptions": 0,
        "view_settings_merged": 0,
        "preferences_updated": 0,
        "filters_added": 0,
        "saved_searches_added": 0,
        "saved_searches_updated": 0,
    }

    # Subscriptions: only feeds this instance already knows, matched by address.
    subscriptions = [item for item in payload.get("subscriptions") or [] if isinstance(item, dict)]
    addresses = [item.get("feed_address") for item in subscriptions if item.get("feed_address")]
    feeds = {feed.feed_address: feed for feed in Feed.objects.filter(feed_address__in=addresses)}
    subscribed = set(UserSubscription.objects.filter(user=user).values_list("feed_id", flat=True))
    added_feed_ids = []

    for item in subscriptions:
        feed = feeds.get(item.get("feed_address"))

        if not feed:
            counts["skipped_subscriptions"] += 1
            continue
        if feed.pk in subscribed:
            continue

        UserSubscription.objects.create(user=user, feed=feed)
        subscribed.add(feed.pk)
        added_feed_ids.append(feed.pk)
        counts["subscriptions_added"] += 1

    # A subscription that is missing from the folder tree never shows up in the
    # sidebar, so park imported feeds at the top level.
    if added_feed_ids:
        folders_row, _ = UserSubscriptionFolders.objects.get_or_create(user=user)
        try:
            tree = jsonlib.loads(folders_row.folders or "[]")
        except ValueError:
            tree = []

        if isinstance(tree, list):
            known = set()

            def collect_ids(items):
                for item in items:
                    if isinstance(item, int):
                        known.add(item)
                    elif isinstance(item, dict):
                        for value in item.values():
                            if isinstance(value, list):
                                collect_ids(value)

            collect_ids(tree)

            for feed_id in added_feed_ids:
                if feed_id not in known:
                    tree.append(feed_id)
                    known.add(feed_id)

            folders_row.folders = jsonlib.dumps(tree)
            folders_row.save(update_fields=["folders"])

    profile = getattr(user, "profile", None)
    incoming_views = payload.get("view_settings")

    if profile and isinstance(incoming_views, dict) and incoming_views:
        current = {}

        try:
            current = jsonlib.loads(profile.view_settings or "{}")
        except ValueError:
            current = {}

        if isinstance(current, dict):
            current.update(incoming_views)
            profile.view_settings = jsonlib.dumps(current)
            profile.save(update_fields=["view_settings"])
            counts["view_settings_merged"] = len(incoming_views)

    preferences = payload.get("preferences") or {}

    if profile and isinstance(preferences, dict) and preferences.get("feed_pane_size"):
        try:
            profile.feed_pane_size = int(preferences["feed_pane_size"])
        except (TypeError, ValueError):
            pass
        else:
            profile.save(update_fields=["feed_pane_size"])
            counts["preferences_updated"] = 1

    valid_scopes = {choice[0] for choice in StoryFilter.SCOPE_CHOICES}
    valid_fields = {choice[0] for choice in StoryFilter.FIELD_CHOICES}
    valid_actions = {choice[0] for choice in StoryFilter.ACTION_CHOICES}

    for item in payload.get("filters") or []:
        if not isinstance(item, dict) or not (item.get("pattern") or "").strip():
            continue

        scope = item.get("scope") if item.get("scope") in valid_scopes else StoryFilter.SCOPE_GLOBAL
        field = item.get("field") if item.get("field") in valid_fields else StoryFilter.FIELD_ANY
        action = item.get("action") if item.get("action") in valid_actions else StoryFilter.ACTION_MARK_READ
        feed = None

        if scope == StoryFilter.SCOPE_FEED:
            feed = Feed.objects.filter(pk=item.get("feed_id")).first()

            if not feed:
                continue

        rule, created = StoryFilter.objects.get_or_create(
            user=user,
            scope=scope,
            feed=feed,
            folder=(item.get("folder") or "")[:255],
            field=field,
            pattern=item["pattern"].strip()[:255],
            action=action,
            tag=(item.get("tag") or "")[:64],
            defaults={
                "is_regex": bool(item.get("is_regex")),
                "case_sensitive": bool(item.get("case_sensitive")),
                "enabled": item.get("enabled", True) is not False,
            },
        )

        if created:
            counts["filters_added"] += 1

    for item in payload.get("saved_searches") or []:
        if not isinstance(item, dict):
            continue

        name = (item.get("name") or "").strip()[:128]
        query = (item.get("query") or "").strip()[:512]

        if not name or not query:
            continue

        saved, created = SavedSearch.objects.get_or_create(
            user=user,
            name=name,
            defaults={"query": query, "order": (item.get("order") or "newest")[:8]},
        )

        if created:
            counts["saved_searches_added"] += 1
        elif saved.query != query:
            saved.query = query
            saved.save(update_fields=["query"])
            counts["saved_searches_updated"] += 1

    return HttpResponse(jsonlib.dumps(counts), content_type="application/json; charset=utf-8")
