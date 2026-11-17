"""Tests for apps/analyzer/classifiers.py.

The registry exists so the trainer payload, the counters and the bulk delete cannot
drift apart: they used to spell the same six models out by hand in three views, and a
missed edit showed up as a classifier that counted but never deleted.
"""

from django.test import TestCase

from apps.analyzer import classifiers
from apps.analyzer.models import MClassifierFeed, MClassifierTag, MClassifierTitle


class Test_Classifier_Registry(TestCase):
    def setUp(self):
        MClassifierTitle.objects.create(user_id=7, feed_id=1, title="plain", score=1, is_regex=False)
        MClassifierTitle.objects.create(user_id=7, feed_id=1, title="^regex$", score=-1, is_regex=True)
        MClassifierTitle.objects.create(user_id=7, feed_id=1, title="untrained", score=0, is_regex=False)
        MClassifierTag.objects.create(user_id=7, feed_id=1, tag="tag", score=1)
        MClassifierFeed.objects.create(user_id=7, feed_id=1, score=1)

    def test_trained_skips_zero_scores(self):
        trained = classifiers.trained(7)
        self.assertEqual({row.title for row in trained["title"]}, {"plain", "^regex$"})
        self.assertEqual(len(trained["feed"]), 1)
        self.assertEqual(trained["author"], [])

    def test_trainer_entry_shape(self):
        table = classifiers.CLASSIFIER_TABLES[0]
        row = MClassifierTitle.objects.filter(user_id=7, title="plain").first()
        self.assertEqual(
            classifiers.trainer_entry(table, row),
            {"title": "plain", "score": 1, "is_regex": False, "scope": "feed", "folder_name": ""},
        )

    def test_scoped_collections_skip_the_feed_table(self):
        scoped = classifiers.scoped_collections()
        self.assertEqual(set(scoped), {"titles", "authors", "tags", "texts", "urls"})
        self.assertTrue(all(value == [] for value in scoped.values()))

    def test_counts_split_regex_from_plain(self):
        counted = classifiers.counts(7)
        self.assertEqual(counted["title"], 2)
        self.assertEqual(counted["title_regex"], 1)
        self.assertEqual(counted["tag"], 1)
        self.assertEqual(counted["feed"], 1)
        self.assertEqual(counted["author"], 0)
        self.assertEqual(counted["author_regex"], 0)
        self.assertEqual(sum(counted.values()), 5)

    def test_delete_categories_reports_rows_and_ignores_unknown_names(self):
        deleted = classifiers.delete_categories(7, ["title_regex", "tag", "nope"])
        self.assertEqual(deleted, {"title_regex": 1, "tag": 1})
        self.assertEqual(MClassifierTitle.objects.filter(user_id=7).count(), 2)
        self.assertEqual(MClassifierTag.objects.filter(user_id=7).count(), 0)

    def test_category_mapping(self):
        table, filters = classifiers.category("title")
        self.assertIs(table.model, MClassifierTitle)
        self.assertEqual(filters, {"is_regex__ne": True})
        table, filters = classifiers.category("title_regex")
        self.assertEqual(filters, {"is_regex": True})
        self.assertEqual(classifiers.category("bogus"), (None, {}))
