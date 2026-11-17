"""Tests for reader story tags (apps/reader/models.py StoryTag and its views)."""

import datetime
import json
import zlib

from django.contrib.auth.models import User
from django.test import TestCase

from apps.reader.models import StoryTag
from apps.rss_feeds.models import Feed, MStory


def make_story(feed, suffix="aaa111", title="A story"):
    return MStory.objects.create(
        story_feed_id=feed.pk,
        story_hash="%s:%s" % (feed.pk, suffix),
        story_guid="guid-%s" % suffix,
        story_title=title,
        story_permalink="https://example.com/%s" % suffix,
        story_content_z=zlib.compress(b"<p>body</p>"),
        story_date=datetime.datetime(2026, 10, 1, 12, 0, 0),
    )


def body_of(response):
    return json.loads(response.content)


class Test_StoryTag(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("reader", "reader@example.com", "pw")

    def test_normalize(self):
        self.assertEqual(StoryTag.normalize("  Python "), "python")
        self.assertEqual(len(StoryTag.normalize("x" * 100)), 64)

    def test_add_is_idempotent(self):
        StoryTag.add(self.user.pk, "1:abc123", "Python")
        StoryTag.add(self.user.pk, "1:abc123", "python")
        self.assertEqual(StoryTag.objects.filter(user_id=self.user.pk).count(), 1)

    def test_remove(self):
        StoryTag.add(self.user.pk, "1:abc123", "python")
        StoryTag.remove(self.user.pk, "1:abc123", "PYTHON")
        self.assertEqual(StoryTag.for_story(self.user.pk, "1:abc123"), [])

    def test_for_story_is_sorted(self):
        StoryTag.add(self.user.pk, "1:abc123", "zebra")
        StoryTag.add(self.user.pk, "1:abc123", "apple")
        self.assertEqual(StoryTag.for_story(self.user.pk, "1:abc123"), ["apple", "zebra"])

    def test_counts(self):
        StoryTag.add(self.user.pk, "1:abc123", "python")
        StoryTag.add(self.user.pk, "1:def456", "python")
        StoryTag.add(self.user.pk, "1:abc123", "rust")
        counts = {row["tag"]: row["count"] for row in StoryTag.counts(self.user.pk)}
        self.assertEqual(counts, {"python": 2, "rust": 1})

    def test_tags_are_per_reader(self):
        other = User.objects.create_user("other", "other@example.com", "pw")
        StoryTag.add(other.pk, "1:abc123", "python")
        self.assertEqual(StoryTag.for_story(self.user.pk, "1:abc123"), [])


class Test_TagViews(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("reader", "reader@example.com", "pw")
        self.feed = Feed.objects.create(
            feed_address="http://example.com/feed", feed_title="Example", feed_link="http://example.com"
        )
        self.story = make_story(self.feed)
        self.client.defaults["HTTP_USER_AGENT"] = "Mozilla/5.0 (X11; Linux x86_64) Chrome/126.0"
        self.client.force_login(self.user)

    def test_add_and_load(self):
        response = self.client.post(
            "/reader/add_story_tag", {"story_hash": self.story.story_hash, "tag": "Python"}
        )
        self.assertEqual(body_of(response)["tags"], ["python"])
        loaded = body_of(self.client.get("/reader/story_tags", {"story_hash": self.story.story_hash}))
        self.assertEqual(loaded["tags"], ["python"])

    def test_add_rejects_an_unknown_story(self):
        response = self.client.post("/reader/add_story_tag", {"story_hash": "9:zzzzzz", "tag": "x"})
        self.assertEqual(body_of(response)["code"], -1)

    def test_add_needs_a_tag(self):
        response = self.client.post("/reader/add_story_tag", {"story_hash": self.story.story_hash})
        self.assertEqual(body_of(response)["code"], -1)

    def test_remove(self):
        StoryTag.add(self.user.pk, self.story.story_hash, "python")
        response = self.client.post(
            "/reader/remove_story_tag", {"story_hash": self.story.story_hash, "tag": "python"}
        )
        self.assertEqual(body_of(response)["tags"], [])

    def test_anonymous_is_rejected(self):
        self.client.logout()
        response = self.client.get("/reader/story_tags")
        self.assertEqual(response.status_code, 403)