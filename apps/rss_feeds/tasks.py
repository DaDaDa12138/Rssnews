"""RSS feed tasks: orchestrate the feed refresh pipeline including fetch and parse."""

import datetime
import time

import redis
from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.db import connection

from apps.profile.middleware import DBProfilerMiddleware
from apps.rss_feeds.scheduling import take_due_feeds, take_priority_feeds
from newsblur_web.celeryapp import app
from utils import log as logging
from utils.redis_raw_log_middleware import RedisDumpMiddleware

FEED_TASKING_MAX = 10000

# Postgres holds every feed's next_scheduled_update, but the queue that is read
# every minute lives in Redis: scheduled_updates. A fetch is taken off that queue
# before it runs and put back only when it finishes, so a restart in between (or a
# Redis restart that loses the sorted set) leaves a feed with a past due date and
# no queue entry. TaskBrokenFeeds sweeps those, but only every six hours and only
# for feeds a day behind, so one restart could stall a feed for most of a day.
TASKED_FEED_STALE_SECONDS = 15 * 60


def reconcile_feed_schedule(r, now):
    """Bring the Redis fetch queue back in line with Postgres before it is read."""
    from apps.rss_feeds.models import Feed

    now_timestamp = int(now.strftime("%s"))
    stale_before = now_timestamp - TASKED_FEED_STALE_SECONDS
    stale_feeds = r.zrangebyscore("tasked_feeds", 0, stale_before)
    if stale_feeds:
        r.zremrangebyscore("tasked_feeds", 0, stale_before)
        logging.debug(
            " ---> ~SN~FBDropped ~SB%s~SN feeds left in tasked_feeds by a restart: ~SB%s"
            % (len(stale_feeds), stale_feeds)
        )

    overdue = Feed.objects.filter(
        active=True, active_subscribers__gte=1, next_scheduled_update__lte=now
    ).values_list("pk", "next_scheduled_update")
    rescheduled = []
    for feed_id, next_update in overdue:
        if next_update is None or r.zscore("scheduled_updates", feed_id) is not None:
            continue
        r.zadd("scheduled_updates", {feed_id: int(next_update.strftime("%s"))})
        rescheduled.append(feed_id)
    if rescheduled:
        logging.debug(
            " ---> ~SN~FBRescheduled ~SB%s~SN overdue feeds missing from the queue: ~SB%s"
            % (len(rescheduled), rescheduled)
        )

    return len(stale_feeds), len(rescheduled)


@app.task(name="task-feeds")
def TaskFeeds():
    from apps.rss_feeds.models import Feed

    now = datetime.datetime.utcnow()
    start = time.time()
    r = redis.Redis(connection_pool=settings.REDIS_FEED_UPDATE_POOL)

    hour_ago = now - datetime.timedelta(hours=1)
    r.zremrangebyscore("fetched_feeds_last_hour", 0, int(hour_ago.strftime("%s")))

    reconcile_feed_schedule(r, now)
    tasked_feeds_size = r.zcard("tasked_feeds")

    now_timestamp = int(now.strftime("%s"))
    # The worker is single threaded, so tasking every due feed at once only
    # builds a broker backlog nobody can drain. Take a small batch per beat and
    # leave the rest scheduled; see apps/rss_feeds/scheduling.py.
    budget = getattr(settings, "FEED_TASKING_PER_MINUTE", 4)
    due_count = r.zcount("scheduled_updates", 0, now_timestamp)
    priority_feeds = take_priority_feeds(r)
    queued_feeds = take_due_feeds(r, now_timestamp, budget)
    if not queued_feeds and not priority_feeds:
        logging.debug(" ---> ~SN~FB~BMNo feeds to queue! Exiting...")
        return

    logging.debug(
        " ---> ~SN~FBQueuing ~SB%s~SN of ~SB%s~SN stale feeds plus ~SB%s~SN manual "
        "(~SB%s~SN/~FG%s~FB~SN/%s tasked/queued/scheduled)"
        % (
            len(queued_feeds),
            due_count,
            len(priority_feeds),
            r.zcard("tasked_feeds"),
            r.scard("queued_feeds"),
            r.zcard("scheduled_updates"),
        )
    )

    # Regular feeds
    if tasked_feeds_size < FEED_TASKING_MAX:
        feeds = r.srandmember("queued_feeds", FEED_TASKING_MAX)
        Feed.task_feeds(feeds, verbose=True)
        active_count = len(feeds)
    else:
        logging.debug(" ---> ~SN~FBToo many tasked feeds. ~SB%s~SN tasked." % tasked_feeds_size)
        active_count = 0
        feeds = []

    logging.debug(
        " ---> ~SN~FBTasking %s feeds took ~SB%s~SN seconds (~SB%s~SN/~FG%s~FB~SN/%s tasked/queued/scheduled)"
        % (
            active_count,
            int((time.time() - start)),
            r.zcard("tasked_feeds"),
            r.scard("queued_feeds"),
            r.zcard("scheduled_updates"),
        )
    )
    logging.debug(" ---> ~FBFeeds being tasked: ~SB%s" % feeds)


@app.task(name="task-broken-feeds")
def TaskBrokenFeeds():
    from apps.rss_feeds.models import Feed

    now = datetime.datetime.utcnow()
    start = time.time()
    r = redis.Redis(connection_pool=settings.REDIS_FEED_UPDATE_POOL)

    logging.debug(" ---> ~SN~FBQueuing broken feeds...")

    # Force refresh feeds
    refresh_feeds = Feed.objects.filter(active=True, fetched_once=False, active_subscribers__gte=1).order_by(
        "?"
    )[:100]
    refresh_count = refresh_feeds.count()
    cp1 = time.time()

    logging.debug(" ---> ~SN~FBFound %s active, unfetched broken feeds" % refresh_count)

    # Mistakenly inactive feeds
    hours_ago = (now - datetime.timedelta(minutes=10)).strftime("%s")
    old_tasked_feeds = r.zrangebyscore("tasked_feeds", 0, hours_ago)
    inactive_count = len(old_tasked_feeds)
    if inactive_count:
        r.zremrangebyscore("tasked_feeds", 0, hours_ago)
        # r.sadd('queued_feeds', *old_tasked_feeds)
        for feed_id in old_tasked_feeds:
            r.zincrby("error_feeds", 1, feed_id)
            feed = Feed.get_by_id(feed_id)
            feed.set_next_scheduled_update()
    logging.debug(
        " ---> ~SN~FBRe-queuing ~SB%s~SN dropped/broken feeds (~SB%s/%s~SN queued/tasked)"
        % (inactive_count, r.scard("queued_feeds"), r.zcard("tasked_feeds"))
    )
    cp2 = time.time()

    old = now - datetime.timedelta(days=1)
    old_feeds = Feed.objects.filter(next_scheduled_update__lte=old, active_subscribers__gte=1).order_by("?")[
        :500
    ]
    old_count = old_feeds.count()
    cp3 = time.time()

    logging.debug(
        " ---> ~SN~FBTasking ~SBrefresh:~FC%s~FB inactive:~FC%s~FB old:~FC%s~SN~FB broken feeds... (%.4s/%.4s/%.4s)"
        % (
            refresh_count,
            inactive_count,
            old_count,
            cp1 - start,
            cp2 - cp1,
            cp3 - cp2,
        )
    )

    Feed.task_feeds(refresh_feeds, verbose=False)
    Feed.task_feeds(old_feeds, verbose=False)

    logging.debug(
        " ---> ~SN~FBTasking broken feeds took ~SB%s~SN seconds (~SB%s~SN/~FG%s~FB~SN/%s tasked/queued/scheduled)"
        % (
            int((time.time() - start)),
            r.zcard("tasked_feeds"),
            r.scard("queued_feeds"),
            r.zcard("scheduled_updates"),
        )
    )


@app.task(name="update-feeds", time_limit=10 * 60, soft_time_limit=9 * 60, ignore_result=True)
def UpdateFeeds(feed_pks):
    from apps.rss_feeds.models import Feed

    r = redis.Redis(connection_pool=settings.REDIS_FEED_UPDATE_POOL)

    mongodb_replication_lag = 0
    compute_scores = True

    profiler = DBProfilerMiddleware()
    profiler_activated = profiler.process_celery()
    if profiler_activated:
        redis_middleware = RedisDumpMiddleware()
        redis_middleware.process_celery(profiler)

    options = {
        "quick": 0.0,
        "updates_off": False,
        "compute_scores": compute_scores,
        "mongodb_replication_lag": mongodb_replication_lag,
    }

    if not isinstance(feed_pks, list):
        feed_pks = [feed_pks]

    try:
        for feed_pk in feed_pks:
            feed = Feed.get_by_id(feed_pk)
            if not feed or feed.pk != int(feed_pk):
                logging.info(
                    " ---> ~FRRemoving feed_id %s from tasked_feeds queue, points to %s..."
                    % (feed_pk, feed and feed.pk)
                )
                r.zrem("tasked_feeds", feed_pk)
            if not feed:
                continue
            if profiler_activated:
                # process_celery_finished reads each feed's queries and turns recording off
                # (apps/profile/middleware.py SQLLogToConsoleMiddleware), so every feed turns it on.
                # The Mongo command logger only exists on the hosted deployment.
                mongo_logger = getattr(settings, "MONGO_COMMAND_LOGGER", None)

                if mongo_logger:
                    mongo_logger.process_celery(profiler)
            try:
                feed.update(**options)
            except SoftTimeLimitExceeded as e:
                feed.save_feed_history(505, "Timeout", e)
                logging.info(" ---> [%-30s] ~BR~FWTime limit hit!~SB~FR Moving on to next feed..." % feed)
            if profiler_activated:
                profiler.process_celery_finished()
    finally:
        # A feed that raised skipped process_celery_finished, which would leave recording on for every
        # later task on this worker thread (utils/mongo_command_monitor.py), and leave the DEBUG that
        # DBProfilerMiddleware.process_celery turned on, which makes the fetcher skip PuSH and Sentry.
        connection.queriesx = None
        if profiler_activated and not getattr(settings, "ORIGINAL_DEBUG", settings.DEBUG):
            settings.DEBUG = False


@app.task(name="new-feeds", time_limit=10 * 60, soft_time_limit=9 * 60, ignore_result=True)
def NewFeeds(feed_pks):
    from apps.rss_feeds.models import Feed

    if not isinstance(feed_pks, list):
        feed_pks = [feed_pks]

    options = {}
    for feed_pk in feed_pks:
        feed = Feed.get_by_id(feed_pk)
        if not feed:
            continue
        feed.update(options=options)


@app.task(name="trim-abandoned-feeds", time_limit=60 * 60, soft_time_limit=55 * 60, ignore_result=True)
def TrimAbandonedFeeds(time_budget_seconds=50 * 60):
    """Daily: trims feeds nobody has been seen reading in DAYS_OF_UNREAD days
    (Feed.trim_if_abandoned in apps/rss_feeds/models.py), oldest last fetch first. A feed stays
    a candidate until its last fetch is twice DAYS_OF_UNREAD old, so a day that runs out of time
    is picked up the next day. Older feeds are left to manage.py trim_feeds.
    apps/rss_feeds/tasks.py"""
    from apps.rss_feeds.models import Feed

    oldest_fetch = datetime.datetime.now() - datetime.timedelta(days=settings.DAYS_OF_UNREAD * 2)
    feed_ids = list(
        Feed.abandoned_feed_candidates()
        .filter(last_update__gte=oldest_fetch)
        .order_by("last_update")
        .values_list("pk", flat=True)
    )
    started = time.time()
    checked = 0
    trimmed_feeds = 0
    trimmed_stories = 0
    for feed_id in feed_ids:
        if time.time() - started > time_budget_seconds:
            break
        checked += 1
        try:
            removed = Feed.trim_if_abandoned(feed_id)
        except SoftTimeLimitExceeded:
            raise
        except Exception as e:
            # One bad feed shouldn't hold up the rest; it stays a candidate for tomorrow.
            logging.debug(" ***> ~FRCouldn't trim abandoned feed %s: %s" % (feed_id, e))
            continue
        if removed:
            trimmed_feeds += 1
            trimmed_stories += removed

    logging.debug(
        " ---> ~FBTrimmed ~SB%s~SN stories from ~SB%s~SN abandoned feeds (%s of %s candidates checked)"
        % (trimmed_stories, trimmed_feeds, checked, len(feed_ids))
    )


@app.task(name="trim-stories", time_limit=60 * 60, soft_time_limit=55 * 60, ignore_result=True)
def TrimStories():
    """Daily: enforces the absolute ceiling and the age cap on every feed, then prunes
    cached translations. The trim after a fetch only runs when new stories arrive, so a
    feed that stopped publishing, or one that handed over its whole archive in a single
    response, is only brought back down here. apps/rss_feeds/tasks.py"""
    from apps.reader.models import TranslationCache
    from apps.rss_feeds.models import Feed

    trimmed_stories = Feed.enforce_story_retention_on_all()
    pruned_translations = TranslationCache.prune()
    logging.debug(
        " ---> ~FBRetention trimmed ~SB%s~SN stories and pruned ~SB%s~SN cached translations"
        % (trimmed_stories, pruned_translations)
    )


@app.task(name="merge-feeds", time_limit=65 * 60, soft_time_limit=60 * 60, ignore_result=True)
def MergeFeeds(original_feed_id, duplicate_feed_id, feed_address=None):
    """merge_feeds off the fetch queue. check_feed_link_for_feed_address hands a merge here
    when it would move MERGE_FEEDS_LARGE_MOVE_SUBSCRIPTIONS or more subscriptions: run inline,
    a merge that size (Hacker News moved 15,492 in 13 minutes, forum #13860) outlasts the
    fetch task's 9 minute soft limit and stalls the rest of its batch. merge_feeds decides the
    survivor itself, exactly as the save collision would have; with the address the check
    discovered, the survivor then takes it and is marked healthy, as an inline fix is. A merge
    cut short here is finished by the pair's next collision or by merge_feeds with the same
    pair. apps/rss_feeds/tasks.py
    """
    from redis.exceptions import LockError

    from apps.rss_feeds.models import Feed, clear_merge_feeds_queued, merge_feeds, settle_address_check_merge

    try:
        survivor = Feed.get_by_id(merge_feeds(original_feed_id, duplicate_feed_id))
        if survivor and feed_address:
            settle_address_check_merge(survivor, feed_address)
    except LockError as e:
        # Another merge of these feeds holds their locks and finishes the job.
        logging.debug(
            " ---> MergeFeeds(%s, %s) found the feeds locked: %s" % (original_feed_id, duplicate_feed_id, e)
        )
    finally:
        clear_merge_feeds_queued(original_feed_id, duplicate_feed_id)


@app.task()
def ScheduleImmediateFetches(feed_ids, user_id=None):
    from apps.rss_feeds.models import Feed

    if not isinstance(feed_ids, list):
        feed_ids = [feed_ids]

    Feed.schedule_feed_fetches_immediately(feed_ids, user_id=user_id)


@app.task()
def ScheduleCountTagsForUser(user_id):
    from apps.rss_feeds.models import MStarredStoryCounts

    MStarredStoryCounts.count_for_user(user_id)
