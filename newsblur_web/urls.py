"""URL routes for the personal edition.

Everything that belonged to the hosted product (marketing pages, the public API,
social/blurblog, push, mobile apps, OAuth, payments, monitoring) is gone. What is
left is the reader itself plus the handful of endpoints it needs to run.
"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, re_path
from django.views.generic import RedirectView
from utils.staticfiles import serve as static_serve

from apps.profile import health_views
from apps.profile import views as profile_views
from apps.profile.language import (
    FLIPPED_STYLESHEET_PATTERN,
    JAVASCRIPT_CATALOG_PATTERN,
    flipped_stylesheet,
    javascript_catalog,
)
from apps.reader import views as reader_views
from apps.rss_feeds import views as rss_feeds_views

urlpatterns = [
    re_path(JAVASCRIPT_CATALOG_PATTERN, javascript_catalog, name="javascript-catalog"),
    re_path(FLIPPED_STYLESHEET_PATTERN, flipped_stylesheet, name="flipped-stylesheet"),
    re_path(r"^$", reader_views.index, name="index"),
    re_path(r"^reader/", include("apps.reader.urls")),
    re_path(r"^welcome/?$", reader_views.welcome_req, name="welcome-page"),
    re_path(r"^add(?:/.*)?$", reader_views.index),
    # The reader pushes /site/<id>/<slug> for readable URLs, so the slug has to be
    # accepted here too; otherwise a reload or a shared link 404s.
    re_path(r"^site/(?P<feed_id>\d+)?(?:/(?P<slug>[^/]+))?/?$", reader_views.index),
    re_path(r"^folder/(?P<folder_name>[^/]+)?/?$", reader_views.index, name="folder"),
    re_path(r"^saved/(?P<tag_name>[^/]+)?/?$", reader_views.index, name="saved-stories-tag"),
    re_path(r"^saved/?$", reader_views.index),
    re_path(r"^read/?$", reader_views.index),
    re_path(r"^story/.*$", reader_views.index),
    re_path(r"^rss_feeds/", include("apps.rss_feeds.urls")),
    re_path(r"^discover/autocomplete/?$", rss_feeds_views.feed_autocomplete, name="feed-autocomplete"),
    re_path(r"^imageproxy/?$", rss_feeds_views.image_proxy, name="image-proxy"),
    re_path(r"^analyzer/", include("apps.analyzer.urls")),
    re_path(r"^classifier/", include("apps.analyzer.urls")),
    re_path(r"^profile/", include("apps.profile.urls")),
    re_path(r"^import/", include("apps.feed_import.urls")),
    re_path(r"^_haproxychk/?$", health_views.haproxy_check),
    re_path(r"^_dbcheck/postgres/?$", health_views.postgres_check),
    re_path(r"^_dbcheck/redis/?$", health_views.redis_check),
    re_path(r"^admin/", admin.site.urls),
    re_path(r"^login/?$", RedirectView.as_view(pattern_name="login", permanent=True)),
    re_path(r"^signup/?$", RedirectView.as_view(pattern_name="signup", permanent=True)),
    re_path(
        r"^forgot-password/?$",
        RedirectView.as_view(pattern_name="profile-forgot-password", permanent=True),
    ),
    re_path(r"^account/login/?$", profile_views.login, name="login"),
    re_path(r"^account/signup/?$", profile_views.signup, name="signup"),
    re_path(r"^account/logout/?$", reader_views.logout, name="logout"),
    re_path(r"^health-check/?$", health_views.health_check, name="health-check"),
    # PWA routes live at the origin root so the service worker's default scope is /.
    re_path(r"^manifest\.webmanifest$", reader_views.manifest, name="pwa-manifest"),
    re_path(r"^service-worker\.js$", reader_views.service_worker, name="pwa-service-worker"),
    re_path(r"^offline/?$", reader_views.offline, name="pwa-offline"),
    re_path(r"^robots\.txt$", health_views.robots_txt),
    # Browsers ask for /favicon.ico even when the pages carry a <link rel="icon">.
    re_path(
        r"^favicon\.ico$",
        RedirectView.as_view(url=settings.MEDIA_URL + "img/favicon.ico", permanent=True),
    ),
]

# The personal edition ships no web server in front of Django: gunicorn serves the
# static and media trees itself. utils.staticfiles.serve wraps django.views.static
# with cache headers and precompressed gzip delivery. django.conf.urls.static.static()
# is not used here because it forwards its "insecure" flag to the view as a kwarg.
for _prefix, _root in ((settings.STATIC_URL, settings.STATIC_ROOT), (settings.MEDIA_URL, settings.MEDIA_ROOT)):
    urlpatterns += [
        re_path(
            r"^%s(?P<path>.*)$" % _prefix.lstrip("/"),
            static_serve,
            {"document_root": _root},
        )
    ]