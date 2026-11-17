"""CSRF enforcement for the reader's write endpoints.

The middleware is global, but the reader talks to it through the csrftoken
cookie and the X-CSRFToken header, so these tests exercise the real check with
enforce_csrf_checks instead of the permissive test client default.
"""

from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client, TestCase

from apps.rss_feeds.models import Feed

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"


class CsrfTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("csrftest", "csrftest@example.com", "csrftest-password")
        self.feed = Feed.objects.create(feed_address="http://csrf.example.com/feed", feed_title="CSRF feed")
        self.client = Client(enforce_csrf_checks=True)
        self.client.defaults["HTTP_USER_AGENT"] = UA
        self.client.force_login(self.user)

    def token(self):
        # /account/login/ renders a form with {% csrf_token %} and sets the cookie.
        # The bare /login path is a permanent redirect and carries no cookie.
        response = self.client.get("/account/login/")
        assert response.status_code == 200, response.status_code
        return self.client.cookies["csrftoken"].value

    def test_middleware_is_enabled(self):
        self.assertIn("django.middleware.csrf.CsrfViewMiddleware", settings.MIDDLEWARE)
        self.assertEqual(settings.CSRF_FAILURE_VIEW, "apps.profile.csrf.csrf_failure")

    def test_page_sets_the_csrf_cookie(self):
        self.assertTrue(self.token())

    def test_post_without_token_is_rejected(self):
        response = self.client.post("/reader/mark_all_as_read", {"days": 0})
        self.assertEqual(response.status_code, 403)

    def test_post_with_token_is_accepted(self):
        token = self.token()
        response = self.client.post(
            "/reader/mark_all_as_read", {"days": 0}, HTTP_X_CSRFTOKEN=token
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["code"], 1)

    def test_xhr_failure_returns_json(self):
        response = self.client.post(
            "/reader/mark_all_as_read", {"days": 0}, HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response["Content-Type"].split(";")[0], "application/json")
        self.assertIn("expired", response.json()["message"])

    def test_mark_all_as_read_rejects_get(self):
        response = self.client.get("/reader/mark_all_as_read")
        self.assertEqual(response.status_code, 405)

    def test_delete_feed_rejects_get(self):
        response = self.client.get("/reader/delete_feed", {"feed_id": self.feed.pk})
        self.assertEqual(response.status_code, 405)
