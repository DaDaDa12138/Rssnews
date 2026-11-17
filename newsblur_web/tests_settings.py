"""Tests for environment handling in the base settings module.

newsblur_web/tests_settings.py

docker-compose.yml passes SECRET_KEY, ADMIN_EMAIL, SERVER_EMAIL and EMAIL_BACKEND
through even when .env leaves them commented out, so the module receives empty
strings instead of unset variables. An empty SECRET_KEY used to reach Django as-is
and made every request fail with "The SECRET_KEY setting must not be empty", so the
fallbacks are pinned here.
"""

import importlib
import os
from unittest import mock

from django.test import SimpleTestCase

DEV_SECRET_KEY = "personal-edition-secret-key-change-me"


class Test_Settings_Env_Fallbacks(SimpleTestCase):
    def load(self, **env):
        with mock.patch.dict(os.environ, env):
            module = importlib.import_module("newsblur_web.settings")
            return importlib.reload(module)

    def test_empty_secret_key_falls_back_to_the_dev_default(self):
        module = self.load(SECRET_KEY="")
        self.assertEqual(module.SECRET_KEY, DEV_SECRET_KEY)

    def test_real_secret_key_is_kept(self):
        module = self.load(SECRET_KEY="x" * 50)
        self.assertEqual(module.SECRET_KEY, "x" * 50)

    def test_empty_mail_settings_fall_back(self):
        module = self.load(ADMIN_EMAIL="", SERVER_EMAIL="", EMAIL_BACKEND="")
        self.assertEqual(module.ADMINS, (("NewsBlur", "admin@localhost"),))
        self.assertTrue(module.SERVER_EMAIL.endswith("@localhost"))
        self.assertEqual(module.EMAIL_BACKEND, "django.core.mail.backends.console.EmailBackend")

    def test_empty_attack_ban_hops_falls_back_to_one(self):
        module = self.load(ATTACK_BAN_PROXY_HOPS="")
        self.assertEqual(module.ATTACK_BAN_PROXY_HOPS, 1)
