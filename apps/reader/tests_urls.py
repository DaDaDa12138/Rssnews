"""The generated route table has to cover every URL the reader's JavaScript calls.

base.html ships apps/reader/url_map.py as NEWSBLUR.URLs. A route that is renamed
in the URLconf but still spelled out in media/js fails silently in the browser,
so these tests compare the JavaScript call sites against the URLconf.
"""

import json
import re
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import NoReverseMatch, reverse

from apps.reader.url_map import PARAMETERIZED_ROUTES, build_url_map

JS_ROOT = Path(settings.BASE_DIR) / "media" / "js" / "newsblur"

# Both spellings the call sites use: NEWSBLUR.URLs['load-feeds'] and NEWSBLUR.URLs.domain.
BRACKET_REFERENCE_RE = re.compile(r"""NEWSBLUR\.URLs\[['"]([^'"]+)['"]\]""")
DOT_REFERENCE_RE = re.compile(r"NEWSBLUR\.URLs\.([A-Za-z_][A-Za-z0-9_]*)")

# A reader route spelled out as a string literal, e.g. '/reader/feeds'. Every one of
# these belongs in NEWSBLUR.URLs instead.
BARE_URL_RE = re.compile(r"""['"]/(?:reader|profile|rss_feeds|classifier|analyzer|import)/""")

# key: (route name, kwargs for reverse(), values for the {placeholders} in the map)
PARAMETERIZED_CASES = {
    "load-single-feed": ("load-single-feed", {"feed_id": 42}, {"feed_id": 42}),
    "load-feed-page": ("load-feed-page", {"feed_id": 42}, {"feed_id": 42}),
    "feed-info": ("feed-info", {"feed_id": 42}, {"feed_id": 42}),
    "feed-settings": ("feed-settings", {"feed_id": 42}, {"feed_id": 42}),
    "feed-statistics": ("feed-statistics", {"feed_id": 42}, {"feed_id": 42}),
    "feed-statistics-embedded": ("feed-statistics-embedded", {"feed_id": 42}, {"feed_id": 42}),
    # The map keeps the {id} spelling the reader's favicon code fills in.
    "favicon": ("feed-favicon", {"feed_id": 42}, {"id": 42}),
    # The map keeps {folder_title} for folders.js, but the route takes folder_slug.
    "folder_rss": (
        "folder-rss-feed",
        {"user_id": 1, "secret_token": "abc123", "unread_filter": "all", "folder_slug": "news"},
        {"user_id": 1, "secret_token": "abc123", "unread_filter": "all", "folder_title": "news"},
    ),
}


def javascript_sources():
    return sorted(JS_ROOT.rglob("*.js"))


class UrlMapTests(TestCase):
    def test_every_reference_exists_in_the_url_map(self):
        urls = build_url_map()
        # base.html adds the site domain next to the generated table.
        known = set(urls) | {"domain"}
        missing = {}
        for path in javascript_sources():
            source = path.read_text(encoding="utf-8")
            for name in BRACKET_REFERENCE_RE.findall(source) + DOT_REFERENCE_RE.findall(source):
                if name not in known:
                    missing.setdefault(name, set()).add(path.name)
        self.assertEqual(missing, {}, "JavaScript reads URL names the URLconf does not define")

    def test_javascript_spells_no_reader_url_itself(self):
        offenders = []
        for path in javascript_sources():
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if BARE_URL_RE.search(line):
                    offenders.append(f"{path.name}:{number}: {line.strip()}")
        self.assertEqual(offenders, [], "Spell these with NEWSBLUR.URLs instead")

    def test_parameterized_routes_match_the_urlconf(self):
        self.assertEqual(set(PARAMETERIZED_ROUTES), set(PARAMETERIZED_CASES))
        for key, (route_name, reverse_kwargs, placeholders) in PARAMETERIZED_CASES.items():
            with self.subTest(key):
                try:
                    reversed_path = reverse(route_name, kwargs=reverse_kwargs)
                except NoReverseMatch:
                    self.fail(f"PARAMETERIZED_ROUTES[{key!r}] points at a missing route")
                self.assertEqual(reversed_path, PARAMETERIZED_ROUTES[key].format(**placeholders))

    def test_map_values_are_absolute_paths(self):
        for key, path in build_url_map().items():
            with self.subTest(key):
                self.assertTrue(path.startswith("/"), f"{key} is not an absolute path: {path}")

    def test_base_template_ships_the_url_map(self):
        response = self.client.get("/account/login/")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        match = re.search(r'<script id="nb-urls" type="application/json">(.*?)</script>', html, re.S)
        self.assertIsNotNone(match, "base.html no longer embeds nb-urls")
        urls = json.loads(match.group(1))
        self.assertEqual(urls["load-feeds"], "/reader/feeds")
        self.assertEqual(urls["profile-set-preference"], "/profile/set_preference")
        self.assertIn("domain", urls)
