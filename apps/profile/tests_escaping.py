"""Template escaping regressions.

base.html used to wrap the whole document in {% autoescape off %}, so every
template that extends it rendered user data raw. These tests pin the escaping
behaviour for the paths that were exploitable.
"""

from django.contrib.auth.models import User
from django.test import TestCase

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"


class LoginNextEscapingTests(TestCase):
    """apps/profile/views.py:150 passes ?next= straight into the hidden field."""

    def setUp(self):
        self.client.defaults["HTTP_USER_AGENT"] = UA

    def test_next_parameter_is_escaped(self):
        payload = '"><script>alert(1)</script>'
        response = self.client.get("/account/login/", {"next": payload})
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertNotIn("<script>alert(1)</script>", body)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", body)


class BaseTemplateEscapingTests(TestCase):
    def setUp(self):
        self.client.defaults["HTTP_USER_AGENT"] = UA

    def test_username_is_escaped_in_js_globals(self):
        user = User.objects.create_user("x<script>alert(1)</script>", "xss@example.com", "xss-password")
        self.client.force_login(user)
        body = self.client.get("/").content.decode()
        self.assertNotIn("<script>alert(1)</script>", body)

    def test_email_is_escaped_in_js_globals(self):
        user = User.objects.create_user("xsstest", 'x"><script>alert(1)</script>@example.com', "xss-password")
        self.client.force_login(user)
        body = self.client.get("/").content.decode()
        self.assertNotIn("<script>alert(1)</script>", body)

class StatisticsEscapingTests(TestCase):
    """templates/rss_feeds/statistics.xhtml used to inject the feed JSON with |safe."""

    def setUp(self):
        self.client.defaults["HTTP_USER_AGENT"] = UA
        self.user = User.objects.create_user("statstest", "stats@example.com", "stats-password")

    def test_feed_title_is_json_escaped(self):
        from apps.reader.models import UserSubscription
        from apps.rss_feeds.models import Feed

        payload = "</script><script>alert(1)</script>"
        feed = Feed.objects.create(feed_address="http://stats.example.com/feed", feed_title=payload)
        UserSubscription.objects.create(user=self.user, feed=feed)
        self.client.force_login(self.user)

        response = self.client.get("/rss_feeds/statistics_embedded/%d" % feed.pk)

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertNotIn(payload, body)
        self.assertIn("\\u003C/script\\u003E", body)
