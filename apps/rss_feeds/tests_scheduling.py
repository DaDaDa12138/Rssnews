"""Tests for the fetch scheduling helpers (apps/rss_feeds/scheduling.py)."""

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, override_settings

from apps.reader.models import UserSubscription
from apps.rss_feeds.models import Feed
from apps.rss_feeds.scheduling import (
    PHASE_SPREAD_FRACTION,
    phase_offset_minutes,
    take_due_feeds,
    take_priority_feeds,
)


class FakeRedis:
    """Minimal stand-in for the sorted set and set calls the helpers make."""

    def __init__(self, scheduled, priority=()):
        self.scheduled = dict(scheduled)
        self.queued = set()
        self.priority = set(priority)

    def zrangebyscore(self, name, low, high, start=0, num=None):
        due = sorted(
            (score, feed_id) for feed_id, score in self.scheduled.items() if low <= score <= high
        )
        ids = [feed_id for _, feed_id in due]
        if num is not None:
            ids = ids[start:start + num]
        return ids

    def zrem(self, name, *members):
        for member in members:
            self.scheduled.pop(member, None)

    def sadd(self, name, *members):
        if name == "priority_feeds":
            self.priority.update(members)
        else:
            self.queued.update(members)

    def srem(self, name, *members):
        if name == "priority_feeds":
            self.priority.difference_update(members)
        else:
            self.queued.difference_update(members)

    def smembers(self, name):
        return set(self.priority) if name == "priority_feeds" else set(self.queued)


class Test_PhaseOffset(SimpleTestCase):
    def test_offset_is_stable_across_cycles(self):
        self.assertEqual(phase_offset_minutes(17, 15), phase_offset_minutes(17, 15))

    def test_offset_stays_inside_the_spread_window(self):
        for feed_id in range(1, 60):
            for interval in (5, 15, 75):
                offset = phase_offset_minutes(feed_id, interval)
                self.assertGreaterEqual(offset, 0)
                self.assertLess(offset, interval * PHASE_SPREAD_FRACTION)

    def test_offset_separates_feeds_on_the_same_cadence(self):
        offsets = {round(phase_offset_minutes(feed_id, 15), 3) for feed_id in range(1, 41)}
        # Every 15 minute feed used to fire at the same second; a handful of
        # buckets is all it takes to break that up.
        self.assertGreaterEqual(len(offsets), 10)

    def test_missing_input_falls_back_to_zero(self):
        self.assertEqual(phase_offset_minutes(None, 15), 0.0)
        self.assertEqual(phase_offset_minutes(3, None), 0.0)
        self.assertEqual(phase_offset_minutes(3, 0), 0.0)


class Test_TakeDueFeeds(SimpleTestCase):
    def test_budget_caps_the_batch_and_keeps_the_rest_scheduled(self):
        r = FakeRedis({feed_id: 100 for feed_id in range(1, 11)})
        queued = take_due_feeds(r, 200, 4)
        self.assertEqual(len(queued), 4)
        self.assertEqual(len(r.queued), 4)
        self.assertEqual(len(r.scheduled), 6)

    def test_oldest_due_feeds_go_first(self):
        r = FakeRedis({1: 300, 2: 100, 3: 200})
        self.assertEqual(take_due_feeds(r, 400, 2), [2, 3])

    def test_nothing_due_returns_empty(self):
        r = FakeRedis({1: 900})
        self.assertEqual(take_due_feeds(r, 400, 4), [])
        self.assertEqual(r.queued, set())

    def test_zero_budget_queues_nothing(self):
        r = FakeRedis({1: 100})
        self.assertEqual(take_due_feeds(r, 200, 0), [])
        self.assertEqual(r.scheduled, {1: 100})


class Test_TakePriorityFeeds(SimpleTestCase):
    def test_manual_feeds_skip_the_budget_and_leave_the_schedule(self):
        r = FakeRedis({feed_id: 900 for feed_id in range(1, 6)}, priority=[2, 4])
        self.assertEqual(take_priority_feeds(r), [2, 4])
        self.assertEqual(r.priority, set())
        self.assertEqual(sorted(r.queued), [2, 4])
        # A manual fetch must not fire twice, so its schedule entry is dropped.
        self.assertEqual(sorted(r.scheduled), [1, 3, 5])

    def test_no_manual_feeds_is_a_no_op(self):
        r = FakeRedis({1: 900})
        self.assertEqual(take_priority_feeds(r), [])
        self.assertEqual(r.scheduled, {1: 900})
        self.assertEqual(r.queued, set())


class Test_MutedFeedCadence(TestCase):
    """A feed every reader muted still warms, just far less often.

    feed chooser only flips UserSubscription.active, and DOCKERBUILD forces
    active_subscribers to the total, so the scheduler has to look at the
    subscriptions themselves instead of the cached counter.
    """

    def setUp(self):
        self.user = User.objects.create_user("muted-reader", "muted@example.com", "pw")
        self.feed = Feed.objects.create(feed_address="http://muted.example/feed", feed_title="Muted")
        UserSubscription.objects.create(user=self.user, feed=self.feed, active=False)

    def test_feed_with_only_muted_subscribers_has_no_active_reader(self):
        self.assertFalse(self.feed.has_unmuted_subscriber())

    @override_settings(MUTED_FEED_FETCH_MINUTES=360)
    def test_muted_feed_is_slowed_to_the_configured_floor(self):
        self.assertEqual(self.feed.slow_fetch_interval_for_muted_readers(15), 360)

    @override_settings(MUTED_FEED_FETCH_MINUTES=360)
    def test_unmuting_restores_the_reader_interval(self):
        UserSubscription.objects.filter(user=self.user, feed=self.feed).update(active=True)
        self.assertTrue(self.feed.has_unmuted_subscriber())
        self.assertEqual(self.feed.slow_fetch_interval_for_muted_readers(15), 15)

    @override_settings(MUTED_FEED_FETCH_MINUTES=0)
    def test_zero_disables_the_floor(self):
        self.assertEqual(self.feed.slow_fetch_interval_for_muted_readers(15), 15)

    @override_settings(MUTED_FEED_FETCH_MINUTES=360)
    def test_a_slower_existing_interval_is_not_shortened(self):
        self.assertEqual(self.feed.slow_fetch_interval_for_muted_readers(720), 720)
