"""Subscription list loading, fetch queues and single-feed story loading.

Split from apps/reader/views.py; see apps/reader/views/__init__.py.
"""

from ._base import *  # noqa: F401,F403
from apps.rss_feeds import search as story_search
from ._base import _get_url_variants



@ratelimit(minutes=1, requests=60)
@never_cache
@json.json_view
def load_feeds(request):
    user = get_user(request)
    feeds = {}
    include_favicons = is_true(request.GET.get("include_favicons", False))
    flat = is_true(request.GET.get("flat", False))
    update_counts = is_true(request.GET.get("update_counts", True))
    try:
        version = int(request.GET.get("v", 1))
    except (ValueError, TypeError):
        version = 1

    if include_favicons == "false":
        include_favicons = False
    if update_counts == "false":
        update_counts = False
    if flat == "false":
        flat = False

    if flat:
        return load_feeds_flat(request)

    platform = extract_user_agent(request)
    if platform in ["iPhone", "iPad", "Androd"]:
        # Remove this check once the iOS and Android updates go out which have update_counts=False
        # and then guarantee a refresh_feeds call
        update_counts = False

    try:
        folders = UserSubscriptionFolders.objects.get(user=user)
    except UserSubscriptionFolders.DoesNotExist:
        data = dict(feeds=[], folders=[])
        return data
    except UserSubscriptionFolders.MultipleObjectsReturned:
        UserSubscriptionFolders.objects.filter(user=user)[1:].delete()
        folders = UserSubscriptionFolders.objects.get(user=user)

    # similar_feeds is part of every feed payload, so fetch the whole set up
    # front instead of once per subscription. apps/reader/views/feeds.py
    user_subs = (
        UserSubscription.objects.select_related("feed")
        .prefetch_related("feed__similar_feeds")
        .filter(user=user)
    )

    now = datetime.datetime.now()
    day_ago = now - datetime.timedelta(days=1)
    scheduled_feeds = []
    expired_mute_ids = []
    for sub in user_subs:
        # Auto-unmute expired timed mutes inline (no extra query)
        if not sub.active and sub.mute_expires_at and sub.mute_expires_at <= now:
            sub.active = True
            sub.mute_expires_at = None
            expired_mute_ids.append(sub.pk)

        pk = sub.feed_id
        if update_counts and sub.needs_unread_recalc:
            sub.calculate_feed_scores(silent=True)
        feeds[pk] = sub.canonical(include_favicon=include_favicons)

        if not sub.active:
            continue
        if not sub.feed.active and not sub.feed.has_feed_exception:
            scheduled_feeds.append(sub.feed.pk)
        elif sub.feed.active_subscribers <= 0:
            scheduled_feeds.append(sub.feed.pk)
        elif sub.feed.next_scheduled_update < day_ago:
            scheduled_feeds.append(sub.feed.pk)

    if expired_mute_ids:
        UserSubscription.objects.filter(pk__in=expired_mute_ids).update(active=True, mute_expires_at=None)
        logging.user(request, "~BB~FWAuto-unmuted ~SB%s~SN expired feeds" % len(expired_mute_ids))

    if len(scheduled_feeds) > 0 and request.user.is_authenticated:
        logging.user(
            request,
            "~SN~FMTasking the scheduling immediate fetch of ~SB%s~SN feeds..." % len(scheduled_feeds),
        )
        ScheduleImmediateFetches.apply_async(kwargs=dict(feed_ids=scheduled_feeds, user_id=user.pk))

    starred_counts, starred_count = MStarredStoryCounts.user_counts(user.pk, include_total=True)
    if not starred_count and len(starred_counts):
        starred_count = MStarredStory.objects(user_id=user.pk).count()


    dashboard_rivers = MDashboardRiver.get_user_rivers(user.pk)

    folder_icons = MFolderIcon.get_folder_icons_for_user(user.pk)
    folder_icons_dict = {fi.folder_title: fi.to_json() for fi in folder_icons}

    feed_icons = MCustomFeedIcon.get_feed_icons_for_user(user.pk)
    feed_icons_dict = {str(fi.feed_id): fi.to_json() for fi in feed_icons}

    folder_auto_mark_read = MFolderAutoMarkRead.get_folder_settings_for_user(user.pk)
    folder_auto_mark_read_dict = {fs.folder_title: fs.to_json() for fs in folder_auto_mark_read}

    logging.user(
        request,
        "~FB~SBLoading ~FY%s~FB feeds%s"
        % (len(list(feeds.keys())), ". ~FCUpdating counts." if update_counts else ""),
    )

    data = {
        "feeds": list(feeds.values()) if version == 2 else feeds,
        "user_profile": user.profile,
        "is_staff": user.is_staff,
        "user_id": user.pk,
        "folders": json.decode(folders.folders),
        "folder_paths_supported": True,
        "starred_count": starred_count,
        "starred_counts": starred_counts,
        "dashboard_rivers": dashboard_rivers,
        "folder_icons": folder_icons_dict,
        "feed_icons": feed_icons_dict,
        "folder_auto_mark_read": folder_auto_mark_read_dict,
        "playback_state": None,
        "share_ext_token": user.profile.secret_token,
    }
    return data



@json.json_view
def load_feed_favicons(request):
    user = get_user(request)
    feed_ids = request.GET.getlist("feed_ids") or request.GET.getlist("feed_ids[]")

    if not feed_ids:
        user_subs = UserSubscription.objects.select_related("feed").filter(user=user, active=True)
        feed_ids = [sub["feed__pk"] for sub in user_subs.values("feed__pk")]

    feed_icons = dict([(i.feed_id, i.data) for i in MFeedIcon.objects(feed_id__in=feed_ids)])

    return feed_icons



def load_feeds_flat(request):
    user = request.user
    include_favicons = is_true(request.GET.get("include_favicons", False))
    update_counts = is_true(request.GET.get("update_counts", True))
    include_inactive = is_true(request.GET.get("include_inactive", False))
    background_ios = is_true(request.GET.get("background_ios", False))

    feeds = {}
    inactive_feeds = {}
    now = datetime.datetime.now()
    day_ago = now - datetime.timedelta(days=1)
    scheduled_feeds = []
    if include_favicons == "false":
        include_favicons = False
    if update_counts == "false":
        update_counts = False

    if not user.is_authenticated:
        return HttpResponseForbidden()

    try:
        folders = UserSubscriptionFolders.objects.get(user=user)
    except UserSubscriptionFolders.DoesNotExist:
        folders = []

    # Include expired muted feeds alongside active feeds so they get auto-unmuted
    user_subs = (
        UserSubscription.objects.select_related("feed")
        .prefetch_related("feed__similar_feeds")
        .filter(user=user)
        .filter(Q(active=True) | Q(active=False, mute_expires_at__isnull=False, mute_expires_at__lte=now))
    )
    if not user_subs and folders:
        folders.auto_activate()
        user_subs = UserSubscription.objects.select_related("feed").filter(user=user, active=True)
    if include_inactive:
        inactive_subs = UserSubscription.objects.select_related("feed").filter(user=user, active=False)

    expired_mute_ids = []
    for sub in user_subs:
        # Auto-unmute expired timed mutes inline
        if not sub.active and sub.mute_expires_at and sub.mute_expires_at <= now:
            sub.active = True
            sub.mute_expires_at = None
            expired_mute_ids.append(sub.pk)

        pk = sub.feed_id
        if update_counts and sub.needs_unread_recalc:
            sub.calculate_feed_scores(silent=True)
        feeds[pk] = sub.canonical(include_favicon=include_favicons)
        if not sub.feed.active and not sub.feed.has_feed_exception:
            scheduled_feeds.append(sub.feed.pk)
        elif sub.feed.active_subscribers <= 0:
            scheduled_feeds.append(sub.feed.pk)
        elif sub.feed.next_scheduled_update < day_ago:
            scheduled_feeds.append(sub.feed.pk)

    if expired_mute_ids:
        UserSubscription.objects.filter(pk__in=expired_mute_ids).update(active=True, mute_expires_at=None)
        logging.user(request, "~BB~FWAuto-unmuted ~SB%s~SN expired feeds" % len(expired_mute_ids))

    if include_inactive:
        for sub in inactive_subs:
            inactive_feeds[sub.feed_id] = sub.canonical(include_favicon=include_favicons)

    if len(scheduled_feeds) > 0 and request.user.is_authenticated:
        logging.user(
            request,
            "~SN~FMTasking the scheduling immediate fetch of ~SB%s~SN feeds..." % len(scheduled_feeds),
        )
        ScheduleImmediateFetches.apply_async(kwargs=dict(feed_ids=scheduled_feeds, user_id=user.pk))

    flat_folders = []
    flat_folders_with_inactive = []
    if folders:
        flat_folders = folders.flatten_folders(feeds=feeds)
        flat_folders_with_inactive = folders.flatten_folders(feeds=feeds, inactive_feeds=inactive_feeds)

    starred_counts, starred_count = MStarredStoryCounts.user_counts(user.pk, include_total=True)
    if not starred_count and len(starred_counts):
        starred_count = MStarredStory.objects(user_id=user.pk).count()

    dashboard_rivers = MDashboardRiver.get_user_rivers(user.pk)

    folder_icons = MFolderIcon.get_folder_icons_for_user(user.pk)
    folder_icons_dict = {fi.folder_title: fi.to_json() for fi in folder_icons}

    feed_icons = MCustomFeedIcon.get_feed_icons_for_user(user.pk)
    feed_icons_dict = {str(fi.feed_id): fi.to_json() for fi in feed_icons}

    folder_auto_mark_read = MFolderAutoMarkRead.get_folder_settings_for_user(user.pk)
    folder_auto_mark_read_dict = {fs.folder_title: fs.to_json() for fs in folder_auto_mark_read}

    logging.user(
        request,
        "~FB~SBLoading ~FY%s~FB/~FR%s~FB feeds/inactive ~FMflat~FB%s%s"
        % (
            len(list(feeds.keys())),
            len(inactive_feeds),
            ". ~FCUpdating counts." if update_counts else "",
            " ~BB(background fetch)" if background_ios else "",
        ),
    )

    data = {
        "flat_folders": flat_folders,
        "flat_folders_with_inactive": flat_folders_with_inactive,
        "feeds": feeds,
        "inactive_feeds": inactive_feeds if include_inactive else {"0": "Include `include_inactive=true`"},
        "user": user.username,
        "user_id": user.pk,
        "is_staff": user.is_staff,
        "user_profile": user.profile,
        "starred_count": starred_count,
        "starred_counts": starred_counts,
        "dashboard_rivers": dashboard_rivers,
        "folder_icons": folder_icons_dict,
        "feed_icons": feed_icons_dict,
        "folder_auto_mark_read": folder_auto_mark_read_dict,
        "playback_state": None,
        "share_ext_token": user.profile.secret_token,
    }
    return data



class ratelimit_refresh_feeds(ratelimit):
    def should_ratelimit(self, request):
        feed_ids = request.POST.getlist("feed_id") or request.POST.getlist("feed_id[]")
        if len(feed_ids) == 1:
            return False
        return True



@ratelimit_refresh_feeds(minutes=1, requests=30)
@never_cache
@json.json_view
def refresh_feeds(request):
    get_post = getattr(request, request.method)
    start = datetime.datetime.now()
    user = get_user(request)
    feed_ids = get_post.getlist("feed_id") or get_post.getlist("feed_id[]")
    check_fetch_status = get_post.get("check_fetch_status")
    favicons_fetching = get_post.getlist("favicons_fetching") or get_post.getlist("favicons_fetching[]")

    feeds = UserSubscription.feeds_with_updated_counts(
        user, feed_ids=feed_ids, check_fetch_status=check_fetch_status
    )
    checkpoint1 = datetime.datetime.now()
    checkpoint2 = datetime.datetime.now()

    favicons_fetching = [int(f) for f in favicons_fetching if f]
    feed_icons = {}
    if favicons_fetching:
        feed_icons = dict([(i.feed_id, i) for i in MFeedIcon.objects(feed_id__in=favicons_fetching)])
        for feed_id, feed in list(feeds.items()):
            if feed_id in favicons_fetching and feed_id in feed_icons:
                feeds[feed_id]["favicon"] = feed_icons[feed_id].data
                feeds[feed_id]["favicon_color"] = feed_icons[feed_id].color
                feeds[feed_id]["favicon_fetching"] = feed.get("favicon_fetching")

    user_subs = UserSubscription.objects.filter(user=user, active=True).only("feed")
    sub_feed_ids = [s.feed_id for s in user_subs]

    if favicons_fetching:
        moved_feed_ids = [f for f in favicons_fetching if f not in sub_feed_ids]
        for moved_feed_id in moved_feed_ids:
            duplicate_feeds = DuplicateFeed.objects.filter(duplicate_feed_id=moved_feed_id)

            if duplicate_feeds and duplicate_feeds[0].feed.pk in feeds:
                feeds[moved_feed_id] = feeds[duplicate_feeds[0].feed_id]
                feeds[moved_feed_id]["dupe_feed_id"] = duplicate_feeds[0].feed_id

    if check_fetch_status:
        missing_feed_ids = list(set(feed_ids) - set(sub_feed_ids))
        if missing_feed_ids:
            duplicate_feeds = DuplicateFeed.objects.filter(duplicate_feed_id__in=missing_feed_ids)
            for duplicate_feed in duplicate_feeds:
                feeds[duplicate_feed.duplicate_feed_id] = {"id": duplicate_feed.feed_id}

    end = datetime.datetime.now()
    extra_fetch = ""
    if check_fetch_status or favicons_fetching:
        extra_fetch = "(%s/%s)" % (check_fetch_status, len(favicons_fetching))
    logging.user(
        request,
        "~FBRefreshing %s feeds %s (%.4s/%.4s/%.4s)"
        % (
            len(list(feeds.keys())),
            extra_fetch,
            (checkpoint1 - start).total_seconds(),
            (checkpoint2 - start).total_seconds(),
            (end - start).total_seconds(),
        ),
    )

    return {
        "feeds": feeds,
    }



@never_cache
@ajax_login_required
@json.json_view
def feed_unread_count(request):
    get_post = getattr(request, request.method)
    user = request.user
    feed_ids = get_post.getlist("feed_id") or get_post.getlist("feed_id[]")

    force = request.GET.get("force", False)

    feeds = {}
    if feed_ids:
        feeds = UserSubscription.feeds_with_updated_counts(user, feed_ids=feed_ids, force=force)

    if len(feed_ids) == 1:
        if settings.DEBUG:
            feed_title = Feed.get_by_id(feed_ids[0]).feed_title
        else:
            feed_title = feed_ids[0]
    else:
        feed_title = "%s feeds" % len(feeds)
    logging.user(request, "~FBUpdating unread count on: %s" % feed_title)

    return {"feeds": feeds}



@ajax_login_required
def refresh_feed(request, feed_id):
    user = get_user(request)
    feed = get_object_or_404(Feed, pk=feed_id)

    feed = feed.update(force=True, compute_scores=False)
    try:
        usersub = UserSubscription.objects.get(user=user, feed=feed)
    except UserSubscription.DoesNotExist:
        # An unsubscribed user can still refresh a feed, there are just no scores to
        # recalculate. load_single_feed below already handles a missing subscription.
        usersub = None
    if usersub:
        usersub.calculate_feed_scores(silent=False)

    logging.user(request, "~FBRefreshing feed: %s" % feed)

    return load_single_feed(request, feed_id)



@never_cache
@json.json_view
def load_single_feed(request, feed_id):
    start = time.time()
    user = get_user(request)
    # offset                  = int(request.GET.get('offset', 0))
    # limit                   = int(request.GET.get('limit', 6))
    limit = 6
    page = int_or_default(request.GET.get("page", 1), 1)
    delay = int_or_default(request.GET.get("delay", 0), 0)
    (
        classifier_filter_type,
        classifier_filter_value,
        _classifier_filter_scope,
    ) = normalize_classifier_filter_params(
        request.GET.get("classifier_filter_type"),
        request.GET.get("classifier_filter_value"),
        request.GET.get("classifier_filter_scope"),
    )
    # Inflate the fetch window so the post-query filter has enough raw
    # stories to find matches. Offset scales with the inflated page so
    # successive pages don't re-scan the same window.
    effective_limit = (
        limit * CLASSIFIER_FILTER_SCAN_MULTIPLIER
        if classifier_filter_type and classifier_filter_value
        else limit
    )
    offset = effective_limit * (page - 1)
    order = request.GET.get("order", "newest")
    read_filter = request.GET.get("read_filter", "all")
    date_filter_start = request.GET.get("date_filter_start")
    date_filter_end = request.GET.get("date_filter_end")
    # Sanitize date filters - JS sends "null" as a string
    if date_filter_start in ("null", "None", "", None):
        date_filter_start = None
    if date_filter_end in ("null", "None", "", None):
        date_filter_end = None
    query = request.GET.get("query", "").strip()
    include_story_content = is_true(request.GET.get("include_story_content", True))
    include_hidden = is_true(request.GET.get("include_hidden", False))
    include_feeds = is_true(request.GET.get("include_feeds", False))
    message = None

    dupe_feed_id = None
    now = localtime_for_timezone(datetime.datetime.now(), user.profile.timezone)
    if not feed_id:
        raise Http404

    feed_address = request.GET.get("feed_address")
    feed = Feed.get_by_id(feed_id, feed_address=feed_address)
    if not feed:
        raise Http404

    try:
        usersub = UserSubscription.objects.get(user=user, feed=feed)
    except UserSubscription.DoesNotExist:
        usersub = None

    if feed.is_newsletter and not usersub:
        # User must be subscribed to a newsletter in order to read it
        raise Http404

    if feed.num_subscribers == 1 and not usersub and not user.is_staff:
        # This feed could be private so user must be subscribed in order to read it
        raise Http404

    if page > 400:
        logging.user(request, "~BR~FK~SBOver page 400 on single feed: %s" % page)
        raise Http404

    # Synchronous insta-fetch for try-feed mode, triggered by the frontend poll.
    # First request returns fast (showing banners / "fetching" indicator), then
    # poll_for_fetch_completion sends insta_fetch=1 to trigger the actual fetch.
    insta_fetch = is_true(request.GET.get("insta_fetch", False))
    if (
        insta_fetch
        and not usersub
        and (
            not feed.fetched_once
            or feed.last_update < datetime.datetime.utcnow() - datetime.timedelta(days=1)
        )
    ):
        feed = feed.update(force=True, compute_scores=False, verbose=True)
        feed = Feed.get_by_id(feed.pk if feed else feed_id)

    if query:
        parsed_query = story_search.parse(query)
        if parsed_query.errors:
            message = parsed_query.errors[0]
            stories = []
        else:
            stories = feed.find_stories(query, order=order, offset=offset, limit=limit, user=user)
    else:
        # Only run feed aggregation if stories weren't already fetched via query
        date_filter_start_utc, date_filter_end_utc, date_filter_end_start_utc = normalize_date_filters(
            date_filter_start, date_filter_end, user.profile.timezone
        )

        # Auto-switch from unread to all if date filter extends beyond unread cutoff
        read_filter = adjust_read_filter_for_date_range(
            read_filter, date_filter_start_utc, date_filter_end_start_utc, user.profile.unread_cutoff
        )

        # Calculate cutoff date based on auto_mark_read_days setting (for archive users)
        default_cutoff = user.profile.unread_cutoff
        if usersub:
            auto_mark_read_cutoff = usersub.get_auto_mark_read_cutoff()
            # Use the more restrictive (newer) cutoff date
            if auto_mark_read_cutoff:
                cutoff_date = max(auto_mark_read_cutoff, default_cutoff)
            else:
                cutoff_date = default_cutoff
        else:
            cutoff_date = default_cutoff

        if read_filter == "starred":
            mstories = MStarredStory.objects(user_id=user.pk, story_feed_id=feed_id).order_by(
                "%sstarred_date" % ("-" if order == "newest" else "")
            )[offset : offset + effective_limit]
            stories = Feed.format_stories(mstories)
        elif usersub and read_filter == "unread":
            stories = usersub.get_stories(
                order=order,
                read_filter=read_filter,
                offset=offset,
                limit=effective_limit,
                cutoff_date=cutoff_date,
                date_filter_start=date_filter_start_utc,
                date_filter_end=date_filter_end_utc,
            )
        else:
            stories = feed.get_stories(
                offset,
                effective_limit,
                order=order,
                date_filter_start=date_filter_start_utc,
                date_filter_end=date_filter_end_utc,
            )

    if classifier_filter_type and classifier_filter_value:
        stories = filter_stories_by_classifier(stories, classifier_filter_type, classifier_filter_value)

    checkpoint1 = time.time()

    checkpoint2 = time.time()

    # Get intelligence classifier for user

    if usersub and usersub.is_trained:
        classifier_feeds = list(MClassifierFeed.objects(user_id=user.pk, feed_id=feed_id, social_user_id=0))
        classifier_authors = list(MClassifierAuthor.objects(user_id=user.pk, feed_id=feed_id))
        classifier_titles = list(MClassifierTitle.objects(user_id=user.pk, feed_id=feed_id))
        classifier_tags = list(MClassifierTag.objects(user_id=user.pk, feed_id=feed_id))
        classifier_texts = list(MClassifierText.objects(user_id=user.pk, feed_id=feed_id))
        classifier_urls = list(MClassifierUrl.objects(user_id=user.pk, feed_id=feed_id))
    else:
        classifier_feeds = []
        classifier_authors = []
        classifier_titles = []
        classifier_tags = []
        classifier_texts = []
        classifier_urls = []

    folder_feed_ids = None

    classifiers = get_classifiers_for_user(
        user,
        feed_id=feed_id,
        classifier_feeds=classifier_feeds,
        classifier_authors=classifier_authors,
        classifier_titles=classifier_titles,
        classifier_tags=classifier_tags,
        classifier_texts=classifier_texts,
        classifier_urls=classifier_urls,
        folder_feed_ids=folder_feed_ids,
    )
    checkpoint3 = time.time()

    unread_story_hashes = []
    if stories:
        if (read_filter == "all" or query) and usersub:
            # Calculate cutoff date for determining unread status
            # This handles both query and non-query cases
            default_cutoff = user.profile.unread_cutoff
            auto_mark_read_cutoff = usersub.get_auto_mark_read_cutoff()
            if auto_mark_read_cutoff:
                unread_cutoff_date = max(auto_mark_read_cutoff, default_cutoff)
            else:
                unread_cutoff_date = default_cutoff
            unread_story_hashes = UserSubscription.story_hashes(
                user.pk,
                read_filter="unread",
                feed_ids=[usersub.feed_id],
                usersubs=[usersub],
                cutoff_date=unread_cutoff_date,
            )
        story_hashes = [story["story_hash"] for story in stories if story["story_hash"]]
        starred_stories = MStarredStory.objects(
            user_id=user.pk, story_feed_id=feed.pk, story_hash__in=story_hashes
        ).hint([("user_id", 1), ("story_hash", 1)])
        starred_stories = dict([(story.story_hash, story) for story in starred_stories])

    checkpoint4 = time.time()

    # Check if user wants YouTube captions enabled
    user_preferences = json.decode(user.profile.preferences)
    youtube_captions_enabled = user_preferences.get("youtube_captions", False)

    for story in stories:
        # Calculate intelligence BEFORE deleting story content (text classifier needs it)
        story["intelligence"] = {
            "feed": apply_classifier_feeds(classifier_feeds, feed),
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

        if not include_story_content:
            del story["story_content"]
        story_date = localtime_for_timezone(story["story_date"], user.profile.timezone)
        nowtz = localtime_for_timezone(now, user.profile.timezone)
        story["short_parsed_date"] = format_story_link_date__short(story_date, nowtz)
        story["long_parsed_date"] = format_story_link_date__long(story_date, nowtz)
        if usersub:
            story["read_status"] = 1
            if story["story_date"] < user.profile.unread_cutoff:
                story["read_status"] = 1
            elif (read_filter == "all" or query) and usersub:
                story["read_status"] = 1 if story["story_hash"] not in unread_story_hashes else 0
            elif read_filter == "unread" and usersub:
                story["read_status"] = 0
            if story["story_hash"] in starred_stories:
                story["starred"] = True
                starred_story = Feed.format_story(starred_stories[story["story_hash"]])
                starred_date = localtime_for_timezone(starred_story["starred_date"], user.profile.timezone)
                story["starred_date"] = format_story_link_date__long(starred_date, nowtz)
                story["starred_timestamp"] = int(starred_date.timestamp())
                story["user_tags"] = starred_story["user_tags"]
                story["user_notes"] = starred_story["user_notes"]
                story["highlights"] = starred_story["highlights"]
        else:
            story["read_status"] = 1

    # Intelligence
    feed_tags = json.decode(feed.data.popular_tags) if feed.data.popular_tags else []
    feed_authors = json.decode(feed.data.popular_authors) if feed.data.popular_authors else []

    if include_feeds:
        feeds = Feed.objects.filter(pk__in=set([story["story_feed_id"] for story in stories]))
        feeds = [f.canonical(include_favicon=False) for f in feeds]

    if usersub:
        usersub.feed_opens += 1
        usersub.needs_unread_recalc = True
        try:
            usersub.save(update_fields=["feed_opens", "needs_unread_recalc"])
        except DatabaseError as e:
            logging.user(request, f"~BR~FK~SBNo changes in usersub, ignoring... {e}")

    phase_load_stories = checkpoint1 - start
    phase_shared = checkpoint2 - checkpoint1
    phase_classifiers = checkpoint3 - checkpoint2
    phase_story_meta = checkpoint4 - checkpoint3
    timediff = time.time() - start
    last_update = relative_timesince(feed.last_update)
    time_breakdown = ""
    if timediff > 1 or settings.DEBUG:
        time_breakdown = "~SN~FR(~SB%.4s/%.4s/%.4s/%.4s~SN)" % (
            phase_load_stories,
            phase_shared,
            phase_classifiers,
            phase_story_meta,
        )

    search_log = "~SN~FG(~SB%s~SN) " % query if query else ""
    date_filter_log = ""
    if date_filter_start and date_filter_start != "all":
        date_filter_log = f"~SN~FG(dates: {date_filter_start}"
        if date_filter_end and date_filter_end != "all":
            date_filter_log += f" to {date_filter_end}"
        date_filter_log += "~SN) "
    elif date_filter_end and date_filter_end != "all":
        date_filter_log = f"~SN~FG(dates: up to {date_filter_end}~SN) "

    logging.user(
        request,
        "~FYLoading feed: ~SB%s%s (%s/%s) %s%s%s"
        % (
            feed.feed_title[:22],
            ("~SN/p%s" % page) if page > 1 else "",
            order,
            read_filter,
            search_log,
            date_filter_log,
            time_breakdown,
        ),
    )

    if timediff >= 0.25:
        logging.info(
            "reader_load "
            f"endpoint=feed read_filter={read_filter} page={page} "
            f"total_ms={int(timediff * 1000)} "
            f"load_ms={int(phase_load_stories * 1000)} "
            f"shared_ms={int(phase_shared * 1000)} "
            f"classifiers_ms={int(phase_classifiers * 1000)} "
            f"story_meta_ms={int(phase_story_meta * 1000)}"
        )

    if not include_hidden:
        hidden_stories_removed = 0
        new_stories = []
        for story in stories:
            if story["score"] >= 0:
                new_stories.append(story)
            else:
                hidden_stories_removed += 1
        stories = new_stories

    data = dict(
        stories=stories,
        feed_tags=feed_tags,
        feed_authors=feed_authors,
        classifiers=classifiers,
        updated=last_update,
        feed_id=feed.pk,
        elapsed_time=round(float(timediff), 2),
        message=message,
    )

    if include_feeds:
        data["feeds"] = feeds
    if not include_hidden:
        data["hidden_stories_removed"] = hidden_stories_removed
    if dupe_feed_id:
        data["dupe_feed_id"] = dupe_feed_id
    if not usersub:
        data.update(feed.canonical())
    # Signal frontend to poll for fetch completion on stale/unfetched try-feeds
    if not usersub and (
        not feed.fetched_once or feed.last_update < datetime.datetime.utcnow() - datetime.timedelta(days=1)
    ):
        data["not_yet_fetched"] = True
        data["fetched_once"] = False
        data["stories"] = []
    # Always include fetched_once when insta_fetch is requested so the frontend
    # poll_for_fetch_completion can terminate for subscribed feeds too
    elif insta_fetch:
        data["fetched_once"] = feed.fetched_once
    # if not usersub and feed.num_subscribers <= 1:
    #     data = dict(code=-1, message="You must be subscribed to this feed.")

    # time.sleep(random.randint(1, 3))
    if delay and user.is_staff:
        # time.sleep(random.randint(2, 7) / 10.0)
        time.sleep(delay)
    # if page == 1:
    #     time.sleep(1)
    # else:
    #     time.sleep(20)
    # if page == 2:
    #     assert False

    return data



def load_feed_page(request, feed_id):
    if not feed_id:
        raise Http404

    feed = Feed.get_by_id(feed_id)
    if feed and feed.has_page and not feed.has_page_exception:
        if settings.BACKED_BY_AWS.get("pages_on_node"):
            domain = Site.objects.get_current().domain
            url = "https://%s/original_page/%s" % (
                domain,
                feed.pk,
            )
            try:
                page_response = requests.get(url, verify=not settings.DEBUG)
            except requests.ConnectionError as e:
                logging.user(request, f"~FR~SBError loading original page: {url} {e}")
                page_response = None
            if page_response and page_response.status_code == 200:
                response = HttpResponse(page_response.content, content_type="text/html; charset=utf-8")
                response["Content-Encoding"] = "deflate"
                response["Last-Modified"] = page_response.headers.get("Last-modified")
                response["Etag"] = page_response.headers.get("Etag")
                response["Content-Length"] = str(len(page_response.content))
                logging.user(
                    request,
                    "~FYLoading original page (%s), proxied from node: ~SB%s bytes"
                    % (feed_id, len(page_response.content)),
                )
                return response

        if settings.BACKED_BY_AWS["pages_on_s3"] and feed.s3_page:
            if settings.PROXY_S3_PAGES:
                key = settings.S3_CONN.Bucket(settings.S3_PAGES_BUCKET_NAME).Object(key=feed.s3_pages_key)
                if key:
                    compressed_data = key.get()["Body"]
                    response = HttpResponse(compressed_data, content_type="text/html; charset=utf-8")
                    response["Content-Encoding"] = "gzip"

                    logging.user(
                        request, "~FYLoading original page, proxied: ~SB%s bytes" % (len(compressed_data))
                    )
                    return response
            else:
                logging.user(request, "~FYLoading original page, non-proxied")
                return HttpResponseRedirect("//%s/%s" % (settings.S3_PAGES_BUCKET_NAME, feed.s3_pages_key))

    data = MFeedPage.get_data(feed_id=feed_id)

    if not data or not feed or not feed.has_page or feed.has_page_exception:
        logging.user(request, "~FYLoading original page, ~FRmissing")
        return HttpResponse("<h1>404</h1><p>Original page not found.</p>", status=404)

    logging.user(request, "~FYLoading original page, from the db")
    return HttpResponse(data, content_type="text/html; charset=utf-8")



@ajax_login_required
@json.json_view
def save_feed_order(request):
    folders = request.POST.get("folders")
    if folders:
        # Test that folders can be JSON decoded
        folders_list = json.decode(folders)
        assert folders_list is not None
        logging.user(request, "~FBFeed re-ordering: ~SB%s folders/feeds" % (len(folders_list)))
        user_sub_folders = UserSubscriptionFolders.objects.get(user=request.user)

        # Guard against a stale or truncated client blindly overwriting the whole tree.
        # Re-ordering must preserve feeds; deletions go through delete_feed, not here. If
        # the incoming tree is missing a large share of the feeds the user still
        # subscribes to, reject it rather than silently drop that organization.
        # apps/reader/views.py
        def _feed_ids_in_tree(items):
            ids = set()
            for item in items:
                if isinstance(item, int):
                    ids.add(item)
                elif isinstance(item, dict):
                    for _, children in item.items():
                        ids |= _feed_ids_in_tree(children)
            return ids

        incoming_ids = _feed_ids_in_tree(folders_list)
        subscribed_ids = set(
            UserSubscription.objects.filter(user=request.user).values_list("feed_id", flat=True)
        )
        missing = subscribed_ids - incoming_ids
        threshold = max(5, int(len(subscribed_ids) * 0.15))
        if subscribed_ids and len(missing) > threshold:
            logging.user(
                request,
                "~FR~SBRejected feed re-order: incoming tree missing ~SB%s~SN of %s subscribed feeds"
                % (len(missing), len(subscribed_ids)),
            )
            return dict(
                code=-1,
                message="Feed order not saved: the update was missing %s of your %s feeds. "
                "Please reload the page and try again." % (len(missing), len(subscribed_ids)),
            )

        user_sub_folders.folders = folders
        user_sub_folders.save()

    return {}



@json.json_view
def find_story_by_permalink(request):
    user = get_user(request)
    url = request.GET.get("story_url", "").strip()

    if not url:
        return dict(code=-1, message=gettext("No URL provided."))

    parsed = urllib.parse.urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return dict(code=-1, message=gettext("Invalid URL."))

    domain = parsed.netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]

    # Find the canonical feed: both feed_address and feed_link must match the domain
    feed = (
        Feed.objects.filter(feed_address__icontains=domain, feed_link__icontains=domain)
        .exclude(feed_address__icontains="/social/rss/")
        .order_by("-num_subscribers")
        .first()
    )
    if not feed:
        return dict(code=-1, message=gettext("No feed found for this URL."))

    # Search for the story in this single feed
    story = None
    url_variants = _get_url_variants(url)
    for variant in url_variants:
        story = MStory.objects(story_permalink=variant, story_feed_id=feed.pk).first()
        if story:
            break
    if not story:
        for variant in url_variants:
            story = MStory.objects(story_guid=variant, story_feed_id=feed.pk).first()
            if story:
                break

    if not story:
        return dict(code=-1, message=gettext("Story not found."))

    is_subscribed = UserSubscription.objects.filter(user=user, feed_id=feed.pk, active=True).exists()

    return dict(
        code=1,
        story_hash=story.story_hash,
        story_feed_id=feed.pk,
        is_subscribed=is_subscribed,
        feed=feed.canonical(),
    )
