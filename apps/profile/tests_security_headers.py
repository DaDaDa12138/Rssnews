"""Security headers: CSP, X-Frame-Options, nosniff (newsblur_web/settings.py MIDDLEWARE)."""

from django.conf import settings
from django.test import TestCase

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"


class SecurityHeaderTests(TestCase):
    def client_kwargs(self):
        # Production settings redirect HTTP to HTTPS and reject the test
        # client's default Host; assert the headers on the final response.
        allowed_hosts = getattr(settings, "ALLOWED_HOSTS", [])
        host = allowed_hosts[0] if allowed_hosts and allowed_hosts[0] != "*" else "testserver"
        return {"secure": True, "HTTP_HOST": host, "HTTP_USER_AGENT": UA}

    def test_csp_header_is_sent(self):
        response = self.client.get("/account/login/", **self.client_kwargs())
        policy = response["Content-Security-Policy"]
        self.assertIn("object-src 'none'", policy)
        self.assertIn("base-uri 'self'", policy)
        self.assertIn("frame-ancestors 'self'", policy)
        self.assertIn("script-src 'self' 'nonce-", policy)
        self.assertIn("'strict-dynamic'", policy)
        self.assertIn("report-uri /profile/csp-report", policy)

    def test_x_frame_options_is_sameorigin(self):
        response = self.client.get("/account/login/", **self.client_kwargs())
        self.assertEqual(response["X-Frame-Options"], "SAMEORIGIN")

    def test_content_type_nosniff(self):
        response = self.client.get("/account/login/", **self.client_kwargs())
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
