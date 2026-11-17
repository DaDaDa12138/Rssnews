"""Static pages load only the static CSS/JS bundles and declare viewport once.

base.html already links the common bundle and declares the viewport. Signup and
the delete-account page used to repeat both in their extra_head_js block, which
downloaded and parsed the whole reader stylesheet a second time at the end of
the document. These tests keep that duplication and the reader bundle from
coming back, and they pin the card layout on the account-facing pages.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"


class StaticPageAssetTests(TestCase):
    def client_kwargs(self):
        host = settings.ALLOWED_HOSTS[0] if settings.ALLOWED_HOSTS else "testserver"
        if host == "*":
            host = "testserver"
        return {"secure": True, "HTTP_HOST": host, "HTTP_USER_AGENT": UA}

    def setUp(self):
        self.client.defaults["HTTP_USER_AGENT"] = UA

    def get(self, name):
        response = self.client.get(reverse(name), **self.client_kwargs())
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def assert_single_stylesheet_and_viewport(self, html):
        self.assertEqual(html.count("css/static."), 1, "static stylesheet linked more than once")
        self.assertEqual(html.count("css/common."), 0, "static page still loads the reader stylesheet")
        self.assertEqual(html.count("js/static."), 1, "static script linked more than once")
        self.assertEqual(html.count("js/common."), 0, "static page still loads the reader script")
        self.assertEqual(html.count("js/common_vendor."), 0, "static page still loads vendor script")
        self.assertEqual(html.count('name="viewport"'), 1, "viewport meta declared more than once")
        self.assertIn("NB-theme-toggle", html, "theme toggle markup missing")

    def test_login_links_the_shared_stylesheet_once(self):
        html = self.get("login")
        self.assert_single_stylesheet_and_viewport(html)
        self.assertIn('class="NB-static NB-static-login', html)

    def test_signup_links_the_shared_stylesheet_once(self):
        self.assert_single_stylesheet_and_viewport(self.get("signup"))

    def test_static_bundle_can_be_mirrored_for_rtl(self):
        from apps.profile.language import FlippedStylesheetUrls

        self.assertTrue(FlippedStylesheetUrls().get("static").startswith("/rtl/static/"))

    def test_welcome_links_the_static_stylesheet_once(self):
        html = self.get("welcome-page")
        self.assert_single_stylesheet_and_viewport(html)
        self.assertIn('class="NB-static NB-static-welcome', html)

    def test_delete_account_links_the_shared_stylesheet_once(self):
        user = get_user_model().objects.create_user(
            username="page-assets-delete", password="not-used-by-this-test"
        )
        self.client.force_login(user)
        html = self.get("profile-delete-account")
        self.assert_single_stylesheet_and_viewport(html)
        self.assertIn('class="NB-static NB-static-delete-account', html)
        self.assertIn("NB-static-card-submit NB-delete-submit", html)

    def test_forgot_password_uses_the_shared_card_layout(self):
        html = self.get("profile-forgot-password")
        self.assert_single_stylesheet_and_viewport(html)
        self.assertIn("NB-static-card", html)
        self.assertIn("NB-static-card-copy", html)
        self.assertIn("NB-static-card-submit", html)
        self.assertNotIn("NB-forgot-password-container", html)

    def test_forgot_password_return_uses_the_static_bundle(self):
        user = get_user_model().objects.create_user(
            username="page-assets-reset", password="not-used-by-this-test"
        )
        self.client.force_login(user)
        html = self.get("profile-forgot-password-return")
        self.assert_single_stylesheet_and_viewport(html)
        self.assertIn("NB-static-card-submit", html)

    def test_email_optout_uses_the_shared_card_layout(self):
        user = get_user_model().objects.create_user(
            username="page-assets-optout", email="optout@example.com", password="not-used-by-this-test"
        )
        self.client.force_login(user)
        html = self.get("profile-email-optout")
        self.assert_single_stylesheet_and_viewport(html)
        self.assertIn("NB-static-card", html)
        self.assertIn("NB-static-card-submit NB-unsubscribe-button", html)
        self.assertNotIn("NB-thanks", html)
        self.assertNotIn("position: absolute", html)
