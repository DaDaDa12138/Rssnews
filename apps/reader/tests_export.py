"""Tests for the settings export bundle (apps/reader/views/export.py)."""

import json

from django.contrib.auth.models import User
from django.test import TestCase

from apps.reader.models import SavedSearch, StoryTag, UserSubscription, UserSubscriptionFolders
from apps.profile.models import Profile
from apps.rss_feeds.models import Feed, StoryFilter


class Test_ExportSettings(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("exportuser", "export@example.com", "export-pass-123")
        self.feed = Feed.objects.create(
            feed_address="http://export.example.com/feed", feed_title="Export feed", feed_link="http://export.example.com"
        )
        UserSubscription.objects.create(user=self.user, feed=self.feed)
        UserSubscriptionFolders.objects.create(user=self.user, folders='[{"Tech": [%s]}]' % self.feed.pk)
        StoryFilter.objects.create(
            user=self.user, scope=StoryFilter.SCOPE_FEED, feed=self.feed, pattern="python", action=StoryFilter.ACTION_STAR
        )
        SavedSearch.objects.create(user=self.user, name="Python", query="title:python")
        StoryTag.add(self.user.pk, "%s:aaa" % self.feed.pk, "later")
        self.client.defaults["HTTP_USER_AGENT"] = "Mozilla/5.0 (X11; Linux x86_64) Chrome/126.0"
        self.client.force_login(self.user)

    def test_export_contains_every_section(self):
        response = self.client.get("/reader/export_settings")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json; charset=utf-8")
        self.assertIn("attachment", response["Content-Disposition"])

        data = json.loads(response.content)
        self.assertEqual(data["version"], 1)
        self.assertEqual(data["user"]["username"], "exportuser")
        self.assertEqual(len(data["subscriptions"]), 1)
        self.assertEqual(data["subscriptions"][0]["feed_id"], self.feed.pk)
        self.assertEqual(data["folders"], '[{"Tech": [%s]}]' % self.feed.pk)
        self.assertEqual(data["filters"][0]["pattern"], "python")
        self.assertEqual(data["saved_searches"][0]["name"], "Python")
        self.assertEqual(data["tags"], ["later"])

    def test_export_requires_login(self):
        self.client.logout()
        response = self.client.get("/reader/export_settings")
        self.assertEqual(response.status_code, 401)


class Test_ImportSettings(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("importer", "importer@example.com", "import-pass-123")
        self.other = User.objects.create_user("exporter", "exporter@example.com", "export-pass-123")
        self.feed = Feed.objects.create(
            feed_address="http://import.example.com/feed", feed_title="Import feed", feed_link="http://import.example.com"
        )
        self.bundle = {
            "version": 1,
            "subscriptions": [
                {"feed_id": 999999, "feed_address": self.feed.feed_address, "feed_title": "Import feed"},
                {"feed_id": 888888, "feed_address": "http://missing.example.com/feed"},
            ],
            "view_settings": {str(self.feed.pk): {"l": "grid"}},
            "preferences": {"feed_pane_size": 300},
            "filters": [
                {"scope": "feed", "feed_id": self.feed.pk, "pattern": "django", "action": "star"}
            ],
            "saved_searches": [{"name": "Django", "query": "title:django", "order": "newest"}],
        }
        self.client.defaults["HTTP_USER_AGENT"] = "Mozilla/5.0 (X11; Linux x86_64) Chrome/126.0"
        self.client.force_login(self.user)

    def post_bundle(self, bundle):
        return self.client.post(
            "/reader/import_settings",
            data=json.dumps(bundle),
            content_type="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

    def test_import_merges_and_adds(self):
        response = self.post_bundle(self.bundle)
        self.assertEqual(response.status_code, 200)
        counts = json.loads(response.content)
        self.assertEqual(counts["subscriptions_added"], 1)
        self.assertEqual(counts["skipped_subscriptions"], 1)
        self.assertEqual(counts["filters_added"], 1)
        self.assertEqual(counts["saved_searches_added"], 1)
        self.assertEqual(counts["view_settings_merged"], 1)

        self.assertTrue(UserSubscription.objects.filter(user=self.user, feed=self.feed).exists())
        folders_row = UserSubscriptionFolders.objects.get(user=self.user)
        self.assertIn(self.feed.pk, json.loads(folders_row.folders))
        self.assertTrue(StoryFilter.objects.filter(user=self.user, pattern="django").exists())
        self.assertTrue(SavedSearch.objects.filter(user=self.user, name="Django").exists())
        profile = Profile.objects.get(user=self.user)
        self.assertEqual(profile.feed_pane_size, 300)
        self.assertEqual(json.loads(profile.view_settings)[str(self.feed.pk)], {"l": "grid"})

    def test_import_is_idempotent(self):
        self.post_bundle(self.bundle)
        counts = json.loads(self.post_bundle(self.bundle).content)
        self.assertEqual(counts["subscriptions_added"], 0)
        self.assertEqual(counts["filters_added"], 0)
        self.assertEqual(counts["saved_searches_added"], 0)

    def test_import_updates_changed_saved_search(self):
        self.post_bundle(self.bundle)
        self.bundle["saved_searches"][0]["query"] = "title:flask"
        counts = json.loads(self.post_bundle(self.bundle).content)
        self.assertEqual(counts["saved_searches_updated"], 1)
        self.assertEqual(SavedSearch.objects.get(user=self.user, name="Django").query, "title:flask")

    def test_import_rejects_requests_without_the_ajax_header(self):
        response = self.client.post(
            "/reader/import_settings", data=json.dumps(self.bundle), content_type="application/json"
        )
        self.assertEqual(response.status_code, 403)

    def test_import_requires_post_and_login(self):
        self.assertEqual(self.client.get("/reader/import_settings").status_code, 405)
        self.client.logout()
        self.assertEqual(self.post_bundle(self.bundle).status_code, 401)

    def test_import_rejects_unknown_version(self):
        self.bundle["version"] = 7
        self.assertEqual(self.post_bundle(self.bundle).status_code, 400)
