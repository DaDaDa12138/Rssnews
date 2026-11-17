"""Scoped classifiers reach calculate_feed_scores (reader.models.UserSubscription).

Folder- and account-scoped classifiers are stored against feed_id=0. Scoring a feed
has to read them, drop folder-scoped rows for folders that do not hold the feed, and
keep is_trained honest when the only classifiers a reader has are scoped ones.
"""

from django.contrib.auth.models import User
from django.test import TestCase

from apps.analyzer.models import MClassifierTitle
from apps.reader.models import UserSubscription, UserSubscriptionFolders
from apps.rss_feeds.models import Feed
from utils import json_functions as json


class Test_CalculateFeedScoresScoping(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("scorer", "scorer@example.com", "scorer-password")
        self.feed = Feed.objects.create(
            feed_address="http://scores.example.com/feed", feed_title="Scores feed"
        )
        self.sub = UserSubscription.objects.create(
            user=self.user, feed=self.feed, is_trained=True, needs_unread_recalc=True
        )

    def add_classifier(self, **kwargs):
        return MClassifierTitle.objects.create(
            user_id=self.user.pk, title="python", score=1, **kwargs
        )

    def test_account_scoped_classifier_keeps_the_feed_trained(self):
        self.add_classifier(feed_id=0, scope="global")

        self.sub.calculate_feed_scores(silent=True)

        self.assertTrue(self.sub.is_trained)

    def test_folder_scoped_classifier_applies_inside_its_folder(self):
        UserSubscriptionFolders.objects.create(
            user=self.user, folders=json.encode([{"Fresh": [self.feed.pk]}])
        )
        self.add_classifier(feed_id=0, scope="folder", folder_name="Fresh")

        self.sub.calculate_feed_scores(silent=True)

        self.assertTrue(self.sub.is_trained)

    def test_folder_scoped_classifier_is_dropped_outside_its_folder(self):
        UserSubscriptionFolders.objects.create(
            user=self.user, folders=json.encode([{"Fresh": [self.feed.pk]}, {"Other": []}])
        )
        self.add_classifier(feed_id=0, scope="folder", folder_name="Other")

        self.sub.calculate_feed_scores(silent=True)

        self.assertFalse(self.sub.is_trained)

    def test_untrained_feed_has_no_classifiers_to_read(self):
        self.sub.is_trained = False
        self.sub.save(update_fields=["is_trained"])

        self.sub.calculate_feed_scores(silent=True)

        self.assertFalse(self.sub.is_trained)
