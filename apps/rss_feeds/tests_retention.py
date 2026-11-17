"""Tests for story retention (apps/rss_feeds/models.py).

The count cap is enforced after every fetch that brings new stories. These cover the
pieces that run without a fetch: the absolute per-feed ceiling, the age cap, and the
daily sweep that also reaches feeds nothing fetches any more.
"""

import datetime
import zlib
from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.reader.models import TranslationCache
from apps.rss_feeds.models import Feed, MStory


def make_feed(title="Example", address="http://example.com/feed", **kwargs):
    return Feed.objects.create(feed_address=address, feed_title=title, feed_link="http://example.com", **kwargs)


def make_story(feed, suffix, days_ago, share_count=0):
    return MStory.objects.create(
        story_feed_id=feed.pk,
        story_hash="%s:%s" % (feed.pk, suffix),
        story_guid="guid-%s" % suffix,
        story_title="Story %s" % suffix,
        story_permalink="https://example.com/%s" % suffix,
        story_content_z=zlib.compress(b"<p>Body</p>"),
        story_date=datetime.datetime.now() - datetime.timedelta(days=days_ago),
        share_count=share_count,
    )


class FakePipeline:
    def get(self, *args, **kwargs):
        return self

    def execute(self):
        # Every week had five reads, so the no-reads cap does not apply.
        return [b"5"] * 64


class FakeRedis:
    def __init__(self, *args, **kwargs):
        pass

    def pipeline(self):
        return FakePipeline()


class Test_RetentionCeiling(TestCase):
    def setUp(self):
        self.feed = make_feed()

    @override_settings(STORY_RETENTION_MAX_PER_FEED=30)
    @patch("apps.rss_feeds.models.redis.Redis", FakeRedis)
    def test_count_is_clamped_to_the_ceiling(self):
        # Three premium subscribers used to mean 300 stories; the ceiling is the hard bound.
        self.feed.active_subscribers = 3
        self.feed.active_premium_subscribers = 3
        self.feed.save(update_fields=["active_subscribers", "active_premium_subscribers"])

        cutoff, _ = self.feed.story_retention()

        self.assertEqual(cutoff, 30)

    @override_settings(STORY_RETENTION_MAX_PER_FEED_ARCHIVE=700)
    def test_archive_subscribers_use_the_archive_ceiling(self):
        self.feed.archive_subscribers = 1
        self.feed.save(update_fields=["archive_subscribers"])

        self.assertEqual(self.feed.story_retention(), (700, False))
        self.assertEqual(self.feed.story_retention_ceiling(), 700)


class Test_TrimByCount(TestCase):
    def setUp(self):
        self.feed = make_feed()
        for index in range(5):
            make_story(self.feed, "s%s" % index, days_ago=index + 1)

    def test_trim_feed_keeps_the_newest(self):
        removed = MStory.trim_feed(feed=self.feed, cutoff=2, verbose=False)

        self.assertEqual(removed, 3)
        self.assertEqual(MStory.objects(story_feed_id=self.feed.pk).count(), 2)

    @override_settings(STORY_RETENTION_MAX_PER_FEED=3, STORY_RETENTION_DAYS=180)
    def test_enforce_story_retention_applies_the_ceiling(self):
        removed = self.feed.enforce_story_retention(verbose=False)

        self.assertEqual(removed, 2)
        self.assertEqual(MStory.objects(story_feed_id=self.feed.pk).count(), 3)


class Test_TrimByAge(TestCase):
    def setUp(self):
        self.feed = make_feed()

    def test_keeps_the_newest_floor_whatever_their_date(self):
        for days_ago in (300, 200, 10, 5, 1):
            make_story(self.feed, "d%s" % days_ago, days_ago=days_ago)

        removed = MStory.trim_feed_by_age(feed=self.feed, days=30, min_keep=4, verbose=False)

        self.assertEqual(removed, 1)
        self.assertEqual(MStory.objects(story_feed_id=self.feed.pk).count(), 4)

    def test_stale_feed_keeps_only_its_newest_floor(self):
        for days_ago in (300, 290, 280, 270, 260):
            make_story(self.feed, "s%s" % days_ago, days_ago=days_ago)

        removed = MStory.trim_feed_by_age(feed=self.feed, days=30, min_keep=2, verbose=False)

        self.assertEqual(removed, 3)
        self.assertEqual(MStory.objects(story_feed_id=self.feed.pk).count(), 2)

    def test_shared_stories_are_kept(self):
        make_story(self.feed, "old", days_ago=300)
        shared = make_story(self.feed, "shared", days_ago=400, share_count=2)

        removed = MStory.trim_feed_by_age(feed=self.feed, days=30, min_keep=0, verbose=False)

        self.assertEqual(removed, 1)
        self.assertTrue(MStory.objects(id=shared.id).exists())

    def test_newly_fetched_stories_are_kept_even_when_old(self):
        # A feed that posts a back-dated item must not have it deleted before it is read.
        make_story(self.feed, "old", days_ago=300)
        fresh = make_story(self.feed, "fresh", days_ago=400)

        removed = MStory.trim_feed_by_age(
            feed=self.feed, days=30, min_keep=0, verbose=False, keep_story_hashes=[fresh.story_hash]
        )

        self.assertEqual(removed, 1)
        self.assertTrue(MStory.objects(id=fresh.id).exists())

    def test_a_disabled_window_deletes_nothing(self):
        make_story(self.feed, "old", days_ago=300)

        self.assertEqual(MStory.trim_feed_by_age(feed=self.feed, days=0, min_keep=0, verbose=False), 0)
        self.assertEqual(MStory.objects(story_feed_id=self.feed.pk).count(), 1)


class Test_DailySweep(TestCase):
    def setUp(self):
        self.feed = make_feed()

    @override_settings(STORY_RETENTION_MAX_PER_FEED=2, STORY_RETENTION_DAYS=180)
    def test_sweep_trims_feeds_that_stopped_publishing(self):
        for index in range(5):
            make_story(self.feed, "s%s" % index, days_ago=index + 1)

        removed = Feed.enforce_story_retention_on_all(verbose=False)

        self.assertEqual(removed, 3)
        self.assertEqual(MStory.objects(story_feed_id=self.feed.pk).count(), 2)

    @override_settings(
        STORY_RETENTION_MAX_PER_FEED=1000, STORY_RETENTION_DAYS=30, STORY_RETENTION_MIN_PER_FEED=2
    )
    def test_sweep_expires_old_stories_and_keeps_the_newest_floor(self):
        for days_ago in (400, 390, 380, 2, 1):
            make_story(self.feed, "d%s" % days_ago, days_ago=days_ago)

        removed = Feed.enforce_story_retention_on_all(verbose=False)

        self.assertEqual(removed, 3)
        self.assertEqual(MStory.objects(story_feed_id=self.feed.pk).count(), 2)


class Test_TranslationCachePrune(TestCase):
    def make_translation(self, text_hash):
        return TranslationCache.objects.create(
            text_hash=text_hash, target_lang="ZH", source_lang="EN", translation="翻译"
        )

    def test_prune_drops_only_rows_older_than_the_window(self):
        old = self.make_translation("old")
        fresh = self.make_translation("fresh")
        TranslationCache.objects.filter(pk=old.pk).update(
            created_at=datetime.datetime.now() - datetime.timedelta(days=60)
        )

        removed = TranslationCache.prune(days=30)

        self.assertEqual(removed, 1)
        self.assertFalse(TranslationCache.objects.filter(pk=old.pk).exists())
        self.assertTrue(TranslationCache.objects.filter(pk=fresh.pk).exists())

    def test_prune_can_be_disabled(self):
        self.make_translation("old")

        self.assertEqual(TranslationCache.prune(days=0), 0)
        self.assertEqual(TranslationCache.objects.count(), 1)
