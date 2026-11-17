"""Story filter CRUD: the per-reader rules that run on new stories.

The rules themselves live in apps/rss_feeds/models.py and are evaluated by
apps/rss_feeds/filters.py; these views only validate and persist them.
"""

from django.views.decorators.http import require_POST

from ._base import *
from apps.rss_feeds.filters import validate_pattern
from apps.rss_feeds.models import Feed, StoryFilter


def serialize_filter(rule):
    return {
        "id": rule.pk,
        "scope": rule.scope,
        "feed_id": rule.feed_id,
        "feed_title": rule.feed.feed_title if rule.feed_id else "",
        "folder": rule.folder,
        "field": rule.field,
        "pattern": rule.pattern,
        "is_regex": rule.is_regex,
        "case_sensitive": rule.case_sensitive,
        "action": rule.action,
        "tag": rule.tag,
        "enabled": rule.enabled,
        "hits": rule.hits,
    }


@ajax_login_required
@json.json_view
def load_story_filters(request):
    user = get_user(request)
    rules = (
        StoryFilter.objects.filter(user=user)
        .select_related("feed")
        .order_by("scope", "feed__feed_title", "id")
    )
    return {
        "code": 0,
        "filters": [serialize_filter(rule) for rule in rules],
        "scopes": [{"value": value, "label": gettext(label)} for value, label in StoryFilter.SCOPE_CHOICES],
        "fields": [{"value": value, "label": gettext(label)} for value, label in StoryFilter.FIELD_CHOICES],
        "actions": [{"value": value, "label": gettext(label)} for value, label in StoryFilter.ACTION_CHOICES],
    }


def _subscription_feed(user, feed_id):
    from apps.reader.models import UserSubscription

    if not feed_id:
        return None
    try:
        feed_id = int(feed_id)
    except (TypeError, ValueError):
        return None
    if not UserSubscription.objects.filter(user=user, feed_id=feed_id).exists():
        return None
    return Feed.objects.filter(pk=feed_id).first()


@ajax_login_required
@require_POST
@json.json_view
def save_story_filter(request):
    user = get_user(request)
    rule_id = request.POST.get("id")
    scope = request.POST.get("scope", StoryFilter.SCOPE_FEED)
    field = request.POST.get("field", StoryFilter.FIELD_ANY)
    action = request.POST.get("action", StoryFilter.ACTION_MARK_READ)
    pattern = (request.POST.get("pattern") or "").strip()
    folder = (request.POST.get("folder") or "").strip()
    tag = (request.POST.get("tag") or "").strip()
    is_regex = is_true(request.POST.get("is_regex", False))
    case_sensitive = is_true(request.POST.get("case_sensitive", False))
    enabled = is_true(request.POST.get("enabled", True))
    feed = None

    if scope not in dict(StoryFilter.SCOPE_CHOICES):
        return {"code": -1, "message": gettext("That filter scope is not available.")}
    if field not in dict(StoryFilter.FIELD_CHOICES):
        return {"code": -1, "message": gettext("That filter field is not available.")}
    if action not in dict(StoryFilter.ACTION_CHOICES):
        return {"code": -1, "message": gettext("That filter action is not available.")}

    error = validate_pattern(pattern, is_regex)
    if error:
        return {"code": -1, "message": error}

    if scope == StoryFilter.SCOPE_FEED:
        feed = _subscription_feed(user, request.POST.get("feed_id"))
        if not feed:
            return {"code": -1, "message": gettext("Choose a site you are subscribed to.")}
    elif scope == StoryFilter.SCOPE_FOLDER and not folder:
        return {"code": -1, "message": gettext("A folder rule needs a folder name.")}
    if action == StoryFilter.ACTION_TAG and not tag:
        return {"code": -1, "message": gettext("A tag rule needs a tag name.")}

    defaults = dict(
        scope=scope,
        feed=feed,
        folder=folder if scope == StoryFilter.SCOPE_FOLDER else "",
        field=field,
        pattern=pattern,
        is_regex=is_regex,
        case_sensitive=case_sensitive,
        action=action,
        tag=tag if action == StoryFilter.ACTION_TAG else "",
        enabled=enabled,
    )
    if rule_id:
        rule = StoryFilter.objects.filter(user=user, pk=rule_id).first()
        if not rule:
            return {"code": -1, "message": gettext("That filter no longer exists.")}
        for key, value in defaults.items():
            setattr(rule, key, value)
        rule.save()
    else:
        rule = StoryFilter.objects.create(user=user, **defaults)

    rule = StoryFilter.objects.select_related("feed").get(pk=rule.pk)
    return {"code": 0, "filter": serialize_filter(rule), "message": gettext("Filter saved.")}


@ajax_login_required
@require_POST
@json.json_view
def delete_story_filter(request):
    user = get_user(request)
    rule = StoryFilter.objects.filter(user=user, pk=request.POST.get("id")).first()
    if not rule:
        return {"code": -1, "message": gettext("That filter no longer exists.")}
    rule.delete()
    return {"code": 0, "message": gettext("Filter deleted.")}


@ajax_login_required
@require_POST
@json.json_view
def toggle_story_filter(request):
    user = get_user(request)
    rule = StoryFilter.objects.filter(user=user, pk=request.POST.get("id")).first()
    if not rule:
        return {"code": -1, "message": gettext("That filter no longer exists.")}
    rule.enabled = not rule.enabled
    rule.save(update_fields=["enabled", "updated"])
    return {"code": 0, "filter": serialize_filter(rule)}


@ajax_login_required
@require_POST
@json.json_view
def run_story_filter(request):
    """Applies one filter to the reader's recent stories, for rules added after the fact."""
    from apps.rss_feeds.filters import apply_rule_to_recent

    user = get_user(request)
    rule = StoryFilter.objects.filter(user=user, pk=request.POST.get("id")).select_related("feed").first()
    if not rule:
        return {"code": -1, "message": gettext("That filter no longer exists.")}
    counts = apply_rule_to_recent(rule, user)
    rule.refresh_from_db()
    return {
        "code": 0,
        "counts": counts,
        "filter": serialize_filter(rule),
        "message": gettext("Matched %(count)s stories.")
        % {"count": counts.get("matched", 0)},
    }
