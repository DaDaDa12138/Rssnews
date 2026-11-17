"""Add known public feeds without the URL discovery/fetch path in reader/views.py."""


import redis
from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction

from apps.reader.models import UserSubscription, UserSubscriptionFolders
from apps.reader.tasks import MaintainFeedSubscriptions
from apps.rss_feeds.models import Feed
from utils import json_functions as json
from utils.folder_paths import InvalidFolderPath, resolve_folder_path


def _destination(tree, folder_path, folder, new_folder):
    if folder_path is None:
        paths = []

        def find_paths(children, parent):
            for item in children:
                if isinstance(item, dict):
                    for name, contents in item.items():
                        path = parent + [name]
                        if name.lower() == folder.lower():
                            paths.append(path)
                        find_paths(contents, path)

        if folder.strip():
            find_paths(tree, [])
            if len(paths) != 1:
                raise InvalidFolderPath("Please choose an unambiguous folder path.")
            folder_path = paths[0]
        else:
            folder_path = []
    parent = resolve_folder_path(tree, folder_path)
    if new_folder:
        # Reuse the same child on a retry, including its original spelling and contents.
        # Unlike blindly appending a new folder, this cannot replace an existing bundle.
        matches = [
            contents
            for item in parent
            if isinstance(item, dict)
            for name, contents in item.items()
            if name.lower() == new_folder.lower()
        ]
        if len(matches) > 1:
            raise InvalidFolderPath("Please choose an unambiguous folder path.")
        if matches:
            return matches[0]
        contents = []
        parent.append({new_folder: contents})
        return contents
    return parent


def _access_error(user, feed, subscribed, banned_urls):
    if subscribed:
        return None
    if any(domain in feed.feed_address for domain in banned_urls):
        return "The publisher of this website has banned NewsBlur."
    return None


def add_feed_ids(
    user, feed_ids, folder_path=None, folder="", new_folder="", auto_active=True, banned_urls=()
):
    results = []
    changed = []
    numeric_ids = []
    for value in feed_ids:
        try:
            number = int(value)
            if isinstance(value, bool) or str(number) != str(value) or not 0 < number <= 2147483647:
                raise ValueError
        except (ValueError, TypeError):
            number = None
        numeric_ids.append(number)
    feeds = Feed.objects.in_bulk(number for number in numeric_ids if number is not None)
    with transaction.atomic():
        # Serialize bundle requests even before a user's folder row exists. Lock the
        # folder row too so other callers that lock it share the same serialization.
        User.objects.select_for_update().get(pk=user.pk)
        folders, _ = UserSubscriptionFolders.objects.get_or_create(user=user)
        folders = UserSubscriptionFolders.objects.select_for_update().get(pk=folders.pk)
        tree = json.decode(folders.folders or "[]")
        destination = _destination(tree, folder_path, folder, new_folder)
        subscriptions = {
            sub.feed_id: sub for sub in UserSubscription.objects.filter(user=user, feed_id__in=feeds)
        }
        active = True
        seen = set()
        for value, feed_id in zip(feed_ids, numeric_ids):
            if feed_id is not None and feed_id in seen:
                continue
            seen.add(feed_id)
            feed = feeds.get(feed_id)
            sub = subscriptions.get(feed_id)
            message = "Invalid feed ID." if feed_id is None else "Feed not found." if feed is None else None
            if not message:
                message = _access_error(user, feed, sub is not None, banned_urls)
            if message:
                results.append(
                    {"feed_id": value if feed_id is None else feed_id, "code": -1, "message": message}
                )
                continue
            created = sub is None
            was_active = sub.active if sub else False
            if created:
                sub = UserSubscription.objects.create(
                    user=user, feed=feed, active=active, needs_unread_recalc=True
                )
            elif active and not sub.active:
                sub.active = True
                sub.needs_unread_recalc = True
                sub.save(update_fields=["active", "needs_unread_recalc"])
            if feed_id not in destination:
                destination.append(feed_id)
            if created or (active and not was_active):
                changed.append((feed.pk, created))
            results.append({"feed_id": feed_id, "code": 1, "message": "", "created": created})
        successful_ids = [item["feed_id"] for item in results if item["code"] == 1]
        if successful_ids:
            folders.folders = json.encode(tree)
            folders.save(update_fields=["folders"])
            # subscription_batch.py queues maintenance only after the outermost transaction commits.
            transaction.on_commit(lambda: MaintainFeedSubscriptions.delay(user.pk, changed, successful_ids))
            transaction.on_commit(
                lambda: redis.Redis(connection_pool=settings.REDIS_PUBSUB_POOL).publish(
                    user.username, "reload:feeds"
                )
            )
    # subscription_batch.py surfaces the first failure so clients can explain partial or failed batches.
    message = next((item["message"] for item in results if item["code"] == -1), "")
    return {
        "code": 1 if len(successful_ids) == len(results) else 0 if successful_ids else -1,
        "message": message,
        "results": results,
        "folders": json.decode(folders.folders or "[]"),
    }
