"""Feed endpoints read numbers straight out of the query string.

Both of these used to raise ValueError on anything that was not a number, which turned
a typo in a URL into a 500 and a traceback in the error log.
"""

import json

from django.contrib.auth.models import User
from django.test import TestCase

# The site bans requests without a user agent, which every browser sends and the test
# client does not. apps/rss_feeds/tests_param_validation.py
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"


class Test_FeedAutocomplete(TestCase):
    def setUp(self):
        self.client.defaults["HTTP_USER_AGENT"] = UA

    def test_autocomplete_falls_back_to_defaults(self):
        response = self.client.get("/rss_feeds/feed_autocomplete?term=linux&v=abc&limit=abc")

        self.assertEqual(response.status_code, 200)
        json.loads(response.content)


class Test_FeedStatus(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("status-staff", "status@example.com", "status-password", is_staff=True)
        self.client.defaults["HTTP_USER_AGENT"] = UA
        self.client.force_login(self.user)

    def test_status_falls_back_to_one_minute(self):
        response = self.client.get("/rss_feeds/status?minutes=abc")

        self.assertEqual(response.status_code, 200)
