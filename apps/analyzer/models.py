"""Intelligence classifier models stored in MongoDB.

Per-user classifiers (MClassifierTitle, MClassifierAuthor, MClassifierTag,
MClassifierFeed, MClassifierText, MClassifierUrl) that score stories as liked
(+1), neutral (0), or disliked (-1).
"""

import re
import threading
import unicodedata
from collections import defaultdict

from django.contrib.auth.models import User
from django.db import models

from apps.rss_feeds.models import Feed
from utils.documents import LegacyDocument
from utils.story_functions import strip_tags

# Regex timeout in seconds to prevent ReDoS attacks
REGEX_TIMEOUT = 0.1  # 100ms


def validate_regex_pattern(pattern):
    """
    Validate a regex pattern.
    Returns (is_valid, error_message).
    """
    try:
        re.compile(pattern)
        return True, None
    except re.error as e:
        return False, str(e)


def safe_regex_match(pattern, text, timeout=REGEX_TIMEOUT):
    """
    Safely perform regex matching with timeout protection.
    Returns True if pattern matches, False otherwise.
    Uses threading-based timeout (works on all platforms).
    """
    result = [False]
    exception = [None]

    def do_match():
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
            if compiled.search(text):
                result[0] = True
        except Exception as e:
            exception[0] = e

    thread = threading.Thread(target=do_match)
    thread.daemon = True
    thread.start()
    thread.join(timeout)

    if thread.is_alive():
        # Thread is still running, regex timed out
        return False

    if exception[0]:
        # Regex raised an exception
        return False

    return result[0]


class FeatureCategory(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    feed = models.ForeignKey(Feed, on_delete=models.CASCADE)
    feature = models.CharField(max_length=255)
    category = models.CharField(max_length=255)
    count = models.IntegerField(default=0)

    def __str__(self):
        return "%s - %s (%s)" % (self.feature, self.category, self.count)


class Category(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    feed = models.ForeignKey(Feed, on_delete=models.CASCADE)
    category = models.CharField(max_length=255)
    count = models.IntegerField(default=0)

    def __str__(self):
        return "%s (%s)" % (self.category, self.count)



class MClassifierTitle(LegacyDocument):
    user_id = models.IntegerField(null=True, blank=True)
    feed_id = models.IntegerField(null=True, blank=True)
    social_user_id = models.IntegerField(null=True, blank=True)
    title = models.CharField(max_length=255, null=True, blank=True)
    score = models.IntegerField(null=True, blank=True)
    is_regex = models.BooleanField(default=False)
    scope = models.TextField(default='feed', null=True, blank=True)
    folder_name = models.TextField(default='', null=True, blank=True)
    creation_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "classifier_title"
        indexes = [
            models.Index(fields=['user_id', 'feed_id']),
            models.Index(fields=['feed_id']),
            models.Index(fields=['user_id', 'social_user_id']),
            models.Index(fields=['social_user_id']),
            models.Index(fields=['is_regex']),
            models.Index(fields=['scope']),
            models.Index(fields=['user_id', 'scope', 'folder_name']),
        ]

    def __str__(self):
        user = User.objects.get(pk=self.user_id)
        regex_indicator = " [regex]" if self.is_regex else ""
        return "%s - %s/%s: (%s) %s%s" % (
            user,
            self.feed_id,
            self.social_user_id,
            self.score,
            self.title[:30],
            regex_indicator,
        )


class MClassifierUrl(LegacyDocument):
    user_id = models.IntegerField(null=True, blank=True)
    feed_id = models.IntegerField(null=True, blank=True)
    social_user_id = models.IntegerField(null=True, blank=True)
    url = models.CharField(max_length=2048, null=True, blank=True)
    score = models.IntegerField(null=True, blank=True)
    is_regex = models.BooleanField(default=False)
    scope = models.TextField(default='feed', null=True, blank=True)
    folder_name = models.TextField(default='', null=True, blank=True)
    creation_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "classifier_url"
        indexes = [
            models.Index(fields=['user_id', 'feed_id']),
            models.Index(fields=['feed_id']),
            models.Index(fields=['user_id', 'social_user_id']),
            models.Index(fields=['social_user_id']),
            models.Index(fields=['is_regex']),
            models.Index(fields=['scope']),
            models.Index(fields=['user_id', 'scope', 'folder_name']),
        ]

    def __str__(self):
        user = User.objects.get(pk=self.user_id)
        regex_indicator = " [regex]" if self.is_regex else ""
        return "%s - %s/%s: (%s) %s%s" % (
            user,
            self.feed_id,
            self.social_user_id,
            self.score,
            self.url[:50],
            regex_indicator,
        )


class MClassifierText(LegacyDocument):
    user_id = models.IntegerField(null=True, blank=True)
    feed_id = models.IntegerField(null=True, blank=True)
    social_user_id = models.IntegerField(null=True, blank=True)
    text = models.CharField(max_length=255, null=True, blank=True)
    score = models.IntegerField(null=True, blank=True)
    is_regex = models.BooleanField(default=False)
    scope = models.TextField(default='feed', null=True, blank=True)
    folder_name = models.TextField(default='', null=True, blank=True)
    creation_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "classifier_text"
        indexes = [
            models.Index(fields=['user_id', 'feed_id']),
            models.Index(fields=['feed_id']),
            models.Index(fields=['user_id', 'social_user_id']),
            models.Index(fields=['social_user_id']),
            models.Index(fields=['is_regex']),
            models.Index(fields=['scope']),
            models.Index(fields=['user_id', 'scope', 'folder_name']),
        ]

    def __str__(self):
        user = User.objects.get(pk=self.user_id)
        regex_indicator = " [regex]" if self.is_regex else ""
        return "%s - %s/%s: (%s) %s%s" % (
            user,
            self.feed_id,
            self.social_user_id,
            self.score,
            self.text[:30],
            regex_indicator,
        )


class MClassifierAuthor(LegacyDocument):
    user_id = models.IntegerField(null=True, blank=True)
    feed_id = models.IntegerField(null=True, blank=True)
    social_user_id = models.IntegerField(null=True, blank=True)
    author = models.CharField(max_length=255, null=True, blank=True)
    score = models.IntegerField(null=True, blank=True)
    is_regex = models.BooleanField(default=False)
    scope = models.TextField(default='feed', null=True, blank=True)
    folder_name = models.TextField(default='', null=True, blank=True)
    creation_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "classifier_author"
        indexes = [
            models.Index(fields=['user_id', 'feed_id']),
            models.Index(fields=['feed_id']),
            models.Index(fields=['user_id', 'social_user_id']),
            models.Index(fields=['social_user_id']),
            models.Index(fields=['is_regex']),
            models.Index(fields=['scope']),
            models.Index(fields=['user_id', 'scope', 'folder_name']),
        ]

    def __str__(self):
        user = User.objects.get(pk=self.user_id)
        regex_indicator = " [regex]" if self.is_regex else ""
        return "%s - %s/%s: (%s) %s%s" % (
            user,
            self.feed_id,
            self.social_user_id,
            self.score,
            self.author[:30],
            regex_indicator,
        )


class MClassifierTag(LegacyDocument):
    user_id = models.IntegerField(null=True, blank=True)
    feed_id = models.IntegerField(null=True, blank=True)
    social_user_id = models.IntegerField(null=True, blank=True)
    tag = models.CharField(max_length=255, null=True, blank=True)
    score = models.IntegerField(null=True, blank=True)
    scope = models.TextField(default='feed', null=True, blank=True)
    folder_name = models.TextField(default='', null=True, blank=True)
    creation_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "classifier_tag"
        indexes = [
            models.Index(fields=['user_id', 'feed_id']),
            models.Index(fields=['feed_id']),
            models.Index(fields=['user_id', 'social_user_id']),
            models.Index(fields=['social_user_id']),
            models.Index(fields=['scope']),
            models.Index(fields=['user_id', 'scope', 'folder_name']),
        ]
        unique_together = (('user_id', 'feed_id', 'social_user_id', 'tag'),)

    def __str__(self):
        user = User.objects.get(pk=self.user_id)
        return "%s - %s/%s: (%s) %s" % (user, self.feed_id, self.social_user_id, self.score, self.tag[:30])


class MClassifierFeed(LegacyDocument):
    user_id = models.IntegerField(null=True, blank=True)
    feed_id = models.IntegerField(null=True, blank=True)
    social_user_id = models.IntegerField(null=True, blank=True)
    score = models.IntegerField(null=True, blank=True)
    creation_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "classifier_feed"
        indexes = [
            models.Index(fields=['user_id', 'feed_id']),
            models.Index(fields=['feed_id']),
            models.Index(fields=['user_id', 'social_user_id']),
            models.Index(fields=['social_user_id']),
        ]
        unique_together = (('user_id', 'feed_id', 'social_user_id'),)

    def __str__(self):
        user = User.objects.get(pk=self.user_id)
        if self.feed_id:
            feed = Feed.get_by_id(self.feed_id)
        else:
            feed = User.objects.get(pk=self.social_user_id)
        return "%s - %s/%s: (%s) %s" % (user, self.feed_id, self.social_user_id, self.score, feed)


def classifier_matches_story_feed(classifier, story_feed_id, folder_feed_ids=None):
    """Check if a classifier applies to a story based on its scope.

    Args:
        classifier: A classifier object with feed_id and optional scope/folder_name
        story_feed_id: The feed_id of the story being scored
        folder_feed_ids: Dict mapping folder_name -> set of feed_ids for folder-scoped classifiers

    Returns:
        True if the classifier applies to this story's feed
    """
    scope = getattr(classifier, "scope", "feed")
    if scope == "global":
        return True
    if scope == "folder":
        if folder_feed_ids is None:
            return False
        folder = getattr(classifier, "folder_name", "")
        feeds_in_folder = folder_feed_ids.get(folder, set())
        return story_feed_id in feeds_in_folder
    # scope == 'feed' (default)
    return classifier.feed_id == story_feed_id


class ScopedClassifiers:
    """Pre-bucketed classifier collection for fast per-story scoring.

    models.py: Per-story scoring calls classifier_matches_story_feed once per
    (story, classifier) pair. For users with tens of thousands of classifiers
    (trained over years) this becomes the dominant cost — mongoengine field
    access via __get__ on `scope` and `feed_id` multiplies into hundreds of
    millions of dereferences and breaches the briefing soft_time_limit. See
    Sentry TASK-317.

    Bucketing classifiers by (scope, feed_id) once turns per-story scoring
    into O(k) where k is the number of classifiers that apply to that story's
    feed, instead of O(N_total).

    Folder-scoped classifiers require folder_feed_ids; passing None drops them,
    matching classifier_matches_story_feed's contract.
    """

    def __init__(self, classifiers, folder_feed_ids=None):
        self._globals = []
        self._by_feed = {}
        for c in classifiers:
            scope = getattr(c, "scope", "feed")
            if scope == "global":
                self._globals.append(c)
            elif scope == "folder":
                if folder_feed_ids is None:
                    continue
                folder = getattr(c, "folder_name", "")
                for fid in folder_feed_ids.get(folder, ()):
                    self._by_feed.setdefault(fid, []).append(c)
            else:
                self._by_feed.setdefault(c.feed_id, []).append(c)

    def for_feed(self, story_feed_id):
        per_feed = self._by_feed.get(story_feed_id)
        if not per_feed:
            return self._globals
        if not self._globals:
            return per_feed
        return per_feed + self._globals

    def __iter__(self):
        # Backwards compat for callers that iterate without a feed context.
        # Tracks id() so a classifier referenced under multiple feed buckets
        # (folder scope) is yielded once.
        yielded = set()
        for c in self._globals:
            yielded.add(id(c))
            yield c
        for bucket in self._by_feed.values():
            for c in bucket:
                key = id(c)
                if key not in yielded:
                    yielded.add(key)
                    yield c

    def __len__(self):
        return sum(1 for _ in self)

    def __bool__(self):
        return bool(self._globals) or bool(self._by_feed)


def _applicable_classifiers(classifiers, story_feed_id, folder_feed_ids):
    """Return classifiers applicable to this story's feed.

    models.py: Fast path when caller passed a ScopedClassifiers index. Falls
    back to the flat-list scope check so existing callers keep working.
    """
    if isinstance(classifiers, ScopedClassifiers):
        return classifiers.for_feed(story_feed_id)
    return [c for c in classifiers if classifier_matches_story_feed(c, story_feed_id, folder_feed_ids)]


def compute_story_score(
    story,
    classifier_titles,
    classifier_authors,
    classifier_tags,
    classifier_feeds,
    classifier_texts=None,
    classifier_urls=None,
    folder_feed_ids=None,
):
    if classifier_texts is None:
        classifier_texts = []
    if classifier_urls is None:
        classifier_urls = []

    intelligence = {
        "feed": apply_classifier_feeds(classifier_feeds, story["story_feed_id"]),
        "author": apply_classifier_authors(classifier_authors, story, folder_feed_ids=folder_feed_ids),
        "author_regex": 0,
        "tags": apply_classifier_tags(classifier_tags, story, folder_feed_ids=folder_feed_ids),
        "title": apply_classifier_titles(classifier_titles, story, folder_feed_ids=folder_feed_ids),
        "title_regex": 0,
        "text": apply_classifier_texts(classifier_texts, story, folder_feed_ids=folder_feed_ids),
        "text_regex": 0,
        "url": apply_classifier_urls(classifier_urls, story, folder_feed_ids=folder_feed_ids),
        "url_regex": 0,
    }

    score = 0

    score_max = max(
        intelligence["title"],
        intelligence["title_regex"],
        intelligence["author"],
        intelligence["author_regex"],
        intelligence["tags"],
        intelligence["text"],
        intelligence["text_regex"],
        intelligence["url"],
        intelligence["url_regex"],
    )
    score_min = min(
        intelligence["title"],
        intelligence["title_regex"],
        intelligence["author"],
        intelligence["author_regex"],
        intelligence["tags"],
        intelligence["text"],
        intelligence["text_regex"],
        intelligence["url"],
        intelligence["url_regex"],
    )
    if score_min <= -2:
        score = score_min  # super downvote beats any positive
    elif score_max > 0:
        score = score_max
    elif score_min < 0:
        score = score_min

    if score == 0:
        score = intelligence["feed"]

    return score


def _is_unicode_word_character(character):
    return character == "_" or character.isalnum() or unicodedata.category(character).startswith("M")


def classifier_title_matches(story_title, classifier_title):
    """Return whether a title classifier matches using classifier word-start semantics."""
    if not story_title or not classifier_title:
        return False

    story_title_lower = story_title.lower()
    classifier_title_lower = classifier_title.lower()
    match_index = story_title_lower.find(classifier_title_lower)
    classifier_starts_with_word = _is_unicode_word_character(classifier_title_lower[0])
    while (
        classifier_starts_with_word
        and match_index > 0
        and _is_unicode_word_character(story_title_lower[match_index - 1])
    ):
        match_index = story_title_lower.find(classifier_title_lower, match_index + 1)

    return match_index >= 0


def apply_classifier_titles(classifiers, story, folder_feed_ids=None):
    """
    Apply title classifiers to a story (non-regex only).

    Args:
        classifiers: List of MClassifierTitle objects
        story: Story dict with 'story_feed_id' and 'story_title'
        folder_feed_ids: Dict mapping folder_name -> set of feed_ids for folder-scoped classifiers

    Returns:
        Score (1 for like, -2 for super downvote, -1 for dislike, 0 for neutral)
    """
    score = 0
    story_title = story.get("story_title", "")
    if not story_title:
        return score

    for classifier in _applicable_classifiers(classifiers, story["story_feed_id"], folder_feed_ids):
        # Skip regex classifiers - they're handled by apply_classifier_regex
        if getattr(classifier, "is_regex", False):
            continue

        if classifier_title_matches(story_title, classifier.title):
            if classifier.score <= -2:
                return classifier.score  # super downvote beats everything
            if classifier.score > 0:
                score = classifier.score
            elif classifier.score < 0 and score <= 0:
                score = classifier.score

    return score


def apply_classifier_texts(classifiers, story, folder_feed_ids=None):
    """
    Apply text classifiers to a story (non-regex only).

    Args:
        classifiers: List of MClassifierText objects
        story: Story dict with 'story_feed_id' and 'story_content'
        folder_feed_ids: Dict mapping folder_name -> set of feed_ids for folder-scoped classifiers

    Returns:
        Score (1 for like, -2 for super downvote, -1 for dislike, 0 for neutral)
    """
    score = 0
    story_content = story.get("story_content", "")
    if not story_content:
        return score

    # Strip HTML tags so classifiers match visible text, not raw HTML.
    # Users train on rendered text, so tags like <em>/<a> inside a phrase
    # must not break substring matching.
    story_content_lower = strip_tags(story_content).lower()

    for classifier in _applicable_classifiers(classifiers, story["story_feed_id"], folder_feed_ids):
        # Skip regex classifiers - they're handled by apply_classifier_regex
        if getattr(classifier, "is_regex", False):
            continue

        # Standard substring matching (case-insensitive)
        if classifier.text.lower() in story_content_lower:
            if classifier.score <= -2:
                return classifier.score
            if classifier.score > 0:
                score = classifier.score
            elif classifier.score < 0 and score <= 0:
                score = classifier.score

    return score


def apply_classifier_title_regex(classifiers, story, folder_feed_ids=None):
    """
    Apply title regex classifiers to a story. Matches title only.

    Args:
        classifiers: List of MClassifierTitle objects with is_regex=True
        story: Story dict with 'story_feed_id' and 'story_title'
        folder_feed_ids: Dict mapping folder_name -> set of feed_ids for folder-scoped classifiers

    Returns:
        Score (1 for like, -2 for super downvote, -1 for dislike, 0 for neutral)
    """
    score = 0
    story_title = story.get("story_title", "")
    if not story_title:
        return score

    for classifier in _applicable_classifiers(classifiers, story["story_feed_id"], folder_feed_ids):
        if not getattr(classifier, "is_regex", False):
            continue

        if safe_regex_match(classifier.title, story_title):
            if classifier.score <= -2:
                return classifier.score
            if classifier.score > 0:
                score = classifier.score
            elif classifier.score < 0 and score <= 0:
                score = classifier.score

    return score


def apply_classifier_text_regex(classifiers, story, folder_feed_ids=None):
    """
    Apply text regex classifiers to a story. Matches content only.

    Args:
        classifiers: List of MClassifierText objects with is_regex=True
        story: Story dict with 'story_feed_id' and 'story_content'
        folder_feed_ids: Dict mapping folder_name -> set of feed_ids for folder-scoped classifiers

    Returns:
        Score (1 for like, -2 for super downvote, -1 for dislike, 0 for neutral)
    """
    score = 0
    story_content = story.get("story_content", "")
    if not story_content:
        return score

    # Strip HTML tags so regex matches visible text, not raw HTML
    story_content = strip_tags(story_content)

    for classifier in _applicable_classifiers(classifiers, story["story_feed_id"], folder_feed_ids):
        if not getattr(classifier, "is_regex", False):
            continue

        if safe_regex_match(classifier.text, story_content):
            if classifier.score <= -2:
                return classifier.score
            if classifier.score > 0:
                score = classifier.score
            elif classifier.score < 0 and score <= 0:
                score = classifier.score

    return score


def apply_classifier_urls(classifiers, story, folder_feed_ids=None):
    """
    Apply URL classifiers to a story (non-regex only).

    Args:
        classifiers: List of MClassifierUrl objects
        story: Story dict with 'story_feed_id' and 'story_permalink'
        folder_feed_ids: Dict mapping folder_name -> set of feed_ids for folder-scoped classifiers

    Returns:
        Score (1 for like, -2 for super downvote, -1 for dislike, 0 for neutral)
    """
    score = 0
    story_url = story.get("story_permalink", "")
    if not story_url:
        return score

    story_url_lower = story_url.lower()

    for classifier in _applicable_classifiers(classifiers, story["story_feed_id"], folder_feed_ids):
        # Skip regex classifiers - they're handled by apply_classifier_url_regex
        if getattr(classifier, "is_regex", False):
            continue

        # Standard substring matching (case-insensitive)
        if classifier.url.lower() in story_url_lower:
            if classifier.score <= -2:
                return classifier.score
            if classifier.score > 0:
                score = classifier.score
            elif classifier.score < 0 and score <= 0:
                score = classifier.score

    return score


def apply_classifier_url_regex(classifiers, story, folder_feed_ids=None):
    """
    Apply URL regex classifiers to a story. Matches permalink URL only.

    Args:
        classifiers: List of MClassifierUrl objects with is_regex=True
        story: Story dict with 'story_feed_id' and 'story_permalink'
        folder_feed_ids: Dict mapping folder_name -> set of feed_ids for folder-scoped classifiers

    Returns:
        Score (1 for like, -2 for super downvote, -1 for dislike, 0 for neutral)
    """
    score = 0
    story_url = story.get("story_permalink", "")
    if not story_url:
        return score

    for classifier in _applicable_classifiers(classifiers, story["story_feed_id"], folder_feed_ids):
        if not getattr(classifier, "is_regex", False):
            continue

        if safe_regex_match(classifier.url, story_url):
            if classifier.score <= -2:
                return classifier.score
            if classifier.score > 0:
                score = classifier.score
            elif classifier.score < 0 and score <= 0:
                score = classifier.score

    return score


def apply_classifier_authors(classifiers, story, folder_feed_ids=None):
    score = 0
    for classifier in _applicable_classifiers(classifiers, story["story_feed_id"], folder_feed_ids):
        # Skip regex classifiers - they're handled by apply_classifier_author_regex
        if getattr(classifier, "is_regex", False):
            continue
        if story.get("story_authors") and classifier.author == story.get("story_authors"):
            # print 'Authors: %s -- %s' % (classifier.author, story['story_authors'])
            if classifier.score <= -2:
                return classifier.score
            if classifier.score > 0:
                score = classifier.score
            elif classifier.score < 0 and score <= 0:
                score = classifier.score
    return score


def apply_classifier_author_regex(classifiers, story, folder_feed_ids=None):
    """
    Apply author regex classifiers to a story. Matches story_authors string.

    Args:
        classifiers: List of MClassifierAuthor objects with is_regex=True
        story: Story dict with 'story_feed_id' and 'story_authors'
        folder_feed_ids: Dict mapping folder_name -> set of feed_ids for folder-scoped classifiers

    Returns:
        Score (1 for like, -2 for super downvote, -1 for dislike, 0 for neutral)
    """
    score = 0
    story_authors = story.get("story_authors", "") or ""
    if not story_authors:
        return score

    for classifier in _applicable_classifiers(classifiers, story["story_feed_id"], folder_feed_ids):
        if not getattr(classifier, "is_regex", False):
            continue

        if safe_regex_match(classifier.author, story_authors):
            if classifier.score <= -2:
                return classifier.score
            if classifier.score > 0:
                score = classifier.score
            elif classifier.score < 0 and score <= 0:
                score = classifier.score

    return score


def apply_classifier_tags(classifiers, story, folder_feed_ids=None):
    score = 0
    for classifier in _applicable_classifiers(classifiers, story["story_feed_id"], folder_feed_ids):
        if story["story_tags"] and classifier.tag in story["story_tags"]:
            # print 'Tags: (%s-%s) %s -- %s' % (classifier.tag in story['story_tags'], classifier.score, classifier.tag, story['story_tags'])
            if classifier.score <= -2:
                return classifier.score
            if classifier.score > 0:
                score = classifier.score
            elif classifier.score < 0 and score <= 0:
                score = classifier.score
    return score


def apply_classifier_feeds(classifiers, feed, social_user_ids=None):
    if not feed and not social_user_ids:
        return 0
    feed_id = None
    if feed:
        feed_id = feed if isinstance(feed, int) else feed.pk

    if social_user_ids and not isinstance(social_user_ids, list):
        social_user_ids = [social_user_ids]

    for classifier in classifiers:
        if classifier.feed_id == feed_id:
            # print 'Feeds: %s -- %s' % (classifier.feed_id, feed.pk)
            return classifier.score
        if social_user_ids and not classifier.feed_id and classifier.social_user_id in social_user_ids:
            return classifier.score
    return 0




SCOPED_CLASSIFIER_CLASSES = [
    MClassifierTitle,
    MClassifierText,
    MClassifierUrl,
    MClassifierAuthor,
    MClassifierTag,
]


def load_scoped_classifiers(user_id):
    """Load all global and folder-scoped classifiers for a user.

    Returns a dict with keys: 'titles', 'texts', 'urls', 'authors', 'tags'
    each containing a list of classifier objects with scope != 'feed'.
    """
    result = {
        "titles": [],
        "texts": [],
        "urls": [],
        "authors": [],
        "tags": [],
    }
    key_map = {
        MClassifierTitle: "titles",
        MClassifierText: "texts",
        MClassifierUrl: "urls",
        MClassifierAuthor: "authors",
        MClassifierTag: "tags",
    }
    for Cls in SCOPED_CLASSIFIER_CLASSES:
        classifiers = list(Cls.objects(user_id=user_id, scope__in=["folder", "global"]))
        result[key_map[Cls]] = classifiers
    return result


def get_classifiers_for_user(
    user,
    feed_id=None,
    social_user_id=None,
    classifier_feeds=None,
    classifier_authors=None,
    classifier_titles=None,
    classifier_tags=None,
    classifier_texts=None,
    classifier_urls=None,
    folder_feed_ids=None,
):
    params = dict(user_id=user.pk)
    if isinstance(feed_id, list):
        params["feed_id__in"] = feed_id
    elif feed_id:
        params["feed_id"] = feed_id
    if social_user_id:
        if isinstance(social_user_id, str):
            social_user_id = int(social_user_id.replace("social:", ""))
        params["social_user_id"] = social_user_id

    if classifier_authors is None:
        classifier_authors = list(MClassifierAuthor.objects(**params))
    if classifier_titles is None:
        classifier_titles = list(MClassifierTitle.objects(**params))
    if classifier_tags is None:
        classifier_tags = list(MClassifierTag.objects(**params))
    if classifier_texts is None:
        classifier_texts = list(MClassifierText.objects(**params))
    if classifier_urls is None:
        classifier_urls = list(MClassifierUrl.objects(**params))
    if classifier_feeds is None:
        if not social_user_id and feed_id:
            params["social_user_id"] = 0
        classifier_feeds = list(MClassifierFeed.objects(**params))

    # Filter scoped classifiers to only those applicable to the current feed.
    # Without this, folder-scoped classifiers bleed into other folders for
    # frontend text highlighting (intelligence scoring is unaffected since
    # it does its own scope check via classifier_matches_story_feed).
    if folder_feed_ids is not None and feed_id and not isinstance(feed_id, list):
        active_feed_id = int(feed_id)
        classifier_authors = [
            c for c in classifier_authors if classifier_matches_story_feed(c, active_feed_id, folder_feed_ids)
        ]
        classifier_titles = [
            c for c in classifier_titles if classifier_matches_story_feed(c, active_feed_id, folder_feed_ids)
        ]
        classifier_tags = [
            c for c in classifier_tags if classifier_matches_story_feed(c, active_feed_id, folder_feed_ids)
        ]
        classifier_texts = [
            c for c in classifier_texts if classifier_matches_story_feed(c, active_feed_id, folder_feed_ids)
        ]
        classifier_urls = [
            c for c in classifier_urls if classifier_matches_story_feed(c, active_feed_id, folder_feed_ids)
        ]

    feeds = []
    for f in classifier_feeds:
        if f.social_user_id and not f.feed_id:
            feeds.append(("social:%s" % f.social_user_id, f.score))
        else:
            feeds.append((f.feed_id, f.score))

    # Build titles dict - only non-regex patterns
    titles_dict = {}
    title_regex_dict = {}
    for t in classifier_titles:
        if getattr(t, "is_regex", False):
            title_regex_dict[t.title] = t.score
        else:
            titles_dict[t.title] = t.score

    # Build texts dict - only non-regex patterns
    texts_dict = {}
    text_regex_dict = {}
    for t in classifier_texts:
        if getattr(t, "is_regex", False):
            text_regex_dict[t.text] = t.score
        else:
            texts_dict[t.text] = t.score

    # Build urls dict - only non-regex patterns
    urls_dict = {}
    url_regex_dict = {}
    for u in classifier_urls:
        if getattr(u, "is_regex", False):
            url_regex_dict[u.url] = u.score
        else:
            urls_dict[u.url] = u.score

    # Build authors dict - only non-regex patterns
    authors_dict = {}
    author_regex_dict = {}
    for a in classifier_authors:
        if getattr(a, "is_regex", False):
            author_regex_dict[a.author] = a.score
        else:
            authors_dict[a.author] = a.score

    # Build scope metadata for UI display
    def _scope_info(classifier):
        scope = getattr(classifier, "scope", "feed")
        if scope == "feed":
            return None
        return {"scope": scope, "folder_name": getattr(classifier, "folder_name", "")}

    titles_scope = {}
    for t in classifier_titles:
        info = _scope_info(t)
        if info:
            titles_scope[t.title] = info
    texts_scope = {}
    for t in classifier_texts:
        info = _scope_info(t)
        if info:
            texts_scope[t.text] = info
    urls_scope = {}
    for u in classifier_urls:
        info = _scope_info(u)
        if info:
            urls_scope[u.url] = info
    authors_scope = {}
    for a in classifier_authors:
        info = _scope_info(a)
        if info:
            authors_scope[a.author] = info
    tags_scope = {}
    for t in classifier_tags:
        info = _scope_info(t)
        if info:
            tags_scope[t.tag] = info

    # AI prompt classifiers were removed with the personal-edition slimming. These keys
    # stay in the payload so the reader's trainer JSON shape does not change.
    prompts_dict = {}
    image_prompts_dict = {}
    prompts_scope = {}
    image_prompts_scope = {}

    payload = {
        "feeds": dict(feeds),
        "authors": authors_dict,
        "author_regex": author_regex_dict,
        "titles": titles_dict,
        "title_regex": title_regex_dict,
        "tags": dict([(t.tag, t.score) for t in classifier_tags]),
        "texts": texts_dict,
        "text_regex": text_regex_dict,
        "urls": urls_dict,
        "url_regex": url_regex_dict,
        "titles_scope": titles_scope,
        "texts_scope": texts_scope,
        "urls_scope": urls_scope,
        "authors_scope": authors_scope,
        "tags_scope": tags_scope,
        "prompts": prompts_dict,
        "image_prompts": image_prompts_dict,
        "prompts_scope": prompts_scope,
        "image_prompts_scope": image_prompts_scope,
    }

    return payload


def sort_classifiers_by_feed(
    user,
    feed_ids=None,
    classifier_feeds=None,
    classifier_authors=None,
    classifier_titles=None,
    classifier_tags=None,
    classifier_texts=None,
    classifier_urls=None,
    folder_feed_ids=None,
):
    def sort_by_feed(classifiers):
        """Sort classifiers by feed_id, distributing global/folder classifiers to all relevant feeds."""
        feed_classifiers = defaultdict(list)
        if classifiers:
            for classifier in classifiers:
                scope = getattr(classifier, "scope", "feed")
                if scope == "global":
                    # Global classifiers apply to all feed_ids
                    for fid in feed_ids or []:
                        feed_classifiers[fid].append(classifier)
                elif scope == "folder" and folder_feed_ids:
                    # Folder classifiers apply to feeds in their folder
                    folder = getattr(classifier, "folder_name", "")
                    for fid in folder_feed_ids.get(folder, set()):
                        if feed_ids is None or fid in feed_ids:
                            feed_classifiers[fid].append(classifier)
                else:
                    feed_classifiers[classifier.feed_id].append(classifier)
        return feed_classifiers

    classifiers = {}

    if feed_ids:
        classifier_feeds = sort_by_feed(classifier_feeds)
        classifier_authors = sort_by_feed(classifier_authors)
        classifier_titles = sort_by_feed(classifier_titles)
        classifier_tags = sort_by_feed(classifier_tags)
        classifier_texts = sort_by_feed(classifier_texts)
        classifier_urls = sort_by_feed(classifier_urls)

        for feed_id in feed_ids:
            classifiers[feed_id] = get_classifiers_for_user(
                user,
                feed_id=feed_id,
                classifier_feeds=classifier_feeds[feed_id],
                classifier_authors=classifier_authors[feed_id],
                classifier_titles=classifier_titles[feed_id],
                classifier_tags=classifier_tags[feed_id],
                classifier_texts=classifier_texts[feed_id],
                classifier_urls=classifier_urls[feed_id],
            )

    return classifiers
