"""Tests for one-click translation (apps/reader/translation.py and its view).

Every upstream call is mocked: these tests must pass on a network where DeepL blocks the
IP and Bing is unreachable, and a stray real request would poison the shared cache with
whatever the machine's exit node happened to return.

apps/reader/tests_translate.py
"""

import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.reader import translation
from apps.reader.models import TranslationCache

BING_PAGE = (
    '<html><script>IG:"1A2B3C4D"</script>'
    '<div data-iid="translator.5024"></div>'
    "<script>params_AbusePreventionHelper = [1720000000000,\"TOKEN\",3600000];</script></html>"
)


class FakeResponse:
    """The three attributes the translation module reads off a requests response."""

    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload


def bing_payload(text, language="en"):
    return [{"translations": [{"text": f"zh:{text}"}], "detectedLanguage": {"language": language}}]


def body_of(response):
    """The project's json_view answers text/json, which Django's response.json rejects."""
    return json.loads(response.content)


def reset_translation_state():
    cache.delete_many(
        [translation.DEEPLX_BREAKER_CACHE_KEY, translation.BING_CREDENTIALS_CACHE_KEY]
    )


class Test_Translation_Splitting(TestCase):
    def test_short_text_is_one_piece(self):
        self.assertEqual(translation.split_text("hello", 100), ["hello"])

    def test_sentences_are_kept_whole(self):
        text = ("One sentence here. " * 20).strip()
        pieces = translation.split_text(text, 100)

        self.assertTrue(all(translation.utf16_length(piece) <= 100 for piece in pieces))
        self.assertTrue(all(piece.endswith(".") for piece in pieces))
        self.assertEqual(" ".join(pieces).split(), text.split())

    def test_a_sentence_longer_than_the_limit_is_hard_cut(self):
        pieces = translation.split_text("x" * 250, 100)

        self.assertEqual([len(piece) for piece in pieces], [100, 100, 50])

    def test_utf16_length_counts_astral_characters_twice(self):
        self.assertEqual(translation.utf16_length("\U0001F600"), 2)
        self.assertEqual(translation.utf16_length("a"), 1)

    def test_chunks_stay_under_the_limit_and_keep_order(self):
        units = [(index, 0, "a" * 60) for index in range(10)]
        chunks = translation.chunk_texts(units, 100)

        self.assertTrue(
            all(sum(translation.utf16_length(unit[2]) for unit in chunk) <= 100 for chunk in chunks)
        )
        self.assertEqual([unit[0] for chunk in chunks for unit in chunk], list(range(10)))

    def test_normalize_collapses_whitespace(self):
        self.assertEqual(translation.normalize_text("  a \n\t b  "), "a b")


@override_settings(
    TRANSLATE_ENABLED=True,
    TRANSLATE_PROVIDER="bing",
    TRANSLATE_TARGET_LANG="ZH",
    TRANSLATE_CALLS_PER_MINUTE=0,
)
class Test_Translation_Service(TestCase):
    def setUp(self):
        reset_translation_state()
        TranslationCache.objects.all().delete()

    @patch("apps.reader.translation.requests.get")
    @patch("apps.reader.translation.requests.post")
    def test_bing_translates_each_string_and_caches_it(self, post, get):
        get.return_value = FakeResponse(text=BING_PAGE)
        post.side_effect = lambda url, data=None, **kwargs: FakeResponse(
            payload=bing_payload(data["text"])
        )

        result = translation.translate_texts(["Hello", "Goodbye"])

        self.assertEqual(result["translations"], ["zh:Hello", "zh:Goodbye"])
        self.assertEqual(result["source_lang"], "en")
        self.assertEqual(result["provider"], "bing")
        self.assertEqual(post.call_count, 2)
        self.assertEqual(TranslationCache.objects.count(), 2)

        again = translation.translate_texts(["Hello", "Goodbye"])

        self.assertEqual(again["translations"], ["zh:Hello", "zh:Goodbye"])
        self.assertEqual(again["provider"], "cache")
        self.assertEqual(post.call_count, 2)

    @override_settings(TRANSLATE_PROVIDER="deeplx", TRANSLATE_ENDPOINT="http://dlx.test/translate")
    @patch("apps.reader.translation.requests.post")
    def test_deeplx_translates_a_batch_in_one_call(self, post):
        post.return_value = FakeResponse(payload={"data": ["ni hao", "zai jian"], "source_lang": "EN"})

        result = translation.translate_texts(["Hello", "Bye"])

        self.assertEqual(result["translations"], ["ni hao", "zai jian"])
        self.assertEqual(result["source_lang"], "EN")
        self.assertEqual(result["provider"], "deeplx")
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.kwargs["json"]["target_lang"], "ZH")

    @override_settings(TRANSLATE_PROVIDER="deeplx", TRANSLATE_ENDPOINT="http://dlx.test/translate")
    @patch("apps.reader.translation.requests.post")
    def test_deeplx_rate_limit_surfaces_as_a_translation_error(self, post):
        post.return_value = FakeResponse(429, {"code": 429, "message": "blocked"})

        with self.assertRaises(translation.TranslationError) as raised:
            translation.translate_texts(["Hello"])

        self.assertEqual(raised.exception.code, 429)

    @override_settings(TRANSLATE_PROVIDER="auto", TRANSLATE_ENDPOINT="http://dlx.test/translate")
    @patch("apps.reader.translation.requests.get")
    @patch("apps.reader.translation.requests.post")
    def test_auto_falls_back_to_bing_and_trips_the_breaker(self, post, get):
        get.return_value = FakeResponse(text=BING_PAGE)
        calls = []

        def fake_post(url, data=None, json=None, **kwargs):
            if json is not None:
                calls.append("deeplx")
                return FakeResponse(429, {"code": 429, "message": "blocked"})
            calls.append("bing")
            return FakeResponse(payload=bing_payload(data["text"]))

        post.side_effect = fake_post

        result = translation.translate_texts(["Hello"])

        self.assertEqual(calls, ["deeplx", "bing"])
        self.assertEqual(result["provider"], "bing")
        self.assertTrue(cache.get(translation.DEEPLX_BREAKER_CACHE_KEY))

        translation.translate_texts(["Another headline"])

        # The breaker keeps the next batch off DLX entirely.
        self.assertEqual(calls, ["deeplx", "bing", "bing"])

    @patch("apps.reader.translation.requests.get")
    @patch("apps.reader.translation.requests.post")
    def test_same_language_is_returned_unchanged_and_not_cached(self, post, get):
        get.return_value = FakeResponse(text=BING_PAGE)
        post.side_effect = lambda url, data=None, **kwargs: FakeResponse(
            payload=[{"translations": [{"text": data["text"]}], "detectedLanguage": {"language": "zh-Hans"}}]
        )

        result = translation.translate_texts(["中文标题"])

        self.assertEqual(result["translations"], ["中文标题"])
        self.assertEqual(result["source_lang"], "zh-Hans")
        self.assertEqual(TranslationCache.objects.count(), 0)

    @patch("apps.reader.translation.requests.get")
    @patch("apps.reader.translation.requests.post")
    def test_a_total_upstream_failure_raises(self, post, get):
        get.return_value = FakeResponse(text=BING_PAGE)
        post.return_value = FakeResponse(500, None)

        with self.assertRaises(translation.TranslationError):
            translation.translate_texts(["Hello"])

    @override_settings(TRANSLATE_CALLS_PER_MINUTE=1)
    @patch("apps.reader.translation.requests.get")
    @patch("apps.reader.translation.requests.post")
    def test_the_minute_budget_stops_a_batch_that_is_too_large(self, post, get):
        get.return_value = FakeResponse(text=BING_PAGE)
        post.side_effect = lambda url, data=None, **kwargs: FakeResponse(
            payload=bing_payload(data["text"])
        )

        with self.assertRaises(translation.TranslationError) as raised:
            translation.translate_texts(["One", "Two", "Three"])

        self.assertEqual(raised.exception.code, 429)
        self.assertEqual(post.call_count, 0)

    @override_settings(TRANSLATE_ENABLED=False)
    def test_disabled_translation_refuses_to_call_out(self):
        with self.assertRaises(translation.TranslationError):
            translation.translate_texts(["Hello"])


@override_settings(
    TRANSLATE_ENABLED=True,
    TRANSLATE_PROVIDER="bing",
    TRANSLATE_TARGET_LANG="ZH",
    TRANSLATE_CALLS_PER_MINUTE=0,
)
class Test_Translate_View(TestCase):
    def setUp(self):
        reset_translation_state()
        TranslationCache.objects.all().delete()
        self.user = User.objects.create_user("reader", "reader@example.com", "secret")
        self.client.force_login(self.user)
        # UserAgentBanMiddleware answers 403 to a request with no user agent.
        self.client.defaults["HTTP_USER_AGENT"] = "Mozilla/5.0 (X11; Linux x86_64) Chrome/126.0"

    def post_json(self, payload):
        return self.client.post(
            "/reader/translate", data=json.dumps(payload), content_type="application/json"
        )

    @patch("apps.reader.translation.requests.get")
    @patch("apps.reader.translation.requests.post")
    def test_translates_a_batch(self, post, get):
        get.return_value = FakeResponse(text=BING_PAGE)
        post.side_effect = lambda url, data=None, **kwargs: FakeResponse(
            payload=bing_payload(data["text"])
        )

        body = body_of(self.post_json({"texts": ["Hello", "World"]}))

        self.assertEqual(body["code"], 0)
        self.assertEqual(body["translations"], ["zh:Hello", "zh:World"])
        self.assertEqual(body["provider"], "bing")

    def test_get_is_refused(self):
        body = body_of(self.client.get("/reader/translate"))

        self.assertEqual(body["code"], -1)
        self.assertIn("POST", body["message"])

    def test_anonymous_callers_are_refused(self):
        self.client.logout()

        response = self.post_json({"texts": ["Hello"]})

        self.assertEqual(response.status_code, 403)

    def test_empty_text_list_is_refused(self):
        body = body_of(self.post_json({"texts": []}))

        self.assertEqual(body["code"], -1)

    def test_malformed_body_is_refused(self):
        response = self.client.post(
            "/reader/translate", data="not json", content_type="application/json"
        )

        self.assertEqual(body_of(response)["code"], -1)

    @override_settings(TRANSLATE_MAX_TEXTS=2)
    def test_too_many_texts_are_refused(self):
        body = body_of(self.post_json({"texts": ["a", "b", "c"]}))

        self.assertEqual(body["code"], -1)
        self.assertIn("2", body["message"])

    @override_settings(TRANSLATE_MAX_REQUEST_CHARS=10)
    def test_an_oversized_request_is_refused(self):
        body = body_of(self.post_json({"texts": ["x" * 20]}))

        self.assertEqual(body["code"], -1)
        self.assertIn("too large", body["message"])

    @patch("apps.reader.translation.requests.get")
    @patch("apps.reader.translation.requests.post")
    def test_an_upstream_failure_reports_its_code(self, post, get):
        get.return_value = FakeResponse(text=BING_PAGE)
        post.return_value = FakeResponse(503, None)

        body = body_of(self.post_json({"texts": ["Hello"]}))

        self.assertEqual(body["code"], 502)
