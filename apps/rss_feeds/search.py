"""Search syntax for story search: title:, author:, body:, url:, tag:, feed:,
folder:, star:, read:, date:, quotes for phrases, and a leading - to negate.

Free words match titles and, when SEARCH_FREE_TEXT_INCLUDES_BODY is on, the plain
text in MStory.story_text. body: uses the same column, so PostgreSQL can answer it
with the trigram GIN index instead of decompressing every candidate row. read: is
still per-reader state in Redis and is applied to the fetched window; star: is an
EXISTS subquery over the reader's starred rows.
"""

import datetime
import re
import zlib

from django.conf import settings
from django.db.models import Exists, OuterRef, Q

from apps.rss_feeds.models import Feed, MStarredStory, MStory

TOKEN_RE = re.compile(r'(-?)([a-zA-Z_]+):("([^"]*)"|\S*)|(-?)"([^"]*)"|(-?)(\S+)')
KNOWN_FIELDS = {"title", "author", "body", "content", "url", "tag", "feed", "folder", "star", "read", "date"}
DATE_RANGES = {"today": 1, "week": 7, "month": 30, "year": 365}
TRUE_WORDS = {"yes", "true", "1", "on"}
FALSE_WORDS = {"no", "false", "0", "off"}
MAX_TERMS = 24
# read: is a Redis set, so it cannot be expressed in the SQL query. A page is
# built by scanning from the newest row and keeping only matches, so offset
# counts matches instead of raw rows. This bounds the work for a single request;
# body: no longer needs a scan because story_text is indexed.
MAX_POST_FILTER_SCAN = 5000


class SearchResults(list):
    """A page of stories plus whether the bounded post-filter scan stopped early."""

    truncated = False
    scanned = 0


class SearchError(ValueError):
    """A query the reader has to fix: an unknown operator or a bad value."""


class ParsedSearch:
    def __init__(self, raw):
        self.raw = raw
        self.terms = []
        self.negated_terms = []
        self.clauses = []
        self.post_filters = []
        self.errors = []

    def __bool__(self):
        return bool(self.terms or self.negated_terms or self.clauses or self.post_filters)

    @property
    def has_post_filters(self):
        return bool(self.post_filters)


def _add_term(parsed, term, negated):
    term = term.strip()
    if not term:
        return
    if len(parsed.terms) + len(parsed.negated_terms) >= MAX_TERMS:
        return
    (parsed.negated_terms if negated else parsed.terms).append(term)


def parse(raw):
    """Turns a query string into a ParsedSearch. Unknown operators stay free text."""
    parsed = ParsedSearch(raw or "")
    text = (raw or "").strip()
    if not text:
        return parsed

    for match in TOKEN_RE.finditer(text):
        negated_field, field, quoted_value, unquoted_value, negated_phrase, phrase, negated_word, word = match.groups()
        if field:
            field = field.lower()
            if quoted_value is not None and quoted_value.startswith('"'):
                value = unquoted_value
            else:
                value = quoted_value if quoted_value is not None else unquoted_value
            value = (value or "").strip()
            negated = bool(negated_field)
            if field not in KNOWN_FIELDS:
                # A colon inside a word ("http://...") is not an operator.
                _add_term(parsed, match.group(0).lstrip("-"), negated)
                continue
            if not value:
                parsed.errors.append('"%s:" needs a value.' % field)
                continue
            if field in ("body", "content"):
                parsed.post_filters.append(("body", value, negated))
            elif field in ("star", "read"):
                lowered = value.lower()
                if lowered in TRUE_WORDS:
                    parsed.post_filters.append((field, True, negated))
                elif lowered in FALSE_WORDS:
                    parsed.post_filters.append((field, False, negated))
                else:
                    parsed.errors.append('"%s:" takes yes or no.' % field)
            elif field == "date":
                # Validate here, before build_queryset. Callers check parsed.errors
                # before they build, so a bad date has to be visible at parse time.
                try:
                    _date_cutoff(value)
                except SearchError as e:
                    parsed.errors.append(str(e))
                    continue
                parsed.clauses.append(("date", value, negated))
            else:
                parsed.clauses.append((field, value, negated))
            continue
        if phrase is not None:
            _add_term(parsed, phrase, bool(negated_phrase))
        elif word:
            _add_term(parsed, word, bool(negated_word))

    return parsed


def _date_cutoff(value):
    lowered = value.lower()
    # USE_TZ is off and story_date is stored as naive UTC. Build the same clock
    # without datetime.utcnow(), which is deprecated in Python 3.12+.
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    if lowered in DATE_RANGES:
        return now - datetime.timedelta(days=DATE_RANGES[lowered])
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            start = datetime.datetime.strptime(value, fmt)
        except ValueError:
            continue
        if fmt == "%Y-%m":
            start = start.replace(day=1)
        if fmt == "%Y-%m-%d":
            return start
        return start
    raise SearchError('"date:" takes today, week, month, year, or a date like 2026-10-01.')


def _feed_ids_for_folder(user, folder):
    from apps.reader.models import UserSubscriptionFolders

    try:
        usf = UserSubscriptionFolders.objects.get(user=user)
    except UserSubscriptionFolders.DoesNotExist:
        return []
    flat = usf.flatten_folders()
    for title, feed_ids in flat.items():
        if (title or "").strip().lower() == folder.strip().lower():
            return list(feed_ids)
    return []


def build_queryset(queryset, parsed, user):
    """Applies the SQL-expressible parts of the query and returns the queryset."""
    include_body = getattr(settings, "SEARCH_FREE_TEXT_INCLUDES_BODY", True)
    for term in parsed.terms:
        condition = Q(story_title__icontains=term)
        if include_body:
            condition |= Q(story_text__icontains=term)
        queryset = queryset.filter(condition)
    for term in parsed.negated_terms:
        condition = Q(story_title__icontains=term)
        if include_body:
            condition |= Q(story_text__icontains=term)
        queryset = queryset.exclude(condition)

    # body: and star: can both be expressed in SQL now. Remove them from
    # post_filters once applied so apply_post_filters() does not run them twice.
    for field, value, negated in list(parsed.post_filters):
        if field == "body":
            condition = Q(story_text__icontains=value)
            queryset = queryset.exclude(condition) if negated else queryset.filter(condition)
            parsed.post_filters.remove((field, value, negated))
            continue
        if field != "star":
            continue
        starred = MStarredStory.objects.filter(user_id=user.pk, story_hash=OuterRef("story_hash"))
        condition = Exists(starred)
        wants_starred = bool(value) != bool(negated)
        queryset = queryset.filter(condition) if wants_starred else queryset.filter(~condition)
        parsed.post_filters.remove((field, value, negated))

    for field, value, negated in parsed.clauses:
        if field == "title":
            condition = Q(story_title__icontains=value)
        elif field == "author":
            condition = Q(story_author_name__icontains=value)
        elif field == "url":
            condition = Q(story_permalink__icontains=value)
        elif field == "feed":
            feed_ids = list(
                Feed.objects.filter(feed_title__icontains=value).values_list("pk", flat=True)[:200]
            )
            if value.isdigit():
                feed_ids.append(int(value))
            condition = Q(story_feed_id__in=feed_ids or [-1])
        elif field == "folder":
            condition = Q(story_feed_id__in=_feed_ids_for_folder(user, value) or [-1])
        elif field == "tag":
            from apps.reader.models import StoryTag

            tagged = StoryTag.objects.filter(
                user_id=user.pk,
                story_hash=OuterRef("story_hash"),
                tag=StoryTag.normalize(value),
            )
            condition = Exists(tagged)
            queryset = queryset.filter(~condition) if negated else queryset.filter(condition)
            continue
        elif field == "date":
            try:
                cutoff = _date_cutoff(value)
            except SearchError as e:
                parsed.errors.append(str(e))
                continue
            condition = Q(story_date__gte=cutoff)
        else:
            continue
        queryset = queryset.exclude(condition) if negated else queryset.filter(condition)

    return queryset


def _read_hashes(user):
    import redis
    from django.conf import settings

    r = redis.Redis(connection_pool=settings.REDIS_STORY_HASH_POOL)
    # Redis answers bytes; story_hash values from Postgres are str.
    return {
        value.decode("utf-8", "replace") if isinstance(value, bytes) else value
        for value in r.smembers("RS:%s" % user.pk)
    }


def _starred_hashes(user):
    return set(MStarredStory.objects.filter(user_id=user.pk).values_list("story_hash", flat=True))


def _post_filter_context(parsed, user):
    """Loads the per-reader sets once for a whole page, not once per story."""
    body_filters = [item for item in parsed.post_filters if item[0] == "body"]
    read_filters = [item for item in parsed.post_filters if item[0] == "read"]
    star_filters = [item for item in parsed.post_filters if item[0] == "star"]
    read_hashes = _read_hashes(user) if read_filters else set()
    starred_hashes = _starred_hashes(user) if star_filters else set()
    return body_filters, read_filters, star_filters, read_hashes, starred_hashes


def _matches_post_filters(story, body_filters, read_filters, star_filters, read_hashes, starred_hashes):
    story_hash = getattr(story, "story_hash", None)
    for _field, value, negated in read_filters:
        if (story_hash in read_hashes) != (value if not negated else not value):
            return False
    for _field, value, negated in star_filters:
        if (story_hash in starred_hashes) != (value if not negated else not value):
            return False
    if body_filters:
        # story_content_str already handles a missing or corrupt compressed body.
        try:
            body = story.story_content_str or ""
        except (zlib.error, TypeError, ValueError, AttributeError):
            body = ""
        lowered = body.lower()
        for _field, value, negated in body_filters:
            needle = value.lower()
            found = needle in lowered
            if found == negated:
                return False
    return True


def apply_post_filters(stories, parsed, user):
    """Filters an already fetched list on body text and read state."""
    if not parsed.post_filters:
        return stories
    context = _post_filter_context(parsed, user)
    return [story for story in stories if _matches_post_filters(story, *context)]


def _stable_ordering(ordering):
    """Append a primary-key tie-breaker so equal dates never swap between pages."""
    if isinstance(ordering, str):
        ordering = [ordering]
    ordering = list(ordering)
    if not any(field.lstrip("-") == "id" for field in ordering):
        ordering.append("-id" if ordering and ordering[0].startswith("-") else "id")
    return ordering


def collect_story_queryset(queryset, parsed, user, ordering):
    """Returns every matching story in ordering order, without a page slice.

    Used when the caller has to merge results from several batches before it can
    apply an offset, such as a read-history search that has to look past the
    1,000-entry lRS list. The caller owns any bound on the result size.
    """
    ordering = _stable_ordering(ordering)
    if user is None or not parsed.has_post_filters:
        return SearchResults(queryset.order_by(*ordering))

    context = _post_filter_context(parsed, user)
    matches = [
        story
        for story in queryset.order_by(*ordering).iterator(chunk_size=1000)
        if _matches_post_filters(story, *context)
    ]
    return SearchResults(matches)


def filter_story_queryset(queryset, parsed, user, ordering, offset=0, limit=25, max_scan=MAX_POST_FILTER_SCAN):
    """Returns one page of stories, with offset counted after post filters.

    A plain SQL slice counts rows before read: is applied. That makes page two
    skip matches and repeat rows that page one already showed. Scanning from the
    newest row and counting matches fixes the page boundary. The scan is bounded
    so one deep page cannot walk the whole table; SearchResults.truncated tells
    the caller when the bound stopped it early.
    """
    ordering = _stable_ordering(ordering)
    if limit <= 0:
        return SearchResults()
    # Without a reader there is no read state, and the caller already fell back
    # to a raw title match. Do not try to load per-reader sets with user=None.
    if user is None or not parsed.has_post_filters:
        results = SearchResults(queryset.order_by(*ordering)[offset : offset + limit])
        results.scanned = len(results)
        return results

    context = _post_filter_context(parsed, user)
    matches = []
    scanned = 0
    truncated = False
    chunk_size = max(limit * 4, 100)
    for story in queryset.order_by(*ordering).iterator(chunk_size=chunk_size):
        if scanned >= max_scan:
            truncated = True
            break
        scanned += 1
        if _matches_post_filters(story, *context):
            matches.append(story)
            if len(matches) >= offset + limit:
                break
    results = SearchResults(matches[offset : offset + limit])
    results.truncated = truncated
    results.scanned = scanned
    return results
