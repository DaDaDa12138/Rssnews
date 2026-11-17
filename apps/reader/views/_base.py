"""Core feed reader views: subscriptions, story loading, folder management, and mark-read.

Handles the primary API endpoints for the NewsBlur reader -- loading feeds and
stories, managing folders and subscriptions, marking stories as read/unread/saved,
and river (multi-feed) story views.
"""

import base64
import concurrent
import datetime
import hashlib
import http.client
import random
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from collections import defaultdict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import redis
import requests
from django.conf import settings
from django.contrib.auth import login as login_user
from django.contrib.auth import logout as logout_user
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.sites.models import Site
from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives
from django.db import IntegrityError
from django.db.models import Q
from django.db.utils import DatabaseError
from django.http import (
    Http404,
    HttpResponse,
    HttpResponseForbidden,
    HttpResponseRedirect,
    UnreadablePostError,
)
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import feedgenerator
from django.utils.encoding import smart_str
from django.utils.translation import gettext, gettext_lazy
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from utils.documents import NotUniqueError, OperationError

from apps.analyzer import classifiers
from apps.analyzer.models import (
    MClassifierAuthor,
    MClassifierFeed,
    MClassifierTag,
    MClassifierText,
    MClassifierTitle,
    MClassifierUrl,
    apply_classifier_author_regex,
    apply_classifier_authors,
    apply_classifier_feeds,
    apply_classifier_tags,
    apply_classifier_text_regex,
    apply_classifier_texts,
    apply_classifier_title_regex,
    apply_classifier_titles,
    apply_classifier_url_regex,
    apply_classifier_urls,
    classifier_title_matches,
    get_classifiers_for_user,
    load_scoped_classifiers,
    sort_classifiers_by_feed,
)
from apps.profile.models import MCustomStyling, MDashboardRiver, Profile
from apps.reader.forms import LoginForm, SignupForm
from apps.reader.models import (
    MCustomFeedIcon,
    MFolderAutoMarkRead,
    MFolderIcon,
    RUserStory,
    RUserUnreadStory,
    UserSubscription,
    UserSubscriptionFolders,
)
from apps.rss_feeds.models import MFeedIcon, MStarredStoryCounts

try:
    from apps.rss_feeds.models import DuplicateFeed, Feed, MFeedPage, MStarredStory, MStory
except:
    pass

from apps.reader.tasks import MarkStoriesAsUnread
from apps.rss_feeds.tasks import ScheduleImmediateFetches
from utils import json_functions as json
from utils import log as logging
from utils.feed_functions import relative_timesince
from utils.folder_paths import (
    InvalidFolderPath,
    folder_path_errors,
    parse_folder_path,
    parse_folder_paths,
    resolve_folder_path,
)
from utils.ratelimit import ratelimit, ratelimit_by_url_user
from utils.story_functions import (
    format_story_link_date__long,
    format_story_link_date__short,
    strip_tags,
    strip_tags_preserve_blockquote,
)
from utils.url_safety import BLOCKED_PRIVATE_URL_MESSAGE, UnsafeUrlError, validate_public_url
from utils.user_functions import ajax_login_required, extract_user_agent, get_user
from utils.view_functions import (
    RequestDeduplicator,
    get_argument_or_404,
    int_argument,
    is_true,
    render_to,
    required_params,
)
from vendor.timezones.utilities import localtime_for_timezone

BANNED_URLS = [
    "brentozar.com",
]
ALLOWED_SUBDOMAINS = [
    "dev",
    "www",
    "hwww",
    "dwww",
    # 'beta',  # Comment to redirect beta -> www, uncomment to allow beta -> staging (+ dns changes)
    "staging",
    "hstaging",
    "discovery",
    "debug",
    "debug3",
    "staging2",
    "staging3",
    "nb",
]
# Deprecated: lazy merge is now always used for all river loads (no ZUNIONSTORE)
RIVER_SLOWDOWN_USERS = []


def int_or_default(value, default):
    """
    Parse an integer request parameter, falling back to the default when it doesn't parse.

    Bots and broken clients regularly mangle querystrings, sending values like
    page="6&feed_address=https://444.hu/feed&order=newest" or limit="abc". Those are
    garbage rather than a real request, so silently using the default beats a 500.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

def int_feed_ids(feed_ids):
    """
    Convert a list of feed id parameters to integers, dropping anything that isn't numeric.

    Same mangled-querystring problem as int_or_default: feed ids arrive as
    "Entrepreneuriat" or as an entire querystring crammed into one value.
    """
    parsed_feed_ids = []
    for feed_id in feed_ids:
        parsed_feed_id = int_or_default(feed_id, None)
        if parsed_feed_id is not None:
            parsed_feed_ids.append(parsed_feed_id)
    return parsed_feed_ids

def adjust_read_filter_for_date_range(
    read_filter, date_filter_start_utc, date_filter_end_start_utc, unread_cutoff
):
    """
    Auto-switch from unread to all if date filter extends beyond unread cutoff.

    If the read filter is set to unread only and the date range starts or ends
    earlier than the user's unread cutoff, switch to all stories so we can show
    stories that wouldn't otherwise be surfaced.
    """
    if read_filter != "unread":
        return read_filter

    should_switch_to_all = False
    if unread_cutoff:
        unread_cutoff_naive = unread_cutoff.replace(tzinfo=None) if unread_cutoff.tzinfo else unread_cutoff
    else:
        unread_cutoff_naive = None

    if unread_cutoff_naive:
        if date_filter_start_utc and date_filter_start_utc < unread_cutoff_naive:
            should_switch_to_all = True

        if date_filter_end_start_utc and date_filter_end_start_utc < unread_cutoff_naive:
            should_switch_to_all = True

    if should_switch_to_all:
        logging.user(
            None,
            f"~FRSwitching read_filter from unread to all: "
            f"date_start={date_filter_start_utc}, date_end={date_filter_end_start_utc}, "
            f"unread_cutoff={unread_cutoff}",
        )
        return "all"

    return read_filter

def normalize_date_filters(date_filter_start, date_filter_end, user_timezone):
    """
    Convert date filter strings (YYYY-MM-DD) in the user's timezone into UTC datetimes.

    Returns a tuple of:
        (start_utc_inclusive, end_utc_exclusive, end_utc_start_of_day)
    """
    tz = user_timezone or datetime.timezone.utc
    if isinstance(tz, str):
        try:
            tz = ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError):
            tz = datetime.timezone.utc

    start_utc = None
    end_utc_exclusive = None
    end_utc_start_of_day = None

    if date_filter_start and date_filter_start != "all":
        try:
            start_naive = datetime.datetime.strptime(date_filter_start, "%Y-%m-%d")
            start_local = start_naive.replace(tzinfo=tz)
            start_utc = start_local.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        except ValueError:
            start_utc = None

    if date_filter_end and date_filter_end != "all":
        try:
            end_start_naive = datetime.datetime.strptime(date_filter_end, "%Y-%m-%d")
            end_start_local = end_start_naive.replace(tzinfo=tz)
            end_utc_start_of_day = end_start_local.astimezone(datetime.timezone.utc).replace(tzinfo=None)

            next_day_local = end_start_local + datetime.timedelta(days=1)
            end_utc_exclusive = next_day_local.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        except ValueError:
            end_utc_exclusive = None
            end_utc_start_of_day = None

    return start_utc, end_utc_exclusive, end_utc_start_of_day

# Classifier filter banner view: most stories are loaded via the normal
# feed/river/folder path and then narrowed here. Archive folder/global tag
# filters can use the story tag index before falling back to this bounded scan.
# Match semantics mirror apps/analyzer/models.py:apply_classifier_* so the
# banner hits the same stories a trained classifier would.
CLASSIFIER_FILTER_TYPES = ("tag", "author", "title", "url", "text")
# The multiplier inflates the fetch window so post-filtering has enough
# raw stories to actually find every match. Some pages may still return
# fewer than `limit` — deliberately dumb, pagination can keep going.
CLASSIFIER_FILTER_SCAN_MULTIPLIER = 20

def normalize_classifier_filter_params(type_value, raw_value, scope_value):
    classifier_type = (type_value or "").strip() or None
    classifier_value = (raw_value or "").strip() or None
    if classifier_type and classifier_type not in CLASSIFIER_FILTER_TYPES:
        classifier_type = None
        classifier_value = None
    scope = (scope_value or "feed").strip() or "feed"
    if scope not in ("feed", "folder", "global"):
        scope = "feed"
    return classifier_type, classifier_value, scope

def filter_stories_by_classifier(stories, classifier_type, classifier_value):
    if not stories or not classifier_type or not classifier_value:
        return stories

    needle_lower = classifier_value.lower()

    def matches(story):
        if classifier_type == "tag":
            return classifier_value in (story.get("story_tags") or [])
        if classifier_type == "author":
            return story.get("story_authors") == classifier_value
        if classifier_type == "title":
            return classifier_title_matches(story.get("story_title"), classifier_value)
        if classifier_type == "url":
            return needle_lower in (story.get("story_permalink") or "").lower()
        if classifier_type == "text":
            content = story.get("story_content") or ""
            return needle_lower in strip_tags(content).lower()
        return False

    return [story for story in stories if matches(story)]


def _get_url_variants(url):
    """URL spellings to try when matching a story by permalink. apps/reader/views.py"""
    variants = [url]
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme:
        variants.append(url.replace(parsed.scheme + "://", "http://", 1))
        variants.append(url.replace(parsed.scheme + "://", "https://", 1))
    stripped = url.split("#", 1)[0]
    if stripped not in variants:
        variants.append(stripped)
    return variants
