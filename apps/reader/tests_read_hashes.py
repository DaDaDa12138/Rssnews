"""Story hashes without a feed never reach the read-story sets (apps/reader/models.py)."""

import datetime
import json
import zlib

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase
import redis

from apps.reader.models import RUserStory, UserSubscription
from apps.rss_feeds.models import Feed, MStory

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"

# A user id no real account uses, so the assertions can delete its keys freely.
PROBE_USER_ID = 987654


class Test_ReadStoryHashes(TestCase):
    def setUp(self):
        self.r = redis.Redis(connection_pool=settings.REDIS_STORY_HASH_POOL)
        self.all_key = "RS:%s" % PROBE_USER_ID
        self.clean()

    def tearDown(self):
        self.clean()

    def clean(self):
        keys = self.r.keys("RS:%s*" % PROBE_USER_ID) + self.r.keys("lRS:%s" % PROBE_USER_ID)
        if keys:
            self.r.delete(*keys)

    def test_a_raw_story_id_without_a_feed_writes_nothing(self):
        RUserStory.mark_read(PROBE_USER_ID, None, "raw-story-id")

        self.assertEqual(self.r.keys("RS:%s*" % PROBE_USER_ID), [])
        self.assertEqual(self.r.keys("lRS:%s" % PROBE_USER_ID), [])

    def test_a_raw_story_id_with_a_feed_becomes_a_real_hash(self):
        RUserStory.mark_read(PROBE_USER_ID, 35, "raw-story-id")

        expected = MStory.ensure_story_hash("raw-story-id", 35)
        self.assertTrue(self.r.sismember(self.all_key, expected))
        self.assertTrue(self.r.sismember("%s:35" % self.all_key, expected))
        self.assertEqual(self.r.lrange("lRS:%s" % PROBE_USER_ID, 0, -1), [expected])

    def test_mark_unread_ignores_an_unattributable_hash(self):
        RUserStory.mark_unread(PROBE_USER_ID, None, "raw-story-id")

        self.assertEqual(self.r.keys("RS:%s*" % PROBE_USER_ID), [])

    def test_iter_read_story_hashes_pages_through_the_unbounded_set(self):
        from unittest.mock import MagicMock, patch

        client = MagicMock()
        client.sscan.side_effect = [(7, ["35:aaa111"]), (0, ["35:bbb222"])]

        with patch("apps.reader.models.redis.Redis", return_value=client):
            batches = list(RUserStory.iter_read_story_hashes(PROBE_USER_ID, batch_size=1))

        self.assertEqual(batches, [["35:aaa111"], ["35:bbb222"]])
        self.assertEqual(client.sscan.call_count, 2)

    def test_a_real_hash_lands_in_both_sets(self):
        story_hash = "35:abc123"
        RUserStory.mark_read(PROBE_USER_ID, 35, story_hash)

        self.assertTrue(self.r.sismember(self.all_key, story_hash))
        self.assertTrue(self.r.sismember("%s:35" % self.all_key, story_hash))

        RUserStory.mark_unread(PROBE_USER_ID, 35, story_hash)
        self.assertFalse(self.r.sismember(self.all_key, story_hash))
        self.assertFalse(self.r.sismember("%s:35" % self.all_key, story_hash))


class Test_ReadStorySearch(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("read-search", "read-search@example.com", "pw")
        self.feed = Feed.objects.create(
            feed_address="http://read-search.example.com/feed",
            feed_title="Read Search",
            feed_link="http://read-search.example.com",
        )
        UserSubscription.objects.create(user=self.user, feed=self.feed)
        self.story = MStory.objects.create(
            story_feed_id=self.feed.pk,
            story_hash="%s:abc123" % self.feed.pk,
            story_guid="read-search-story",
            story_title="Needle in the read history",
            story_content_z=zlib.compress(b"A searchable body"),
            story_date=datetime.datetime.utcnow() - datetime.timedelta(days=1),
        )
        self.r = redis.Redis(connection_pool=settings.REDIS_STORY_HASH_POOL)
        self.all_key = "RS:%s" % self.user.pk
        self.r.delete(self.all_key, "lRS:%s" % self.user.pk)
        self.client.defaults["HTTP_USER_AGENT"] = UA
        self.client.login(username="read-search", password="pw")

    def tearDown(self):
        self.r.delete(self.all_key, "lRS:%s" % self.user.pk)

    def test_search_reads_past_the_lrs_cap(self):
        # lRS is capped at 1,001 entries, but the RS set is the full read history.
        # Fill RS with hashes that have no story rows, then add the real one.
        self.r.sadd(self.all_key, *["%s:%06d" % (self.feed.pk, index) for index in range(1001)])
        RUserStory.mark_read(self.user.pk, self.feed.pk, self.story.story_hash)

        allowed_hosts = getattr(settings, "ALLOWED_HOSTS", [])
        host = allowed_hosts[0] if allowed_hosts and allowed_hosts[0] != "*" else "testserver"
        response = self.client.get(
            "/reader/read_stories",
            {"query": "title:needle", "limit": "10"},
            secure=True,
            HTTP_HOST=host,
        )

        self.assertEqual(response.status_code, 200)
        stories = json.loads(response.content)["stories"]
        self.assertEqual([story["story_title"] for story in stories], [self.story.story_title])
