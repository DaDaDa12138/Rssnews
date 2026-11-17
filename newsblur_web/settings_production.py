"""Production settings profile.

newsblur_web/settings.py is the local development default: DEBUG on, every host
allowed, console email, dev autologin. This module layers the opposite choices on
top for a host that other people can reach, and everything that differs per host
comes from the environment so the same checkout can run anywhere:

    DJANGO_SETTINGS_MODULE=newsblur_web.settings_production \
    SECRET_KEY="$(python -c 'from django.core.management.utils import get_random_secret_key as k; print(k())')" \
    ALLOWED_HOSTS=newsblur.example.com \
    NEWSBLUR_URL=https://newsblur.example.com \
    python manage.py check --deploy

The local deployment documented in docs/DEPLOYMENT.md keeps using the default
module, so nothing here changes how this machine runs today.
"""

import copy
import logging
import os

from django.core.exceptions import ImproperlyConfigured

from newsblur_web.settings import *  # noqa: F401,F403
from newsblur_web.settings import env_bool, env_int

DEBUG = False
DEBUG_QUERIES = False
# Turning this off makes the templates link the compiled bundles from assets.yml,
# which only exist after a pipeline build. collectstatic runs at container start
# (newsblur_web/entrypoint.sh), so the bundles are always present in production.
DEBUG_ASSETS = env_bool("DEBUG_ASSETS", False)

# Three settings in the base module are computed while DEBUG is still its dev
# default, so the star import above leaves the development values in place even
# though DEBUG is off now: the template loaders re-read every file on each render,
# and the apps and newsblur loggers write DEBUG lines to a rotating file.
# Recompute all three.
LOG_LEVEL = logging.INFO
LOGGING = copy.deepcopy(LOGGING)
LOGGING["loggers"]["apps"]["level"] = "INFO"
LOGGING["loggers"]["newsblur"]["level"] = LOG_LEVEL

TEMPLATES = copy.deepcopy(TEMPLATES)
TEMPLATES[0]["OPTIONS"]["loaders"] = [
    (
        "django.template.loaders.cached.Loader",
        (
            "django.template.loaders.filesystem.Loader",
            "django.template.loaders.app_directories.Loader",
        ),
    ),
]

SECRET_KEY = os.environ.get("SECRET_KEY", "").strip()
if not SECRET_KEY or SECRET_KEY == "personal-edition-secret-key-change-me":
    raise ImproperlyConfigured(
        "newsblur_web.settings_production needs a unique SECRET_KEY. Generate one with "
        "python -c \"from django.core.management.utils import get_random_secret_key as k; print(k())\""
    )

ALLOWED_HOSTS = [host.strip() for host in os.environ.get("ALLOWED_HOSTS", "").split(",") if host.strip()]
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        "newsblur_web.settings_production needs ALLOWED_HOSTS, comma separated "
        "(for example newsblur.example.com,203.0.113.10)"
    )
# The base module allows every host because it is the dev default. Copying that
# into this profile would quietly turn off Django's Host header check, which is the
# only thing standing between a published port and a DNS rebinding request.
if "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        "newsblur_web.settings_production refuses ALLOWED_HOSTS='*'. List the host "
        "names (and LAN addresses) this deployment answers on."
    )

# The star import above copies NEWSBLUR_URL as it was when the base module was first
# imported, so the environment has to be read again here.
NEWSBLUR_URL = os.environ.get("NEWSBLUR_URL", NEWSBLUR_URL)

# The middleware stack was written for the dev server and never had the two
# header-setting ones, so SECURE_* and the clickjacking header were dead settings.
# Both are appended here rather than in the base module because the local dev
# server keeps its old, header-free behaviour.
MIDDLEWARE = list(MIDDLEWARE)
MIDDLEWARE.insert(0, "django.middleware.security.SecurityMiddleware")
MIDDLEWARE.insert(
    MIDDLEWARE.index("django.middleware.common.CommonMiddleware") + 1,
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
)
MIDDLEWARE = tuple(MIDDLEWARE)
# The reader frames its own preview panes, so same-origin rather than deny.
X_FRAME_OPTIONS = "SAMEORIGIN"

# CSRF middleware is on. Reader pages carry @ensure_csrf_cookie, so the token is
# already in the csrftoken cookie; media/js/newsblur/common/csrf.js sends it back
# in X-CSRFToken on every unsafe request. The Google Reader API and the inbound
# mail webhook stay @csrf_exempt because they authenticate without a browser
# session. Keep mutating views on @require_POST so a cross-site top level link
# cannot fire them with a Lax cookie.

# The public URL decides whether the deployment is behind TLS. Secure cookies and
# the redirect are only safe to switch on when the browser really speaks https,
# and the local stack runs plain http on a LAN address.
HTTPS = NEWSBLUR_URL.startswith("https://")

# TLS terminates in front of gunicorn, so the forwarded header is the only way
# Django can tell the request arrived over https.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", HTTPS)
SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
SECURE_HSTS_PRELOAD = False
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", HTTPS)
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", HTTPS)
# The reader keeps a session for months on a phone, but ten years outlives the
# browser that holds it and any stolen cookie.
SESSION_COOKIE_AGE = env_int("SESSION_COOKIE_AGE", 60 * 60 * 24 * 30)

CSRF_TRUSTED_ORIGINS = [
    origin.strip() for origin in os.environ.get("CSRF_TRUSTED_ORIGINS", NEWSBLUR_URL).split(",") if origin.strip()
]

# The console backend is a development convenience: a real deployment that sends
# password resets has to configure SMTP (EMAIL_HOST and friends in settings.py).
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")

# With DEBUG off Django mails uncaught exceptions to ADMINS. The base module already
# reads ADMIN_EMAIL and SERVER_EMAIL from the environment, so a deployment only has
# to set those two plus the SMTP host; nothing to override here.

# gunicorn keeps a connection per thread for a minute (CONN_MAX_AGE in the base
# module). Without the health check the first request after a Postgres restart
# fails on a socket the server has already closed.
CONN_HEALTH_CHECKS = True
