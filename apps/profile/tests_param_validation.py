"""Profile and health endpoints that read request parameters without a guard."""

import json

from django.contrib.auth.models import User
from django.test import TestCase

# The site bans requests without a user agent, which every browser sends and the test
# client does not. apps/profile/tests_param_validation.py
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"


class Test_RedisCheck(TestCase):
    def setUp(self):
        self.client.defaults["HTTP_USER_AGENT"] = UA

    def test_missing_pool_is_a_client_error(self):
        response = self.client.get("/_dbcheck/redis/")

        self.assertEqual(response.status_code, 400)
        self.assertIn(b"pool must be one of", response.content)

    def test_unknown_pool_is_a_client_error(self):
        response = self.client.get("/_dbcheck/redis/?pool=bogus")

        self.assertEqual(response.status_code, 400)


class Test_SetViewSetting(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("view-user", "view@example.com", "view-password")
        self.client.defaults["HTTP_USER_AGENT"] = UA
        self.client.login(username="view-user", password="view-password")

    def test_missing_feed_id_is_reported(self):
        response = self.client.post("/profile/set_view_setting", {"feed_view_setting": "list"})

        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertEqual(body["code"], -1)
        self.assertEqual(body["message"], "Missing feed_id.")
