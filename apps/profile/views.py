"""User profile views: account settings, login/signup, and preferences.

Manages user authentication (login, signup, logout), profile settings,
notification preferences, and account maintenance for the personal edition.
"""

import datetime
import os
import shutil
import time

import redis
import requests
from django.conf import settings
from django.contrib.auth import login as login_user
from django.contrib.auth import logout as logout_user
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import connection
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext, gettext_lazy
from django.views.decorators.csrf import csrf_exempt, csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_POST
from apps.analyzer import classifiers
from apps.profile.forms import (
    AccountSettingsForm,
    DeleteAccountForm,
    ForgotPasswordForm,
    ForgotPasswordReturnForm,
)
from apps.profile.models import Profile
from apps.profile.preferences import PreferenceError, coerce_preference
from apps.reader.forms import LoginForm, SignupForm
from apps.reader.models import UserSubscription, UserSubscriptionFolders
from apps.rss_feeds.models import MStarredStory, MStarredStoryCounts
from utils import json_functions as json
from utils import log as logging
from utils.languages import normalize_language
from utils.user_functions import ajax_login_required
from utils.view_functions import render_to

INTEGER_FIELD_PREFS = ("feed_pane_size", "days_of_unread")
SINGLE_FIELD_PREFS = (
    "timezone",
    "send_emails",
    "hide_getting_started",
    "has_setup_feeds",
    "has_found_friends",
    "has_trained_intelligence",
)
SPECIAL_PREFERENCES = (
    "old_password",
    "new_password",
    "dashboard_date",
)

@ajax_login_required
@require_POST
@json.json_view
def set_preference(request):
    code = 1
    message = ""
    new_preferences = request.POST
    if "language" in new_preferences and normalize_language(new_preferences["language"]) is None:
        return dict(code=-1, message=gettext("Unsupported language"))

    profile = request.user.profile
    preferences = json.decode(profile.preferences)
    reschedule_feeds = False

    # Validate the whole request before writing anything: save_preferences() posts
    # several keys at once, and one malformed value should not half-apply a batch.
    validated = {}
    try:
        for preference_name, preference_value in list(new_preferences.items()):
            if preference_name == "language":
                validated[preference_name] = normalize_language(preference_value)
            elif preference_name in SINGLE_FIELD_PREFS:
                validated[preference_name] = coerce_preference(preference_name, preference_value)
            elif preference_name in INTEGER_FIELD_PREFS:
                validated[preference_name] = coerce_preference(preference_name, preference_value)
            elif preference_name in SPECIAL_PREFERENCES:
                validated[preference_name] = preference_value
            else:
                validated[preference_name] = coerce_preference(preference_name, preference_value)
    except PreferenceError as error:
        return dict(code=-1, message=str(error))

    for preference_name, preference_value in validated.items():
        if preference_name in SINGLE_FIELD_PREFS:
            setattr(profile, preference_name, preference_value)
        elif preference_name in INTEGER_FIELD_PREFS:
            if preference_name == "days_of_unread" and preference_value != profile.days_of_unread:
                UserSubscription.all_subs_needs_unread_recalc(request.user.pk)
            setattr(profile, preference_name, preference_value)
            if preference_name in preferences:
                del preferences[preference_name]
        elif preference_name in SPECIAL_PREFERENCES:
            if preference_name == "dashboard_date":
                profile.dashboard_date = datetime.datetime.utcnow()
        else:
            if preference_name == "fetch_interval":
                reschedule_feeds = True
            preferences[preference_name] = preference_value
        if preference_name == "intro_page":
            logging.user(request, "~FBAdvancing intro to page ~FM~SB%s" % preference_value)

    profile.preferences = json.encode(preferences)
    profile.save()

    if reschedule_feeds:
        # The reader-wide fetch interval only takes effect once every feed is
        # rescheduled against it (apps/rss_feeds/models.py get_global_fetch_interval).
        from apps.rss_feeds.models import Feed

        for feed in Feed.objects.all():
            feed.set_next_scheduled_update(verbose=False)

    logging.user(request, "~FMSaving preference: %s" % new_preferences)
    response = dict(code=code, message=message, new_preferences=new_preferences)
    return response

@ajax_login_required
@json.json_view
def get_preference(request):
    code = 1
    preference_name = request.POST.get("preference")
    preferences = json.decode(request.user.profile.preferences)

    payload = preferences
    if preference_name:
        if preference_name in SINGLE_FIELD_PREFS:
            # These live on the Profile model, not in the preferences JSON blob
            # (see set_preference above), so read the field for a fresh value.
            payload = getattr(request.user.profile, preference_name)
            if not isinstance(payload, (bool, int, str, type(None))):
                payload = str(payload)
        else:
            payload = preferences.get(preference_name)

    response = dict(code=code, payload=payload)
    return response

def _safe_next_url(request):
    """Return the POSTed next target only when it stays on this host.

    apps/profile/views.py: login and signup both bounced to request.POST["next"]
    unchecked, which allowed https://example.com/evil and raised KeyError (500)
    when the field was missing.
    """
    target = request.POST.get("next") or ""
    if target and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return target
    return reverse("index")


@csrf_protect
def login(request):
    form = LoginForm()

    if request.method == "POST":
        form = LoginForm(data=request.POST)
        if form.is_valid():
            login_user(request, form.get_user(), backend="django.contrib.auth.backends.ModelBackend")
            logging.user(form.get_user(), "~FG~BBOAuth Login~FW")
            return HttpResponseRedirect(_safe_next_url(request))

    return render(
        request,
        "accounts/login.html",
        {"form": form, "next": request.POST.get("next", "") or request.GET.get("next", "")},
    )

@csrf_protect
@ensure_csrf_cookie
def signup(request):
    form = SignupForm(prefix="signup")
    recaptcha = request.POST.get("g-recaptcha-response", None)
    recaptcha_error = None

    if settings.ENFORCE_SIGNUP_CAPTCHA:
        if not recaptcha:
            recaptcha_error = 'Please hit the "I\'m not a robot" button.'
        else:
            response = requests.post(
                "https://www.google.com/recaptcha/api/siteverify",
                {
                    "secret": settings.RECAPTCHA_SECRET_KEY,
                    "response": recaptcha,
                },
            )
            result = response.json()
            if not result["success"]:
                recaptcha_error = 'Really, please hit the "I\'m not a robot" button.'

    if request.method == "POST":
        form = SignupForm(data=request.POST, prefix="signup")
        if form.is_valid() and not recaptcha_error:
            new_user = form.save(request=request)
            login_user(request, new_user, backend="django.contrib.auth.backends.ModelBackend")
            logging.user(new_user, "~FG~SB~BBNEW SIGNUP: ~FW%s" % new_user.email)
            new_user.profile.activate_free()

            return HttpResponseRedirect(_safe_next_url(request))

    return render(
        request,
        "accounts/signup.html",
        {
            "form": form,
            "recaptcha_error": recaptcha_error,
            "next": request.POST.get("next", ""),
        },
    )

@ajax_login_required
@require_POST
@json.json_view
def set_account_settings(request):
    code = -1
    message = "OK"

    form = AccountSettingsForm(user=request.user, data=request.POST)
    if form.is_valid():
        form.save()
        code = 1
    else:
        message = form.errors[list(form.errors.keys())[0]][0]

    payload = {
        "username": request.user.username,
        "email": request.user.email,
    }
    return dict(code=code, message=message, payload=payload)

@ajax_login_required
@require_POST
@json.json_view
def set_view_setting(request):
    feed_id = request.POST.get("feed_id")
    if not feed_id:
        return dict(code=-1, message="Missing feed_id.")
    code = 1
    feed_view_setting = request.POST.get("feed_view_setting")
    feed_order_setting = request.POST.get("feed_order_setting")
    feed_read_filter_setting = request.POST.get("feed_read_filter_setting")
    feed_layout_setting = request.POST.get("feed_layout_setting")
    feed_dashboard_count_setting = request.POST.get("feed_dashboard_count_setting")
    feed_stories_discover_setting = request.POST.get("feed_stories_discover_setting")
    view_settings = json.decode(request.user.profile.view_settings)

    setting = view_settings.get(feed_id, {})
    if isinstance(setting, str):
        setting = {"v": setting}
    if feed_view_setting:
        setting["v"] = feed_view_setting
    if feed_order_setting:
        setting["o"] = feed_order_setting
    if feed_read_filter_setting:
        setting["r"] = feed_read_filter_setting
    if feed_dashboard_count_setting:
        setting["d"] = feed_dashboard_count_setting
    if feed_layout_setting:
        setting["l"] = feed_layout_setting
    if feed_stories_discover_setting:
        setting["s"] = feed_stories_discover_setting

    view_settings[feed_id] = setting
    request.user.profile.view_settings = json.encode(view_settings)
    request.user.profile.save()

    logging.user(
        request,
        "~FMView settings: %s/%s/%s/%s"
        % (feed_view_setting, feed_order_setting, feed_read_filter_setting, feed_layout_setting),
    )
    response = dict(code=code, view_settings=view_settings)
    return response

@ajax_login_required
@require_POST
@json.json_view
def clear_view_setting(request):
    code = 1
    view_setting_type = request.POST.get("view_setting_type")
    view_settings = json.decode(request.user.profile.view_settings)
    new_view_settings = {}
    removed = 0
    for feed_id, view_setting in list(view_settings.items()):
        if view_setting_type == "layout" and "l" in view_setting:
            del view_setting["l"]
            removed += 1
        if view_setting_type == "view" and "v" in view_setting:
            del view_setting["v"]
            removed += 1
        if view_setting_type == "order" and "o" in view_setting:
            del view_setting["o"]
            removed += 1
        if view_setting_type == "order" and "r" in view_setting:
            del view_setting["r"]
            removed += 1
        new_view_settings[feed_id] = view_setting

    request.user.profile.view_settings = json.encode(new_view_settings)
    request.user.profile.save()

    logging.user(request, "~FMClearing view settings: %s (found %s)" % (view_setting_type, removed))
    response = dict(code=code, view_settings=view_settings, removed=removed)
    return response


@ajax_login_required
@require_POST
@json.json_view
def set_collapsed_folders(request):
    code = 1
    collapsed_folders = request.POST.get("collapsed_folders", "[]")

    request.user.profile.collapsed_folders = collapsed_folders
    request.user.profile.save()

    logging.user(request, "~FMCollapsing folder: %s" % collapsed_folders)
    response = dict(code=code)
    return response


@login_required
@render_to("profile/delete_account.xhtml")
def delete_account(request):
    if request.method == "POST":
        form = DeleteAccountForm(request.POST, user=request.user)
        if form.is_valid():
            logging.user(request.user, "~SK~BC~FRDeleting ~SB%s~SN's account." % request.user.username)
            request.user.profile.delete_user(confirm=True)
            logout_user(request)
            return HttpResponseRedirect(reverse("index"))
        else:
            logging.user(
                request.user, "~BC~FRFailed attempt to delete ~SB%s~SN's account." % request.user.username
            )
    else:
        logging.user(request.user, "~BC~FRAttempting to delete ~SB%s~SN's account." % request.user.username)
        form = DeleteAccountForm(user=request.user)

    return {
        "delete_form": form,
    }

@render_to("profile/forgot_password.xhtml")
def forgot_password(request):
    if request.method == "POST":
        form = ForgotPasswordForm(request.POST)
        if form.is_valid():
            # Use the cleaned email, since the form strips the surrounding whitespace
            # that the raw POST value still carries. Looking the raw value up instead
            # misses the account the form just validated.
            email = form.cleaned_data["email"]
            logging.user(request.user, "~BC~FRForgot password: ~SB%s" % email)
            try:
                user = User.objects.get(email__iexact=email)
            except User.MultipleObjectsReturned:
                user = User.objects.filter(email__iexact=email)[0]
            except User.DoesNotExist:
                # The account went away between form validation and this lookup.
                logging.user(request.user, "~BC~FRFailed forgot password: ~SB%s~SN" % email)
                form.add_error("email", "No user has that email address.")
                user = None
            if user:
                user.profile.send_forgot_password_email()
                return HttpResponseRedirect(reverse("index"))
        else:
            logging.user(request.user, "~BC~FRFailed forgot password: ~SB%s~SN" % request.POST.get("email"))
    else:
        logging.user(request.user, "~BC~FRAttempting to retrieve forgotton password.")
        form = ForgotPasswordForm()

    return {
        "forgot_password_form": form,
    }

@login_required
@render_to("profile/forgot_password_return.xhtml")
def forgot_password_return(request):
    if request.method == "POST":
        logging.user(request.user, "~BC~FRReseting ~SB%s~SN's password." % request.user.username)
        new_password = request.POST.get("password", "")
        request.user.set_password(new_password)
        request.user.save()
        return HttpResponseRedirect(reverse("index"))
    else:
        logging.user(request.user, "~BC~FRAttempting to reset ~SB%s~SN's password." % request.user.username)
        form = ForgotPasswordReturnForm()

    return {
        "forgot_password_return_form": form,
    }

@ajax_login_required
@json.json_view
def delete_starred_stories(request):
    timestamp = request.POST.get("timestamp", None)
    if timestamp:
        delete_date = datetime.datetime.fromtimestamp(int(timestamp))
    else:
        delete_date = datetime.datetime.now()
    starred_stories = MStarredStory.objects.filter(user_id=request.user.pk, starred_date__lte=delete_date)
    stories_deleted = starred_stories.count()
    starred_stories.delete()

    MStarredStoryCounts.count_for_user(request.user.pk, total_only=True)
    starred_counts, starred_count = MStarredStoryCounts.user_counts(request.user.pk, include_total=True)

    logging.user(
        request.user,
        "~BC~FRDeleting %s/%s starred stories (%s)"
        % (stories_deleted, stories_deleted + starred_count, delete_date),
    )

    return dict(
        code=1, stories_deleted=stories_deleted, starred_counts=starred_counts, starred_count=starred_count
    )

@ajax_login_required
@json.json_view
def count_starred_stories(request):
    timestamp = request.POST.get("timestamp", None)
    if timestamp:
        delete_date = datetime.datetime.fromtimestamp(int(timestamp))
    else:
        delete_date = datetime.datetime.now()
    count = MStarredStory.objects.filter(user_id=request.user.pk, starred_date__lte=delete_date).count()
    return dict(code=1, count=count)

@ajax_login_required
@json.json_view
def count_classifiers(request):
    counts = classifiers.counts(request.user.pk)
    total = sum(counts.values())
    return dict(code=1, counts=counts, total=total)

@ajax_login_required
@json.json_view
def delete_classifiers(request):
    categories = request.POST.getlist("categories")
    deleted_counts = classifiers.delete_categories(request.user.pk, categories)
    total_deleted = sum(deleted_counts.values())

    logging.user(
        request.user,
        "~BC~FRDeleting %s classifiers (%s)"
        % (total_deleted, ", ".join("%s: %s" % (k, v) for k, v in deleted_counts.items())),
    )

    return dict(code=1, total_deleted=total_deleted, deleted_counts=deleted_counts)

@ajax_login_required
@json.json_view
def delete_all_sites(request):
    request.user.profile.send_opml_export_email(
        reason=gettext_lazy(
            "You have deleted all of your sites, so here's a backup of all of your subscriptions just in case."
        )
    )

    subs = UserSubscription.objects.filter(user=request.user)
    sub_count = subs.count()
    subs.delete()

    usf = UserSubscriptionFolders.objects.get(user=request.user)
    usf.folders = "[]"
    usf.save()

    logging.user(request.user, "~BC~FRDeleting %s sites" % sub_count)

    return dict(code=1)

@login_required
@render_to("profile/email_optout.xhtml")
def email_optout(request):
    """Unsubscribe from all NewsBlur emails. GET shows a confirmation button so that
    mail clients pre-loading links don't unsubscribe anybody; only the POST from the
    button on templates/profile/email_optout.xhtml actually unsubscribes."""
    user = request.user
    unsubscribed = False

    if request.method == "POST":
        user.profile.send_emails = False
        user.profile.save()
        unsubscribed = True
        logging.user(user, "~BB~FM~SBUnsubscribed from all NewsBlur emails")

    return {
        "user": user,
        "unsubscribed": unsubscribed,
    }

@csrf_exempt
@render_to("profile/email_optout.xhtml")
def email_optout_token(request, username, secret):
    """Tokened unsubscribe link used in email footers (templates/mail/email_base.xhtml).
    Validates the same secret_token as the autologin links in emails and logs the user
    in, so no login is required to unsubscribe. GET shows a confirmation button; POST
    unsubscribes. POST also serves RFC 8058 List-Unsubscribe one-click requests from
    mail providers, which is why this view is csrf_exempt: the secret token in the URL
    authorizes the action."""
    profile = Profile.objects.filter(user__username=username, secret_token=secret).first()
    if not profile:
        return HttpResponseForbidden()

    user = profile.user
    if request.user.pk != user.pk:
        user.backend = settings.AUTHENTICATION_BACKENDS[0]
        login_user(request, user, backend="django.contrib.auth.backends.ModelBackend")
        logging.user(user, "~FG~BB~SKAuto-Login via email unsubscribe link~FW")

    unsubscribed = False
    if request.method == "POST":
        profile.send_emails = False
        profile.save()
        unsubscribed = True
        logging.user(user, "~BB~FM~SBUnsubscribed from all NewsBlur emails via email link")

    return {
        "user": user,
        "unsubscribed": unsubscribed,
    }



# ---------------------------------------------------------------------------
# Storage usage
# ---------------------------------------------------------------------------

STORAGE_CACHE_SECONDS = 60
storage_cache = {"at": 0, "data": None}


def directory_size(path):
    total = 0
    for root, dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def database_size():
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_database_size(current_database())")
        return int(cursor.fetchone()[0])


def cache_size():
    client = redis.Redis(connection_pool=settings.REDIS_POOL)
    return int(client.info("memory").get("used_memory", 0))


@ajax_login_required
@json.json_view
def storage_usage(request):
    """Disk the personal edition occupies on its host, for the preferences modal.

    Walking media/ and static/ takes a moment, so the answer is cached for a
    minute. Postgres and Redis live in containers, so their numbers are the
    logical database size and the Redis allocator size, not the volume bytes.
    """
    now = time.time()
    if storage_cache["data"] and now - storage_cache["at"] < STORAGE_CACHE_SECONDS:
        return storage_cache["data"]

    database = database_size()
    media = directory_size(settings.MEDIA_ROOT)
    static = directory_size(settings.STATIC_ROOT)
    logs = directory_size(os.path.dirname(settings.LOG_FILE))
    cache = cache_size()
    host = shutil.disk_usage(settings.MEDIA_ROOT)
    data = {
        "database": database,
        "media": media,
        "static": static,
        "logs": logs,
        "cache": cache,
        "total": database + media + static + logs + cache,
        "host_total": host.total,
        "host_used": host.used,
        "host_free": host.free,
    }
    storage_cache["at"] = now
    storage_cache["data"] = data
    return data


@csrf_exempt
@require_POST
def csp_report(request):
    """apps/profile/views.py records Content Security Policy violations.

    The enforcing policy reports blocked scripts and styles here, so a missed
    nonce or a newly blocked third-party request is visible in the logs. Keep the
    log line bounded: a browser can send a large report body and an attacker can
    post arbitrary content here.
    """
    payload = request.body[:8192].decode("utf-8", "replace").replace("\n", " ").replace("\r", " ")
    logging.warning("CSP report: %s" % payload)
    return HttpResponse(status=204)
