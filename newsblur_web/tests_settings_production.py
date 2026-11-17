"""Tests for the production settings profile.

newsblur_web/tests_settings_production.py

The profile refuses to start without a real SECRET_KEY and ALLOWED_HOSTS, and it
derives the cookie flags from the public URL, so those three decisions are what
the tests pin down.
"""

import importlib
import logging
import os
import re
import secrets
import subprocess
import sys
from unittest import mock

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase


class Test_Production_Settings(SimpleTestCase):
    def load(self, **env):
        with mock.patch.dict(os.environ, env):
            module = importlib.import_module("newsblur_web.settings_production")
            return importlib.reload(module)

    def test_debug_is_off_and_hosts_are_parsed(self):
        module = self.load(SECRET_KEY="x" * 50, ALLOWED_HOSTS="newsblur.example.com, 203.0.113.10")
        self.assertFalse(module.DEBUG)
        self.assertFalse(module.DEBUG_QUERIES)
        self.assertEqual(module.ALLOWED_HOSTS, ["newsblur.example.com", "203.0.113.10"])

    def test_https_url_turns_on_secure_cookies(self):
        module = self.load(
            SECRET_KEY="x" * 50,
            ALLOWED_HOSTS="newsblur.example.com",
            NEWSBLUR_URL="https://newsblur.example.com",
        )
        self.assertTrue(module.SESSION_COOKIE_SECURE)
        self.assertTrue(module.CSRF_COOKIE_SECURE)
        self.assertTrue(module.SECURE_SSL_REDIRECT)
        self.assertEqual(module.SECURE_PROXY_SSL_HEADER, ("HTTP_X_FORWARDED_PROTO", "https"))

    def test_http_url_keeps_cookies_usable(self):
        module = self.load(
            SECRET_KEY="x" * 50,
            ALLOWED_HOSTS="203.0.113.10",
            NEWSBLUR_URL="http://203.0.113.10:8080",
        )
        self.assertFalse(module.SESSION_COOKIE_SECURE)
        self.assertFalse(module.CSRF_COOKIE_SECURE)
        self.assertFalse(module.SECURE_SSL_REDIRECT)

    def test_missing_secret_key_is_fatal(self):
        with mock.patch.dict(os.environ, {"ALLOWED_HOSTS": "newsblur.example.com"}):
            os.environ.pop("SECRET_KEY", None)
            with self.assertRaises(ImproperlyConfigured):
                self.load(ALLOWED_HOSTS="newsblur.example.com")

    def test_placeholder_secret_key_is_fatal(self):
        with self.assertRaises(ImproperlyConfigured):
            self.load(SECRET_KEY="personal-edition-secret-key-change-me", ALLOWED_HOSTS="newsblur.example.com")

    def test_missing_allowed_hosts_is_fatal(self):
        with mock.patch.dict(os.environ, {"SECRET_KEY": "x" * 50}):
            os.environ.pop("ALLOWED_HOSTS", None)
            with self.assertRaises(ImproperlyConfigured):
                self.load(SECRET_KEY="x" * 50)

    def test_wildcard_hosts_are_fatal(self):
        with self.assertRaises(ImproperlyConfigured):
            self.load(SECRET_KEY="x" * 50, ALLOWED_HOSTS="newsblur.example.com,*")

    def test_debug_dependent_settings_are_recomputed(self):
        # The base module decides the template loaders and both log levels while
        # DEBUG is still on, so the profile has to rebuild them itself.
        module = self.load(SECRET_KEY="x" * 50, ALLOWED_HOSTS="newsblur.example.com")
        self.assertTrue(module.CONN_HEALTH_CHECKS)
        loaders = module.TEMPLATES[0]["OPTIONS"]["loaders"]
        self.assertEqual(loaders[0][0], "django.template.loaders.cached.Loader")
        self.assertEqual(module.LOGGING["loggers"]["apps"]["level"], "INFO")
        self.assertEqual(module.LOGGING["loggers"]["newsblur"]["level"], logging.INFO)

    def test_deploy_check_only_reports_the_two_known_gaps(self):
        # HSTS is opt in through the environment and the reader frames its own
        # preview panes, so SAMEORIGIN rather than DENY. CSRF middleware is on, so
        # W003 must stay gone; anything else here is a regression.
        env = dict(os.environ)
        env.update(
            {
                "DJANGO_SETTINGS_MODULE": "newsblur_web.settings_production",
                "SECRET_KEY": secrets.token_urlsafe(48),
                "ALLOWED_HOSTS": "newsblur.example.com",
                "NEWSBLUR_URL": "https://newsblur.example.com",
            }
        )
        result = subprocess.run(
            [sys.executable, "manage.py", "check", "--deploy"],
            cwd=str(settings.BASE_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = result.stdout + result.stderr
        self.assertIn("System check identified", output)
        self.assertEqual(set(re.findall(r"security\.(W\d+)", output)), {"W004", "W019"})
        self.assertNotIn("security.W003", output)
