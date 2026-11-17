"""Tests for the search syntax (apps/rss_feeds/search.py).

The parser is pure; the queryset and post filters run against real MStory rows
so a change in the compression of story bodies shows up here.
"""

import datetime
import json
import zlib
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.reader.models import StoryTag, UserSubscriptionFolders
from apps.rss_feeds import search
from apps.rss_feeds.models import Feed, MStarredStory, MStory


def make_feed(title="Example", address="http://example.com/feed"):
    return Feed.objects.create(feed_address=address, feed_title=title, feed_link="http://example.com")


def make_story(feed, suffix, title, body="", author="", permalink=None, days_ago=1):
    return MStory.objects.create(
        story_feed_id=feed.pk,
        story_hash="%s:%s" % (feed.pk, suffix),
        story_guid="guid-%s" % suffix,
        story_title=title,
        story_author_name=author,
        story_permalink=permalink or "https://example.com/%s" % suffix,
        story_content_z=zlib.compress(body.encode("utf-8")),
        story_date=datetime.datetime.utcnow() - datetime.timedelta(days=days_ago),
    )


class Test_Parse(TestCase):
    def test_free_words(self):
        parsed = search.parse("python release")
        self.assertEqual(parsed.terms, ["python", "release"])
        self.assertFalse(parsed.errors)

    def test_quoted_phrase_stays_one_term(self):
        self.assertEqual(search.parse('"python release"').terms, ["python release"])

    def test_negated_word(self):
        parsed = search.parse("python -rust")
        self.assertEqual(parsed.terms, ["python"])
        self.assertEqual(parsed.negated_terms, ["rust"])

    def test_field_operators(self):
        parsed = search.parse('title:python author:"guido van rossum"')
        self.assertEqual(parsed.clauses, [("title", "python", False), ("author", "guido van rossum", False)])

    def test_unknown_operator_is_free_text(self):
        parsed = search.parse("http://example.com/post")
        self.assertEqual(parsed.terms, ["http://example.com/post"])
        self.assertEqual(parsed.clauses, [])

    def test_body_goes_to_post_filters(self):
        parsed = search.parse("body:sunrise")
        self.assertEqual(parsed.post_filters, [("body", "sunrise", False)])
        self.assertTrue(parsed.has_post_filters)

    def test_star_and_read_need_a_boolean(self):
        self.assertTrue(search.parse("star:maybe").errors)
        self.assertEqual(search.parse("read:yes").post_filters, [("read", True, False)])
        self.assertEqual(search.parse("star:no").post_filters, [("star", False, False)])

    def test_date_goes_to_clauses(self):
        self.assertEqual(search.parse("date:week").clauses, [("date", "week", False)])

    def test_bad_date_is_reported_at_parse_time(self):
        parsed = search.parse("date:someday")
        self.assertTrue(parsed.errors)
        self.assertEqual(parsed.clauses, [])

    def test_empty_operator_value_is_an_error(self):
        self.assertTrue(search.parse("title:").errors)

    def test_terms_are_capped(self):
        parsed = search.parse(" ".join("word%d" % index for index in range(40)))
        self.assertEqual(len(parsed.terms), search.MAX_TERMS)


class Test_BuildQueryset(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("reader", "reader@example.com", "pw")
        self.feed = make_feed("Tech Daily")
        self.other_feed = make_feed("Cooking", "http://cooking.example.com/feed")
        self.python = make_story(
            self.feed, "aaa111", "Python 3.14 released", body="A fast runtime", author="Guido"
        )
        self.rust = make_story(
            self.feed, "bbb222", "Rust 2.0 released", body="A fast compiler", author="Graydon"
        )
        self.cake = make_story(
            self.other_feed, "ccc333", "Chocolate cake", body="A sweet dessert", author="Baker"
        )

    def results(self, query):
        parsed = search.parse(query)
        queryset = search.build_queryset(MStory.objects.all(), parsed, self.user)
        return {story.story_hash for story in queryset}

    def test_free_word_matches_titles(self):
        self.assertEqual(self.results("python"), {self.python.story_hash})

    def test_free_word_matches_story_text(self):
        self.assertEqual(self.results("runtime"), {self.python.story_hash})

    @override_settings(SEARCH_FREE_TEXT_INCLUDES_BODY=False)
    def test_free_word_body_matching_can_be_disabled(self):
        self.assertEqual(self.results("runtime"), set())

    def test_body_operator_is_pushed_into_sql(self):
        parsed = search.parse("body:runtime")
        queryset = search.build_queryset(MStory.objects.all(), parsed, self.user)
        self.assertEqual(parsed.post_filters, [])
        self.assertIn("story_text", str(queryset.query))
        self.assertEqual({story.story_hash for story in queryset}, {self.python.story_hash})

    def test_negated_body_operator_is_pushed_into_sql(self):
        parsed = search.parse("-body:runtime")
        queryset = search.build_queryset(MStory.objects.all(), parsed, self.user)
        self.assertEqual(parsed.post_filters, [])
        self.assertEqual({story.story_hash for story in queryset}, {self.rust.story_hash, self.cake.story_hash})

    def test_story_text_is_written_on_save(self):
        self.python.refresh_from_db()
        self.assertIn("runtime", self.python.story_text)

    def test_story_text_strips_markup(self):
        story = make_story(self.feed, "ddd444", "Markup", body="<p>Hello <b>world</b></p>")
        story.refresh_from_db()
        self.assertEqual(story.story_text, "Hello world")

    def test_story_text_updates_when_content_changes(self):
        self.python.story_content = "<p>Completely new words</p>"
        self.python.save()
        self.python.refresh_from_db()
        self.assertIn("Completely new words", self.python.story_text)
        self.assertNotIn("runtime", self.python.story_text)

    def test_negated_word_excludes(self):
        self.assertEqual(self.results("released -rust"), {self.python.story_hash})

    def test_author_operator(self):
        self.assertEqual(self.results("author:guido"), {self.python.story_hash})

    def test_url_operator(self):
        self.assertEqual(self.results("url:bbb222"), {self.rust.story_hash})

    def test_feed_operator_by_title(self):
        self.assertEqual(self.results("feed:cooking"), {self.cake.story_hash})

    def test_feed_operator_by_id(self):
        self.assertEqual(self.results("feed:%s" % self.feed.pk), {self.python.story_hash, self.rust.story_hash})

    def test_folder_operator(self):
        UserSubscriptionFolders.objects.create(
            user=self.user, folders=json.dumps([{"Reading": [self.feed.pk]}])
        )
        self.assertEqual(self.results("folder:reading"), {self.python.story_hash, self.rust.story_hash})

    def test_tag_operator(self):
        StoryTag.add(self.user.pk, self.cake.story_hash, "Dessert")
        self.assertEqual(self.results("tag:dessert"), {self.cake.story_hash})

    def test_date_operator(self):
        make_story(self.feed, "ddd444", "Old news", days_ago=40)
        self.assertEqual(self.results("date:week"), {self.python.story_hash, self.rust.story_hash, self.cake.story_hash})

    def test_bad_date_is_reported(self):
        parsed = search.parse("date:someday")
        search.build_queryset(MStory.objects.all(), parsed, self.user)
        self.assertTrue(parsed.errors)

    def test_star_operator_is_applied_in_sql(self):
        MStarredStory.objects.create(
            user_id=self.user.pk,
            story_hash=self.python.story_hash,
            story_guid=self.python.story_guid,
            story_feed_id=self.feed.pk,
            story_title=self.python.story_title,
        )
        parsed = search.parse("star:yes")
        queryset = search.build_queryset(MStory.objects.all(), parsed, self.user)
        self.assertEqual({story.story_hash for story in queryset}, {self.python.story_hash})
        self.assertFalse(parsed.post_filters)


class Test_PostFilters(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("reader", "reader@example.com", "pw")
        self.feed = make_feed()
        self.story = make_story(self.feed, "aaa111", "Sunrise over the bay", body="The tide was low")

    def run_filters(self, query, stories=None):
        parsed = search.parse(query)
        stories = stories if stories is not None else [self.story]
        return search.apply_post_filters(stories, parsed, self.user)

    def test_body_matches_the_compressed_content(self):
        self.assertEqual(len(self.run_filters("body:tide")), 1)
        self.assertEqual(self.run_filters("body:volcano"), [])

    def test_negated_body(self):
        self.assertEqual(len(self.run_filters("-body:volcano")), 1)
        self.assertEqual(self.run_filters("-body:tide"), [])

    def test_read_state(self):
        with patch.object(search, "_read_hashes", return_value={self.story.story_hash}):
            self.assertEqual(len(self.run_filters("read:yes")), 1)
            self.assertEqual(self.run_filters("read:no"), [])
            self.assertEqual(self.run_filters("-read:yes"), [])

    def test_starred_state(self):
        MStarredStory.objects.create(
            user_id=self.user.pk,
            story_hash=self.story.story_hash,
            story_guid=self.story.story_guid,
            story_feed_id=self.feed.pk,
            story_title=self.story.story_title,
        )
        self.assertEqual(len(self.run_filters("star:yes")), 1)
        self.assertEqual(self.run_filters("star:no"), [])

    def test_corrupt_body_is_treated_as_empty(self):
        broken = make_story(self.feed, "broken", "Broken body", body="valid")
        broken.story_content_z = b"not a zlib stream"
        broken.save(update_fields=["story_content_z"])
        self.assertEqual(broken.story_content_str, "")
        self.assertEqual(self.run_filters("body:tide", stories=[broken]), [])


class Test_FindStories(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("reader", "reader@example.com", "pw")
        self.feed = make_feed()
        self.match = make_story(self.feed, "aaa111", "Python 3.14 released", body="Fast")
        make_story(self.feed, "bbb222", "Rust 2.0 released", body="Also fast")

    def test_find_stories_uses_the_syntax(self):
        stories = Feed.find_stories(self.feed, "title:python", user=self.user)
        self.assertEqual([story["story_title"] for story in stories], [self.match.story_title])

    def test_body_search_uses_story_text(self):
        stories = Feed.find_stories(self.feed, "body:also", user=self.user)
        self.assertEqual([story["story_title"] for story in stories], ["Rust 2.0 released"])

    def test_without_a_user_it_falls_back_to_titles(self):
        stories = Feed.find_stories(self.feed, "python")
        self.assertEqual([story["story_title"] for story in stories], [self.match.story_title])

    def test_body_search_pages_count_matches_not_raw_rows(self):
        feed = make_feed("Paged", "http://paged.example.com/feed")
        make_story(feed, "p1", "match one", body="needle", days_ago=1)
        make_story(feed, "n1", "noise one", body="hay", days_ago=2)
        make_story(feed, "p2", "match two", body="needle", days_ago=3)
        make_story(feed, "n2", "noise two", body="hay", days_ago=4)
        make_story(feed, "p3", "match three", body="needle", days_ago=5)
        first = Feed.find_feed_stories([feed.pk], "body:needle", user=self.user, offset=0, limit=2)
        second = Feed.find_feed_stories([feed.pk], "body:needle", user=self.user, offset=2, limit=2)
        self.assertEqual([story["story_title"] for story in first], ["match one", "match two"])
        self.assertEqual([story["story_title"] for story in second], ["match three"])

    def test_invalid_date_returns_no_results(self):
        self.assertEqual(Feed.find_feed_stories([self.feed.pk], "date:someday", user=self.user), [])

    def test_truncated_search_reports_the_bound(self):
        parsed = search.parse("read:yes")
        with patch.object(search, "_read_hashes", return_value=set()):
            results = search.filter_story_queryset(
                MStory.objects.all(), parsed, self.user, "-story_date", limit=1, max_scan=1
            )
        self.assertEqual(results, [])
        self.assertTrue(results.truncated)
        self.assertEqual(results.scanned, 1)

    def test_collect_story_queryset_returns_every_match_in_order(self):
        feed = make_feed("Collected", "http://collected.example.com/feed")
        make_story(feed, "c1", "needle one", body="hay", days_ago=1)
        make_story(feed, "c2", "needle two", body="hay", days_ago=2)
        make_story(feed, "c3", "needle three", body="hay", days_ago=3)
        parsed = search.parse("title:needle")
        queryset = search.build_queryset(MStory.objects.filter(story_feed_id=feed.pk), parsed, self.user)

        stories = search.collect_story_queryset(queryset, parsed, self.user, "-story_date")

        self.assertEqual([story.story_title for story in stories], ["needle one", "needle two", "needle three"])

    def test_stable_ordering_adds_a_primary_key_tiebreaker(self):
        self.assertEqual(search._stable_ordering("-story_date"), ["-story_date", "-id"])
        self.assertEqual(search._stable_ordering("story_date"), ["story_date", "id"])
        self.assertEqual(search._stable_ordering(["-story_date", "id"]), ["-story_date", "id"])

    def test_backfill_command_fills_missing_story_text(self):
        MStory.objects.filter(pk=self.match.pk).update(story_text=None)
        call_command("backfill_story_text", "--batch-size", "1", stdout=StringIO())
        self.match.refresh_from_db()
        self.assertIn("Fast", self.match.story_text)
