"""One source of truth for the reader theme.

The theme used to live in three places: the Profile.preferences blob, a body class
rendered by templates/reader/dashboard.xhtml, and a localStorage copy with a six
hour TTL that templates/base.html trusted first. The cache now only avoids a
first-paint flash; a signed-in reader always gets the stored preference.
"""

import json as std_json
import re

from django.contrib.auth.models import User
from django.test import TestCase

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"

THEME_STATE_RE = re.compile(
    r'<script id="nb-theme" type="application/json">(.*?)</script>', re.S
)


class ThemeStateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("themecheck", password="pw")
        self.profile = self.user.profile

    def set_preferences(self, preferences):
        self.profile.preferences = std_json.dumps(preferences)
        self.profile.save()

    def theme_state(self, response):
        html = response.content.decode()
        match = THEME_STATE_RE.search(html)
        self.assertIsNotNone(match, "nb-theme json_script missing from page")
        return std_json.loads(match.group(1))

    def test_anonymous_page_has_no_theme(self):
        response = self.client.get("/account/login/", HTTP_USER_AGENT=UA)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.theme_state(response), {"theme": None, "authenticated": False}
        )
        self.assertNotIn("NB-dark", response.content.decode().split("<body")[1][:200])

    def test_first_paint_script_has_no_expiry(self):
        # The six hour TTL (216e5 ms) is what made a stored dark theme revert.
        response = self.client.get("/account/login/", HTTP_USER_AGENT=UA)
        self.assertNotIn("216e5", response.content.decode())

    def test_signed_in_theme_is_the_stored_preference(self):
        self.set_preferences({"theme": "dark"})
        self.client.force_login(self.user)
        response = self.client.get("/reader/", HTTP_USER_AGENT=UA)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.theme_state(response), {"theme": "dark", "authenticated": True}
        )
        self.assertIn("NB-dark", response.content.decode())

    def test_signed_in_default_theme_is_auto(self):
        self.client.force_login(self.user)
        response = self.client.get("/reader/", HTTP_USER_AGENT=UA)
        self.assertEqual(
            self.theme_state(response), {"theme": "auto", "authenticated": True}
        )

    def test_unknown_theme_falls_back_to_auto(self):
        # clean_preferences drops values the schema does not know, so a stale
        # preference cannot reach the page and paint an unstyled body class.
        self.set_preferences({"theme": "chartreuse"})
        self.client.force_login(self.user)
        response = self.client.get("/reader/", HTTP_USER_AGENT=UA)
        self.assertEqual(
            self.theme_state(response), {"theme": "auto", "authenticated": True}
        )

    def test_theme_cache_is_rewritten_from_preference(self):
        # theme_toggle.js keeps no expiry of its own, and reader.js rewrites the
        # cache from the preference on every load.
        with open("media/js/newsblur/common/theme_toggle.js") as handle:
            toggle_js = handle.read()
        with open("media/js/newsblur/reader/reader.js") as handle:
            reader_js = handle.read()
        self.assertNotIn("TTL_MS", toggle_js)
        self.assertIn("cache_theme: function (theme)", reader_js)
