"""Enforcing Content Security Policy.

Every executable script carries a per-response nonce, so script-src can use
strict-dynamic without breaking the reader's inline bootstrapping. The only
eval() allowance is for Google reCAPTCHA, whose client calls eval() internally.
"""

import re
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from utils.feed_functions import TimeoutError

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
NONCE_RE = re.compile(r"'nonce-([^']+)'")


class ContentSecurityPolicyTests(TestCase):
    def client_kwargs(self):
        # The suite runs under either newsblur_web.settings or
        # newsblur_web.settings_production. Production redirects HTTP to HTTPS
        # and rejects the test client's default Host, so use the first allowed
        # host and an HTTPS request. This keeps the assertions about the policy
        # itself, not about the redirect middleware.
        allowed_hosts = getattr(settings, "ALLOWED_HOSTS", [])
        host = allowed_hosts[0] if allowed_hosts and allowed_hosts[0] != "*" else "testserver"
        return {"secure": True, "HTTP_HOST": host, "HTTP_USER_AGENT": UA}

    def test_enforcing_policy_has_a_fresh_nonce(self):
        first = self.client.get("/account/login/", **self.client_kwargs())
        second = self.client.get("/account/login/", **self.client_kwargs())
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertNotIn("Content-Security-Policy-Report-Only", first)
        first_policy = first["Content-Security-Policy"]
        second_policy = second["Content-Security-Policy"]
        first_nonce = NONCE_RE.search(first_policy).group(1)
        second_nonce = NONCE_RE.search(second_policy).group(1)
        self.assertNotEqual(first_nonce, second_nonce)
        self.assertIn(
            "script-src 'self' 'nonce-%s' 'strict-dynamic' 'unsafe-eval'" % first_nonce,
            first_policy,
        )
        self.assertIn("report-uri /profile/csp-report", first_policy)
        self.assertIn('nonce="%s"' % first_nonce, first.content.decode())

    def test_policy_blocks_inline_script_but_allows_recaptcha_eval(self):
        response = self.client.get("/account/login/", **self.client_kwargs())
        policy = response["Content-Security-Policy"]
        script_src = policy.split("script-src ", 1)[1].split(";", 1)[0]
        self.assertNotIn("'unsafe-inline'", script_src)
        self.assertNotIn("*", script_src)
        self.assertIn("'strict-dynamic'", script_src)
        self.assertIn("'unsafe-eval'", script_src)
        self.assertIn("https://www.google.com", script_src)

    def test_every_executable_script_carries_the_nonce(self):
        response = self.client.get("/account/login/", **self.client_kwargs())
        nonce = NONCE_RE.search(response["Content-Security-Policy"]).group(1)
        scripts = re.findall(
            r"<script\b(?![^>]*type=\"application/json\")[^>]*>", response.content.decode()
        )
        self.assertTrue(scripts, "login page should load at least one script")
        for tag in scripts:
            self.assertIn('nonce="%s"' % nonce, tag)

    def assert_strict_style_policy(self, response, label):
        self.assertEqual(response.status_code, 200, label)
        policy = response["Content-Security-Policy"]
        nonce = NONCE_RE.search(policy).group(1)
        self.assertIn("style-src 'self' 'nonce-%s'" % nonce, policy, label)
        self.assertNotIn("style-src 'self' 'unsafe-inline'", policy, label)
        styles = re.findall(r"<style\b[^>]*>", response.content.decode())
        self.assertTrue(styles, label)
        for tag in styles:
            self.assertIn('nonce="%s"' % nonce, tag, label)

    def test_account_pages_use_a_strict_style_policy(self):
        for path in (
            "/account/login/",
            "/account/signup/",
            "/welcome/",
            "/profile/forgot_password/",
        ):
            self.assert_strict_style_policy(self.client.get(path, **self.client_kwargs()), path)

    def test_authenticated_account_pages_use_a_strict_style_policy(self):
        user = get_user_model().objects.create_user(
            username="csp-account", password="not-used-by-this-test"
        )
        self.client.force_login(user)
        for name in ("profile-delete-account", "profile-email-optout"):
            self.assert_strict_style_policy(self.client.get(reverse(name), **self.client_kwargs()), name)
        token_path = reverse(
            "profile-email-optout-token",
            kwargs={"username": user.username, "secret": user.profile.secret_token},
        )
        self.assert_strict_style_policy(
            self.client.get(token_path, **self.client_kwargs()),
            "profile-email-optout-token",
        )

    def test_opml_delayed_page_uses_a_strict_style_policy(self):
        user = get_user_model().objects.create_user(
            username="csp-opml", email="opml@example.com", password="not-used-by-this-test"
        )
        self.client.force_login(user)
        with mock.patch("apps.feed_import.views.OPMLExporter.process", side_effect=TimeoutError):
            with mock.patch("apps.feed_import.views.ProcessOPMLExport.delay"):
                response = self.client.get("/import/opml_export/", **self.client_kwargs())
        self.assert_strict_style_policy(response, "opml-export")
        html = response.content.decode()
        self.assertIn("NB-static-card", html)
        self.assertIn("NB-static-opml-export", html)
        self.assertNotIn('style="', html)

    def test_reader_keeps_inline_styles_for_rendered_story_markup(self):
        response = self.client.get("/", **self.client_kwargs())
        self.assertEqual(response.status_code, 200)
        self.assertIn("style-src 'self' 'unsafe-inline'", response["Content-Security-Policy"])

    def test_report_endpoint_accepts_browser_reports(self):
        response = self.client.post(
            "/profile/csp-report",
            data='{"csp-report": {"blocked-uri": "inline"}}',
            content_type="application/csp-report",
            **self.client_kwargs(),
        )
        self.assertEqual(response.status_code, 204)

    def test_report_endpoint_rejects_get(self):
        response = self.client.get("/profile/csp-report", **self.client_kwargs())
        self.assertEqual(response.status_code, 405)
