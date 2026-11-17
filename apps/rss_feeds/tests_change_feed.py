"""Regression tests for the Change Feed Address/Link views.

Both views used to carry a dead "fix broken feed" branch behind an
`if False` guard. The live path is to branch onto the feed that already
holds the requested address or link, and never to re-parent that feed
under the reader's current feed (forum #13860).
"""

from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.rss_feeds.models import Feed

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"


class Test_ExceptionChangeFeed(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("change-feed", "change-feed@example.com", "pw")
        self.client.force_login(self.user)
        self.original = Feed.objects.create(
            feed_address="http://original.example.com/feed",
            feed_link="http://original.example.com/",
            feed_title="Original",
        )

    def client_kwargs(self):
        # Production redirects plain HTTP to HTTPS and rejects requests without a
        # browser User-Agent; keep these tests on the view, not the front door.
        allowed_hosts = getattr(settings, "ALLOWED_HOSTS", [])
        host = allowed_hosts[0] if allowed_hosts and allowed_hosts[0] != "*" else "testserver"
        return {"secure": True, "HTTP_HOST": host, "HTTP_USER_AGENT": UA}

    def _post(self, view_name, **data):
        return self.client.post(
            reverse(view_name),
            {"feed_id": self.original.pk, **data},
            **self.client_kwargs(),
        )

    def _mock_branch_target(self, target):
        usersub = MagicMock()
        usersub.feed_id = target.pk
        usersub.user = self.user
        usersub.canonical.return_value = {"feed_title": target.feed_title}

        return (
            patch("apps.rss_feeds.views.UserSubscription.objects.get", return_value=usersub),
            patch("apps.rss_feeds.views.Feed.update", return_value=target),
            patch("apps.rss_feeds.views.Feed.get_by_id", return_value=target),
            patch("apps.rss_feeds.views.Feed.update_all_statistics"),
            patch("apps.rss_feeds.views.MFetchHistory.feed", return_value={
                "feed_fetch_history": [],
                "page_fetch_history": [],
                "push_history": [],
            }),
            patch("apps.rss_feeds.views.get_classifiers_for_user", return_value=[]),
        )

    def test_broken_feed_branches_to_an_existing_address(self):
        self.original.has_feed_exception = True
        self.original.save()
        target = Feed.objects.create(
            feed_address="http://example.com/feed",
            feed_link=self.original.feed_link,
            feed_title="Target",
        )

        patches = self._mock_branch_target(target)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            response = self._post(
                "exception-change-feed-address", feed_address=target.feed_address
            )

        self.assertEqual(response.status_code, 200, response.content[:500])
        payload = response.json()
        self.assertIn("new_feed_id", payload, payload)
        self.assertEqual(payload["new_feed_id"], target.pk)
        self.assertEqual(payload["code"], 1)

        self.original.refresh_from_db()
        target.refresh_from_db()
        self.assertTrue(self.original.has_feed_exception)
        self.assertIsNone(target.branch_from_feed_id)
        self.assertFalse(target.feed_address_locked)

    def test_broken_feed_branches_to_an_existing_link(self):
        self.original.has_page_exception = True
        self.original.save()
        target = Feed.objects.create(
            feed_address=self.original.feed_address,
            feed_link="http://example.com/",
            feed_title="Target",
        )

        patches = self._mock_branch_target(target)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            response = self._post("exception-change-feed-link", feed_link=target.feed_link)

        self.assertEqual(response.status_code, 200, response.content[:500])
        payload = response.json()
        self.assertIn("new_feed_id", payload, payload)
        self.assertEqual(payload["new_feed_id"], target.pk)
        self.assertEqual(payload["code"], 1)

        self.original.refresh_from_db()
        target.refresh_from_db()
        self.assertTrue(self.original.has_page_exception)
        self.assertIsNone(target.branch_from_feed_id)
        self.assertFalse(target.feed_link_locked)
