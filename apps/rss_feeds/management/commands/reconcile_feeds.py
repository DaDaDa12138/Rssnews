"""Put the reader's feed state back in line with Postgres after a restart or a reset.

Three things live outside Postgres and drift when the database is rebuilt or a
container is restarted mid-fetch:

* the Redis sorted set scheduled_updates, which is the fetch queue (see
  apps/rss_feeds/tasks.py:reconcile_feed_schedule, which runs every minute),
* the Redis subscriber sets behind Feed.active_subscribers (rebuilt by
  manage.py count_subscribers),
* the feed ids in UserSubscriptionFolders.folders, which is a JSON tree and keeps
  ids of feeds the user has since removed.

This command repairs the last one and re-runs the queue repair on demand.
"""

import datetime
import json

import redis
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.reader.models import UserSubscription, UserSubscriptionFolders
from apps.rss_feeds.models import Feed
from apps.rss_feeds.tasks import reconcile_feed_schedule


class Command(BaseCommand):
    help = "Drop feed ids without a subscription from the folder tree and rebuild the fetch queue."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", dest="dry_run", action="store_true", help="Report what would change, change nothing."
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        for usf in UserSubscriptionFolders.objects.all():
            subscribed = set(
                UserSubscription.objects.filter(user=usf.user, active=True).values_list("feed_id", flat=True)
            )
            folders = json.loads(usf.folders)
            dropped = []

            def prune(items):
                kept = []
                for item in items:
                    if isinstance(item, int):
                        if item in subscribed:
                            kept.append(item)
                        else:
                            dropped.append(item)
                    elif isinstance(item, dict):
                        kept.append({name: prune(children) for name, children in item.items()})
                return kept

            pruned = prune(folders)
            print(
                " ---> %s: %s feeds subscribed, folder tree %s -> %s"
                % (usf.user.username, len(subscribed), len(json.dumps(folders)), len(json.dumps(pruned)))
            )
            if dropped:
                print(" ---> Dropping feed ids without a subscription: %s" % sorted(set(dropped)))
            if not dry_run and pruned != folders:
                usf.folders = json.dumps(pruned)
                usf.save(update_fields=["folders"])

        now = datetime.datetime.utcnow()
        r = redis.Redis(connection_pool=settings.REDIS_FEED_UPDATE_POOL)
        stale, rescheduled = reconcile_feed_schedule(r, now)

        # A feed that lost its last subscriber keeps its queue entry until the fetch
        # that is already scheduled runs, and set_next_scheduled_update stops there.
        # Dropping the entry now means no fetch happens at all.
        unsubscribed = [
            feed_id
            for feed_id in r.zrange("scheduled_updates", 0, -1)
            if not UserSubscription.objects.filter(feed_id=feed_id, active=True).exists()
            and not Feed.objects.filter(pk=feed_id, active_subscribers__gte=1).exists()
        ]
        if unsubscribed:
            r.zrem("scheduled_updates", *unsubscribed)
            print(" ---> Dropped queued feeds with no subscriber left: %s" % sorted(int(f) for f in unsubscribed))
        print(
            " ---> Fetch queue: %s stale tasked entries dropped, %s overdue feeds rescheduled, "
            "%s feeds scheduled in total"
            % (stale, rescheduled, r.zcard("scheduled_updates"))
        )
        print(
            " ---> Feeds with no active subscriber: %s"
            % list(Feed.objects.filter(active_subscribers=0).values_list("pk", "feed_title"))
        )
