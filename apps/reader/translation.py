"""One-click translation of story titles and paragraphs.

The reader posts batches of plain text and this module hides which upstream does the
work. Two are supported:

* DLX (the newsblur_deeplx sidecar) speaks the DeepLX wire format and translates a
  whole batch per call. DeepL rate limits the anonymous endpoint per IP range, so on a
  blocked network every call comes back 429.
* Bing's web translator is the fallback. It needs an IG/IID pair and an abuse token
  scraped from the translator page, and translates one string per call, but it answers
  from networks DeepL refuses.

TRANSLATE_PROVIDER picks one: deeplx, bing, or auto (try DLX, fall back to Bing, and
stop asking DLX for 15 minutes after a rate limit).

The view in apps/reader/views/translate.py only validates the request; splitting,
caching, retrying and rate limiting all live here.
"""

import hashlib
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from django.conf import settings
from django.core.cache import cache

from apps.reader.models import TranslationCache

logger = logging.getLogger(__name__)

BING_PAGE_URL = "https://www.bing.com/translator"
BING_TRANSLATE_URL = "https://www.bing.com/ttranslatev3"
BING_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
BING_CONCURRENCY = 6
BING_CREDENTIALS_CACHE_KEY = "translate-bing-credentials"
BING_CREDENTIALS_TTL = 45 * 60
DEEPLX_BREAKER_CACHE_KEY = "translate-deeplx-breaker"
DEEPLX_BREAKER_TTL = 15 * 60
BUDGET_CACHE_PREFIX = "translate-budget"

# Characters one upstream call may carry. DLX documents 1500 UTF-16 units per anonymous
# request; Bing's web endpoint starts answering 400 at 1200, so both stay below their
# own ceiling with room for the separator added when joining paragraphs.
PROVIDER_MAX_CHARS = {"deeplx": 1400, "bing": 1000}

SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?\u3002\uff01\uff1f\uff1b;\n])\s*")
WHITESPACE = re.compile(r"\s+")


class TranslationError(Exception):
    """An upstream refused or failed; the message is safe to show to the reader."""

    def __init__(self, message, code=502):
        super().__init__(message)
        self.message = message
        self.code = code


def utf16_length(text):
    """Length in UTF-16 code units, which is how the upstreams count characters."""
    return len(text.encode("utf-16-le")) // 2


def normalize_text(text):
    """Collapse the whitespace feeds love to leave behind so caching actually hits."""
    return WHITESPACE.sub(" ", text or "").strip()


def split_text(text, limit):
    """Cut one string into pieces no longer than limit UTF-16 units.

    Splitting prefers sentence boundaries so a piece never ends mid sentence, and falls
    back to a hard cut only for a single sentence that is longer than the whole limit.
    """
    if utf16_length(text) <= limit:
        return [text]

    pieces, current = [], ""
    for sentence in SENTENCE_BOUNDARY.split(text):
        if not sentence:
            continue
        if utf16_length(sentence) > limit:
            if current:
                pieces.append(current)
                current = ""
            # A single sentence longer than the limit: cut it on character boundaries,
            # which can only undershoot the UTF-16 limit, never overshoot it.
            for start in range(0, len(sentence), limit):
                pieces.append(sentence[start : start + limit])
            continue
        candidate = f"{current} {sentence}".strip() if current else sentence
        if utf16_length(candidate) > limit:
            pieces.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        pieces.append(current)
    return [piece for piece in pieces if piece]


def chunk_texts(units, limit):
    """Group (index, position, text) units into batches under limit UTF-16 units."""
    chunks, current, current_length = [], [], 0
    for unit in units:
        size = utf16_length(unit[2])
        if current and current_length + size > limit:
            chunks.append(current)
            current, current_length = [], 0
        current.append(unit)
        current_length += size
    if current:
        chunks.append(current)
    return chunks


def text_hash(text, target_lang):
    return hashlib.sha256(f"{target_lang}\n{text}".encode("utf-8")).hexdigest()


def translate_texts(texts, target_lang=None):
    """Translate plain strings, returning one entry per input in the same order.

    Returns {"translations": [...], "source_lang": "en", "provider": "bing"}.
    Raises TranslationError when nothing could be translated.
    """
    if not getattr(settings, "TRANSLATE_ENABLED", False):
        raise TranslationError("translation is disabled", code=400)

    target = (target_lang or settings.TRANSLATE_TARGET_LANG or "ZH").upper()
    normalized = [normalize_text(text) for text in texts]
    translations = [""] * len(normalized)
    pending = [(index, text) for index, text in enumerate(normalized) if text]
    if not pending:
        return {"translations": translations, "source_lang": "", "provider": "cache"}

    hashes = {index: text_hash(text, target) for index, text in pending}
    cached = {
        row.text_hash: row
        for row in TranslationCache.objects.filter(
            text_hash__in=set(hashes.values()), target_lang=target
        )
    }
    misses, source_langs = [], set()
    for index, text in pending:
        row = cached.get(hashes[index])
        if row is None:
            misses.append((index, text))
        else:
            translations[index] = row.translation
            if row.source_lang:
                source_langs.add(row.source_lang)

    provider = "cache"
    source_lang = _pick_source_lang(source_langs)
    if misses:
        _check_budget(len(misses))
        fresh, source_lang, provider = _translate_misses(misses, target)
        rows = []
        for index, text in misses:
            translation = fresh.get(index, "")
            translations[index] = translation
            if not translation or translation == text:
                # Same language in, same language out: caching it would only waste a row.
                continue
            rows.append(
                TranslationCache(
                    text_hash=hashes[index],
                    target_lang=target,
                    source_lang=source_lang,
                    translation=translation,
                )
            )
        if rows:
            TranslationCache.objects.bulk_create(rows, ignore_conflicts=True)

    return {"translations": translations, "source_lang": source_lang, "provider": provider}


def _translate_misses(misses, target):
    provider = _resolve_provider()
    if provider == "deeplx":
        try:
            translations, source_lang = _translate_with_deeplx(misses, target)
        except TranslationError as error:
            if _configured_provider() != "auto":
                raise
            logger.warning("translation: DLX failed (%s), falling back to Bing", error.message)
            _trip_deeplx_breaker()
            translations, source_lang = _translate_with_bing(misses, target)
            provider = "bing"
    else:
        translations, source_lang = _translate_with_bing(misses, target)
    return translations, source_lang, provider


def _configured_provider():
    return (getattr(settings, "TRANSLATE_PROVIDER", "auto") or "auto").strip().lower()


def _resolve_provider():
    configured = _configured_provider()
    if configured == "auto":
        return "bing" if cache.get(DEEPLX_BREAKER_CACHE_KEY) else "deeplx"
    if configured not in PROVIDER_MAX_CHARS:
        raise TranslationError(f"unknown translation provider: {configured}", code=500)
    return configured


def _trip_deeplx_breaker():
    cache.set(DEEPLX_BREAKER_CACHE_KEY, 1, DEEPLX_BREAKER_TTL)


def _check_budget(call_count):
    """Cap upstream traffic so one impatient reader cannot get the IP blocked."""
    limit = getattr(settings, "TRANSLATE_CALLS_PER_MINUTE", 0)
    if not limit:
        return
    bucket = f"{BUDGET_CACHE_PREFIX}:{time.strftime('%Y%m%d%H%M')}"
    try:
        used = cache.incr(bucket, call_count)
    except ValueError:
        cache.set(bucket, call_count, 120)
        used = call_count
    if used > limit:
        raise TranslationError("translation is busy, try again in a minute", code=429)


def _timeout():
    return getattr(settings, "TRANSLATE_TIMEOUT", 25)


def _translate_with_deeplx(misses, target):
    units = []
    for index, text in misses:
        for position, piece in enumerate(split_text(text, PROVIDER_MAX_CHARS["deeplx"])):
            units.append((index, position, piece))

    collected = {index: {} for index, _ in misses}
    source_lang = ""
    for chunk in chunk_texts(units, PROVIDER_MAX_CHARS["deeplx"]):
        translated, detected = _call_deeplx([unit[2] for unit in chunk], target)
        if detected:
            source_lang = detected
        for (index, position, _), translation in zip(chunk, translated):
            collected[index][position] = translation
    return _join_units(collected), source_lang


def _call_deeplx(texts, target):
    headers = {"Content-Type": "application/json"}
    token = getattr(settings, "TRANSLATE_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = requests.post(
            settings.TRANSLATE_ENDPOINT,
            json={"text": texts, "source_lang": "auto", "target_lang": target},
            headers=headers,
            timeout=_timeout(),
        )
    except requests.RequestException as error:
        raise TranslationError(f"DLX is unreachable: {error}")

    if response.status_code == 429:
        raise TranslationError("DLX is rate limited", code=429)
    if response.status_code != 200:
        raise TranslationError(f"DLX returned {response.status_code}", code=response.status_code)
    try:
        payload = response.json()
    except ValueError:
        raise TranslationError("DLX returned malformed JSON")
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list) or len(data) != len(texts):
        raise TranslationError("DLX returned an unexpected payload")
    if not all(isinstance(item, str) for item in data):
        raise TranslationError("DLX returned an unexpected payload")
    detected = payload.get("source_lang") if isinstance(payload, dict) else ""
    return data, str(detected or "")


def _translate_with_bing(misses, target):
    credentials = _bing_credentials()
    units = []
    for index, text in misses:
        for position, piece in enumerate(split_text(text, PROVIDER_MAX_CHARS["bing"])):
            units.append((index, position, piece))

    collected = {index: {} for index, _ in misses}
    detected_langs, failures = set(), 0
    with ThreadPoolExecutor(max_workers=BING_CONCURRENCY) as pool:
        futures = {
            pool.submit(_call_bing_one, piece, target, credentials): (index, position)
            for index, position, piece in units
        }
        for future in as_completed(futures):
            index, position = futures[future]
            try:
                translation, detected = future.result()
            except TranslationError as error:
                failures += 1
                logger.warning("translation: Bing failed for one segment: %s", error.message)
                continue
            collected[index][position] = translation
            if detected:
                detected_langs.add(detected)

    if units and failures == len(units):
        raise TranslationError("Bing could not translate this story")
    return _join_units(collected), _pick_source_lang(detected_langs)


def _call_bing_one(text, target, credentials):
    url = (
        f"{BING_TRANSLATE_URL}?isVertical=1"
        f"&IG={credentials['ig']}&IID={credentials['iid']}"
    )
    try:
        response = requests.post(
            url,
            data={
                "fromLang": "auto-detect",
                "to": _bing_target(target),
                "text": text,
                "token": credentials["token"],
                "key": credentials["key"],
            },
            headers={"User-Agent": BING_USER_AGENT, "Referer": BING_PAGE_URL},
            timeout=_timeout(),
        )
    except requests.RequestException as error:
        raise TranslationError(f"Bing is unreachable: {error}")

    if response.status_code != 200:
        raise TranslationError(f"Bing returned {response.status_code}", code=response.status_code)
    try:
        payload = response.json()
    except ValueError:
        raise TranslationError("Bing returned malformed JSON")
    if isinstance(payload, dict):
        reason = payload.get("errorMessage") or payload.get("statusCode") or "unknown error"
        raise TranslationError(f"Bing refused the request: {reason}")
    try:
        item = payload[0]
        translation = item["translations"][0]["text"]
    except (IndexError, KeyError, TypeError):
        raise TranslationError("Bing returned an unexpected payload")
    detected = (item.get("detectedLanguage") or {}).get("language", "")
    return translation, str(detected or "")


def _bing_target(target):
    """Bing spells Chinese as zh-Hans; every other code it takes as-is."""
    return "zh-Hans" if target.upper().startswith("ZH") else target


def _bing_credentials():
    credentials = cache.get(BING_CREDENTIALS_CACHE_KEY)
    if credentials:
        return credentials

    try:
        response = requests.get(
            BING_PAGE_URL, headers={"User-Agent": BING_USER_AGENT}, timeout=_timeout()
        )
    except requests.RequestException as error:
        raise TranslationError(f"Bing is unreachable: {error}")
    if response.status_code != 200:
        raise TranslationError(f"Bing returned {response.status_code}", code=response.status_code)

    html = response.text
    ig = re.search(r'IG:"([0-9A-Fa-f]+)"', html)
    iid = re.search(r'data-iid="([^"]+)"', html)
    helper = re.search(r"params_AbusePreventionHelper\s*=\s*\[([^\]]+)\]", html)
    if not (ig and iid and helper):
        raise TranslationError("Bing did not hand out a translation token")
    parts = [part.strip().strip('"') for part in helper.group(1).split(",")]
    if len(parts) < 2:
        raise TranslationError("Bing did not hand out a translation token")

    credentials = {"ig": ig.group(1), "iid": iid.group(1), "key": parts[0], "token": parts[1]}
    cache.set(BING_CREDENTIALS_CACHE_KEY, credentials, BING_CREDENTIALS_TTL)
    return credentials


def _join_units(collected):
    translations = {}
    for index, positions in collected.items():
        ordered = [positions[position] for position in sorted(positions)]
        translations[index] = " ".join(ordered).strip()
    return translations


def _pick_source_lang(languages):
    """One detected language is informative; a mixed batch tells the reader nothing."""
    languages = {language for language in languages if language}
    if len(languages) == 1:
        return languages.pop()
    return ""
