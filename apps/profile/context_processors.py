"""Template context for the reader's preferences.

templates/base.html used to carry its own copy of every preference default and
spliced the stored JSON blobs into a <script> block with |safe. Both now come from
apps/profile/preferences.py and json_script, so the defaults live in one place and
the blobs cannot break out of their script tags.
"""

from django.core.exceptions import ObjectDoesNotExist

from apps.profile.preferences import PREFERENCE_DEFAULTS, clean_preferences
from utils import json_functions as json


def _decode(raw, expected):
    if not raw:
        return expected
    try:
        value = json.decode(raw)
    except (TypeError, ValueError):
        return expected
    if not isinstance(value, type(expected)):
        return expected
    return value


def preference_context(request):
    user = getattr(request, "user", None)
    profile = None
    if user is not None and user.is_authenticated:
        try:
            profile = user.profile
        except ObjectDoesNotExist:
            profile = None

    if profile is None:
        return {
            "preference_defaults": PREFERENCE_DEFAULTS,
            "user_preferences": {},
            "user_view_settings": {},
            "user_collapsed_folders": [],
            # base.html: an anonymous visitor's theme is whatever their browser cached,
            # so there is no server-side answer to hand the first-paint script.
            "theme_state": {"theme": None, "authenticated": False},
        }

    preferences = clean_preferences(_decode(profile.preferences, {}))
    return {
        "preference_defaults": PREFERENCE_DEFAULTS,
        "user_preferences": preferences,
        "user_view_settings": _decode(profile.view_settings, {}),
        "user_collapsed_folders": _decode(profile.collapsed_folders, []),
        # base.html: the stored preference is the only truth for a signed-in reader.
        # The first-paint script reads this instead of trusting its localStorage cache,
        # which used to expire after six hours and flip the theme back.
        "theme_state": {"theme": preferences.get("theme", "auto"), "authenticated": True},
    }
