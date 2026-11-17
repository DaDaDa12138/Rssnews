"""Tests for story rules (apps/rss_feeds/filters.py) and the StoryFilter model.

A rule is evaluated while a feed is ingested, so these tests build real MStory
rows and check both matching and the side effects (read, star, tag).
"""

import datetime
import json
import zlib
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from apps.reader.models import StoryTag, UserSubscription, UserSubscriptionFolders
from apps.rss_feeds import filters
from apps.rss_feeds.models import Feed, MStarredStory, MStory, StoryFilter


def make_feed(title="Example", address="http://example.com/feed"):
    return Feed.objects.create(feed_address=address, feed_title=title, feed_link="http://example.com")


def make_story(feed, suffix="abc123", title="A title", body="", author="", permalink=None):
    return MStory.objects.create(
        story_feed_id=feed.pk,
        story_hash="%s:%s" % (feed.pk, suffix),
        story_guid="guid-%s" % suffix,
        story_title=title,
        story_author_name=author,
        story_permalink=permalink or "https://example.com/%s" % suffix,
        story_content_z=zlib.compress(body.encode("utf-8")),
        story_date=datetime.datetime(2026, 10, 1, 12, 0, 0),
    )


class Test_CompiledRule(TestCase):
    def setUp(self):
        self.feed = make_feed()
        self.story = make_story(self.feed, title="Python 3.14 released", body="<p>Fast and small</p>", author="Guido")

    def rule(self, **kwargs):
        defaults = dict(
            user_id=1,
            scope=StoryFilter.SCOPE_FEED,
            feed=self.feed,
            field=StoryFilter.FIELD_ANY,
            pattern="python",
            action=StoryFilter.ACTION_MARK_READ,
        )
        defaults.update(kwargs)
        return StoryFilter(**defaults)

    def test_substring_match_ignores_case(self):
        self.assertTrue(filters.CompiledRule(self.rule(pattern="python")).matches(self.story))
        self.assertTrue(filters.CompiledRule(self.rule(pattern="PYTHON")).matches(self.story))

    def test_case_sensitive_rule_needs_the_exact_case(self):
        rule = self.rule(pattern="python", case_sensitive=True)
        self.assertFalse(filters.CompiledRule(rule).matches(self.story))
        rule.pattern = "Python"
        self.assertTrue(filters.CompiledRule(rule).matches(self.story))

    def test_regex_matches(self):
        rule = self.rule(pattern=r"3\.\d+", is_regex=True)
        self.assertTrue(filters.CompiledRule(rule).matches(self.story))

    def test_invalid_regex_never_matches(self):
        rule = self.rule(pattern="([unclosed", is_regex=True)
        self.assertFalse(filters.CompiledRule(rule).matches(self.story))

    def test_field_scoping(self):
        self.assertFalse(filters.CompiledRule(self.rule(field="title", pattern="Fast")).matches(self.story))
        self.assertTrue(filters.CompiledRule(self.rule(field="author", pattern="guido")).matches(self.story))
        self.assertTrue(filters.CompiledRule(self.rule(field="url", pattern="example.com")).matches(self.story))

    def test_content_field_reads_the_compressed_body(self):
        # story_content is null for every ingested story; the body lives in story_content_z.
        self.assertFalse(self.story.story_content)
        rule = self.rule(field="content", pattern="fast and small")
        self.assertTrue(filters.CompiledRule(rule).matches(self.story))


class Test_RulesForFeed(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("reader", "reader@example.com", "pw")
        self.other = User.objects.create_user("other", "other@example.com", "pw")
        self.feed = make_feed()
        self.other_feed = make_feed("Other", "http://other.example.com/feed")
        UserSubscription.objects.create(user=self.user, feed=self.feed)
        UserSubscription.objects.create(user=self.user, feed=self.other_feed)

    def make_rule(self, user=None, **kwargs):
        defaults = dict(
            user=user or self.user,
            scope=StoryFilter.SCOPE_FEED,
            feed=self.feed,
            pattern="python",
            action=StoryFilter.ACTION_MARK_READ,
        )
        defaults.update(kwargs)
        return StoryFilter.objects.create(**defaults)

    def test_feed_scope_only_applies_to_that_feed(self):
        self.make_rule()
        self.assertIn(self.user.pk, filters.rules_for_feed(self.feed))
        self.assertNotIn(self.user.pk, filters.rules_for_feed(self.other_feed))

    def test_global_scope_applies_to_every_feed(self):
        self.make_rule(scope=StoryFilter.SCOPE_GLOBAL, feed=None)
        self.assertIn(self.user.pk, filters.rules_for_feed(self.feed))
        self.assertIn(self.user.pk, filters.rules_for_feed(self.other_feed))

    def test_folder_scope_follows_the_subscription_folders(self):
        self.make_rule(scope=StoryFilter.SCOPE_FOLDER, feed=None, folder="Tech")
        UserSubscriptionFolders.objects.create(
            user=self.user, folders=json.dumps([{"Tech": [self.feed.pk]}])
        )
        self.assertIn(self.user.pk, filters.rules_for_feed(self.feed))
        self.assertNotIn(self.user.pk, filters.rules_for_feed(self.other_feed))

    def test_disabled_rules_are_skipped(self):
        self.make_rule(enabled=False)
        self.assertNotIn(self.user.pk, filters.rules_for_feed(self.feed))

    def test_other_users_rules_are_separate(self):
        self.make_rule(user=self.other)
        self.assertNotIn(self.user.pk, filters.rules_for_feed(self.feed))
        self.assertIn(self.other.pk, filters.rules_for_feed(self.feed))


class Test_ApplyRules(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("reader", "reader@example.com", "pw")
        self.feed = make_feed()
        self.subscription = UserSubscription.objects.create(user=self.user, feed=self.feed)
        self.story = make_story(self.feed, title="Python 3.14 released")

    def rule(self, **kwargs):
        defaults = dict(
            user=self.user,
            scope=StoryFilter.SCOPE_FEED,
            feed=self.feed,
            pattern="python",
            action=StoryFilter.ACTION_MARK_READ,
        )
        defaults.update(kwargs)
        return StoryFilter.objects.create(**defaults)

    def test_mark_read_marks_the_story_for_that_reader(self):
        rule = self.rule()
        compiled = filters.CompiledRule(rule)
        with patch.object(UserSubscription, "mark_story_ids_as_read") as mark_read:
            result = filters.apply_rules({self.user.pk: [compiled]}, self.story, self.feed.pk)
        mark_read.assert_called_once_with([self.story.story_hash], aggregated=True)
        self.assertEqual(result["read"], 1)
        rule.refresh_from_db()
        self.assertEqual(rule.hits, 1)

    def test_star_copies_the_story_into_saved(self):
        rule = self.rule(action=StoryFilter.ACTION_STAR)
        compiled = filters.CompiledRule(rule)
        filters.apply_rules({self.user.pk: [compiled]}, self.story, self.feed.pk)
        starred = MStarredStory.objects.filter(user_id=self.user.pk, story_guid=self.story.story_guid)
        self.assertEqual(starred.count(), 1)

    def test_tag_adds_a_story_tag(self):
        rule = self.rule(action=StoryFilter.ACTION_TAG, tag="Python")
        compiled = filters.CompiledRule(rule)
        filters.apply_rules({self.user.pk: [compiled]}, self.story, self.feed.pk)
        self.assertEqual(StoryTag.for_story(self.user.pk, self.story.story_hash), ["python"])

    def test_a_non_matching_story_is_left_alone(self):
        rule = self.rule(pattern="rust")
        compiled = filters.CompiledRule(rule)
        result = filters.apply_rules({self.user.pk: [compiled]}, self.story, self.feed.pk)
        self.assertEqual(result["read"], 0)
        rule.refresh_from_db()
        self.assertEqual(rule.hits, 0)

    def test_apply_rule_to_recent_counts_matches(self):
        rule = self.rule(action=StoryFilter.ACTION_TAG, tag="python")
        make_story(self.feed, suffix="zzz999", title="Something else")
        with patch.object(UserSubscription, "mark_story_ids_as_read"):
            counts = filters.apply_rule_to_recent(rule, self.user)
        self.assertEqual(counts["matched"], 1)
        self.assertEqual(counts["tagged"], 1)


class Test_ValidatePattern(TestCase):
    def test_empty_pattern_is_rejected(self):
        self.assertTrue(filters.validate_pattern("", False))

    def test_long_pattern_is_rejected(self):
        self.assertTrue(filters.validate_pattern("x" * 256, False))

    def test_bad_regex_is_rejected(self):
        self.assertTrue(filters.validate_pattern("([unclosed", True))

    def test_good_values_pass(self):
        self.assertIsNone(filters.validate_pattern("python", False))
        self.assertIsNone(filters.validate_pattern(r"py\w+", True))
