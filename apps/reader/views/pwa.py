"""Progressive Web App endpoints: manifest, service worker, offline shell.

The reader is a server-rendered Django app, so the PWA layer deliberately stays
small: the manifest makes it installable, the service worker caches only static
assets and never authenticated HTML, and the offline shell is a public page.
"""

import hashlib
import re

from django.conf import settings
from django.contrib.staticfiles.storage import staticfiles_storage
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET


PWA_PRECACHE_ASSETS = (
    "css/common.css",
    "js/common_vendor.js",
    "js/common.js",
    "css/pwa-offline.css",
)


def _media(path):
    return settings.MEDIA_URL + path


def _asset_version():
    """Hash the hashed bundle URLs so a deploy retires the old shell cache."""
    digest = hashlib.sha256()
    for path in PWA_PRECACHE_ASSETS:
        digest.update(staticfiles_storage.url(path).encode())
    return digest.hexdigest()[:12]


def _cache_version():
    # The value is interpolated into the worker's JavaScript and a cache name, so
    # keep it to characters that need no escaping there.
    raw = f"{settings.PWA_CACHE_VERSION}-{_asset_version()}"
    return re.sub(r"[^0-9A-Za-z._-]", "-", raw)


@require_GET
@cache_control(max_age=300, public=True)
def manifest(request):
    """Return a Web App Manifest with stable, unhashed icon URLs."""
    icon_192 = _media("img/pwa/icon-192.png")
    icon_512 = _media("img/pwa/icon-512.png")
    maskable_512 = _media("img/pwa/icon-maskable-512.png")
    data = {
        "id": reverse("index"),
        "name": "NewsBlur",
        "short_name": "NewsBlur",
        "description": "A personal news reader for feeds, folders, and saved stories.",
        "lang": "en",
        "dir": "auto",
        "start_url": reverse("index"),
        "scope": reverse("index"),
        "display": "standalone",
        "display_override": ["standalone", "minimal-ui"],
        "orientation": "any",
        "background_color": "#F7F8FA",
        "theme_color": "#1875F3",
        "categories": ["news", "magazines", "productivity"],
        "icons": [
            {"src": icon_192, "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": icon_512, "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": maskable_512, "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
        "shortcuts": [
            {
                "name": "All Stories",
                "short_name": "All Stories",
                "url": reverse("index") + "reader/",
                "icons": [{"src": icon_192, "sizes": "192x192"}],
            },
            {
                "name": "Saved Stories",
                "short_name": "Saved",
                "url": reverse("index") + "saved/",
                "icons": [{"src": icon_192, "sizes": "192x192"}],
            },
        ],
    }
    response = JsonResponse(data, json_dumps_params={"ensure_ascii": False, "indent": 2})
    response["Content-Type"] = "application/manifest+json"
    return response


@require_GET
@cache_control(no_cache=True, no_store=True, must_revalidate=True)
def service_worker(request):
    """Serve the worker from the origin root so its scope can cover the app."""
    response = render(
        request,
        "pwa/service-worker.js",
        {"cache_version": _cache_version()},
        content_type="application/javascript",
    )
    # A worker at /service-worker.js already defaults to /, but the header makes
    # the intent explicit and keeps the route movable without narrowing scope.
    response["Service-Worker-Allowed"] = "/"
    return response


@require_GET
@cache_control(max_age=86400, public=True)
def offline(request):
    """Public offline shell precached by the service worker."""
    # The stylesheet query must match PRECACHE_URLS in the worker, otherwise the
    # cached copy misses and the offline page renders unstyled.
    return render(request, "pwa/offline.html", {"cache_version": _cache_version()})
