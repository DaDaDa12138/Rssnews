"""Story filters: per-reader rules applied to stories as they are fetched.

Feed.add_update_stories calls apply_rules() for every new story, once per feed
fetch, with the rule set already resolved by rules_for_feed(). Story rows are
shared by every subscriber, so an action never deletes a story: mark_read and
hide write the reader's read state, star copies the story into the reader's
starred list, and tag attaches a reader tag.
"""

import logging
import re

from django.db.models import F, Q
from django.utils.translation import gettext

from apps.rss_feeds.models import MStarredStory, MStarredStoryCounts, MStory, StoryFilter

logger = logging.getLogger(__name__)

FIELD_ATTRS = {
    StoryFilter.FIELD_ANY: ("story_title", "story_author_name", "story_content_str", "story_permalink"),
    "title": ("story_title",),
    "author": ("story_author_name",),
    "content": ("story_content_str",),
    "url": ("story_permalink",),
}

MAX_PATTERN_LENGTH = StoryFilter._meta.get_field("pattern").max_length


class CompiledRule:
    """A StoryFilter plus its compiled matcher. Invalid regexes compile to None."""

    __slots__ = ("rule", "regex", "needle")

    def __init__(self, rule):
        self.rule = rule
        self.regex = None
        self.needle = rule.pattern
        if rule.is_regex:
            flags = 0 if rule.case_sensitive else re.IGNORECASE
            try:
                self.regex = re.compile(rule.pattern, flags)
            except re.error as e:
                logger.warning("StoryFilter %s has an invalid pattern %r: %s", rule.pk, rule.pattern, e)
                self.regex = False
        elif not rule.case_sensitive:
            self.needle = rule.pattern.lower()

    def matches(self, story):
        if self.regex is False:
            return False
        values = []
        for attr in FIELD_ATTRS.get(self.rule.field, FIELD_ATTRS[StoryFilter.FIELD_ANY]):
            value = getattr(story, attr, None)
            if value:
                values.append(value if isinstance(value, str) else str(value))
        if not values:
            return False
        if self.regex is not None:
            return any(self.regex.search(value) for value in values)
        if self.rule.case_sensitive:
            return any(self.needle in value for value in values)
        return any(self.needle in value.lower() for value in values)


def _folder_map_for(user_id, cache):
    if user_id not in cache:
        from apps.reader.models import UserSubscriptionFolders

        try:
            user = UserSubscriptionFolders._meta.get_field("user").related_model.objects.get(pk=user_id)
            cache[user_id] = UserSubscriptionFolders.get_feed_folder_mapping(user)
        except Exception:
            cache[user_id] = {}
    return cache[user_id]


def rules_for_feed(feed):
    """Returns {user_id: [CompiledRule, ...]} for the rules that apply to this feed."""
    if not feed or not feed.pk:
        return {}
    candidates = StoryFilter.objects.filter(enabled=True).filter(
        Q(scope=StoryFilter.SCOPE_GLOBAL)
        | Q(scope=StoryFilter.SCOPE_FEED, feed_id=feed.pk)
        | Q(scope=StoryFilter.SCOPE_FOLDER)
    )
    folder_cache = {}
    by_user = {}
    for rule in candidates:
        if rule.scope == StoryFilter.SCOPE_FOLDER:
            folders = _folder_map_for(rule.user_id, folder_cache).get(feed.pk, [])
            if rule.folder not in folders:
                continue
        compiled = CompiledRule(rule)
        if compiled.regex is False:
            continue
        by_user.setdefault(rule.user_id, []).append(compiled)
    return by_user


def star_story_for_user(user_id, story, user_tags=None):
    """Copies a story into a reader's starred list, the same way starring a story does."""
    import datetime

    fields = {}
    for field in story._meta.concrete_fields:
        if field.auto_created or field.name in ("id", "user_id", "starred_date", "user_tags", "highlights", "user_notes"):
            continue
        value = getattr(story, field.name, None)
        if value is not None:
            fields[field.name] = value
    fields.pop("story_latest_content_z", None)

    existing = MStarredStory.objects.filter(user_id=user_id, story_guid=story.story_guid).limit(1)
    if existing:
        starred = existing[0]
        if user_tags:
            starred.user_tags = sorted(set(starred.user_tags or []) | set(user_tags))
            starred.save()
        return starred

    starred = MStarredStory.objects.create(
        user_id=user_id,
        starred_date=datetime.datetime.now(),
        user_tags=user_tags or [],
        **fields
    )
    MStarredStoryCounts.adjust_count(user_id, feed_id=story.story_feed_id, amount=1)
    for tag in user_tags or []:
        MStarredStoryCounts.adjust_count(user_id, tag=tag, amount=1)
    return starred


def _tag_story(user_id, story, tag):
    from apps.reader.models import StoryTag

    return StoryTag.add(user_id, story.story_hash, tag)


def apply_rules(ruleset, story, feed_id, verbose=False):
    """Applies every matching rule for every reader to one freshly saved story.

    Returns {"rules": n, "read": n, "starred": n, "tagged": n}.
    """
    counts = {"rules": 0, "read": 0, "starred": 0, "tagged": 0}
    if not ruleset:
        return counts

    story_hash = getattr(story, "story_hash", None)
    if not story_hash:
        return counts

    matched_rules = []
    for user_id, rules in ruleset.items():
        matched = [rule for rule in rules if rule.matches(story)]
        if not matched:
            continue
        matched_rules.extend(matched)
        counts["rules"] += len(matched)

        read = any(rule.rule.action in (StoryFilter.ACTION_MARK_READ, StoryFilter.ACTION_HIDE) for rule in matched)
        star = any(rule.rule.action == StoryFilter.ACTION_STAR for rule in matched)
        tags = [rule.rule.tag for rule in matched if rule.rule.action == StoryFilter.ACTION_TAG and rule.rule.tag]

        if read:
            try:
                from apps.reader.models import UserSubscription

                usersub = UserSubscription.objects.filter(user_id=user_id, feed_id=feed_id).first()
                if usersub:
                    usersub.mark_story_ids_as_read([story_hash], aggregated=True)
                    counts["read"] += 1
            except Exception as e:
                logger.warning("StoryFilter read action failed for user %s story %s: %s", user_id, story_hash, e)

        if star:
            try:
                star_story_for_user(user_id, story)
                counts["starred"] += 1
            except Exception as e:
                logger.warning("StoryFilter star action failed for user %s story %s: %s", user_id, story_hash, e)

        for tag in tags:
            try:
                _tag_story(user_id, story, tag)
                counts["tagged"] += 1
            except Exception as e:
                logger.warning("StoryFilter tag action failed for user %s story %s: %s", user_id, story_hash, e)

    if matched_rules:
        StoryFilter.objects.filter(pk__in=[rule.rule.pk for rule in matched_rules]).update(hits=F("hits") + 1)
        if verbose:
            logger.info("StoryFilter matched %s rules on %s: %s", len(matched_rules), story_hash, counts)

    return counts


def validate_pattern(pattern, is_regex):
    """Returns an error string, or None when the pattern is usable."""
    pattern = (pattern or "").strip()
    if not pattern:
        return gettext("A filter needs a pattern.")
    if len(pattern) > MAX_PATTERN_LENGTH:
        return gettext("A filter pattern is limited to %s characters.") % MAX_PATTERN_LENGTH
    if is_regex:
        try:
            re.compile(pattern)
        except re.error as e:
            return gettext("That regular expression is not valid: %s") % e
    return None

def feed_ids_for_rule(rule, user):
    """The feeds a rule covers, so run-now and ingest agree on the scope."""
    from apps.reader.models import UserSubscription, UserSubscriptionFolders

    if rule.scope == StoryFilter.SCOPE_FEED:
        return [rule.feed_id] if rule.feed_id else []
    subscribed = list(UserSubscription.objects.filter(user=user).values_list("feed_id", flat=True))
    if rule.scope == StoryFilter.SCOPE_GLOBAL:
        return subscribed
    try:
        usf = UserSubscriptionFolders.objects.get(user=user)
    except UserSubscriptionFolders.DoesNotExist:
        return []
    flat = usf.flatten_folders()
    for title, feed_ids in flat.items():
        if (title or "").strip().lower() == rule.folder.strip().lower():
            return [feed_id for feed_id in feed_ids if feed_id in set(subscribed)]
    return []


def apply_rule_to_recent(rule, user, limit=300):
    """Runs one rule over the reader's newest stories, newest first."""
    compiled = CompiledRule(rule)
    counts = {"matched": 0, "read": 0, "starred": 0, "tagged": 0}
    if compiled.regex is False:
        return counts
    feed_ids = feed_ids_for_rule(rule, user)
    if not feed_ids:
        return counts
    stories = MStory.objects(story_feed_id__in=feed_ids).order_by("-story_date")[:limit]
    for story in stories:
        if not compiled.matches(story):
            continue
        counts["matched"] += 1
        result = apply_rules({user.pk: [compiled]}, story, story.story_feed_id)
        for key in ("read", "starred", "tagged"):
            counts[key] += result[key]
    return counts