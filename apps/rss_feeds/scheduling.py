"""Fetch scheduling helpers.

The fetch worker runs a single thread (see newsblur_web/supervisor.py), so the
scheduler has to hand it work in small batches and spread feed due times out
instead of letting every feed with the same interval fire at the same second.
"""

# Share of the interval a feed may be shifted by. 20% keeps a 15 minute feed
# inside 15 to 18 minutes while still separating feeds that share a cadence.
PHASE_SPREAD_FRACTION = 0.2


def phase_offset_minutes(feed_id, interval_minutes):
    """Return a stable offset inside the first fifth of the interval.

    The offset is derived from the feed id, not from a random number, so a feed
    keeps its slot across fetch cycles and the due times stay spread out. Feeds
    with ids that differ by one land in different buckets, which is what breaks
    up the burst that used to happen when every 15 minute feed was scheduled
    from the same tick.
    """
    try:
        interval_minutes = float(interval_minutes)
        feed_id = int(feed_id)
    except (TypeError, ValueError):
        return 0.0

    spread = interval_minutes * PHASE_SPREAD_FRACTION
    if spread <= 0:
        return 0.0

    bucket = (feed_id * 37) % 100
    return bucket / 100.0 * spread


def take_due_feeds(r, now_timestamp, budget):
    """Move at most budget due feeds from the schedule into the queue.

    Feeds are taken oldest due first and the remainder stays in
    scheduled_updates for the next beat, which keeps the broker from filling
    with tasks the single worker cannot reach for many minutes. Returns the feed
    ids that were queued.
    """
    if not budget or budget <= 0:
        return []

    due = r.zrangebyscore("scheduled_updates", 0, now_timestamp, start=0, num=int(budget))
    if not due:
        return []

    r.zrem("scheduled_updates", *due)
    r.sadd("queued_feeds", *due)
    return due


def take_priority_feeds(r):
    """Feeds the reader asked for by hand.

    A manual refresh writes the feed into priority_feeds, and those fetches skip
    the per minute budget so the reader does not wait behind the normal
    rotation. They are pulled out of scheduled_updates so the next beat does not
    fetch the same feed twice.
    """
    try:
        priority = r.smembers("priority_feeds")
    except Exception:
        return []

    if not priority:
        return []

    feeds = sorted(priority)
    r.srem("priority_feeds", *feeds)
    r.zrem("scheduled_updates", *feeds)
    # TaskFeeds drains queued_feeds, so manual refreshes join the same queue.
    r.sadd("queued_feeds", *feeds)
    return feeds
