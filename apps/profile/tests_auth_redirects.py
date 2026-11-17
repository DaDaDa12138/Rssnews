"""Login and signup redirect targets (apps/profile/views.py:_safe_next_url).

Both views used to redirect to request.POST["next"] unchecked: an open redirect
to any host, and a 500 (MultiValueDictKeyError) when the field was absent.
"""

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase
from django.urls import reverse

from apps.profile.views import _safe_next_url

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"


class SafeNextUrlTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def request(self, next_value=None, secure=False):
        data = {} if next_value is None else {"next": next_value}
        request = self.factory.post("/account/login/", data, secure=secure)
        return request

    def test_missing_next_falls_back_to_index(self):
        self.assertEqual(_safe_next_url(self.request()), reverse("index"))

    def test_external_host_is_rejected(self):
        self.assertEqual(_safe_next_url(self.request("https://example.com/evil")), reverse("index"))

    def test_protocol_relative_url_is_rejected(self):
        self.assertEqual(_safe_next_url(self.request("//example.com/evil")), reverse("index"))

    def test_relative_path_is_kept(self):
        self.assertEqual(_safe_next_url(self.request("/reader/")), "/reader/")


class LoginRedirectTests(TestCase):
    def setUp(self):
        self.client.defaults["HTTP_USER_AGENT"] = UA
        self.user = User.objects.create_user("redirecttest", "redirect@example.com", "redirect-password")

    def login(self, next_value=None):
        data = {"username": "redirecttest", "password": "redirect-password"}
        if next_value is not None:
            data["next"] = next_value
        return self.client.post("/account/login/", data)

    def test_missing_next_does_not_500(self):
        response = self.login()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("index"))

    def test_external_next_is_not_followed(self):
        response = self.login("https://example.com/evil")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("index"))

    def test_relative_next_is_followed(self):
        response = self.login("/reader/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/reader/")


class SignupCsrfTests(TestCase):
    def test_signup_is_no_longer_csrf_exempt(self):
        from apps.profile import views

        self.assertFalse(getattr(views.signup, "csrf_exempt", False))
