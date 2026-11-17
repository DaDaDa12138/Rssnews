"""Preference schema and validation.

Profile.preferences used to accept any key with any value, and templates/base.html
carried its own copy of every default. These tests pin the schema
(apps/profile/preferences.py) and the set_preference validation that uses it.
"""

import json as std_json

from django.contrib.auth.models import User
from django.test import TestCase

from apps.profile.preferences import (
    PREFERENCE_DEFAULTS,
    PreferenceError,
    clean_preferences,
    coerce_preference,
    merged_preferences,
)

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"


class CoercePreferenceTests(TestCase):
    def test_unknown_key_is_rejected(self):
        with self.assertRaises(PreferenceError):
            coerce_preference("not_a_preference", "1")

    def test_bool_accepts_form_strings(self):
        self.assertIs(coerce_preference("animations", "false"), False)
        self.assertIs(coerce_preference("animations", "true"), True)

    def test_bool_rejects_other_words(self):
        with self.assertRaises(PreferenceError):
            coerce_preference("animations", "maybe")

    def test_int_flag_accepts_boolean(self):
        # show_tooltips defaults to 1/0 but the reader toggles it with booleans.
        self.assertEqual(coerce_preference("show_tooltips", True), 1)
        self.assertEqual(coerce_preference("show_tooltips", False), 0)

    def test_int_rejects_text(self):
        with self.assertRaises(PreferenceError):
            coerce_preference("feed_pane_size", "wide")

    def test_string_length_is_capped(self):
        with self.assertRaises(PreferenceError):
            coerce_preference("story_layout", "x" * 201)

    def test_list_rejects_nested_values(self):
        with self.assertRaises(PreferenceError):
            coerce_preference("collapsed_folders", [["nested"]])

    def test_clean_drops_unknown_and_invalid_values(self):
        cleaned = clean_preferences(
            {"theme": "dark", "nope": 1, "mark_read_days": "x", "feed_pane_size": 300}
        )
        self.assertEqual(cleaned, {"theme": "dark"})

    def test_merged_preferences_fills_defaults(self):
        merged = merged_preferences({"theme": "dark"})
        self.assertEqual(merged["theme"], "dark")
        self.assertEqual(merged["density"], "comfortable")
        self.assertEqual(len(merged), len(PREFERENCE_DEFAULTS))


class SetPreferenceTests(TestCase):
    def setUp(self):
        self.client.defaults["HTTP_USER_AGENT"] = UA
        self.user = User.objects.create_user("prefuser", "pref@example.com", "pref-password")
        self.client.force_login(self.user)

    def post(self, **data):
        return self.client.post("/profile/set_preference", data)

    def stored(self):
        self.user.profile.refresh_from_db()
        return std_json.loads(self.user.profile.preferences)

    def test_known_preference_is_stored(self):
        response = self.post(theme="dark")
        self.assertEqual(response.json()["code"], 1)
        self.assertEqual(self.stored()["theme"], "dark")

    def test_unknown_preference_is_rejected(self):
        response = self.post(evil_key="1")
        self.assertEqual(response.json()["code"], -1)
        self.assertIn("Unknown preference", response.json()["message"])
        self.assertNotIn("evil_key", self.stored())

    def test_batch_with_one_bad_key_changes_nothing(self):
        response = self.post(theme="dark", nope="1")
        self.assertEqual(response.json()["code"], -1)
        self.assertNotIn("theme", self.stored())

    def test_integer_field_rejects_text(self):
        response = self.post(feed_pane_size="wide")
        self.assertEqual(response.json()["code"], -1)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.feed_pane_size, 282)

    def test_integer_field_is_saved(self):
        self.post(feed_pane_size="320")
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.feed_pane_size, 320)

    def test_boolean_field_is_saved(self):
        self.post(send_emails="false")
        self.user.profile.refresh_from_db()
        self.assertFalse(self.user.profile.send_emails)

    def test_boolean_field_rejects_junk(self):
        response = self.post(send_emails="maybe")
        self.assertEqual(response.json()["code"], -1)
        self.user.profile.refresh_from_db()
        self.assertTrue(self.user.profile.send_emails)

    def test_legacy_hide_mobile_is_stored_in_blob(self):
        # set_preference used to setattr this onto Profile, where no field exists.
        response = self.post(hide_mobile="true")
        self.assertEqual(response.json()["code"], 1)
        self.assertIs(self.stored()["hide_mobile"], True)


class PreferenceRenderingTests(TestCase):
    def setUp(self):
        self.client.defaults["HTTP_USER_AGENT"] = UA

    def test_anonymous_page_carries_defaults(self):
        body = self.client.get("/account/login/").content.decode()
        self.assertIn('id="nb-preference-defaults"', body)
        self.assertIn('"theme": "auto"', body)

    def test_stored_blob_cannot_close_the_script_tag(self):
        # dateformat is a free-form STRING, so it is the vector json_script has to
        # contain. theme is enum-checked (apps/profile/preferences.py:ENUM_PREFERENCES),
        # so the same payload is dropped rather than rendered.
        user = User.objects.create_user("prefxss", "prefxss@example.com", "pref-password")
        profile = user.profile
        profile.preferences = std_json.dumps(
            {
                "dateformat": "</script><script>alert(1)</script>",
                "theme": "</script><script>alert(1)</script>",
            }
        )
        profile.save()
        self.client.force_login(user)

        body = self.client.get("/").content.decode()

        self.assertNotIn("<script>alert(1)</script>", body)
        self.assertIn("\\u003C/script\\u003E", body)
        self.assertIn('"theme": "auto"', body)
