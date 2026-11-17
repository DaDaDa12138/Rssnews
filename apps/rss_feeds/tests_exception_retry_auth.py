"""Retrying a broken feed is an action, not a read: anonymous visitors must not trigger it.

Without the guard an anonymous POST /rss_feeds/exception_retry cleared the feed's exception
flags, re-scheduled it and ran Feed.update(force=True). apps/rss_feeds/tests_exception_retry_auth.py
"""

from unittest import mock

from django.contrib.auth.models import User
from django.test import Client, TestCase

from apps.rss_feeds.models import Feed

# The site bans requests without a user agent. apps/rss_feeds/tests_exception_retry_auth.py
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"


class Test_ExceptionRetryAuth(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("retry-user", "retry@example.com", "retry-password")
        self.feed = Feed.objects.create(feed_address="http://example.com/retry.xml", feed_title="Retry")
        self.anonymous = Client(HTTP_USER_AGENT=UA)
        self.client.defaults["HTTP_USER_AGENT"] = UA
        self.client.login(username="retry-user", password="retry-password")

    def test_anonymous_cannot_retry_a_feed(self):
        with mock.patch.object(Feed, "update", autospec=True, return_value=self.feed) as update, mock.patch.object(
            Feed, "schedule_feed_fetch_immediately", autospec=True
        ) as schedule:
            response = self.anonymous.post(
                "/rss_feeds/exception_retry",
                {"feed_id": self.feed.pk, "reset_fetch": "true"},
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(update.call_count, 0)
        self.assertEqual(schedule.call_count, 0)

    def test_a_logged_in_reader_is_not_blocked(self):
        with mock.patch.object(Feed, "update", autospec=True, return_value=self.feed), mock.patch.object(
            Feed, "schedule_feed_fetch_immediately", autospec=True
        ):
            response = self.client.post(
                "/rss_feeds/exception_retry",
                {"feed_id": self.feed.pk, "reset_fetch": "true"},
            )

        self.assertNotEqual(response.status_code, 403)
