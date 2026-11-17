"""Adding, renaming, moving and deleting feeds and folders.

Split from apps/reader/views.py; see apps/reader/views/__init__.py.
"""

from django.views.decorators.http import require_POST

from ._base import *  # noqa: F401,F403



@ajax_login_required
@json.json_view
@folder_path_errors
def add_url(request):
    code = 0
    url = request.POST.get("url", "")
    folder = request.POST.get("folder", "").replace("river:", "")
    new_folder = request.POST.get("new_folder", "").replace("river:", "")
    auto_active = is_true(request.POST.get("auto_active", 1))
    skip_fetch = is_true(request.POST.get("skip_fetch", False))
    feed = None
    folder_path = parse_folder_path(request, "folder_path")
    if folder_path is not None:
        subscription_folders, _ = UserSubscriptionFolders.objects.get_or_create(user=request.user)
        resolve_folder_path(json.decode(subscription_folders.folders or "[]"), folder_path)
        folder = folder_path

    if not url:
        code = -1
        message = "Enter in the website address or the feed URL."
    elif any([(banned_url in url) for banned_url in BANNED_URLS]):
        code = -1
        message = "The publisher of this website has banned NewsBlur."
    else:
        try:
            validate_public_url(url)
        except UnsafeUrlError:
            code = -1
            message = BLOCKED_PRIVATE_URL_MESSAGE

    if code == -1:
        return dict(code=code, message=message)

    if new_folder:
        usf, _ = UserSubscriptionFolders.objects.get_or_create(user=request.user)
        usf.add_folder(folder, new_folder)
        folder = folder + [new_folder] if isinstance(folder, list) else new_folder

    code, message, us = UserSubscription.add_subscription(
        user=request.user, feed_address=url, folder=folder, auto_active=auto_active, skip_fetch=skip_fetch
    )
    feed = us and us.feed
    if feed:
        r = redis.Redis(connection_pool=settings.REDIS_PUBSUB_POOL)
        r.publish(request.user.username, "reload:%s" % feed.pk)

    return dict(code=code, message=message, feed=feed)



@ajax_login_required
@json.json_view
@folder_path_errors
def add_feeds(request):
    """Subscribe a discovery selection in one request, using already known feed IDs."""
    from django.http import HttpResponseNotAllowed

    from apps.reader.subscription_batch import add_feed_ids

    if request.method == "GET":
        return {"batch_add_supported": True, "max_feeds": 100}
    if request.method != "POST":
        return HttpResponseNotAllowed(["GET", "POST"])
    feed_ids = request.POST.getlist("feed_ids") or request.POST.getlist("feed_ids[]")
    if len(feed_ids) == 1 and feed_ids[0].startswith("["):
        try:
            feed_ids = json.decode(feed_ids[0])
        except (ValueError, TypeError):
            feed_ids = None
    if not isinstance(feed_ids, list) or not 1 <= len(feed_ids) <= 100:
        return {"code": -1, "message": "Provide between 1 and 100 feed IDs.", "results": []}
    if any(not isinstance(value, (str, int)) for value in feed_ids):
        return {"code": -1, "message": "Invalid feed IDs.", "results": []}
    return add_feed_ids(
        request.user,
        feed_ids,
        folder_path=parse_folder_path(request, "folder_path"),
        folder=request.POST.get("folder", "").replace("river:", ""),
        new_folder=request.POST.get("new_folder", "").strip(),
        auto_active=is_true(request.POST.get("auto_active", 1)),
        banned_urls=BANNED_URLS,
    )



@ajax_login_required
@json.json_view
@folder_path_errors
def add_folder(request):
    folder = request.POST.get("folder", "").replace("river:", "")
    parent_folder = request.POST.get("parent_folder", "").replace("river:", "")
    parent_path = parse_folder_path(request, "parent_folder_path")
    if parent_path is not None:
        parent_folder = parent_path
    folders = None
    logging.user(request, "~FRAdding Folder: ~SB%s (in %s)" % (folder, parent_folder))

    if folder:
        code = 1
        message = ""
        user_sub_folders_object, _ = UserSubscriptionFolders.objects.get_or_create(user=request.user)
        user_sub_folders_object.add_folder(parent_folder, folder)
        folders = json.decode(user_sub_folders_object.folders)
        r = redis.Redis(connection_pool=settings.REDIS_PUBSUB_POOL)
        r.publish(request.user.username, "reload:feeds")
    else:
        code = -1
        message = "Gotta write in a folder name."

    return dict(code=code, message=message, folders=folders)



@ajax_login_required
@require_POST
@json.json_view
@required_params("feed_id", feed_id=int)
@folder_path_errors
def delete_feed(request):
    feed_id = int(request.POST["feed_id"])
    in_folder = request.POST.get("in_folder", "").replace("river:", "")
    if not in_folder or in_folder == " ":
        in_folder = ""

    folder_path = parse_folder_path(request, "folder_path")
    if folder_path is not None:
        in_folder = folder_path

    user_sub_folders = get_object_or_404(UserSubscriptionFolders, user=request.user)
    user_sub_folders.delete_feed(feed_id, in_folder)

    feed = Feed.objects.filter(pk=feed_id)
    if feed:
        feed[0].count_subscribers()

    r = redis.Redis(connection_pool=settings.REDIS_PUBSUB_POOL)
    r.publish(request.user.username, "reload:feeds")

    return dict(code=1, message="Removed %s from '%s'." % (feed, in_folder))



@ajax_login_required
@require_POST
@json.json_view
def delete_feed_by_url(request):
    message = ""
    code = 0
    url = request.POST.get("url", "")
    if not url:
        return dict(code=-1, message="URL not found.")
    in_folder = request.POST.get("in_folder", "").replace("river:", "")
    if in_folder == " ":
        in_folder = ""

    logging.user(request.user, "~FBFinding feed (delete_feed_by_url): %s" % url)
    feed = Feed.get_feed_from_url(url, create=False)
    if feed:
        user_sub_folders = get_object_or_404(UserSubscriptionFolders, user=request.user)
        user_sub_folders.delete_feed(feed.pk, in_folder)
        code = 1
        feed = Feed.objects.filter(pk=feed.pk)
        if feed:
            feed[0].count_subscribers()
    else:
        code = -1
        message = "URL not found."

    return dict(code=code, message=message)



@ajax_login_required
@require_POST
@json.json_view
@folder_path_errors
def delete_folder(request):
    folder_to_delete = request.POST.get("folder_name") or request.POST.get("folder_to_delete")
    in_folder = request.POST.get("in_folder", None)
    folder_path = parse_folder_path(request, "folder_path")
    if folder_path is not None:
        if not folder_path:
            raise InvalidFolderPath("Choose a folder, not Top Level.")
        folder_to_delete = folder_path[-1]
        in_folder = folder_path[:-1]
        folder_tree = UserSubscriptionFolders.objects.get(user=request.user)
        resolve_folder_path(json.decode(folder_tree.folders), folder_path)
    feed_ids_in_folder = request.POST.getlist("feed_id") or request.POST.getlist("feed_id[]")
    feed_ids_in_folder = [int(f) for f in feed_ids_in_folder if f]

    request.user.profile.send_opml_export_email(
        reason=gettext_lazy(
            "You have deleted an entire folder of feeds, so here's a backup of all of your subscriptions just in case."
        )
    )

    # Works piss poor with duplicate folder titles, if they are both in the same folder.
    # Deletes all, but only in the same folder parent. But nobody should be doing that, right?
    user_sub_folders = get_object_or_404(UserSubscriptionFolders, user=request.user)
    user_sub_folders.delete_folder(folder_to_delete, in_folder, feed_ids_in_folder)
    folders = json.decode(user_sub_folders.folders)

    # Clean up folder icon when folder is deleted
    MFolderIcon.delete_folder_icon(
        request.user.pk, " - ".join(folder_path) if folder_path else folder_to_delete
    )

    r = redis.Redis(connection_pool=settings.REDIS_PUBSUB_POOL)
    r.publish(request.user.username, "reload:feeds")

    return dict(code=1, folders=folders)



@required_params("feeds_by_folder")
@ajax_login_required
@require_POST
@json.json_view
def delete_feeds_by_folder(request):
    feeds_by_folder = json.decode(request.POST["feeds_by_folder"])

    request.user.profile.send_opml_export_email(
        reason=gettext_lazy(
            "You have deleted a number of feeds at once, so here's a backup of all of your subscriptions just in case."
        )
    )

    # Works piss poor with duplicate folder titles, if they are both in the same folder.
    # Deletes all, but only in the same folder parent. But nobody should be doing that, right?
    user_sub_folders = get_object_or_404(UserSubscriptionFolders, user=request.user)
    user_sub_folders.delete_feeds_by_folder(feeds_by_folder)
    folders = json.decode(user_sub_folders.folders)

    r = redis.Redis(connection_pool=settings.REDIS_PUBSUB_POOL)
    r.publish(request.user.username, "reload:feeds")

    return dict(code=1, folders=folders)



@ajax_login_required
@json.json_view
def rename_feed(request):
    feed_id = request.POST.get("feed_id")
    feed_title = request.POST.get("feed_title")
    if not feed_id or not feed_title:
        return dict(code=-1, message=gettext("Missing feed_id or feed_title"))

    feed = get_object_or_404(Feed, pk=int(feed_id))
    try:
        user_sub = UserSubscription.objects.get(user=request.user, feed=feed)
    except UserSubscription.DoesNotExist:
        return dict(code=-1, message=f"You are not subscribed to {feed.feed_title}")

    logging.user(request, "~FRRenaming feed '~SB%s~SN' to: ~SB%s" % (feed.feed_title, feed_title))

    user_sub.user_title = feed_title
    user_sub.save()

    return dict(code=1)



def _find_full_folder_path(flat_folders, folder_leaf_name, parent_leaf_name):
    """Find the full flattened path for a folder given its leaf name and immediate parent name.

    flat_folders is the dict from UserSubscriptionFolders.flatten_folders(), where keys are
    full paths like "Parent - Child - Grandchild". parent_leaf_name is the immediate parent's
    leaf name (empty string for top-level folders).
    """
    if isinstance(parent_leaf_name, list):
        candidate = " - ".join(parent_leaf_name + [folder_leaf_name])
        return candidate if candidate in flat_folders else None

    for path in flat_folders:
        parts = path.split(" - ")
        if parts[-1] != folder_leaf_name:
            continue
        if not parent_leaf_name:
            if len(parts) == 1:
                return path
        elif len(parts) >= 2 and parts[-2] == parent_leaf_name:
            return path
    return None



def _update_classifiers_for_folder_path_change(user_id, old_path, new_path):
    """Update folder-scoped classifiers when a folder's full path changes (move or rename).

    Updates the moved/renamed folder itself and all of its subfolders.
    """
    # Update standard classifiers (exact match on the folder itself)
    for Cls in [MClassifierTitle, MClassifierText, MClassifierUrl, MClassifierAuthor, MClassifierTag]:
        Cls.objects(user_id=user_id, scope="folder", folder_name=old_path).update(folder_name=new_path)
        # Update subfolder classifiers (paths starting with old_path + " - ")
        old_prefix = old_path + " - "
        for classifier in Cls.objects(user_id=user_id, scope="folder", folder_name__startswith=old_prefix):
            classifier.folder_name = new_path + classifier.folder_name[len(old_path) :]
            classifier.save()



@ajax_login_required
@json.json_view
@folder_path_errors
def rename_folder(request):
    folder_to_rename = request.POST.get("folder_name") or request.POST.get("folder_to_rename")
    new_folder_name = request.POST.get("new_folder_name", "")
    in_folder = request.POST.get("in_folder", "").replace("river:", "")
    if "Top Level" in in_folder:
        in_folder = ""
    folder_path = parse_folder_path(request, "folder_path")
    if folder_path is not None:
        if not folder_path:
            raise InvalidFolderPath("Choose a folder, not Top Level.")
        folder_to_rename = folder_path[-1]
        in_folder = folder_path[:-1]
        folder_tree = UserSubscriptionFolders.objects.get(user=request.user)
        resolve_folder_path(json.decode(folder_tree.folders), folder_path)
    code = 0

    # Works piss poor with duplicate folder titles, if they are both in the same folder.
    # renames all, but only in the same folder parent. But nobody should be doing that, right?
    if folder_to_rename and new_folder_name:
        user_sub_folders = get_object_or_404(UserSubscriptionFolders, user=request.user)
        # Find the full flattened path before renaming so we can update classifiers
        old_flat = user_sub_folders.flatten_folders()
        old_path = _find_full_folder_path(old_flat, folder_to_rename, in_folder)

        user_sub_folders.rename_folder(folder_to_rename, new_folder_name, in_folder)
        # Update folder icon when folder is renamed
        icon_old_name = " - ".join(folder_path) if folder_path else folder_to_rename
        icon_new_name = " - ".join(folder_path[:-1] + [new_folder_name]) if folder_path else new_folder_name
        MFolderIcon.rename_folder_icon(request.user.pk, icon_old_name, icon_new_name)
        # Update folder-scoped classifiers using full flattened paths
        if old_path:
            parts = list(folder_path) if folder_path else old_path.split(" - ")
            parts[-1] = new_folder_name
            new_path = " - ".join(parts)
            _update_classifiers_for_folder_path_change(request.user.pk, old_path, new_path)
        code = 1
    else:
        code = -1

    return dict(code=code)



@ajax_login_required
@json.json_view
@required_params("feed_id", feed_id=int)
@folder_path_errors
def move_feed_to_folders(request):
    feed_id = int(request.POST["feed_id"])
    in_folders = request.POST.getlist("in_folders", "") or request.POST.getlist("in_folders[]", "")
    to_folders = request.POST.getlist("to_folders", "") or request.POST.getlist("to_folders[]", "")

    in_paths = parse_folder_paths(request, "in_folder_paths")
    to_paths = parse_folder_paths(request, "to_folder_paths")
    if in_paths is not None or to_paths is not None:
        if in_paths is None or to_paths is None:
            raise InvalidFolderPath("Supply both source and destination folder paths.")
        in_folders, to_folders = in_paths, to_paths

    user_sub_folders = get_object_or_404(UserSubscriptionFolders, user=request.user)
    user_sub_folders = user_sub_folders.move_feed_to_folders(
        feed_id, in_folders=in_folders, to_folders=to_folders
    )

    r = redis.Redis(connection_pool=settings.REDIS_PUBSUB_POOL)
    r.publish(request.user.username, "reload:feeds")

    return dict(code=1, folders=json.decode(user_sub_folders.folders))



@ajax_login_required
@json.json_view
@required_params("feed_id", feed_id=int)
def move_feed_to_folder(request):
    feed_id = int(request.POST["feed_id"])
    in_folder = request.POST.get("in_folder", "")
    to_folder = request.POST.get("to_folder", "")

    user_sub_folders = get_object_or_404(UserSubscriptionFolders, user=request.user)
    user_sub_folders = user_sub_folders.move_feed_to_folder(feed_id, in_folder=in_folder, to_folder=to_folder)

    r = redis.Redis(connection_pool=settings.REDIS_PUBSUB_POOL)
    r.publish(request.user.username, "reload:feeds")

    return dict(code=1, folders=json.decode(user_sub_folders.folders))



@ajax_login_required
@json.json_view
def move_folder_to_folder(request):
    folder_name = request.POST.get("folder_name", "")
    if not folder_name:
        return dict(code=-1, message="Choose a folder to move.")
    in_folder = request.POST.get("in_folder", "")
    to_folder = request.POST.get("to_folder", "")

    user_sub_folders = get_object_or_404(UserSubscriptionFolders, user=request.user)
    # Find the full flattened path before moving so we can update classifiers
    old_flat = user_sub_folders.flatten_folders()
    old_path = _find_full_folder_path(old_flat, folder_name, in_folder)

    user_sub_folders = user_sub_folders.move_folder_to_folder(
        folder_name, in_folder=in_folder, to_folder=to_folder
    )

    # Update folder-scoped classifiers with new folder paths
    if old_path:
        new_flat = user_sub_folders.flatten_folders()
        new_path = _find_full_folder_path(new_flat, folder_name, to_folder)
        if new_path and old_path != new_path:
            _update_classifiers_for_folder_path_change(request.user.pk, old_path, new_path)

    r = redis.Redis(connection_pool=settings.REDIS_PUBSUB_POOL)
    r.publish(request.user.username, "reload:feeds")

    return dict(code=1, folders=json.decode(user_sub_folders.folders))



@required_params("feeds_by_folder", "to_folder")
@ajax_login_required
@json.json_view
def move_feeds_by_folder_to_folder(request):
    feeds_by_folder = json.decode(request.POST["feeds_by_folder"])
    to_folder = request.POST["to_folder"]
    new_folder = request.POST.get("new_folder", None)

    request.user.profile.send_opml_export_email(
        reason=gettext_lazy(
            "You have moved a number of feeds at once, so here's a backup of all of your subscriptions just in case."
        )
    )

    user_sub_folders = get_object_or_404(UserSubscriptionFolders, user=request.user)

    if new_folder:
        user_sub_folders.add_folder(to_folder, new_folder)
        to_folder = new_folder

    user_sub_folders = user_sub_folders.move_feeds_by_folder_to_folder(feeds_by_folder, to_folder)

    r = redis.Redis(connection_pool=settings.REDIS_PUBSUB_POOL)
    r.publish(request.user.username, "reload:feeds")

    return dict(code=1, folders=json.decode(user_sub_folders.folders))
