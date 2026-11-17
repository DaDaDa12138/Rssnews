"""Reader story tags: tagging a story does not require saving it.

Rows live in apps/reader/models.py StoryTag and are read by the tag: search
operator in apps/rss_feeds/search.py.
"""

from django.views.decorators.http import require_POST

from ._base import *
from apps.reader.models import StoryTag
from apps.rss_feeds.models import MStory


@ajax_login_required
@json.json_view
def load_story_tags(request):
    user = get_user(request)
    story_hash = request.GET.get("story_hash")
    if story_hash:
        return {"code": 0, "story_hash": story_hash, "tags": StoryTag.for_story(user.pk, story_hash)}
    return {
        "code": 0,
        "tags": [{"tag": row["tag"], "count": row["count"]} for row in StoryTag.counts(user.pk)],
    }


@ajax_login_required
@require_POST
@json.json_view
def add_story_tag(request):
    user = get_user(request)
    story_hash = (request.POST.get("story_hash") or "").strip()
    tag = StoryTag.normalize(request.POST.get("tag"))
    if not story_hash or not tag:
        return {"code": -1, "message": gettext("A tag needs a story and a name.")}
    if not MStory.objects.filter(story_hash=story_hash).exists():
        return {"code": -1, "message": gettext("That story no longer exists.")}
    StoryTag.add(user.pk, story_hash, tag)
    return {"code": 0, "story_hash": story_hash, "tags": StoryTag.for_story(user.pk, story_hash)}


@ajax_login_required
@require_POST
@json.json_view
def remove_story_tag(request):
    user = get_user(request)
    story_hash = (request.POST.get("story_hash") or "").strip()
    tag = StoryTag.normalize(request.POST.get("tag"))
    if not story_hash or not tag:
        return {"code": -1, "message": gettext("A tag needs a story and a name.")}
    StoryTag.remove(user.pk, story_hash, tag)
    return {"code": 0, "story_hash": story_hash, "tags": StoryTag.for_story(user.pk, story_hash)}
