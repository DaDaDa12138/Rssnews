"""Schema, defaults, and validation for the Profile.preferences JSON blob.

The blob is a single TextField (apps/profile/models.py:41) that used to accept any
key with any value: set_preference (apps/profile/views.py) copied POST data into it
verbatim, and templates/base.html kept a second, hand-written copy of every default
in JavaScript. A typo in either place was silent, and a key that no code read stayed
in the blob forever.

PREFERENCE_DEFAULTS is now the only place the reader's defaults live. It is rendered
into templates/base.html through json_script (apps/profile/context_processors.py),
and set_preference validates every key against PREFERENCE_TYPES before writing.

Keys that live on Profile model fields instead of the blob (feed_pane_size,
days_of_unread, timezone, send_emails, hide_getting_started, has_setup_feeds,
has_found_friends, has_trained_intelligence) are listed in FIELD_PREFERENCES and
handled by set_preference's existing branches. They are not part of the blob.
"""

from django.utils.translation import gettext

BOOL = "bool"
INT = "int"
STRING = "string"
LIST = "list"
DICT = "dict"

# Defaults rendered into templates/base.html as NEWSBLUR.Preferences.
# Mirrors the values the template hard-coded before this module existed.
PREFERENCE_DEFAULTS = {
    "unread_view": 0,
    "lock_mouse_indicator": 300,
    "story_titles_pane_size": 420,
    "story_pane_anchor": "west",
    "new_window": 1,
    "default_view": "feed",
    "default_order": "newest",
    "default_read_filter": "all",
    "default_dashboard_count": 5,
    "grid_columns": 0,
    "grid_height": "m",
    "hide_read_feeds": 0,
    "show_tooltips": 1,
    "show_contextmenus": 1,
    "feed_order": "ALPHABETICAL",
    "keyboard_verticalarrows": "story",
    "keyboard_horizontalarrows": "view",
    "space_scroll_spacing": 40,
    "arrow_scroll_spacing": 100,
    "space_bar_action": "next_unread",
    "infrequent_stories_per_month": 30,
    "ssl": 0,
    "open_feed_action": "newest",
    "read_story_delay": 0,
    "feed_view_single_story": 0,
    "animations": True,
    "dateformat": "12",
    "folder_counts": False,
    "view_settings": {},
    "story_layout": "split",
    "collapsed_folders": [],
    "story_styling": "sans-serif",
    "feed_font": "whitney",
    "feed_size": "m",
    "story_size": "m",
    "story_line_spacing": "m",
    "story_button_placement": "right",
    "sticky_story_sideoptions": True,
    "title_counts": True,
    "show_infrequent_site_stories": True,
    "full_width_story": False,
    "story_position": "center",
    "truncate_story": "none",
    "autoopen_folder": False,
    "show_content_preview": True,
    "image_preview": "small-right",
    "mark_read_on_scroll_titles": False,
    "density": "comfortable",
    "doubleclick_feed": "open",
    "doubleclick_unread": "markread",
    "mark_read_river_confirm": "folders_only",
    "markread_nextfeed": "nextfeed",
    "show_sideoption_save": True,
    "show_sideoption_train": True,
    "theme": "auto",
    "highlights": True,
    "dashboard_columns": 2,
    "mark_read_days": 1,
    "mark_unread_days": 14,
}

# Preferences stored on Profile model fields rather than in the blob.
# apps/profile/views.py:44-52 owns their branches in set_preference.
FIELD_PREFERENCES = (
    "feed_pane_size",
    "days_of_unread",
    "timezone",
    "send_emails",
    "hide_getting_started",
    "has_setup_feeds",
    "has_found_friends",
    "has_trained_intelligence",
)

# Keys written outside the reader UI: apps/profile/language.py saves "language",
# and "hide_mobile" is a legacy account setting that set_preference used to setattr
# onto the Profile even though no such field exists (so it never persisted).
EXTRA_PREFERENCE_TYPES = {"language": STRING, "hide_mobile": BOOL}

# Preferences whose value must be one of a fixed set. "theme" drives body.NB-dark
# (media/css/reader/grid.css:835) and the first-paint script in templates/base.html,
# so a stale or hand-written value would leave the reader with no theme at all.
ENUM_PREFERENCES = {"theme": ("auto", "light", "dark")}

MAX_STRING_LENGTH = 200
MAX_LIST_LENGTH = 500
MAX_DICT_KEYS = 200


class PreferenceError(ValueError):
    """Raised when a preference key or value fails validation."""


def _type_of(default):
    if isinstance(default, bool):
        return BOOL
    if isinstance(default, int):
        return INT
    if isinstance(default, str):
        return STRING
    if isinstance(default, dict):
        return DICT
    if isinstance(default, list):
        return LIST
    raise TypeError("Unsupported preference default: %r" % (default,))


PREFERENCE_TYPES = {key: _type_of(value) for key, value in PREFERENCE_DEFAULTS.items()}
PREFERENCE_TYPES.update(EXTRA_PREFERENCE_TYPES)

# Types for the keys set_preference stores on Profile model fields. They are valid
# request keys but never belong in the blob.
FIELD_PREFERENCE_TYPES = {
    "feed_pane_size": INT,
    "days_of_unread": INT,
    "timezone": STRING,
    "send_emails": BOOL,
    "hide_getting_started": BOOL,
    "has_setup_feeds": BOOL,
    "has_found_friends": BOOL,
    "has_trained_intelligence": BOOL,
}
PREFERENCE_TYPES.update(FIELD_PREFERENCE_TYPES)


def is_known(name):
    """True for keys that belong in the Profile.preferences blob."""
    return name in PREFERENCE_TYPES and name not in FIELD_PREFERENCE_TYPES


def _as_bool(name, raw):
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int) and raw in (0, 1):
        return bool(raw)
    if isinstance(raw, str):
        lowered = raw.strip().lower()
        if lowered in ("true", "1", "on", "yes"):
            return True
        if lowered in ("false", "0", "off", "no"):
            return False
    raise PreferenceError(gettext("Preference %(name)s must be true or false") % {"name": name})


def _as_int(name, raw):
    if isinstance(raw, bool):
        # The reader's toggles (show_tooltips, hide_read_feeds) default to 1/0 but
        # JavaScript sends booleans once they are switched.
        return int(raw)
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        try:
            return int(raw.strip())
        except ValueError:
            pass
    raise PreferenceError(gettext("Preference %(name)s must be a whole number") % {"name": name})


def _as_string(name, raw):
    if not isinstance(raw, str):
        raise PreferenceError(gettext("Preference %(name)s must be text") % {"name": name})
    value = raw.strip()
    if len(value) > MAX_STRING_LENGTH:
        raise PreferenceError(
            gettext("Preference %(name)s is longer than %(max)s characters")
            % {"name": name, "max": MAX_STRING_LENGTH}
        )
    return value


def _as_list(name, raw):
    if not isinstance(raw, list):
        raise PreferenceError(gettext("Preference %(name)s must be a list") % {"name": name})
    if len(raw) > MAX_LIST_LENGTH:
        raise PreferenceError(
            gettext("Preference %(name)s holds more than %(max)s items")
            % {"name": name, "max": MAX_LIST_LENGTH}
        )
    for item in raw:
        if isinstance(item, (dict, list)):
            raise PreferenceError(gettext("Preference %(name)s must hold plain values") % {"name": name})
    return raw


def _as_dict(name, raw):
    if not isinstance(raw, dict):
        raise PreferenceError(gettext("Preference %(name)s must be an object") % {"name": name})
    if len(raw) > MAX_DICT_KEYS:
        raise PreferenceError(
            gettext("Preference %(name)s holds more than %(max)s keys") % {"name": name, "max": MAX_DICT_KEYS}
        )
    return raw


_COERCERS = {BOOL: _as_bool, INT: _as_int, STRING: _as_string, LIST: _as_list, DICT: _as_dict}


def coerce_preference(name, raw):
    """Validate one POSTed preference and return the value to store.

    Raises PreferenceError for unknown keys and for values that do not match the
    key's declared type. Strings arrive as strings, numbers as strings, and
    booleans as "true"/"false" because the reader posts form data.
    """
    kind = PREFERENCE_TYPES.get(name)
    if kind is None:
        raise PreferenceError(gettext("Unknown preference: %(name)s") % {"name": name})
    value = _COERCERS[kind](name, raw)
    allowed = ENUM_PREFERENCES.get(name)
    if allowed is not None and value not in allowed:
        raise PreferenceError(
            gettext("Preference %(name)s must be one of: %(choices)s")
            % {"name": name, "choices": ", ".join(allowed)}
        )
    return value


def clean_preferences(stored):
    """Return the blob with unknown keys and invalid values dropped.

    Used when the blob is merged with PREFERENCE_DEFAULTS, so a row written by an
    older release (or by hand) cannot smuggle unexpected values into a page.
    """
    if not isinstance(stored, dict):
        return {}
    cleaned = {}
    for name, value in stored.items():
        if not is_known(name):
            continue
        try:
            cleaned[name] = coerce_preference(name, value)
        except PreferenceError:
            continue
    return cleaned


def merged_preferences(stored):
    """PREFERENCE_DEFAULTS overlaid with the values actually stored on the profile."""
    merged = dict(PREFERENCE_DEFAULTS)
    merged.update(clean_preferences(stored))
    return merged
