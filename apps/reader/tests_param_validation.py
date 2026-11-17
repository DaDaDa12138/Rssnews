"""Reader endpoints take user input straight from the query string and form body.

A bare int() on that input raises ValueError and the 500 with its traceback lands in
the error log, so these cover the fallbacks and the 400s instead of the happy path.
"""

import json

from django.contrib.auth.models import User
from django.test import TestCase

# The site bans requests without a user agent, which every browser sends and the test
# client does not. apps/reader/tests_param_validation.py
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"


class Test_NumericParameters(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("param-user", "param@example.com", "param-password")
        self.client.defaults["HTTP_USER_AGENT"] = UA
        self.client.login(username="param-user", password="param-password")

    def test_saved_stories_falls_back_to_the_first_page(self):
        response = self.client.get("/reader/starred_stories?offset=abc&limit=abc&page=abc&v=abc")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["stories"], [])

    def test_read_stories_falls_back_to_the_first_page(self):
        response = self.client.get("/reader/read_stories?offset=abc&limit=abc&page=abc")

        self.assertEqual(response.status_code, 200)
        self.assertIn("stories", json.loads(response.content))

    def test_complete_river_defaults_the_page(self):
        response = self.client.post("/reader/complete_river", {"page": "abc"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["code"], 1)

    def test_mark_feed_as_read_defaults_the_cutoff(self):
        response = self.client.post("/reader/mark_feed_as_read", {"cutoff_timestamp": "abc"})

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(json.loads(response.content)["cutoff_date"])


class Test_MissingFeedId(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("feed-id-user", "feed-id@example.com", "feed-id-password")
        self.client.defaults["HTTP_USER_AGENT"] = UA
        self.client.login(username="feed-id-user", password="feed-id-password")

    def test_delete_feed_requires_a_feed_id(self):
        response = self.client.post("/reader/delete_feed", {})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.content)["message"], "Missing parameter: feed_id")

    def test_delete_feed_rejects_a_feed_id_that_is_not_a_number(self):
        response = self.client.post("/reader/delete_feed", {"feed_id": "abc"})

        self.assertEqual(response.status_code, 400)

    def test_move_feed_to_folders_requires_a_feed_id(self):
        response = self.client.post("/reader/move_feed_to_folders", {})

        self.assertEqual(response.status_code, 400)

    def test_move_feed_to_folder_requires_a_feed_id(self):
        response = self.client.post("/reader/move_feed_to_folder", {})

        self.assertEqual(response.status_code, 400)

    def test_save_dashboard_river_rejects_a_non_numeric_order(self):
        response = self.client.post(
            "/reader/save_dashboard_river", {"river_id": "1", "river_side": "right", "river_order": "abc"}
        )

        self.assertEqual(response.status_code, 400)


class Test_MissingFolderNames(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("folder-user", "folder@example.com", "folder-password")
        self.client.defaults["HTTP_USER_AGENT"] = UA
        self.client.login(username="folder-user", password="folder-password")

    def test_add_folder_without_a_name_reports_it(self):
        response = self.client.post("/reader/add_folder", {})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["message"], "Gotta write in a folder name.")

    def test_delete_feed_by_url_without_a_url_reports_it(self):
        response = self.client.post("/reader/delete_feed_by_url", {})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["message"], "URL not found.")

    def test_rename_folder_without_a_new_name_reports_it(self):
        response = self.client.post("/reader/rename_folder", {"folder_name": "Fresh"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["code"], -1)

    def test_move_folder_to_folder_without_a_folder_reports_it(self):
        response = self.client.post("/reader/move_folder_to_folder", {})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["message"], "Choose a folder to move.")
