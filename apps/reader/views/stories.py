"""River story loading, pagination helpers and unread hashes.

Split from apps/reader/views.py; see apps/reader/views/__init__.py.
"""

from ._base import *  # noqa: F401,F403
from apps.rss_feeds import search as story_search



@json.json_view
def load_river_stories__redis(request):
    # get_post is request.REQUEST, since this endpoint needs to handle either
    # GET or POST requests, since the parameters for this endpoint can be
    # very long, at which point the max size of a GET url request is exceeded.
    get_post = getattr(request, request.method)
    limit = int_or_default(get_post.get("limit", 12), 12)
    start = time.time()
    user = get_user(request)
    message = None
    search_truncated = False
    search_scanned = 0
    feed_ids = get_post.getlist("feeds") or get_post.getlist("feeds[]")
    feed_ids = int_feed_ids(feed_ids)
    if not feed_ids:
        feed_ids = get_post.getlist("f") or get_post.getlist("f[]")
        feed_ids = int_feed_ids(get_post.getlist("f"))
    story_hashes = get_post.getlist("h") or get_post.getlist("h[]")
    story_hashes = story_hashes[:100]
    requested_hashes = len(story_hashes)
    original_feed_ids = list(feed_ids)
    page = int_or_default(get_post.get("page", 1), 1)
    order = get_post.get("order", "newest")
    read_filter = get_post.get("read_filter", "unread")
    if page > 400 and not story_hashes:
        logging.user(request, "~BR~FK~SBOver page 400 on river stories: %s" % page)
        raise Http404
    date_filter_start = get_post.get("date_filter_start")
    date_filter_end = get_post.get("date_filter_end")
    # Sanitize date filters - JS sends "null" as a string
    if date_filter_start in ("null", "None", "", None):
        date_filter_start = None
    if date_filter_end in ("null", "None", "", None):
        date_filter_end = None

    query = get_post.get("query", "").strip()
    (
        classifier_filter_type,
        classifier_filter_value,
        classifier_filter_scope,
    ) = normalize_classifier_filter_params(
        get_post.get("classifier_filter_type"),
        get_post.get("classifier_filter_value"),
        get_post.get("classifier_filter_scope"),
    )
    # Classifier filters are per-site in the personal edition (mirrors the
    # scope handling in apps/analyzer/views.py).
    if classifier_filter_scope != "feed":
        classifier_filter_scope = "feed"
    include_hidden = is_true(get_post.get("include_hidden", False))
    include_feeds = is_true(get_post.get("include_feeds", False))
    on_dashboard = is_true(get_post.get("dashboard", False)) or is_true(get_post.get("on_dashboard", False))
    infrequent = is_true(get_post.get("infrequent", False))
    if infrequent:
        infrequent = get_post.get("infrequent")

    # Log when read_filter is "all" to understand why ZUNIONSTORE uses zF: keys
    if read_filter == "all":
        logging.user(
            request,
            f"~FRload_river_stories read_filter=all (before adjust), page={page}, on_dashboard={on_dashboard}",
        )
    now = localtime_for_timezone(datetime.datetime.now(), user.profile.timezone)
    usersubs = []
    code = 1
    effective_limit = (
        limit * CLASSIFIER_FILTER_SCAN_MULTIPLIER
        if (classifier_filter_type and classifier_filter_value)
        else limit
    )
    offset = (page - 1) * effective_limit
    story_date_order = "%sstory_date" % ("" if order == "oldest" else "-")

    # Android app duplicate request deduplication - only kicks in when concurrent requests detected
    # The Android app has a bug where it fires multiple identical requests simultaneously
    platform = extract_user_agent(request)
    is_android = platform in ["Androd", "androd"]
    deduper = None
    if is_android and not story_hashes and not query:
        feeds_hash = hashlib.md5(",".join(str(f) for f in sorted(feed_ids)).encode()).hexdigest()[:12]
        cache_key = (
            f"river:{user.pk}:{feeds_hash}:{page}:{order}:{read_filter}:{date_filter_start}:{date_filter_end}"
        )
        deduper = RequestDeduplicator(request, cache_key)
        cached = deduper.check_for_duplicate()
        if cached is not None:
            return cached

    if infrequent:
        feed_ids = Feed.low_volume_feeds(feed_ids, stories_per_month=infrequent)

    if story_hashes:
        unread_feed_story_hashes = None
        read_filter = "all"
        mstories = MStory.objects(story_hash__in=story_hashes).order_by(story_date_order)
        stories = Feed.format_stories(mstories)
    elif query:
        usersubs = UserSubscription.subs_for_feeds(user.pk, feed_ids=feed_ids, read_filter="all")
        feed_ids = [sub.feed_id for sub in usersubs]
        if infrequent:
            feed_ids = Feed.low_volume_feeds(feed_ids, stories_per_month=infrequent)
        parsed_query = story_search.parse(query)
        if parsed_query.errors:
            message = parsed_query.errors[0]
            stories = []
        else:
            # Search is per-reader: title/author/url/feed/folder/tag/date need the
            # reader for folder and tag lookups, and body:/read:/star: are not
            # expressible without one. Without user the model falls back to a raw
            # title match, which silently drops every operator.
            stories = Feed.find_feed_stories(
                feed_ids, query, order=order, offset=offset, limit=limit, user=user
            )
        mstories = stories
        unread_feed_story_hashes = UserSubscription.story_hashes(
            user.pk,
            feed_ids=feed_ids,
            read_filter="unread",
            order=order,
            cutoff_date=user.profile.unread_cutoff,
        )
    else:
        # Only run feed aggregation if stories weren't already fetched via story_hashes or query
        date_filter_start_utc, date_filter_end_utc, date_filter_end_start_utc = normalize_date_filters(
            date_filter_start, date_filter_end, user.profile.timezone
        )

        # Auto-switch from unread to all if date filter extends beyond unread cutoff
        original_read_filter = read_filter
        read_filter = adjust_read_filter_for_date_range(
            read_filter, date_filter_start_utc, date_filter_end_start_utc, user.profile.unread_cutoff
        )

        # Log if read_filter changed after adjust
        if original_read_filter != read_filter:
            logging.user(
                request,
                f"~FRload_river_stories read_filter changed: {original_read_filter} -> {read_filter} (after adjust)",
            )

        if read_filter == "starred":
            mstories = MStarredStory.objects(user_id=user.pk, story_feed_id__in=feed_ids).order_by(
                "%sstarred_date" % ("-" if order == "newest" else "")
            )[offset : offset + effective_limit]
            stories = Feed.format_stories(mstories)
            unread_feed_story_hashes = None
        else:
            requested_feed_ids = list(feed_ids)
            if read_filter == "unread":
                cache_usersubs = UserSubscription.subs_for_feeds(
                    user.pk, feed_ids=requested_feed_ids, read_filter="all"
                )
                cache_feed_ids = [sub.feed_id for sub in cache_usersubs]
            else:
                cache_feed_ids = []
            usersubs = UserSubscription.subs_for_feeds(user.pk, feed_ids=feed_ids, read_filter=read_filter)
            feed_ids = [sub.feed_id for sub in usersubs]
            if not cache_feed_ids:
                cache_feed_ids = [sub.feed_id for sub in usersubs]
            if infrequent:
                feed_ids = Feed.low_volume_feeds(feed_ids, stories_per_month=infrequent)
                cache_feed_ids = Feed.low_volume_feeds(cache_feed_ids, stories_per_month=infrequent)

            if feed_ids:
                params = {
                    "user_id": user.pk,
                    "feed_ids": feed_ids,
                    "all_feed_ids": cache_feed_ids,
                    "offset": offset,
                    "limit": effective_limit,
                    "order": order,
                    "read_filter": read_filter,
                    "usersubs": usersubs,
                    "cutoff_date": user.profile.unread_cutoff,
                    "cache_prefix": "dashboard:" if on_dashboard else "",
                    "date_filter_start": date_filter_start_utc,
                    "date_filter_end": date_filter_end_utc,
                    "use_lazy_merge": user.pk in RIVER_SLOWDOWN_USERS,
                }
                story_hashes, unread_feed_story_hashes = UserSubscription.feed_stories(**params)

                def fetch_more_story_hashes(fetch_limit):
                    refill_params = dict(params)
                    refill_params["limit"] = fetch_limit
                    return UserSubscription.feed_stories(**refill_params)

                story_hashes, unread_feed_story_hashes, mstories = load_existing_mstories(
                    user.pk,
                    story_hashes,
                    unread_feed_story_hashes,
                    story_date_order,
                    effective_limit,
                    fetch_more=fetch_more_story_hashes,
                )
            else:
                story_hashes = []
                unread_feed_story_hashes = []
                mstories = []

            stories = Feed.format_stories(mstories)

    search_truncated = bool(getattr(stories, "truncated", False))
    search_scanned = int(getattr(stories, "scanned", 0))

    if classifier_filter_type and classifier_filter_value:
        stories = filter_stories_by_classifier(stories, classifier_filter_type, classifier_filter_value)

    checkpoint1 = time.time()
    found_feed_ids = list(set([story["story_feed_id"] for story in stories]))
    checkpoint2 = time.time()

    if not usersubs:
        usersubs = UserSubscription.subs_for_feeds(user.pk, feed_ids=found_feed_ids, read_filter=read_filter)

    trained_feed_ids = [sub.feed_id for sub in usersubs if sub.is_trained]
    found_trained_feed_ids = list(set(trained_feed_ids) & set(found_feed_ids))

    # Find starred stories
    if found_feed_ids:
        # Only reuse mstories directly when we know it contains MStarredStory objects
        # (i.e., when read_filter is "starred" and we're not searching or fetching specific hashes)
        if read_filter == "starred" and not query and not requested_hashes:
            starred_stories = mstories
        else:
            story_hashes = [s["story_hash"] for s in stories]
            starred_stories = MStarredStory.objects(user_id=user.pk, story_hash__in=story_hashes)
        starred_stories = dict(
            [
                (
                    story.story_hash,
                    dict(
                        starred_date=story.starred_date,
                        user_tags=story.user_tags,
                        highlights=story.highlights,
                        user_notes=story.user_notes,
                    ),
                )
                for story in starred_stories
            ]
        )
    else:
        starred_stories = {}

    # Intelligence classifiers for all feeds involved
    if found_trained_feed_ids:
        if found_trained_feed_ids:
            classifier_feeds = list(
                MClassifierFeed.objects(user_id=user.pk, feed_id__in=found_trained_feed_ids, social_user_id=0)
            )
            classifier_authors = list(
                MClassifierAuthor.objects(user_id=user.pk, feed_id__in=found_trained_feed_ids)
            )
            classifier_titles = list(
                MClassifierTitle.objects(user_id=user.pk, feed_id__in=found_trained_feed_ids)
            )
            classifier_tags = list(
                MClassifierTag.objects(user_id=user.pk, feed_id__in=found_trained_feed_ids)
            )
            classifier_texts = list(
                MClassifierText.objects(user_id=user.pk, feed_id__in=found_trained_feed_ids)
            )
            classifier_urls = list(
                MClassifierUrl.objects(user_id=user.pk, feed_id__in=found_trained_feed_ids)
            )
        else:
            classifier_feeds = []
            classifier_authors = []
            classifier_titles = []
            classifier_tags = []
            classifier_texts = []
            classifier_urls = []
    else:
        classifier_feeds = []
        classifier_authors = []
        classifier_titles = []
        classifier_tags = []
        classifier_texts = []
        classifier_urls = []

    folder_feed_ids = None

    classifiers = sort_classifiers_by_feed(
        user=user,
        feed_ids=found_feed_ids,
        classifier_feeds=classifier_feeds,
        classifier_authors=classifier_authors,
        classifier_titles=classifier_titles,
        classifier_tags=classifier_tags,
        classifier_texts=classifier_texts,
        classifier_urls=classifier_urls,
        folder_feed_ids=folder_feed_ids,
    )
    checkpoint3 = time.time()

    # Just need to format stories
    nowtz = localtime_for_timezone(now, user.profile.timezone)

    # Check if user wants YouTube captions enabled
    user_preferences = json.decode(user.profile.preferences)
    youtube_captions_enabled = user_preferences.get("youtube_captions", False)

    # Look up actual read status for starred stories from Redis
    if read_filter == "starred":
        r2 = redis.Redis(connection_pool=settings.REDIS_STORY_HASH_POOL)
        read_stories_key = "RS:%s" % user.pk
        story_hash_list = [s["story_hash"] for s in stories]
        if story_hash_list:
            pipeline = r2.pipeline()
            for sh in story_hash_list:
                pipeline.sismember(read_stories_key, sh)
            read_results = pipeline.execute()
            starred_read_hashes = {sh for sh, is_read in zip(story_hash_list, read_results) if is_read}
        else:
            starred_read_hashes = set()

    for story in stories:
        if read_filter == "starred":
            story["read_status"] = 1 if story["story_hash"] in starred_read_hashes else 0
        else:
            story["read_status"] = 0
        if read_filter == "all" or query:
            if unread_feed_story_hashes is not None and story["story_hash"] not in unread_feed_story_hashes:
                story["read_status"] = 1
        story_date = localtime_for_timezone(story["story_date"], user.profile.timezone)
        story["short_parsed_date"] = format_story_link_date__short(story_date, nowtz)
        story["long_parsed_date"] = format_story_link_date__long(story_date, nowtz)
        if story["story_hash"] in starred_stories:
            story["starred"] = True
            starred_date = localtime_for_timezone(
                starred_stories[story["story_hash"]]["starred_date"], user.profile.timezone
            )
            story["starred_date"] = format_story_link_date__long(starred_date, nowtz)
            story["starred_timestamp"] = int(starred_date.timestamp())
            story["user_tags"] = starred_stories[story["story_hash"]]["user_tags"]
            story["user_notes"] = starred_stories[story["story_hash"]]["user_notes"]
            story["highlights"] = starred_stories[story["story_hash"]]["highlights"]
        story["intelligence"] = {
            "feed": apply_classifier_feeds(classifier_feeds, story["story_feed_id"]),
            "author": apply_classifier_authors(classifier_authors, story, folder_feed_ids=folder_feed_ids),
            "tags": apply_classifier_tags(classifier_tags, story, folder_feed_ids=folder_feed_ids),
            "title": apply_classifier_titles(classifier_titles, story, folder_feed_ids=folder_feed_ids),
            "title_regex": 0,
            "text": 0,
            "text_regex": 0,
            "url": apply_classifier_urls(classifier_urls, story, folder_feed_ids=folder_feed_ids),
            "url_regex": 0,
            # Prompt classifiers belonged to the AI classifier service, which the
            # personal edition does not ship; the keys stay so the JS keeps working.
            "prompt": 0,
        }
        story["prompt_classifiers"] = []
        story["score"] = UserSubscription.score_story(story["intelligence"])

        # Apply YouTube captions if user preference is enabled
        if youtube_captions_enabled and "story_content" in story and story["story_content"]:
            story["story_content"] = Feed.apply_youtube_captions(story["story_content"])

    if include_feeds:
        feeds = Feed.objects.filter(pk__in=set([story["story_feed_id"] for story in stories]))
        feeds = [feed.canonical(include_favicon=False) for feed in feeds]

    if not include_hidden:
        hidden_stories_removed = 0
        new_stories = []
        for story in stories:
            if story["score"] >= 0:
                new_stories.append(story)
            else:
                hidden_stories_removed += 1
        stories = new_stories

    checkpoint4 = time.time()
    diff = time.time() - start
    timediff = round(float(diff), 2)
    phase_load_stories = checkpoint1 - start
    phase_shared = checkpoint2 - checkpoint1
    phase_classifiers = checkpoint3 - checkpoint2
    phase_finalize = checkpoint4 - checkpoint3
    if requested_hashes and story_hashes:
        logging.user(
            request,
            "~FB%sLoading ~FC%s~FB stories: %s%s"
            % (
                "~FBAuto-" if on_dashboard else "",
                requested_hashes,
                story_hashes[:3],
                f"...(+{len(story_hashes)-3})" if len(story_hashes) > 3 else "",
            ),
        )
    else:
        date_filter_str = ""
        if date_filter_start and date_filter_start != "all":
            date_filter_str = f", dates: {date_filter_start}"
            if date_filter_end and date_filter_end != "all":
                date_filter_str += f" to {date_filter_end}"
        elif date_filter_end and date_filter_end != "all":
            date_filter_str = f", dates: up to {date_filter_end}"

        logging.user(
            request,
            "~FY%sLoading ~FC%sriver stories~FY: ~SBp%s~SN (%s/%s "
            "stories, ~SN%s/%s/%s feeds, %s/%s%s)"
            % (
                "~FCAuto-" if on_dashboard else "",
                "~FB~SBinfrequent~SN~FC " if infrequent else "",
                page,
                len(stories),
                len(mstories),
                len(found_feed_ids),
                len(feed_ids),
                len(original_feed_ids),
                order,
                read_filter,
                date_filter_str,
            ),
        )

    if diff >= 0.25:
        logging.info(
            "reader_load "
            f"endpoint=river read_filter={read_filter} page={page} "
            f"total_ms={int(diff * 1000)} "
            f"load_ms={int(phase_load_stories * 1000)} "
            f"shared_ms={int(phase_shared * 1000)} "
            f"classifiers_ms={int(phase_classifiers * 1000)} "
            f"finalize_ms={int(phase_finalize * 1000)} "
            f"feeds_requested={len(original_feed_ids)} feeds_found={len(found_feed_ids)}"
        )

    data = dict(
        code=code,
        message=message,
        stories=stories,
        classifiers=classifiers,
        elapsed_time=timediff,
        search_truncated=search_truncated,
        search_scanned=search_scanned,
    )

    if include_feeds:
        data["feeds"] = feeds
    if not include_hidden:
        data["hidden_stories_removed"] = hidden_stories_removed

    # Cache result briefly for any waiting duplicate Android requests
    if deduper:
        deduper.cache_result(data)

    return data



@json.json_view
def complete_river(request):
    user = get_user(request)
    feed_ids = request.POST.getlist("feeds") or request.POST.getlist("feeds[]")
    feed_ids = [int(feed_id) for feed_id in feed_ids if feed_id and feed_id.isnumeric()]
    page = int_argument(request.POST, "page", 1)
    read_filter = request.POST.get("read_filter", "unread")
    infrequent = is_true(request.POST.get("infrequent", False))
    if infrequent:
        infrequent = request.POST.get("infrequent")
    stories_truncated = 0

    usersubs = UserSubscription.subs_for_feeds(user.pk, feed_ids=feed_ids, read_filter=read_filter)
    feed_ids = [sub.feed_id for sub in usersubs]
    # Apply infrequent filter to match load_river_stories() behavior
    if infrequent:
        feed_ids = Feed.low_volume_feeds(feed_ids, stories_per_month=infrequent)
    if feed_ids:
        stories_truncated = UserSubscription.truncate_river(
            user.pk, feed_ids, read_filter, cache_prefix="dashboard:"
        )

    if page >= 1:
        logging.user(
            request,
            "~FC~BBRiver complete on page ~SB%s~SN, truncating ~SB%s~SN stories from ~SB%s~SN feeds"
            % (page, stories_truncated, len(feed_ids)),
        )

    return dict(code=1, message="Truncated %s stories from %s" % (stories_truncated, len(feed_ids)))



@json.json_view
def unread_story_hashes(request):
    user = get_user(request)
    feed_ids = request.GET.getlist("feed_id") or request.GET.getlist("feed_id[]")
    feed_ids = [int(feed_id) for feed_id in feed_ids if feed_id]
    include_timestamps = is_true(request.GET.get("include_timestamps", False))
    order = request.GET.get("order", "newest")
    read_filter = request.GET.get("read_filter", "unread")

    story_hashes = UserSubscription.story_hashes(
        user.pk,
        feed_ids=feed_ids,
        order=order,
        read_filter=read_filter,
        include_timestamps=include_timestamps,
        group_by_feed=True,
        cutoff_date=user.profile.unread_cutoff,
    )

    logging.user(
        request,
        "~FYLoading ~FCunread story hashes~FY: ~SB%s feeds~SN (%s story hashes)"
        % (len(feed_ids), len(story_hashes)),
    )
    return dict(unread_feed_story_hashes=story_hashes)



@json.json_view
def load_read_stories(request):
    user = get_user(request)
    offset = int_argument(request.GET, "offset", 0)
    limit = int_argument(request.GET, "limit", 10)
    page = int_argument(request.GET, "page", 0)
    order = request.GET.get("order", "newest")
    date_filter_start = request.GET.get("date_filter_start")
    date_filter_end = request.GET.get("date_filter_end")
    # Sanitize date filters - JS sends "null" as a string
    if date_filter_start in ("null", "None", "", None):
        date_filter_start = None
    if date_filter_end in ("null", "None", "", None):
        date_filter_end = None
    query = request.GET.get("query", "").strip()
    now = localtime_for_timezone(datetime.datetime.now(), user.profile.timezone)
    message = None
    search_truncated = False
    search_scanned = 0
    if page:
        offset = limit * (page - 1)

    # Normalize date filters from user timezone to UTC
    date_filter_start_utc, date_filter_end_utc, date_filter_end_start_utc = normalize_date_filters(
        date_filter_start, date_filter_end, user.profile.timezone
    )

    if date_filter_start or date_filter_end:
        logging.user(
            request,
            "~FBDate filters for read stories: start=%s end=%s (UTC: start=%s end=%s)"
            % (date_filter_start, date_filter_end, date_filter_start_utc, date_filter_end_utc),
        )

    # Optional feed_id filtering
    feed_ids = request.GET.getlist("feed_id") or request.GET.getlist("feed_id[]")
    feed_ids = [int(f) for f in feed_ids if f]

    if query:
        # Search only the reader's read list. Searching every subscribed feed and
        # intersecting afterwards had two hard caps (200 search rows and 1,000 read
        # hashes) and ignored the date filter, so deep pages were incomplete.
        search_feed_ids = feed_ids
        if not search_feed_ids:
            usersubs = UserSubscription.objects.filter(user__pk=user.pk).only("feed")
            search_feed_ids = [sub.feed_id for sub in usersubs]
        parsed_query = story_search.parse(query)
        if parsed_query.errors:
            message = parsed_query.errors[0]
            stories = []
        else:
            ordering = "-story_date" if order != "oldest" else "story_date"
            matched_stories = []
            seen_hashes = set()
            for read_story_hashes in RUserStory.iter_read_story_hashes(user.pk):
                batch_hashes = [
                    story_hash
                    for story_hash in read_story_hashes
                    if story_hash and story_hash not in seen_hashes
                ]
                seen_hashes.update(batch_hashes)
                if not batch_hashes or not search_feed_ids:
                    continue
                queryset = MStory.objects(
                    story_hash__in=batch_hashes, story_feed_id__in=search_feed_ids
                )
                if date_filter_start_utc:
                    queryset = queryset.filter(story_date__gte=date_filter_start_utc)
                if date_filter_end_utc:
                    # normalize_date_filters returns an exclusive end, so a story
                    # at midnight the next day must not appear in the previous day.
                    queryset = queryset.filter(story_date__lt=date_filter_end_utc)
                queryset = story_search.build_queryset(queryset, parsed_query, user)
                matched_stories.extend(
                    story_search.collect_story_queryset(queryset, parsed_query, user, ordering)
                )
            if matched_stories:
                # Each batch is ordered by the database; merge them in Python so
                # offset counts the whole read history, not the first 1,000 rows.
                matched_stories.sort(
                    key=lambda story: (story.story_date or datetime.datetime.min, story.id),
                    reverse=bool(order != "oldest"),
                )
                stories = Feed.format_stories(matched_stories[offset : offset + limit])
            else:
                stories = []
    else:
        story_hashes = RUserStory.get_read_stories(
            user.pk,
            offset=offset,
            limit=limit,
            order=order,
            date_filter_start=date_filter_start_utc,
            date_filter_end=date_filter_end_utc,
        )
        mstories = MStory.objects(story_hash__in=story_hashes).order_by()
        stories = Feed.format_stories(mstories)
        stories = sorted(
            stories,
            key=lambda story: story_hashes.index(story["story_hash"]),
            reverse=bool(order == "oldest"),
        )
        # Apply feed_id filter if specified
        if feed_ids:
            stories = [s for s in stories if s["story_feed_id"] in feed_ids]

    search_truncated = bool(getattr(stories, "truncated", False))
    search_scanned = int(getattr(stories, "scanned", 0))

    story_hashes = [story["story_hash"] for story in stories]
    story_feed_ids = list(set(s["story_feed_id"] for s in stories))
    usersub_ids = UserSubscription.objects.filter(user__pk=user.pk, feed__pk__in=story_feed_ids).values(
        "feed__pk"
    )
    usersub_ids = [us["feed__pk"] for us in usersub_ids]
    unsub_feed_ids = list(set(story_feed_ids).difference(set(usersub_ids)))
    unsub_feeds = Feed.objects.filter(pk__in=unsub_feed_ids)
    unsub_feeds = [feed.canonical(include_favicon=False) for feed in unsub_feeds]

    starred_stories = MStarredStory.objects(user_id=user.pk, story_hash__in=story_hashes).hint(
        [("user_id", 1), ("story_hash", 1)]
    )
    starred_stories = dict([(story.story_hash, story) for story in starred_stories])

    nowtz = localtime_for_timezone(now, user.profile.timezone)
    for story in stories:
        story_date = localtime_for_timezone(story["story_date"], user.profile.timezone)
        story["short_parsed_date"] = format_story_link_date__short(story_date, nowtz)
        story["long_parsed_date"] = format_story_link_date__long(story_date, nowtz)
        story["read_status"] = 1
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
        if story["story_hash"] in starred_stories:
            story["starred"] = True
            starred_story = Feed.format_story(starred_stories[story["story_hash"]])
            starred_date = localtime_for_timezone(starred_story["starred_date"], user.profile.timezone)
            story["starred_date"] = format_story_link_date__long(starred_date, nowtz)
            story["starred_timestamp"] = int(starred_date.timestamp())
    search_log = "~SN~FG(~SB%s~SN)" % query if query else ""
    logging.user(request, "~FCLoading read stories: ~SB%s stories %s" % (len(stories), search_log))

    return {
        "stories": stories,
        "feeds": unsub_feeds,
        "message": message,
        "search_truncated": search_truncated,
        "search_scanned": search_scanned,
    }



def prune_missing_river_story_hashes(user_id, story_hashes):
    if not story_hashes:
        return

    r = redis.Redis(connection_pool=settings.REDIS_STORY_HASH_POOL)
    pipeline = r.pipeline()
    unique_story_hashes = []
    seen_story_hashes = set()

    for story_hash in story_hashes:
        if isinstance(story_hash, bytes):
            story_hash = story_hash.decode()
        if story_hash in seen_story_hashes:
            continue
        seen_story_hashes.add(story_hash)
        unique_story_hashes.append(story_hash)

    for story_hash in unique_story_hashes:
        feed_id = story_hash.split(":", 1)[0]
        pipeline.srem(f"F:{feed_id}", story_hash)
        pipeline.zrem(f"zF:{feed_id}", story_hash)
        pipeline.zrem(f"zU:{user_id}:{feed_id}", story_hash)
        pipeline.zrem(f"uU:{user_id}:{feed_id}", story_hash)
        pipeline.zrem(f"uU:{user_id}", story_hash)

    pipeline.execute()



def load_existing_mstories(
    user_id, story_hashes, unread_feed_story_hashes, story_date_order, limit, fetch_more=None
):
    if not story_hashes:
        return story_hashes, unread_feed_story_hashes, []

    current_story_hashes = story_hashes
    current_unread_feed_story_hashes = unread_feed_story_hashes
    fetch_limit = min(len(current_story_hashes), limit)
    max_fetch_limit = max(limit * 32, 400)

    while True:
        candidate_hashes = current_story_hashes[:fetch_limit]
        mstories = list(MStory.objects(story_hash__in=candidate_hashes).order_by(story_date_order))
        found_story_hashes = {story.story_hash for story in mstories}
        missing_story_hashes = [
            story_hash for story_hash in candidate_hashes if story_hash not in found_story_hashes
        ]

        if missing_story_hashes:
            prune_missing_river_story_hashes(user_id, missing_story_hashes)

        if (
            len(mstories) >= limit
            or len(candidate_hashes) < fetch_limit
            or not fetch_more
            or fetch_limit >= max_fetch_limit
        ):
            return current_story_hashes, current_unread_feed_story_hashes, mstories

        next_fetch_limit = min(fetch_limit * 2, max_fetch_limit)
        if next_fetch_limit <= fetch_limit:
            return current_story_hashes, current_unread_feed_story_hashes, mstories

        current_story_hashes, current_unread_feed_story_hashes = fetch_more(next_fetch_limit)
        if len(current_story_hashes) <= fetch_limit:
            return current_story_hashes, current_unread_feed_story_hashes, mstories

        fetch_limit = min(next_fetch_limit, len(current_story_hashes))
