"""Saved searches: a named query the reader re-runs from the sidebar.

The query is the same search syntax the toolbar accepts (apps/rss_feeds/search.py),
so a saved search keeps working as the syntax grows. share_token exposes a
read-only JSON feed of the newest matches without a login.
"""

from django.views.decorators.http import require_POST

from ._base import *
from apps.reader.models import SavedSearch, UserSubscription
from apps.rss_feeds import search as story_search
from apps.rss_feeds.models import Feed


def serialize_search(saved):
    return {
        "id": saved.pk,
        "name": saved.name,
        "query": saved.query,
        "order": saved.order,
        "share_token": saved.share_token,
        "shared": bool(saved.share_token),
    }


@ajax_login_required
@json.json_view
def load_saved_searches(request):
    user = get_user(request)
    searches = SavedSearch.objects.filter(user=user).order_by("name")
    return {"code": 0, "searches": [serialize_search(saved) for saved in searches]}


@ajax_login_required
@require_POST
@json.json_view
def save_saved_search(request):
    user = get_user(request)
    name = (request.POST.get("name") or "").strip()
    query = (request.POST.get("query") or "").strip()
    order = request.POST.get("order", "newest")
    if not name:
        return {"code": -1, "message": gettext("Give the search a name.")}
    if not query:
        return {"code": -1, "message": gettext("A saved search needs a query.")}
    parsed = story_search.parse(query)
    if parsed.errors:
        return {"code": -1, "message": parsed.errors[0]}
    saved, created = SavedSearch.objects.update_or_create(
        user=user, name=name[:128], defaults={"query": query[:512], "order": order}
    )
    return {
        "code": 0,
        "search": serialize_search(saved),
        "created": created,
        "message": gettext("Search saved."),
    }


@ajax_login_required
@require_POST
@json.json_view
def delete_saved_search(request):
    user = get_user(request)
    saved = SavedSearch.objects.filter(user=user, pk=request.POST.get("id")).first()
    if not saved:
        return {"code": -1, "message": gettext("That saved search no longer exists.")}
    saved.delete()
    return {"code": 0, "message": gettext("Saved search deleted.")}


@ajax_login_required
@require_POST
@json.json_view
def share_saved_search(request):
    user = get_user(request)
    saved = SavedSearch.objects.filter(user=user, pk=request.POST.get("id")).first()
    if not saved:
        return {"code": -1, "message": gettext("That saved search no longer exists.")}
    token = saved.ensure_share_token()
    return {
        "code": 0,
        "search": serialize_search(saved),
        "url": request.build_absolute_uri(reverse("saved-search-shared", args=[token])),
    }


@json.json_view
def saved_search_shared(request, token):
    saved = SavedSearch.objects.filter(share_token=token).select_related("user").first()
    if not saved:
        return {"code": -1, "message": gettext("That shared search no longer exists.")}
    feed_ids = list(UserSubscription.objects.filter(user=saved.user).values_list("feed_id", flat=True))
    stories = Feed.find_feed_stories(
        feed_ids, saved.query, order=saved.order, offset=0, limit=50, user=saved.user
    )
    return {
        "code": 0,
        "name": saved.name,
        "query": saved.query,
        "stories": [
            {
                "story_title": story["story_title"],
                "story_permalink": story["story_permalink"],
                "story_date": story["story_date"].isoformat(),
                "story_feed_id": story["story_feed_id"],
            }
            for story in stories
        ],
    }
