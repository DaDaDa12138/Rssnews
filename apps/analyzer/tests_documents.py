"""Regression tests for the mongoengine lookup shim in utils/documents.py.

The personal edition replaced Mongo with Postgres, and utils/documents.py keeps the
mongoengine spellings alive so the ~600 call sites did not have to be rewritten. The
spelling that matters most is field__ne, which mongoengine put after the field name.
Two routed endpoints depend on it (/reader/all_classifiers, /profile/count_classifiers),
so a silent FieldError there is a 500 in the UI.

apps/analyzer/tests_documents.py
"""

from django.test import TestCase

from apps.analyzer.models import MClassifierTitle
from apps.rss_feeds.models import MStarredStory


class Test_Legacy_Lookups(TestCase):
    def setUp(self):
        MClassifierTitle.objects.create(user_id=1, feed_id=1, title="keep", score=1, is_regex=True)
        MClassifierTitle.objects.create(user_id=1, feed_id=1, title="drop", score=0, is_regex=False)

    def test_ne_lookup_on_queryset(self):
        titles = {classifier.title for classifier in MClassifierTitle.objects.filter(user_id=1, score__ne=0)}
        self.assertEqual(titles, {"keep"})

    def test_ne_lookup_on_manager_call(self):
        titles = {classifier.title for classifier in MClassifierTitle.objects(user_id=1, score__ne=0)}
        self.assertEqual(titles, {"keep"})

    def test_ne_lookup_on_boolean(self):
        self.assertEqual(MClassifierTitle.objects.filter(is_regex__ne=True).count(), 1)

    def test_plain_lookups_are_untouched(self):
        self.assertEqual(MClassifierTitle.objects.filter(user_id=1, score=0).count(), 1)

    def test_exclude_with_ne_lookup(self):
        # exclude(score__ne=1) is the same set as filter(score=1).
        self.assertEqual(MClassifierTitle.objects.exclude(score__ne=1).count(), 1)


    def test_empty_json_list_can_be_excluded(self):
        # The Mongo $where that selected saved stories with highlights became
        # exclude(highlights=[]): Django reads highlights__len as the JSON key "len", so
        # there is no length lookup to rely on.
        MStarredStory.objects.create(user_id=1, story_guid="g1", story_title="with", highlights=["a"])
        MStarredStory.objects.create(user_id=1, story_guid="g2", story_title="without", highlights=[])
        titles = {
            story.story_title for story in MStarredStory.objects.filter(user_id=1).exclude(highlights=[])
        }
        self.assertEqual(titles, {"with"})

    def test_nin_lookup(self):
        # MStory.trim_feed keeps the hashes it just fetched with story_hash__nin, so a
        # missing translation made every feed trim raise FieldError.
        titles = {
            classifier.title for classifier in MClassifierTitle.objects.filter(title__nin=["drop"])
        }
        self.assertEqual(titles, {"keep"})

    def test_raw_lookup_fails_loudly(self):
        with self.assertRaises(NotImplementedError):
            MClassifierTitle.objects.filter(__raw__={"$where": "this.score > 0"}).count()
