"""Deleting saved stories reports the remaining counts (profile.views.delete_starred_stories)."""

import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from apps.rss_feeds.models import MStarredStory


class Test_DeleteStarredStories(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("saver", "saver@example.com", "saver-password")
        self.client.force_login(self.user)

    def test_deletes_saved_stories_and_returns_counts(self):
        # MStarredStory derives story_hash from story_guid, so both have to be set.
        MStarredStory.objects.create(
            user_id=self.user.pk,
            story_feed_id=1,
            story_guid="guid-aaa111",
            story_hash="1:aaa111",
            story_title="Saved story",
            starred_date=timezone.now(),
        )

        response = self.client.post("/profile/delete_starred_stories")
        body = json.loads(response.content)

        self.assertEqual(response.status_code, 200, body)
        self.assertEqual(body["code"], 1, body)
        self.assertEqual(body["stories_deleted"], 1, body)
        self.assertEqual(body["starred_count"], 0, body)
        self.assertEqual(MStarredStory.objects.filter(user_id=self.user.pk).count(), 0)
