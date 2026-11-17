"""Saved stories and starred tag management.

Split from apps/reader/views.py; see apps/reader/views/__init__.py.
"""

from django.views.decorators.http import require_POST

from ._base import *  # noqa: F401,F403



@ratelimit(minutes=5, requests=50, use_path=True)
@json.json_view
def load_starred_stories(request):
    user = get_user(request)
    offset = int_argument(request.GET, "offset", 0)
    limit = int_argument(request.GET, "limit", 10)
    page = int_argument(request.GET, "page", 0)
    query = request.GET.get("query", "").strip()
    order = request.GET.get("order", "newest")
    read_filter = request.GET.get("read_filter", "all")
    date_filter_start = request.GET.get("date_filter_start")
    date_filter_end = request.GET.get("date_filter_end")
    # Sanitize date filters - JS sends "null" as a string
    if date_filter_start in ("null", "None", "", None):
        date_filter_start = None
    if date_filter_end in ("null", "None", "", None):
        date_filter_end = None
    tag = request.GET.get("tag")
    highlights = is_true(request.GET.get("highlights", False))
    story_hashes = request.GET.getlist("h") or request.GET.getlist("h[]")
    story_hashes = story_hashes[:100]
    version = int_argument(request.GET, "v", 1)
    now = localtime_for_timezone(datetime.datetime.now(), user.profile.timezone)
    message = None
    order_by = "-" if order == "newest" else ""
    if page:
        offset = limit * (page - 1)

    # Normalize date filters from user timezone to UTC
    date_filter_start_utc, date_filter_end_utc, date_filter_end_start_utc = normalize_date_filters(
        date_filter_start, date_filter_end, user.profile.timezone
    )

    # Auto-switch from unread to all if date filter extends beyond unread cutoff
    read_filter = adjust_read_filter_for_date_range(
        read_filter, date_filter_start_utc, date_filter_end_start_utc, user.profile.unread_cutoff
    )

    if query:
        stories = MStarredStory.find_stories(
            query,
            user.pk,
            tag=tag,
            offset=offset,
            limit=limit,
            order=order,
            date_filter_start=date_filter_start_utc,
            date_filter_end=date_filter_end_utc,
        )
    elif highlights:
        mstories_query = MStarredStory.objects(user_id=user.pk).exclude(highlights=[])
        if date_filter_start_utc:
            mstories_query = mstories_query.filter(starred_date__gte=date_filter_start_utc)
        if date_filter_end_utc:
            mstories_query = mstories_query.filter(starred_date__lt=date_filter_end_utc)
        mstories = mstories_query.order_by("%sstarred_date" % order_by)[offset : offset + limit]
        stories = Feed.format_stories(mstories)
    elif tag:
        mstories_query = MStarredStory.objects(user_id=user.pk, user_tags__contains=tag)
        if date_filter_start_utc:
            mstories_query = mstories_query.filter(starred_date__gte=date_filter_start_utc)
        if date_filter_end_utc:
            mstories_query = mstories_query.filter(starred_date__lt=date_filter_end_utc)
        mstories = mstories_query.order_by("%sstarred_date" % order_by)[offset : offset + limit]
        stories = Feed.format_stories(mstories)
    elif story_hashes:
        limit = 100
        mstories_query = MStarredStory.objects(user_id=user.pk, story_hash__in=story_hashes)
        if date_filter_start_utc:
            mstories_query = mstories_query.filter(starred_date__gte=date_filter_start_utc)
        if date_filter_end_utc:
            mstories_query = mstories_query.filter(starred_date__lt=date_filter_end_utc)
        mstories = mstories_query.order_by("%sstarred_date" % order_by)[offset : offset + limit]
        stories = Feed.format_stories(mstories)
    else:
        mstories_query = MStarredStory.objects(user_id=user.pk)
        if date_filter_start_utc:
            mstories_query = mstories_query.filter(starred_date__gte=date_filter_start_utc)
        if date_filter_end_utc:
            mstories_query = mstories_query.filter(starred_date__lt=date_filter_end_utc)
        mstories = mstories_query.order_by("%sstarred_date" % order_by)[offset : offset + limit]
        stories = Feed.format_stories(mstories)


    story_hashes = [story["story_hash"] for story in stories]
    story_feed_ids = list(set(s["story_feed_id"] for s in stories))
    usersub_ids = UserSubscription.objects.filter(user__pk=user.pk, feed__pk__in=story_feed_ids).values(
        "feed__pk"
    )
    usersub_ids = [us["feed__pk"] for us in usersub_ids]
    unsub_feed_ids = list(set(story_feed_ids).difference(set(usersub_ids)))
    unsub_feeds = Feed.objects.filter(pk__in=unsub_feed_ids)
    unsub_feeds = dict((feed.pk, feed.canonical(include_favicon=False)) for feed in unsub_feeds)
    for story in stories:
        if story["story_feed_id"] in unsub_feeds:
            continue
        duplicate_feed = DuplicateFeed.objects.filter(duplicate_feed_id=story["story_feed_id"])
        if not duplicate_feed:
            continue
        feed_id = duplicate_feed[0].feed_id
        try:
            saved_story = MStarredStory.objects.get(user_id=user.pk, story_hash=story["story_hash"])
            saved_story.feed_id = feed_id
            _, story_hash = MStory.split_story_hash(story["story_hash"])
            saved_story.story_hash = "%s:%s" % (feed_id, story_hash)
            saved_story.story_feed_id = feed_id
            story["story_hash"] = saved_story.story_hash
            story["story_feed_id"] = saved_story.story_feed_id
            saved_story.save()
            logging.user(
                request, "~FCSaving new feed for starred story: ~SB%s -> %s" % (story["story_hash"], feed_id)
            )
        except (MStarredStory.DoesNotExist, MStarredStory.MultipleObjectsReturned):
            logging.user(request, "~FCCan't find feed for starred story: ~SB%s" % (story["story_hash"]))
            continue


    # Look up actual read status for starred stories from Redis
    r = redis.Redis(connection_pool=settings.REDIS_STORY_HASH_POOL)
    read_stories_key = "RS:%s" % user.pk
    story_hash_list = [s["story_hash"] for s in stories]
    if story_hash_list:
        pipeline = r.pipeline()
        for sh in story_hash_list:
            pipeline.sismember(read_stories_key, sh)
        read_results = pipeline.execute()
        read_story_hashes = {sh for sh, is_read in zip(story_hash_list, read_results) if is_read}
    else:
        read_story_hashes = set()

    nowtz = localtime_for_timezone(now, user.profile.timezone)
    for story in stories:
        story_date = localtime_for_timezone(story["story_date"], user.profile.timezone)
        story["short_parsed_date"] = format_story_link_date__short(story_date, nowtz)
        story["long_parsed_date"] = format_story_link_date__long(story_date, nowtz)
        starred_date = localtime_for_timezone(story["starred_date"], user.profile.timezone)
        story["starred_date"] = format_story_link_date__long(starred_date, nowtz)
        story["starred_timestamp"] = int(starred_date.timestamp())
        story["read_status"] = 1 if story["story_hash"] in read_story_hashes else 0
        story["starred"] = True
        story["intelligence"] = {
            "feed": 1,
            "author": 0,
            "tags": 0,
            "title": 0,
            "title_regex": 0,
            "text": 0,
            "text_regex": 0,
            "url": 0,
            "url_regex": 0,
        }
    search_log = "~SN~FG(~SB%s~SN)" % query if query else ""
    logging.user(request, "~FCLoading starred stories: ~SB%s stories %s" % (len(stories), search_log))

    return {
        "stories": stories,
        "feeds": list(unsub_feeds.values()) if version == 2 else unsub_feeds,
        "message": message,
    }



@json.json_view
def starred_story_hashes(request):
    user = get_user(request)
    include_timestamps = is_true(request.GET.get("include_timestamps", False))

    mstories = (
        MStarredStory.objects(user_id=user.pk)
        .only("story_hash", "starred_date", "starred_updated")
        .order_by("-starred_date")
    )

    if include_timestamps:
        story_hashes = []
        for s in mstories:
            date = s.starred_date
            if s.starred_updated:
                date = s.starred_updated
            story_hashes.append((s.story_hash, date.strftime("%s")))
    else:
        story_hashes = [s.story_hash for s in mstories]

    logging.user(request, "~FYLoading ~FCstarred story hashes~FY: %s story hashes" % (len(story_hashes)))

    return dict(starred_story_hashes=story_hashes)



@ajax_login_required
@json.json_view
def starred_counts(request):
    starred_counts, starred_count = MStarredStoryCounts.user_counts(request.user.pk, include_total=True)
    logging.user(
        request,
        "~FCRequesting starred counts: ~SB%s stories (%s tags)"
        % (starred_count, len([s for s in starred_counts if s["tag"]])),
    )

    return {"starred_count": starred_count, "starred_counts": starred_counts}



@ajax_login_required
@json.json_view
def rename_starred_tag(request):
    """Rename a user's saved story tag across all their starred stories."""
    old_tag = request.POST.get("old_tag_name", "").strip()
    new_tag = request.POST.get("new_tag_name", "").strip()

    if not old_tag:
        return {"code": -1, "message": gettext("Original tag name is required.")}

    if not new_tag:
        return {"code": -1, "message": gettext("New tag name is required.")}

    if len(new_tag) > 128:
        return {"code": -1, "message": gettext("Tag name must be 128 characters or less.")}

    logging.user(request, "~FCRenaming starred tag: ~SB%s~SN to ~SB%s" % (old_tag, new_tag))

    starred_counts = MStarredStoryCounts.rename_tag(request.user.pk, old_tag, new_tag)

    if starred_counts is None:
        return {"code": -1, "message": gettext("Failed to rename tag.")}

    return {"code": 1, "starred_counts": starred_counts}



@ajax_login_required
@require_POST
@json.json_view
def delete_starred_tag(request):
    """Remove a tag from all user's starred stories (stories remain saved)."""
    tag_name = request.POST.get("tag_name", "").strip()

    if not tag_name:
        return {"code": -1, "message": gettext("Tag name is required.")}

    logging.user(request, "~FCDeleting starred tag: ~SB%s" % tag_name)

    starred_counts = MStarredStoryCounts.delete_tag(request.user.pk, tag_name)

    if starred_counts is None:
        return {"code": -1, "message": gettext("Failed to delete tag.")}

    return {"code": 1, "starred_counts": starred_counts}



@required_params("story_id", feed_id=int)
@ajax_login_required
@json.json_view
def mark_story_as_starred(request):
    return _mark_story_as_starred(request)



@required_params("story_hash")
@ajax_login_required
@json.json_view
def mark_story_hash_as_starred(request):
    return _mark_story_as_starred(request)



def _mark_story_as_starred(request):
    code = 1
    feed_id = int(request.POST.get("feed_id", 0))
    story_id = request.POST.get("story_id", None)
    user_tags = request.POST.getlist("user_tags") or request.POST.getlist("user_tags[]")
    user_notes = request.POST.get("user_notes", None)
    highlights = request.POST.getlist("highlights") or request.POST.getlist("highlights[]") or []
    message = ""
    story_hashes = request.POST.getlist("story_hash") or request.POST.getlist("story_hash[]")
    datas = []
    if not len(story_hashes):
        story, _ = MStory.find_story(story_feed_id=feed_id, story_id=story_id)
        if story:
            story_hashes = [story.story_hash]

    if not len(story_hashes):
        return {"code": -1, "message": gettext("Could not find story to save.")}

    for story_hash in story_hashes:
        story, _ = MStory.find_story(story_hash=story_hash)
        if not story:
            logging.user(request, "~FCStarring ~FRfailed~FC: %s not found" % (story_hash))
            datas.append(
                {"code": -1, "message": gettext("Could not save story, not found"), "story_hash": story_hash}
            )
            continue

        feed_id = story and story.story_feed_id

        # mongoengine exposed the raw document as _data; the columns are the same thing now.
        story_db = {
            field.name: getattr(story, field.name)
            for field in story._meta.concrete_fields
            if not field.auto_created and getattr(story, field.name, None) is not None
        }
        # Pop all existing user-specific fields because we don't want to reuse them from the found story
        # in case MStory.find_story uses somebody else's saved/shared story (because the original is deleted)
        story_db.pop("user_id", None)
        story_db.pop("starred_date", None)
        story_db.pop("id", None)
        story_db.pop("user_tags", None)
        story_db.pop("highlights", None)
        story_db.pop("user_notes", None)

        now = datetime.datetime.now()
        story_values = dict(
            starred_date=now, user_tags=user_tags, highlights=highlights, user_notes=user_notes, **story_db
        )
        params = dict(story_guid=story.story_guid, user_id=request.user.pk)
        starred_story = MStarredStory.objects(**params).limit(1)
        created = False
        changed_user_notes = False
        removed_user_tags = []
        removed_highlights = []
        if not starred_story:
            params.update(story_values)
            if "story_latest_content_z" in params:
                params.pop("story_latest_content_z")
            try:
                starred_story = MStarredStory.objects.create(**params)
            except OperationError as e:
                logging.user(
                    request, "~FCStarring ~FRfailed~FC: ~SB%s (~FM~SB%s~FC~SN)" % (story.story_title[:32], e)
                )
                datas.append(
                    {"code": -1, "message": "Could not save story due to: %s" % e, "story_hash": story_hash}
                )
                continue

            created = True
            new_user_tags = user_tags
            new_highlights = highlights
            changed_user_notes = bool(user_notes)
            MStarredStoryCounts.adjust_count(request.user.pk, feed_id=feed_id, amount=1)
        else:
            starred_story = starred_story[0]
            new_user_tags = list(set(user_tags) - set(starred_story.user_tags or []))
            removed_user_tags = list(set(starred_story.user_tags or []) - set(user_tags))
            new_highlights = list(set(highlights) - set(starred_story.highlights or []))
            removed_highlights = list(set(starred_story.highlights or []) - set(highlights))
            changed_user_notes = bool(user_notes != starred_story.user_notes)
            starred_story.user_tags = user_tags
            starred_story.highlights = highlights
            starred_story.user_notes = user_notes
            try:
                starred_story.save()
            except NotUniqueError as e:
                # A double click or a retried request can unsave the story between the
                # lookup above and this save, which turns the update into an upsert that
                # collides on the unique user_id/story_guid index.
                logging.user(
                    request, "~FCStarring ~FRfailed~FC: ~SB%s (~FM~SB%s~FC~SN)" % (story.story_title[:32], e)
                )
                datas.append(
                    {"code": -1, "message": "Could not save story due to: %s" % e, "story_hash": story_hash}
                )
                continue

        if len(highlights) == 1 and len(new_highlights) == 1:
            MStarredStoryCounts.adjust_count(request.user.pk, highlights=True, amount=1)
        elif len(highlights) == 0 and len(removed_highlights):
            MStarredStoryCounts.adjust_count(request.user.pk, highlights=True, amount=-1)

        for tag in new_user_tags:
            MStarredStoryCounts.adjust_count(request.user.pk, tag=tag, amount=1)
        for tag in removed_user_tags:
            MStarredStoryCounts.adjust_count(request.user.pk, tag=tag, amount=-1)

        if random.random() < 0.01:
            MStarredStoryCounts.schedule_count_tags_for_user(request.user.pk)
        MStarredStoryCounts.count_for_user(request.user.pk, total_only=True)
        starred_counts, starred_count = MStarredStoryCounts.user_counts(request.user.pk, include_total=True)
        if not starred_count and len(starred_counts):
            starred_count = MStarredStory.objects(user_id=request.user.pk).count()

        if not changed_user_notes:
            r = redis.Redis(connection_pool=settings.REDIS_PUBSUB_POOL)
            r.publish(request.user.username, "story:starred:%s" % story.story_hash)

        if created:
            logging.user(
                request,
                "~FCStarring: ~SB%s (~FM~SB%s~FC~SN)" % (story.story_title[:32], starred_story.user_tags),
            )
        else:
            logging.user(
                request,
                "~FCUpdating starred:~SN~FC ~SB%s~SN (~FM~SB%s~FC~SN/~FM%s~FC)"
                % (story.story_title[:32], starred_story.user_tags, starred_story.user_notes),
            )

        datas.append(
            {
                "code": code,
                "message": message,
                "starred_count": starred_count,
                "starred_counts": starred_counts,
            }
        )

    if len(datas) >= 2:
        return datas
    elif len(datas) == 1:
        return datas[0]
    return datas



@required_params("story_id")
@ajax_login_required
@json.json_view
def mark_story_as_unstarred(request):
    return _mark_story_as_unstarred(request)



@required_params("story_hash")
@ajax_login_required
@json.json_view
def mark_story_hash_as_unstarred(request):
    return _mark_story_as_unstarred(request)



def _mark_story_as_unstarred(request):
    code = 1
    story_id = request.POST.get("story_id", None)
    story_hashes = request.POST.getlist("story_hash") or request.POST.getlist("story_hash[]")
    starred_counts = None
    starred_story = None
    if story_id:
        starred_story = MStarredStory.objects(user_id=request.user.pk, story_guid=story_id)
        if starred_story:
            starred_story = starred_story[0]
            story_hashes = [starred_story.story_hash]
        else:
            story_hashes = [story_id]

    datas = []
    for story_hash in story_hashes:
        starred_story = MStarredStory.objects(user_id=request.user.pk, story_hash=story_hash)
        if not starred_story:
            logging.user(request, "~FCUnstarring ~FRfailed~FC: %s not found" % (story_hash))
            datas.append(
                {
                    "code": -1,
                    "message": gettext("Could not unsave story, not found"),
                    "story_hash": story_hash,
                }
            )
            continue

        try:
            starred_story = starred_story[0]
        except IndexError:
            # Two unsaves racing each other (double click, retried request) can delete the
            # story between the check above and this fetch, leaving an empty cursor.
            logging.user(request, "~FCUnstarring ~FRfailed~FC: %s not found" % (story_hash))
            datas.append(
                {
                    "code": -1,
                    "message": gettext("Could not unsave story, not found"),
                    "story_hash": story_hash,
                }
            )
            continue

        logging.user(request, "~FCUnstarring: ~SB%s" % (starred_story.story_title[:50]))
        user_tags = starred_story.user_tags
        feed_id = starred_story.story_feed_id
        starred_story.user_id = 0
        try:
            starred_story.save()
        except NotUniqueError:
            starred_story.delete()

        MStarredStoryCounts.adjust_count(request.user.pk, feed_id=feed_id, amount=-1)

        for tag in user_tags:
            try:
                MStarredStoryCounts.adjust_count(request.user.pk, tag=tag, amount=-1)
            except MStarredStoryCounts.DoesNotExist:
                pass
        MStarredStoryCounts.schedule_count_tags_for_user(request.user.pk)
        MStarredStoryCounts.count_for_user(request.user.pk, total_only=True)
        starred_counts = MStarredStoryCounts.user_counts(request.user.pk)

        r = redis.Redis(connection_pool=settings.REDIS_PUBSUB_POOL)
        r.publish(request.user.username, "story:unstarred:%s" % starred_story.story_hash)

    if not story_hashes:
        datas.append(dict(code=-1, message=f"Failed to find {story_hashes}"))

    return {"code": code, "starred_counts": starred_counts, "messages": datas}
