"""Forcing a feed fetch is an action, not a read: anonymous visitors must not trigger it.

Without the guard an anonymous GET /reader/refresh_feed/<id> ran Feed.update(force=True)
and tied up a web worker on an outbound fetch. apps/reader/tests_refresh_feed_auth.py
"""

from unittest import mock

from django.contrib.auth.models import User
from django.test import Client, TestCase

from apps.rss_feeds.models import Feed

# The site bans requests without a user agent. apps/reader/tests_refresh_feed_auth.py
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"


class Test_RefreshFeedAuth(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("refresh-user", "refresh@example.com", "refresh-password")
        self.feed = Feed.objects.create(feed_address="http://example.com/refresh.xml", feed_title="Refresh")
        self.anonymous = Client(HTTP_USER_AGENT=UA)
        self.client.defaults["HTTP_USER_AGENT"] = UA
        self.client.login(username="refresh-user", password="refresh-password")

    def test_anonymous_cannot_force_a_fetch(self):
        with mock.patch.object(Feed, "update", autospec=True, return_value=self.feed) as update:
            response = self.anonymous.get("/reader/refresh_feed/%s" % self.feed.pk)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(update.call_count, 0)

    def test_a_logged_in_reader_is_not_blocked(self):
        with mock.patch.object(Feed, "update", autospec=True, return_value=self.feed):
            response = self.client.get("/reader/refresh_feed/%s" % self.feed.pk)

        self.assertNotEqual(response.status_code, 403)
