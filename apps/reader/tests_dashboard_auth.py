"""Dashboard river writes: only a logged in reader may create or delete rows.

Without the login guard an anonymous POST reached MDashboardRiver with a null user_id.
Postgres treats nulls as distinct in the unique constraint, so every request inserted
another row instead of updating the previous one. apps/reader/tests_dashboard_auth.py
"""

import json

from django.contrib.auth.models import User
from django.test import Client, TestCase

from apps.profile.models import MDashboardRiver

# The site bans requests without a user agent, which every browser sends and the test
# client does not. apps/reader/tests_dashboard_auth.py
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"

RIVER = {"river_id": "river:all", "river_side": "right", "river_order": 7}


class Test_DashboardRiverAuth(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("dash-user", "dash@example.com", "dash-password")
        self.anonymous = Client(HTTP_USER_AGENT=UA)
        self.client.defaults["HTTP_USER_AGENT"] = UA
        self.client.login(username="dash-user", password="dash-password")

    def test_anonymous_cannot_save_a_river(self):
        response = self.anonymous.post("/reader/save_dashboard_river", RIVER)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(MDashboardRiver.objects.count(), 0)

    def test_anonymous_cannot_remove_a_river(self):
        response = self.anonymous.post("/reader/remove_dashboard_river", RIVER)

        self.assertEqual(response.status_code, 403)

    def test_anonymous_cannot_replace_every_river(self):
        response = self.anonymous.post(
            "/reader/save_dashboard_rivers",
            data=json.dumps({"dashboard_rivers": [RIVER]}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(MDashboardRiver.objects.count(), 0)

    def test_logged_in_reader_can_save_and_remove(self):
        response = self.client.post("/reader/save_dashboard_river", RIVER)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(MDashboardRiver.objects.filter(user_id=self.user.pk).count(), 1)

        response = self.client.post("/reader/remove_dashboard_river", RIVER)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(MDashboardRiver.objects.filter(user_id=self.user.pk).count(), 0)
