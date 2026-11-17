"""Tests for the Google Reader API shim (apps/reader/views/greader.py).

Third party clients keep a signed token instead of a session, so every test
authenticates with the Authorization header the way a native reader app does.
"""

import datetime
import json
import zlib
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from apps.reader.models import UserSubscription
from apps.reader.views.greader import issue_token
from apps.rss_feeds.models import Feed, MStarredStory, MStory


def make_feed(title="Example", address="http://example.com/feed"):
    return Feed.objects.create(feed_address=address, feed_title=title, feed_link="http://example.com")


def make_story(feed, suffix="abc123", title="A title", body="<p>Body</p>"):
    return MStory.objects.create(
        story_feed_id=feed.pk,
        story_hash="%s:%s" % (feed.pk, suffix),
        story_guid="guid-%s" % suffix,
        story_title=title,
        story_permalink="https://example.com/%s" % suffix,
        story_content_z=zlib.compress(body.encode("utf-8")),
        story_date=datetime.datetime(2026, 10, 1, 12, 0, 0),
    )


class GReaderTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("grtest", "grtest@example.com", "grtest-pass-123")
        self.feed = make_feed()
        self.story = make_story(self.feed, suffix="aaa111", title="First story")
        self.other_story = make_story(self.feed, suffix="bbb222", title="Second story")
        self.sub = UserSubscription.objects.create(
            user=self.user, feed=self.feed, unread_count_positive=4, unread_count_neutral=1
        )
        self.token = issue_token(self.user)
        self.client.defaults["HTTP_USER_AGENT"] = "Mozilla/5.0 (X11; Linux x86_64) Chrome/126.0"
        self.client.defaults["HTTP_AUTHORIZATION"] = "GoogleLogin auth=%s" % self.token

    def get_json(self, path, **params):
        response = self.client.get(path, params)
        self.assertEqual(response.status_code, 200, response.content[:300])
        return json.loads(response.content)

    def test_login_returns_auth_token(self):
        response = self.client.post(
            "/reader/api/0/login", {"Email": "grtest", "Passwd": "grtest-pass-123"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Auth=", response.content.decode())

    def test_login_rejects_get(self):
        response = self.client.get("/reader/api/0/login", {"Email": "grtest", "Passwd": "nope"})
        self.assertEqual(response.status_code, 405)

    def test_login_rejects_a_bad_password(self):
        response = self.client.post("/reader/api/0/login", {"Email": "grtest", "Passwd": "nope"})
        self.assertEqual(response.status_code, 401)

    def test_token_requires_auth(self):
        response = self.client.get("/reader/api/0/token", HTTP_AUTHORIZATION="")
        self.assertEqual(response.status_code, 401)

    def test_token_returns_a_working_token(self):
        response = self.client.get("/reader/api/0/token")
        self.assertEqual(response.status_code, 200)
        self.assertIn(":", response.content.decode())

    def test_user_info(self):
        data = self.get_json("/reader/api/0/user-info")
        self.assertEqual(data["userName"], "grtest")

    def test_subscription_list(self):
        data = self.get_json("/reader/api/0/subscription/list")
        self.assertEqual(len(data["subscriptions"]), 1)
        self.assertEqual(data["subscriptions"][0]["id"], "feed/%s" % self.feed.pk)
        self.assertEqual(data["subscriptions"][0]["title"], "Example")

    def test_unread_count_sums_positive_and_neutral(self):
        data = self.get_json("/reader/api/0/unread-count")
        counts = {row["id"]: row["count"] for row in data["unreadcounts"]}
        self.assertEqual(counts["feed/%s" % self.feed.pk], 5)
        self.assertEqual(counts["user/-/state/com.google/reading-list"], 5)

    def test_tag_list_has_state_tags(self):
        data = self.get_json("/reader/api/0/tag/list")
        ids = [tag["id"] for tag in data["tags"]]
        self.assertIn("user/-/state/com.google/read", ids)
        self.assertIn("user/-/state/com.google/starred", ids)

    def test_stream_contents_reading_list(self):
        data = self.get_json("/reader/api/0/stream/contents/user/-/state/com.google/reading-list")
        titles = [item["title"] for item in data["items"]]
        self.assertIn("First story", titles)
        self.assertEqual(data["items"][0]["origin"]["streamId"], "feed/%s" % self.feed.pk)

    def test_stream_contents_single_feed_ignores_other_feeds(self):
        other_feed = make_feed("Other", "http://other.example.com/feed")
        make_story(other_feed, suffix="ccc333", title="Other story")

        data = self.get_json("/reader/api/0/stream/contents/feed/%s" % self.feed.pk)
        titles = [item["title"] for item in data["items"]]
        self.assertIn("First story", titles)
        self.assertNotIn("Other story", titles)

    def test_stream_contents_paginates(self):
        data = self.get_json("/reader/api/0/stream/contents/feed/%s" % self.feed.pk, n=1)
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["continuation"], "1")

    def test_edit_tag_stars_a_story(self):
        response = self.client.post(
            "/reader/api/0/edit-tag",
            {"a": "user/-/state/com.google/starred", "i": self.story.story_hash},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            MStarredStory.objects.filter(user_id=self.user.pk, story_hash=self.story.story_hash).exists()
        )

    def test_edit_tag_unstars_a_story(self):
        self.client.post(
            "/reader/api/0/edit-tag",
            {"a": "user/-/state/com.google/starred", "i": self.story.story_hash},
        )
        self.client.post(
            "/reader/api/0/edit-tag",
            {"r": "user/-/state/com.google/starred", "i": self.story.story_hash},
        )
        self.assertFalse(
            MStarredStory.objects.filter(user_id=self.user.pk, story_hash=self.story.story_hash).exists()
        )

    def test_edit_tag_marks_read(self):
        with patch.object(UserSubscription, "mark_story_ids_as_read") as mark_read:
            response = self.client.post(
                "/reader/api/0/edit-tag",
                {"a": "user/-/state/com.google/read", "i": self.story.story_hash},
            )

        self.assertEqual(response.status_code, 200)
        mark_read.assert_called_once_with([self.story.story_hash], aggregated=True)

    def test_mark_all_as_read_uses_unread_stories(self):
        with patch.object(UserSubscription, "mark_story_ids_as_read") as mark_read:
            response = self.client.post("/reader/api/0/mark-all-as-read", {"s": "feed/%s" % self.feed.pk})

        self.assertEqual(response.status_code, 200)
        hashes = mark_read.call_args[0][0]
        self.assertIn(self.story.story_hash, hashes)
