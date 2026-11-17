"""Batch feed adding must reactivate an existing subscription (subscription_batch.add_feed_ids)."""

from django.contrib.auth.models import User
from django.test import TestCase

from apps.reader.models import UserSubscription
from apps.reader.subscription_batch import add_feed_ids
from apps.rss_feeds.models import Feed


class Test_AddFeedIds(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("batcher", "batcher@example.com", "batcher-password")
        self.feed = Feed.objects.create(
            feed_address="http://batch.example.com/feed", feed_title="Batch feed"
        )

    def test_adds_a_new_subscription(self):
        result = add_feed_ids(self.user, [self.feed.pk])

        self.assertEqual(result["code"], 1, result)
        self.assertEqual(result["results"][0]["created"], True)
        self.assertTrue(UserSubscription.objects.get(user=self.user, feed=self.feed).active)

    def test_reactivates_an_inactive_subscription(self):
        sub = UserSubscription.objects.create(user=self.user, feed=self.feed, active=False)

        result = add_feed_ids(self.user, [self.feed.pk])

        self.assertEqual(result["code"], 1, result)
        self.assertEqual(result["results"][0]["created"], False)
        sub.refresh_from_db()
        self.assertTrue(sub.active)
        self.assertTrue(sub.needs_unread_recalc)
