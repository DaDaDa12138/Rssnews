"""One source of truth for the URLs JavaScript calls.

The reader used to spell its routes out three ways: {% url %} in templates,
reverse() in Python, and about ninety string literals in media/js. Renaming a
route updated the first two and left the JavaScript posting to a dead path,
which failed silently in the browser. NEWSBLUR.URLs is now generated from the
URLconf and every call site reads from it, so a rename either works everywhere
or fails apps/reader/tests_urls.py.
"""

from functools import lru_cache

from django.urls import NoReverseMatch, get_resolver, reverse

# Routes that take arguments, spelled with {placeholders} the call sites fill in.
# apps/reader/tests_urls.py reverses each of these with real values and compares,
# so these templates cannot drift from the URLconf.
PARAMETERIZED_ROUTES = {
    "load-single-feed": "/reader/feed/{feed_id}",
    "load-feed-page": "/reader/page/{feed_id}",
    "feed-info": "/rss_feeds/feed/{feed_id}",
    "feed-settings": "/rss_feeds/feed_settings/{feed_id}",
    "feed-statistics": "/rss_feeds/statistics/{feed_id}",
    "feed-statistics-embedded": "/rss_feeds/statistics_embedded/{feed_id}",
    "favicon": "/rss_feeds/icon/{id}",
    "folder_rss": "/reader/folder_rss/{user_id}/{secret_token}/{unread_filter}/{folder_title}",
}

# The reader only needs its own routes; the admin and the health checks stay out
# of a map that every page ships to the browser.
APP_PREFIXES = ("/reader/", "/profile/", "/rss_feeds/", "/classifier/", "/analyzer/", "/import/")

# Root-level routes the reader's JavaScript calls. They stay out of APP_PREFIXES
# because they are not part of the reader URL tree, but pwa.js needs the worker
# path from the same generated table as every other client-side route.
EXTRA_ROUTES = ("pwa-service-worker",)


@lru_cache(maxsize=1)
def build_url_map():
    """Every named route that needs no arguments, keyed by URL name."""
    urls = {}
    for name in get_resolver().reverse_dict:
        if not isinstance(name, str):
            continue
        try:
            path = reverse(name)
        except NoReverseMatch:
            continue
        if path.startswith(APP_PREFIXES) or name in EXTRA_ROUTES:
            urls[name] = path
    urls.update(PARAMETERIZED_ROUTES)
    return urls
