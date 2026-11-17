"""Tests for saved searches (apps/reader/views/saved_searches.py)."""

import datetime
import json
import zlib

from django.contrib.auth.models import User
from django.test import TestCase

from apps.reader.models import SavedSearch, UserSubscription
from apps.rss_feeds.models import Feed, MStory


def make_story(feed, suffix, title):
    return MStory.objects.create(
        story_feed_id=feed.pk,
        story_hash="%s:%s" % (feed.pk, suffix),
        story_guid="guid-%s" % suffix,
        story_title=title,
        story_permalink="https://example.com/%s" % suffix,
        story_content_z=zlib.compress(b"<p>body</p>"),
        story_date=datetime.datetime.utcnow(),
    )


def body_of(response):
    return json.loads(response.content)


class Test_SavedSearchViews(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("reader", "reader@example.com", "pw")
        self.feed = Feed.objects.create(
            feed_address="http://example.com/feed", feed_title="Example", feed_link="http://example.com"
        )
        UserSubscription.objects.create(user=self.user, feed=self.feed)
        make_story(self.feed, "aaa111", "Python 3.14 released")
        make_story(self.feed, "bbb222", "Rust 2.0 released")
        self.client.defaults["HTTP_USER_AGENT"] = "Mozilla/5.0 (X11; Linux x86_64) Chrome/126.0"
        self.client.force_login(self.user)

    def save(self, name="Python", query="title:python"):
        return body_of(self.client.post("/reader/save_saved_search", {"name": name, "query": query}))

    def test_save_and_load(self):
        payload = self.save()
        self.assertEqual(payload["code"], 0)
        self.assertTrue(payload["created"])
        loaded = body_of(self.client.get("/reader/saved_searches"))
        self.assertEqual([search["name"] for search in loaded["searches"]], ["Python"])

    def test_saving_the_same_name_updates_it(self):
        self.save()
        payload = self.save(query="title:rust")
        self.assertFalse(payload["created"])
        self.assertEqual(SavedSearch.objects.filter(user=self.user).count(), 1)
        self.assertEqual(SavedSearch.objects.get(user=self.user).query, "title:rust")

    def test_name_and_query_are_required(self):
        self.assertEqual(self.save(name="")["code"], -1)
        self.assertEqual(self.save(query="")["code"], -1)

    def test_bad_syntax_is_rejected(self):
        self.assertEqual(self.save(query="star:maybe")["code"], -1)

    def test_delete(self):
        saved_id = self.save()["search"]["id"]
        self.assertEqual(body_of(self.client.post("/reader/delete_saved_search", {"id": saved_id}))["code"], 0)
        self.assertEqual(SavedSearch.objects.count(), 0)

    def test_share_returns_a_token_url(self):
        saved_id = self.save()["search"]["id"]
        payload = body_of(self.client.post("/reader/share_saved_search", {"id": saved_id}))
        self.assertEqual(payload["code"], 0)
        self.assertIn("/reader/shared_search/", payload["url"])
        self.assertEqual(len(payload["search"]["share_token"]), 32)

    def test_shared_search_is_public(self):
        saved_id = self.save()["search"]["id"]
        token = body_of(self.client.post("/reader/share_saved_search", {"id": saved_id}))["search"][
            "share_token"
        ]
        self.client.logout()
        payload = body_of(self.client.get("/reader/shared_search/%s" % token))
        self.assertEqual(payload["code"], 0)
        self.assertEqual([story["story_title"] for story in payload["stories"]], ["Python 3.14 released"])

    def test_unknown_token(self):
        payload = body_of(self.client.get("/reader/shared_search/%s" % ("0" * 32)))
        self.assertEqual(payload["code"], -1)