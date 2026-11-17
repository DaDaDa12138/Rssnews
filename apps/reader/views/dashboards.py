"""Dashboard river configuration and auto-mark-read settings.

Split from apps/reader/views.py; see apps/reader/views/__init__.py.
"""

from ._base import *  # noqa: F401,F403



@ajax_login_required
@required_params("river_id", "river_side", "river_order", river_order=int)
@json.json_view
def save_dashboard_river(request):
    river_id = request.POST["river_id"]
    river_side = request.POST["river_side"]
    river_order = int(request.POST["river_order"])

    logging.user(request, "~FCSaving dashboard river: ~SB%s~SN (%s %s)" % (river_id, river_side, river_order))

    MDashboardRiver.save_user(request.user.pk, river_id, river_side, river_order)
    dashboard_rivers = MDashboardRiver.get_user_rivers(request.user.pk)

    return {
        "dashboard_rivers": dashboard_rivers,
    }



@ajax_login_required
@required_params("river_id", "river_side", "river_order", river_order=int)
@json.json_view
def remove_dashboard_river(request):
    river_id = request.POST["river_id"]
    river_side = request.POST["river_side"]
    river_order = int(request.POST["river_order"])

    logging.user(
        request, "~FRRemoving~FC dashboard river: ~SB%s~SN (%s %s)" % (river_id, river_side, river_order)
    )

    MDashboardRiver.remove_river(request.user.pk, river_side, river_order)
    dashboard_rivers = MDashboardRiver.get_user_rivers(request.user.pk)

    return {
        "dashboard_rivers": dashboard_rivers,
    }



@ajax_login_required
@json.json_view
def save_dashboard_rivers(request):
    try:
        data = json.decode(request.body)
        dashboard_rivers = data["dashboard_rivers"]
    except KeyError:
        return {"code": -1, "message": gettext("Invalid JSON data")}

    if not isinstance(dashboard_rivers, list):
        return {"code": -1, "message": gettext("dashboard_rivers must be a list")}

    # Validate all rivers first
    for river_data in dashboard_rivers:
        if not all(k in river_data for k in ["river_id", "river_side", "river_order"]):
            return {
                "code": -1,
                "message": gettext("Each river must have river_id, river_side, and river_order"),
            }

        try:
            river_order = int(river_data["river_order"])
            if river_order < 0:
                return {"code": -1, "message": gettext("river_order must be non-negative")}
        except ValueError:
            return {"code": -1, "message": gettext("river_order must be an integer")}

    logging.user(request, "~FCSaving dashboard rivers: ~SB%s~SN" % dashboard_rivers)

    # Delete all existing rivers for this user
    MDashboardRiver.objects(user_id=request.user.pk).delete()

    # Save new rivers in order
    for river_data in dashboard_rivers:
        MDashboardRiver.objects.create(
            user_id=request.user.pk,
            river_id=river_data["river_id"],
            river_side=river_data["river_side"],
            river_order=int(river_data["river_order"]),
        )

    # Get updated rivers
    dashboard_rivers = MDashboardRiver.get_user_rivers(request.user.pk)

    return {
        "dashboard_rivers": dashboard_rivers,
    }



@ajax_login_required
@json.json_view
def save_feed_auto_mark_read(request):
    """
    Save the auto-mark-read setting for a feed.

    POST Parameters:
        feed_id: The feed ID to update
        auto_mark_read_days: Number of days (1-365), 0 for never, or null/empty for inherit
    """
    user = request.user
    feed_id = request.POST.get("feed_id")
    days = request.POST.get("auto_mark_read_days")

    if not feed_id:
        return {"code": -1, "message": gettext("Feed ID required")}

    try:
        feed_id = int(feed_id)
    except (ValueError, TypeError):
        return {"code": -1, "message": gettext("Invalid feed ID")}

    # Get the user subscription
    try:
        sub = UserSubscription.objects.get(user=user, feed_id=feed_id)
    except UserSubscription.DoesNotExist:
        return {"code": -1, "message": gettext("Feed not found in subscriptions")}

    # Parse days value
    if days is None or days == "" or days == "null":
        sub.auto_mark_read_days = None  # Inherit from folder/site-wide
    else:
        try:
            days = int(days)
            if days < 0 or days > 365:
                return {"code": -1, "message": gettext("Days must be between 0 and 365")}
            sub.auto_mark_read_days = days
        except (ValueError, TypeError):
            return {"code": -1, "message": gettext("Invalid days value")}

    sub.needs_unread_recalc = True
    sub.save()

    # Calculate effective setting for response
    effective_days, source = sub.get_effective_auto_mark_read_days()

    logging.user(
        request,
        "~FBSaving feed auto-mark-read: ~SB%s~SN days=%s (effective: %s from %s)"
        % (feed_id, sub.auto_mark_read_days, effective_days, source),
    )

    return {
        "code": 1,
        "feed_id": feed_id,
        "auto_mark_read_days": sub.auto_mark_read_days,
        "effective_days": effective_days,
        "source": source,
    }



@ajax_login_required
@json.json_view
def save_folder_auto_mark_read(request):
    """
    Save the auto-mark-read setting for a folder.

    POST Parameters:
        folder_title: The folder title to update
        auto_mark_read_days: Number of days (1-365), 0 for never, or null/empty for inherit
    """
    user = request.user
    folder_title = request.POST.get("folder_title", "").replace("river:", "")
    days = request.POST.get("auto_mark_read_days")

    if not folder_title:
        return {"code": -1, "message": gettext("Folder title required")}

    # Parse days value
    if days is None or days == "" or days == "null":
        # Delete the setting to inherit from parent
        MFolderAutoMarkRead.delete_folder_setting(user.pk, folder_title)
        # Clearing the setting means "inherit", so report null rather than echoing
        # the "null" string the browser posted back.
        days = None
    else:
        try:
            days = int(days)
            if days < 0 or days > 365:
                return {"code": -1, "message": gettext("Days must be between 0 and 365")}
            MFolderAutoMarkRead.save_folder_setting(user.pk, folder_title, days)
        except (ValueError, TypeError):
            return {"code": -1, "message": gettext("Invalid days value")}

    # Trigger recalc for all feeds in this folder
    try:
        usf = UserSubscriptionFolders.objects.get(user=user)
        flat_folders = usf.flatten_folders()
        affected_feeds = []

        # Collect all feeds that might be affected (this folder and nested folders)
        for ft, feed_ids in flat_folders.items():
            if ft == folder_title or ft.startswith(folder_title + " - "):
                affected_feeds.extend(feed_ids)

        if affected_feeds:
            UserSubscription.objects.filter(user=user, feed_id__in=affected_feeds).update(
                needs_unread_recalc=True
            )
    except UserSubscriptionFolders.DoesNotExist:
        pass

    logging.user(
        request,
        "~FBSaving folder auto-mark-read: ~SB%s~SN days=%s" % (folder_title, days),
    )

    # Return all folder settings
    folder_settings = MFolderAutoMarkRead.get_folder_settings_for_user(user.pk)
    return {
        "code": 1,
        "folder_title": folder_title,
        "auto_mark_read_days": days if days != "" and days is not None else None,
        "folder_auto_mark_read": {fs.folder_title: fs.to_json() for fs in folder_settings},
    }



@ajax_login_required
@json.json_view
def get_auto_mark_read_settings(request):
    """
    Get all auto-mark-read settings for the user (folders and feeds).

    Returns folder settings and site-wide setting.
    """
    user = request.user

    # Get all folder settings
    folder_settings = MFolderAutoMarkRead.get_folder_settings_for_user(user.pk)

    # Get site-wide setting
    site_wide_days = user.profile.days_of_unread

    return {
        "code": 1,
        "folder_auto_mark_read": {fs.folder_title: fs.to_json() for fs in folder_settings},
        "site_wide_days": site_wide_days,
    }
