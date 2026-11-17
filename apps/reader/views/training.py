"""Intelligence trainer payloads and muting.

Split from apps/reader/views.py; see apps/reader/views/__init__.py.
"""

from ._base import *  # noqa: F401,F403



@json.json_view
def feeds_trainer(request):
    classifiers = []
    feed_id = request.GET.get("feed_id")
    user = get_user(request)
    usersubs = UserSubscription.objects.filter(user=user, active=True)

    if feed_id:
        feed = get_object_or_404(Feed, pk=feed_id)
        usersubs = usersubs.filter(feed=feed)
    usersubs = usersubs.select_related("feed", "feed__data").order_by("-feed__stories_last_month")

    # The six classifier tables are read once for the whole account and grouped
    # by feed. Asking get_classifiers_for_user per site ran six queries for each
    # of them, which is 454 queries to open the trainer; the grouped lists feed
    # the same rows into the same payload with six queries in total.
    # apps/reader/views/training.py
    classifier_keys = (
        "classifier_authors",
        "classifier_titles",
        "classifier_tags",
        "classifier_texts",
        "classifier_urls",
        "classifier_feeds",
    )
    grouped = {}
    for rows, key in (
        (MClassifierAuthor.objects(user_id=user.pk), "classifier_authors"),
        (MClassifierTitle.objects(user_id=user.pk), "classifier_titles"),
        (MClassifierTag.objects(user_id=user.pk), "classifier_tags"),
        (MClassifierText.objects(user_id=user.pk), "classifier_texts"),
        (MClassifierUrl.objects(user_id=user.pk), "classifier_urls"),
        # get_classifiers_for_user adds social_user_id=0 for the feed table, so
        # this pass has to filter the same way or social rows leak in.
        (MClassifierFeed.objects(user_id=user.pk, social_user_id=0), "classifier_feeds"),
    ):
        for row in rows:
            bucket = grouped.get(row.feed_id)
            if bucket is None:
                bucket = grouped[row.feed_id] = {name: [] for name in classifier_keys}
            bucket[key].append(row)

    for us in usersubs:
        if (not us.is_trained and us.feed.stories_last_month > 0) or feed_id:
            classifier = dict()
            # Empty lists matter as much as filled ones: a None argument tells
            # get_classifiers_for_user to run its own query for that table.
            classifier["classifiers"] = get_classifiers_for_user(
                user,
                feed_id=us.feed.pk,
                **(grouped.get(us.feed.pk) or {name: [] for name in classifier_keys}),
            )
            classifier["feed_id"] = us.feed_id
            classifier["stories_last_month"] = us.feed.stories_last_month
            classifier["num_subscribers"] = us.feed.num_subscribers
            classifier["feed_tags"] = (
                json.decode(us.feed.data.popular_tags) if us.feed.data.popular_tags else []
            )
            classifier["feed_authors"] = (
                json.decode(us.feed.data.popular_authors) if us.feed.data.popular_authors else []
            )
            classifiers.append(classifier)

    # Opening the trainer used to write the profile on every request; only the
    # first visit has anything to record.
    if not user.profile.has_trained_intelligence:
        user.profile.has_trained_intelligence = True
        user.profile.save(update_fields=["has_trained_intelligence"])

    logging.user(user, "~FGLoading Trainer: ~SB%s feeds" % (len(classifiers)))

    return classifiers



@json.json_view
def all_classifiers(request):
    """
    Return all trained classifiers for a user, organized by feed and folder structure.
    Only returns classifiers with non-zero scores (trained items).
    """
    user = get_user(request)
    if not user.is_authenticated:
        return {"folders": [], "total_classifiers": 0}

    # Get folder structure for organizing output
    try:
        usf = UserSubscriptionFolders.objects.get(user=user)
        flat_folders = usf.flatten_folders()
    except UserSubscriptionFolders.DoesNotExist:
        flat_folders = {" ": []}

    # Get all classifiers for user with non-zero scores, grouped by feed. The table
    # registry keeps this loop and the counters in apps/profile/views.py in step.
    trained = classifiers.trained(user.pk)

    classifiers_by_feed = defaultdict(
        lambda: {
            "titles": [],
            "authors": [],
            "tags": [],
            "texts": [],
            "feeds": [],
            "urls": [],
            "prompts": [],
            "image_prompts": [],
        }
    )

    # Separate scoped classifiers (global/folder) from feed-scoped ones
    scoped_classifiers = classifiers.scoped_collections()

    for table in classifiers.CLASSIFIER_TABLES:
        for classifier in trained[table.key]:
            if table.text_field is None:
                classifiers_by_feed[classifier.feed_id][table.collection].append(
                    {"feed_id": classifier.feed_id, "score": classifier.score}
                )
                continue
            entry = classifiers.trainer_entry(table, classifier)
            if entry["scope"] != "feed":
                scoped_classifiers[table.collection].append(entry)
            else:
                classifiers_by_feed[classifier.feed_id][table.collection].append(entry)

    # Batch fetch all feeds with classifiers to avoid N+1 queries
    all_classifier_feed_ids = set(classifiers_by_feed.keys())
    feeds_by_id = {f.pk: f for f in Feed.objects.filter(pk__in=all_classifier_feed_ids)}

    # Fetch user-renamed feed titles so the training UI shows custom names
    user_titles = dict(
        UserSubscription.objects.filter(user=user, feed_id__in=all_classifier_feed_ids)
        .exclude(user_title__isnull=True)
        .exclude(user_title="")
        .values_list("feed_id", "user_title")
    )

    # Build response organized by folder structure
    folders_with_classifiers = []
    all_folder_feed_ids = set()

    for folder_name, feed_ids in flat_folders.items():
        all_folder_feed_ids.update(feed_ids)
        folder_feeds = []
        for feed_id in feed_ids:
            if feed_id in classifiers_by_feed:
                feed = feeds_by_id.get(feed_id)
                if feed:
                    folder_feeds.append(
                        {
                            "feed_id": feed_id,
                            "feed_title": user_titles.get(feed_id, feed.feed_title),
                            "favicon_url": feed.favicon_url,
                            "favicon_color": feed.favicon_color,
                            "favicon_fetching": feed.favicon_fetching,
                            "classifiers": classifiers_by_feed[feed_id],
                        }
                    )

        if folder_feeds:
            folders_with_classifiers.append({"folder_name": folder_name, "feeds": folder_feeds})

    # Check for feeds with classifiers not in any folder
    orphan_feeds = []
    for feed_id, feed_classifiers in classifiers_by_feed.items():
        if feed_id not in all_folder_feed_ids:
            feed = feeds_by_id.get(feed_id)
            if feed:
                orphan_feeds.append(
                    {
                        "feed_id": feed_id,
                        "feed_title": user_titles.get(feed_id, feed.feed_title),
                        "favicon_url": feed.favicon_url,
                        "favicon_color": feed.favicon_color,
                        "favicon_fetching": feed.favicon_fetching,
                        "classifiers": feed_classifiers,
                    }
                )

    if orphan_feeds:
        folders_with_classifiers.append({"folder_name": "Uncategorized", "feeds": orphan_feeds})

    total_classifiers = sum(
        len(c["titles"])
        + len(c["authors"])
        + len(c["tags"])
        + len(c["texts"])
        + len(c["feeds"])
        + len(c["urls"])
        + len(c["prompts"])
        + len(c["image_prompts"])
        for c in classifiers_by_feed.values()
    )

    logging.user(
        user,
        "~FGLoading All Classifiers: ~SB%s classifiers across %s feeds"
        % (total_classifiers, len(classifiers_by_feed)),
    )

    # Count scoped classifiers too
    total_scoped = sum(len(v) for v in scoped_classifiers.values())
    total_classifiers += total_scoped

    result = {"folders": folders_with_classifiers, "total_classifiers": total_classifiers}

    # Add scoped classifiers as a separate section
    has_scoped = any(len(v) > 0 for v in scoped_classifiers.values())
    if has_scoped:
        result["scoped_classifiers"] = scoped_classifiers

    return result



@ajax_login_required
@json.json_view
def save_feed_chooser(request):
    """
    Batch update feed mute status. Used by the feed chooser dialog.

    WARNING: This endpoint can accidentally mute feeds if the client sends an
    incomplete approved_feeds list. For individual feed mute/unmute operations,
    use the safer /reader/set_feed_mute endpoint instead.
    """
    approve_all = request.POST.get("approve_all", "").lower() in ("true", "1", "yes")
    approved_feeds = request.POST.getlist("approved_feeds") or request.POST.getlist("approved_feeds[]")
    approved_feeds = [int(feed_id) for feed_id in approved_feeds if feed_id]
    activated = 0
    muted = 0
    usersubs = UserSubscription.objects.filter(user=request.user)
    total_subs = usersubs.count()
    currently_active = usersubs.filter(active=True).count()

    # Safety check: warn if this would mute many feeds unexpectedly
    approved_set = set(approved_feeds)
    if not approve_all and total_subs > 10:
        would_mute = currently_active - len(
            approved_set & set(usersubs.filter(active=True).values_list("feed_id", flat=True))
        )
        if would_mute > 10 and len(approved_feeds) < total_subs * 0.5:
            logging.user(
                request,
                "~BR~FW~SB[SAFETY WARNING]~SN Feed chooser would mute ~FC%s~SN feeds "
                "(approved: ~FC%s~SN, total: ~FC%s~SN, currently active: ~FC%s~SN)"
                % (would_mute, len(approved_feeds), total_subs, currently_active),
            )

    for sub in usersubs:
        try:
            if sub.feed_id in approved_feeds:
                activated += 1
                if not sub.active:
                    sub.active = True
                    sub.save()
                    if sub.feed.active_subscribers <= 0:
                        sub.feed.count_subscribers()
            elif sub.active:
                sub.active = False
                sub.save()
                muted += 1
        except Feed.DoesNotExist:
            pass

    UserSubscription.queue_new_feeds(request.user)
    UserSubscription.refresh_stale_feeds(request.user, exclude_new=True)

    r = redis.Redis(connection_pool=settings.REDIS_PUBSUB_POOL)
    r.publish(request.user.username, "reload:feeds")

    logging.user(
        request,
        "~BB~FW~SBFeed chooser: ~FC%s~SN active, ~FC%s~SN muted /~SB%s~SN total"
        % (activated, muted, total_subs),
    )

    return {"activated": activated, "muted": muted}



@ajax_login_required
@json.json_view
def set_feed_mute(request):
    """
    Safely mute or unmute a single feed without requiring the full list of feeds.
    This prevents accidental mass-muting that can occur with save_feed_chooser
    when the client has an incomplete feed list.
    """
    feed_id = request.POST.get("feed_id")
    mute = request.POST.get("mute", "true").lower() in ("true", "1", "yes")
    mute_duration_days = request.POST.get("mute_duration_days")

    if not feed_id:
        return {"code": -1, "message": gettext("feed_id is required")}

    try:
        feed_id = int(feed_id)
    except (ValueError, TypeError):
        return {"code": -1, "message": gettext("Invalid feed_id")}

    try:
        sub = UserSubscription.objects.get(user=request.user, feed_id=feed_id)
    except UserSubscription.DoesNotExist:
        return {"code": -1, "message": gettext("You are not subscribed to this feed")}

    if mute_duration_days:
        try:
            mute_duration_days = int(mute_duration_days)
        except (ValueError, TypeError):
            return {"code": -1, "message": gettext("Invalid mute_duration_days")}

    if mute:
        sub.active = False
        if mute_duration_days and mute_duration_days > 0:
            sub.mute_expires_at = datetime.datetime.now() + datetime.timedelta(days=mute_duration_days)
        else:
            sub.mute_expires_at = None
        sub.save()
        duration_text = (
            "%s days" % mute_duration_days if mute_duration_days and mute_duration_days > 0 else "forever"
        )
        logging.user(request, "~BB~FW~SBMuted feed ~FC%s~FB for %s" % (feed_id, duration_text))
    else:
        if not sub.active:
            sub.active = True
            sub.mute_expires_at = None
            sub.save()
            if sub.feed.active_subscribers <= 0:
                sub.feed.count_subscribers()
            logging.user(request, "~BB~FW~SBUnmuted feed: ~FC%s" % feed_id)

    r = redis.Redis(connection_pool=settings.REDIS_PUBSUB_POOL)
    r.publish(request.user.username, "reload:feeds")

    response = {"code": 1, "feed_id": feed_id, "muted": mute}
    if sub.mute_expires_at:
        response["mute_expires_at"] = sub.mute_expires_at.isoformat()
    return response



@ajax_login_required
def retrain_all_sites(request):
    for sub in UserSubscription.objects.filter(user=request.user):
        sub.is_trained = False
        sub.save()

    return feeds_trainer(request)
