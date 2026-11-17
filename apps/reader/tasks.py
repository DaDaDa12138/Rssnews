"""Reader tasks: periodic maintenance for reader subscriptions."""

import redis
from django.conf import settings
from django.contrib.auth.models import User

from apps.reader.models import UserSubscription
from newsblur_web.celeryapp import app


@app.task(name="maintain-feed-subscriptions")
def MaintainFeedSubscriptions(user_id, changed, feed_ids):
    # apps/reader/tasks.py keeps Redis and subscriber maintenance outside the batch HTTP request.
    from apps.rss_feeds.models import Feed

    user = User.objects.filter(pk=user_id).first()
    if user is None:
        return
    feeds = Feed.objects.in_bulk(feed_id for feed_id, _ in changed)
    for feed_id, created in changed:
        feed = feeds.get(feed_id)
        if feed is None:
            continue
        if created:
            feed.setup_feed_for_premium_subscribers()
        if feed.archive_count:
            feed.schedule_fetch_archive_feed()
    redis.Redis(connection_pool=settings.REDIS_PUBSUB_POOL).publish(user.username, "reload:feeds")


@app.task(name="mark-stories-as-unread")
def MarkStoriesAsUnread(user_id, feed_ids, days):
    UserSubscription.mark_stories_as_unread(user_id, feed_ids, days)
