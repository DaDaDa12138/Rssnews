"""Auto-mark-read settings: the guard branches that only run on bad or empty input."""

import json

from django.contrib.auth.models import User
from django.test import TestCase

from apps.reader.models import MFolderAutoMarkRead

# The site bans requests without a user agent, which every browser sends and the test
# client does not. apps/reader/tests_auto_mark_read.py
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"


class Test_SaveFolderAutoMarkRead(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("ager", "ager@example.com", "ager-password")
        self.client.defaults["HTTP_USER_AGENT"] = UA
        self.client.login(username="ager", password="ager-password")

    def post(self, **data):
        response = self.client.post("/reader/save_folder_auto_mark_read", data)
        return json.loads(response.content)

    def test_requires_a_folder_title(self):
        result = self.post(auto_mark_read_days=7)

        self.assertEqual(result["code"], -1)
        self.assertEqual(result["message"], "Folder title required")

    def test_rejects_a_value_that_is_not_a_number(self):
        result = self.post(folder_title="Fresh", auto_mark_read_days="soon")

        self.assertEqual(result["code"], -1)
        self.assertEqual(result["message"], "Invalid days value")
        self.assertFalse(MFolderAutoMarkRead.objects.filter(user_id=self.user.pk).exists())

    def test_rejects_a_value_past_a_year(self):
        result = self.post(folder_title="Fresh", auto_mark_read_days=400)

        self.assertEqual(result["code"], -1)
        self.assertEqual(result["message"], "Days must be between 0 and 365")

    def test_saves_a_day_count(self):
        result = self.post(folder_title="Fresh", auto_mark_read_days=7)

        self.assertEqual(result["code"], 1, result)
        self.assertEqual(result["auto_mark_read_days"], 7)
        setting = MFolderAutoMarkRead.objects.get(user_id=self.user.pk, folder_title="Fresh")
        self.assertEqual(setting.auto_mark_read_days, 7)

    def test_keeps_zero_as_never_rather_than_inherit(self):
        result = self.post(folder_title="Fresh", auto_mark_read_days=0)

        self.assertEqual(result["code"], 1, result)
        self.assertEqual(result["auto_mark_read_days"], 0)
        setting = MFolderAutoMarkRead.objects.get(user_id=self.user.pk, folder_title="Fresh")
        self.assertEqual(setting.auto_mark_read_days, 0)

    def test_resetting_reports_null_and_drops_the_row(self):
        MFolderAutoMarkRead.objects.create(user_id=self.user.pk, folder_title="Fresh", auto_mark_read_days=7)

        result = self.post(folder_title="Fresh", auto_mark_read_days="null")

        self.assertEqual(result["code"], 1, result)
        self.assertIsNone(result["auto_mark_read_days"])
        self.assertFalse(MFolderAutoMarkRead.objects.filter(user_id=self.user.pk).exists())
