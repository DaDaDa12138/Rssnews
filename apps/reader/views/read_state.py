"""Mark read/unread endpoints.

Split from apps/reader/views.py; see apps/reader/views/__init__.py.
"""

from django.views.decorators.http import require_POST

from ._base import *  # noqa: F401,F403



@ajax_login_required
@require_POST
@json.json_view
def mark_all_as_read(request):
    code = 1
    try:
        days = int(request.POST.get("days", 0))
    except ValueError:
        return dict(code=-1, message="Days parameter must be an integer, not: %s" % request.POST.get("days"))
    read_date = datetime.datetime.utcnow() - datetime.timedelta(days=days)

    feeds = UserSubscription.objects.filter(user=request.user)

    infrequent = is_true(request.POST.get("infrequent", False))
    if infrequent:
        infrequent = request.POST.get("infrequent")
        feed_ids = Feed.low_volume_feeds([usersub.feed.pk for usersub in feeds], stories_per_month=infrequent)
        feeds = UserSubscription.objects.filter(user=request.user, feed_id__in=feed_ids)

    updated_feed_ids = []
    for sub in feeds:
        if days == 0:
            sub.mark_feed_read(force=True)
        else:
            if sub.mark_read_date < read_date:
                sub.needs_unread_recalc = True
                sub.mark_read_date = read_date
                sub.save()
                if hasattr(sub, "feed_id"):
                    updated_feed_ids.append(sub.feed_id)

    r = redis.Redis(connection_pool=settings.REDIS_PUBSUB_POOL)
    r.publish(request.user.username, "reload:feeds")

    logging.user(
        request,
        "~FMMarking %s as read: ~SB%s days"
        % (
            ("all" if not infrequent else "infrequent stories"),
            days,
        ),
    )
    return dict(code=code)



@ajax_login_required
@require_POST
@json.json_view
def mark_story_as_read(request):
    story_ids = request.POST.getlist("story_id") or request.POST.getlist("story_id[]")
    try:
        feed_id = int(get_argument_or_404(request, "feed_id"))
    except ValueError:
        return dict(code=-1, errors=["You must pass a valid feed_id: %s" % request.POST.get("feed_id")])

    try:
        usersub = UserSubscription.objects.select_related("feed").get(user=request.user, feed=feed_id)
    except Feed.DoesNotExist:
        duplicate_feed = DuplicateFeed.objects.filter(duplicate_feed_id=feed_id)
        if duplicate_feed:
            feed_id = duplicate_feed[0].feed_id
            try:
                usersub = UserSubscription.objects.get(user=request.user, feed=duplicate_feed[0].feed)
            except Feed.DoesNotExist:
                return dict(code=-1, errors=["No feed exists for feed_id %d." % feed_id])
        else:
            return dict(code=-1, errors=["No feed exists for feed_id %d." % feed_id])
    except UserSubscription.DoesNotExist:
        usersub = None

    if usersub:
        data = usersub.mark_story_ids_as_read(story_ids, request=request)
    else:
        data = dict(code=-1, errors=["User is not subscribed to this feed."])

    return data



@ajax_login_required
@require_POST
@json.json_view
def mark_story_hashes_as_read(request):
    retrying_failed = is_true(request.POST.get("retrying_failed", False))
    r = redis.Redis(connection_pool=settings.REDIS_PUBSUB_POOL)
    try:
        story_hashes = request.POST.getlist("story_hash") or request.POST.getlist("story_hash[]")
    except UnreadablePostError:
        return dict(code=-1, message=gettext("Missing `story_hash` list parameter."))

    # Filter out story hashes already marked as read to avoid redundant work.
    # Some clients (e.g. NetNewsWire) re-send all read hashes on every sync cycle.
    # Check both global (RS:{user_id}) and feed-specific (RS:{user_id}:{feed_id}) sets,
    # because trim_read_stories can remove from the feed-specific set when a story is
    # temporarily missing from the feed (e.g. unpublish/republish), creating an
    # inconsistency where the global set says "read" but the feed set doesn't.
    if story_hashes:
        rsh = redis.Redis(connection_pool=settings.REDIS_STORY_HASH_POOL)
        all_read_key = "RS:%s" % request.user.pk
        p = rsh.pipeline()
        for story_hash in story_hashes:
            feed_id = story_hash.split(":")[0]
            p.sismember(all_read_key, story_hash)
            p.sismember("RS:%s:%s" % (request.user.pk, feed_id), story_hash)
        results = p.execute()
        original_count = len(story_hashes)
        # Only skip if read in BOTH global and feed-specific sets
        story_hashes = [
            sh for i, sh in enumerate(story_hashes) if not (results[i * 2] and results[i * 2 + 1])
        ]
        skipped_count = original_count - len(story_hashes)
        if skipped_count > 0 and not story_hashes:
            logging.user(
                request,
                "~FYRead ~SB%s~SN already read stories, skipping" % skipped_count,
            )
            return dict(code=1, story_hashes=[], feed_ids=[], friend_user_ids=[])
        elif skipped_count > 0:
            logging.user(
                request,
                "~FYSkipped ~SB%s~SN/%s already read, processing %s new"
                % (skipped_count, original_count, len(story_hashes)),
            )

    feed_ids, friend_ids = RUserStory.mark_story_hashes_read(
        request.user.pk, story_hashes, username=request.user.username
    )

    # Also count on original subscription
    for feed_id in feed_ids:
        usersubs = UserSubscription.objects.filter(user=request.user.pk, feed=feed_id)
        if usersubs:
            usersub = usersubs[0]
            usersub.last_read_date = datetime.datetime.now()
            if not usersub.needs_unread_recalc:
                usersub.needs_unread_recalc = True
                usersub.save(update_fields=["needs_unread_recalc", "last_read_date"])
            else:
                usersub.save(update_fields=["last_read_date"])
            r.publish(request.user.username, "feed:%s" % feed_id)

    hash_count = len(story_hashes)
    logging.user(
        request,
        "~FYRead %s %s: %s %s"
        % (
            hash_count,
            "story" if hash_count == 1 else "stories",
            story_hashes,
            "(retrying failed)" if retrying_failed else "",
        ),
    )

    return dict(code=1, story_hashes=story_hashes, feed_ids=feed_ids, friend_user_ids=friend_ids)



@ajax_login_required
@require_POST
@json.json_view
def mark_feed_stories_as_read(request):
    r = redis.Redis(connection_pool=settings.REDIS_PUBSUB_POOL)
    feeds_stories = request.POST.get("feeds_stories", "{}")
    feeds_stories = json.decode(feeds_stories)
    data = {"code": -1, "message": gettext("Nothing was marked as read")}

    for feed_id, story_ids in list(feeds_stories.items()):
        try:
            feed_id = int(feed_id)
        except ValueError:
            continue
        try:
            usersub = UserSubscription.objects.select_related("feed").get(user=request.user, feed=feed_id)
            data = usersub.mark_story_ids_as_read(story_ids, request=request)
        except UserSubscription.DoesNotExist:
            return dict(code=-1, error="You are not subscribed to this feed_id: %d" % feed_id)
        except Feed.DoesNotExist:
            duplicate_feed = DuplicateFeed.objects.filter(duplicate_feed_id=feed_id)
            try:
                if not duplicate_feed:
                    raise Feed.DoesNotExist
                usersub = UserSubscription.objects.get(user=request.user, feed=duplicate_feed[0].feed)
                data = usersub.mark_story_ids_as_read(story_ids, request=request)
            except (UserSubscription.DoesNotExist, Feed.DoesNotExist):
                return dict(code=-1, error="No feed exists for feed_id: %d" % feed_id)

        r.publish(request.user.username, "feed:%s" % feed_id)

    return data



@required_params("story_id", feed_id=int)
@ajax_login_required
@require_POST
@json.json_view
def mark_story_as_unread(request):
    story_id = request.POST.get("story_id", None)
    feed_id = int(request.POST.get("feed_id", 0))

    try:
        usersub = UserSubscription.objects.select_related("feed").get(user=request.user, feed=feed_id)
        feed = usersub.feed
    except UserSubscription.DoesNotExist:
        usersub = None
        feed = Feed.get_by_id(feed_id)

    if usersub and not usersub.needs_unread_recalc:
        usersub.needs_unread_recalc = True
        usersub.save(update_fields=["needs_unread_recalc"])

    data = dict(code=0, payload=dict(story_id=story_id))

    story, found_original = MStory.find_story(feed_id, story_id)

    if not story:
        logging.user(request, "~FY~SBUnread~SN story in feed: %s (NOT FOUND)" % (feed))
        return dict(code=-1, message=gettext("Story not found."))

    message = RUserStory.story_can_be_marked_unread_by_user(story, request.user)
    if message:
        data["code"] = -1
        data["message"] = message
        return data

    if usersub:
        data = usersub.invert_read_stories_after_unread_story(story, request)

    RUserStory.mark_story_hash_unread(request.user, story_hash=story.story_hash)

    r = redis.Redis(connection_pool=settings.REDIS_PUBSUB_POOL)
    r.publish(request.user.username, "feed:%s" % feed_id)

    logging.user(request, "~FY~SBUnread~SN story in feed: %s" % (feed,))

    return data



@ajax_login_required
@require_POST
@json.json_view
@required_params("story_hash")
def mark_story_hash_as_unread(request):
    r = redis.Redis(connection_pool=settings.REDIS_PUBSUB_POOL)
    story_hashes = request.POST.getlist("story_hash") or request.POST.getlist("story_hash[]")
    is_list = len(story_hashes) > 1
    datas = []
    for story_hash in story_hashes:
        feed_id, _ = MStory.split_story_hash(story_hash)
        story, _ = MStory.find_story(feed_id, story_hash)
        if not story:
            data = dict(
                code=-1,
                message=gettext("That story has been removed from the feed, no need to mark it unread."),
                story_hash=story_hash,
            )
            if not is_list:
                return data
            else:
                datas.append(data)
        message = RUserStory.story_can_be_marked_unread_by_user(story, request.user)
        if message:
            data = dict(code=-1, message=message, story_hash=story_hash)
            if not is_list:
                return data
            else:
                datas.append(data)

        # Also count on original subscription
        usersubs = UserSubscription.objects.filter(user=request.user.pk, feed=feed_id)
        if usersubs:
            usersub = usersubs[0]
            if not usersub.needs_unread_recalc:
                usersub.needs_unread_recalc = True
                usersub.save(update_fields=["needs_unread_recalc"])
            data = usersub.invert_read_stories_after_unread_story(story, request)
            r.publish(request.user.username, "feed:%s" % feed_id)

        feed_id, friend_ids = RUserStory.mark_story_hash_unread(request.user, story_hash)

        logging.user(request, "~FYUnread story in feed: %s" % (feed_id,))

        data = dict(code=1, story_hash=story_hash, feed_id=feed_id, friend_user_ids=friend_ids)
        if not is_list:
            return data
        else:
            datas.append(data)

    return datas



@ajax_login_required
@require_POST
@json.json_view
def mark_stories_as_unread(request):
    try:
        days = int(request.POST.get("days", 0))
    except ValueError:
        return dict(code=-1, message=gettext("Days parameter must be an integer."))

    if days <= 0:
        return dict(code=-1, message=gettext("Days must be a positive integer."))

    max_days = settings.DAYS_OF_UNREAD

    if days > max_days:
        return dict(code=-1, message="Cannot mark more than %s days as unread." % max_days)

    feed_id = request.POST.get("feed_id", None)
    folder = request.POST.get("folder", None)

    is_async = False
    if feed_id:
        try:
            feed_id = int(feed_id)
        except ValueError:
            return dict(code=-1, message=gettext("Invalid feed_id."))
        feed_ids = [feed_id]
        total = UserSubscription.mark_stories_as_unread(request.user.pk, feed_ids, days)
        logging.user(request, "~FY~SBUnread~SN %s stories in feed %s (%s days)" % (total, feed_id, days))
    elif folder:
        try:
            usf = UserSubscriptionFolders.objects.get(user=request.user)
            flat_folders = usf.flatten_folders()
            feed_ids = flat_folders.get(folder, [])
        except UserSubscriptionFolders.DoesNotExist:
            feed_ids = []
        if not feed_ids:
            return dict(code=-1, message="No feeds found in folder '%s'." % folder)
        MarkStoriesAsUnread.delay(request.user.pk, feed_ids, days)
        is_async = True
        logging.user(
            request,
            "~FY~SBUnread~SN stories in folder %s (%s feeds, %s days)" % (folder, len(feed_ids), days),
        )
    else:
        feed_ids = list(UserSubscription.objects.filter(user=request.user).values_list("feed_id", flat=True))
        if not feed_ids:
            return dict(code=-1, message=gettext("No feeds found."))
        MarkStoriesAsUnread.delay(request.user.pk, feed_ids, days)
        is_async = True
        logging.user(request, "~FY~SBUnread~SN stories in all %s feeds (%s days)" % (len(feed_ids), days))

    return dict(code=1, **{"async": is_async})



@ajax_login_required
@require_POST
@json.json_view
def mark_feed_as_read(request):
    r = redis.Redis(connection_pool=settings.REDIS_PUBSUB_POOL)
    feed_ids = request.POST.getlist("feed_id") or request.POST.getlist("feed_id[]")
    cutoff_timestamp = int_argument(request.POST, "cutoff_timestamp", 0)
    direction = request.POST.get("direction", "older")
    infrequent = is_true(request.POST.get("infrequent", False))
    if infrequent:
        infrequent = request.POST.get("infrequent")
    multiple = len(feed_ids) > 1
    code = 1
    errors = []
    cutoff_date = datetime.datetime.fromtimestamp(cutoff_timestamp) if cutoff_timestamp else None

    if infrequent:
        feed_ids = Feed.low_volume_feeds(feed_ids, stories_per_month=infrequent)
        feed_ids = [str(f) for f in feed_ids]  # This method expects strings

    if cutoff_date:
        logging.user(
            request,
            "~FMMark %s feeds read, %s - cutoff: %s/%s"
            % (len(feed_ids), direction, cutoff_timestamp, cutoff_date),
        )

    for feed_id in feed_ids:
        try:
            feed = Feed.objects.get(id=feed_id)
            sub = UserSubscription.objects.get(feed=feed, user=request.user)
            if not multiple:
                logging.user(request, "~FMMarking feed as read: ~SB%s" % (feed,))
        except (Feed.DoesNotExist, UserSubscription.DoesNotExist) as e:
            errors.append("User not subscribed: %s" % e)
            continue
        except ValueError as e:
            errors.append("Invalid feed_id: %s" % e)
            continue

        if not sub:
            errors.append("User not subscribed: %s" % feed_id)
            continue

        try:
            if direction == "older":
                marked_read = sub.mark_feed_read(cutoff_date=cutoff_date, force=True)
            else:
                marked_read = sub.mark_newer_stories_read(cutoff_date=cutoff_date)
            if marked_read and not multiple:
                r.publish(request.user.username, "feed:%s" % feed_id)
        except IntegrityError as e:
            errors.append("Could not mark feed as read: %s" % e)
            code = -1

    if multiple:
        logging.user(request, "~FMMarking ~SB%s~SN feeds as read" % len(feed_ids))
        r.publish(request.user.username, "refresh:%s" % ",".join(feed_ids))

    if errors:
        logging.user(request, "~FMMarking read had errors: ~FR%s" % errors)

    return dict(code=code, errors=errors, cutoff_date=cutoff_date, direction=direction)
