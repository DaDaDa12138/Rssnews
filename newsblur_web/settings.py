"""NewsBlur personal edition settings.

This is a slimmed down settings module for a single user, single host deployment.
Everything that used to live in docker_local_settings.py / local_settings.py is
folded in here and driven by environment variables, so the same file works in
Docker and on a bare host.

Local overrides (not committed) go in newsblur_web/local_settings.py, which is
imported at the very bottom of this file.
"""

import datetime
import logging
import os
import sys

import redis
import yaml
from django.core.exceptions import ImproperlyConfigured
from kombu import Queue

# ===========================
# = Directory Declarations  =
# ===========================

SETTINGS_DIR = os.path.dirname(__file__)
NEWSBLUR_DIR = os.path.abspath(os.path.join(SETTINGS_DIR, ".."))
MEDIA_ROOT = os.path.join(NEWSBLUR_DIR, "media")
STATIC_ROOT = os.path.join(NEWSBLUR_DIR, "static")
UTILS_ROOT = os.path.join(NEWSBLUR_DIR, "utils")
VENDOR_ROOT = os.path.join(NEWSBLUR_DIR, "vendor")
LOG_FILE = os.environ.get("LOG_FILE", os.path.join(NEWSBLUR_DIR, "logs/newsblur.log"))
IMAGE_MASK = os.path.join(MEDIA_ROOT, "img/mask.png")
BASE_DIR = NEWSBLUR_DIR

# ==============
# = PYTHONPATH =
# ==============

if UTILS_ROOT not in sys.path:
    sys.path.append(UTILS_ROOT)
if VENDOR_ROOT not in sys.path:
    sys.path.append(VENDOR_ROOT)

from utils.languages import LANGUAGES as UI_LANGUAGES  # noqa: E402


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def env_int(name, default):
    value = os.environ.get(name)
    if value in (None, ""):
        return default
    return int(value)


# ===================
# = Server Settings =
# ===================

ADMINS = (("NewsBlur", os.environ.get("ADMIN_EMAIL", "admin@localhost")),)
MANAGERS = ADMINS

SERVER_NAME = os.environ.get("SERVER_NAME", "localhost")
SERVER_EMAIL = os.environ.get("SERVER_EMAIL", "newsblur@localhost")
HELLO_EMAIL = os.environ.get("HELLO_EMAIL", "hello@localhost")
DEFAULT_FROM_EMAIL = SERVER_EMAIL

# Public URL of this instance. Used for absolute links in emails and in the reader.
NEWSBLUR_URL = os.environ.get("NEWSBLUR_URL", "http://localhost:8080")
PUSH_DOMAIN = os.environ.get("PUSH_DOMAIN", "localhost")

# Empty means "load images straight from their original URL". There is no
# image proxy in the personal edition.
IMAGES_URL = os.environ.get("IMAGES_URL", "")

SECRET_KEY = os.environ.get("SECRET_KEY", "personal-edition-secret-key-change-me")
DOCKERBUILD = env_bool("DOCKERBUILD", True)

# ===================
# = Global Settings =
# ===================

DEBUG = env_bool("DEBUG", True)
# Running production on the repository default would make session cookies and
# password reset tokens forgeable, so refuse to boot instead of logging a warning.
if not DEBUG and SECRET_KEY == "personal-edition-secret-key-change-me":
    raise ImproperlyConfigured("SECRET_KEY must be set to a unique value when DEBUG is off.")
TEST_DEBUG = False

# AttackBanMiddleware (apps/profile/middleware.py) reads the client address from
# X-Forwarded-For by counting entries from the right: only entries appended by a
# proxy you control are safe to trust. This is how many of those proxies sit in
# front of Django. One reverse proxy (Caddy or nginx) that appends a single entry
# means 1; a CDN in front of that proxy means 2.
ATTACK_BAN_PROXY_HOPS = int(os.environ.get("ATTACK_BAN_PROXY_HOPS", 1))

# Log detected payloads without banning. On by default in DEBUG so a local test
# cannot lock the developer out of their own machine; set ATTACK_BAN_DRY_RUN=1 to
# dry-run in production too.
ATTACK_BAN_DRY_RUN = env_bool("ATTACK_BAN_DRY_RUN", DEBUG)

DEBUG_QUERIES = env_bool("DEBUG_QUERIES", False)
DEBUG_QUERIES_SUMMARY_ONLY = True
# Templates link the fingerprinted bundles from assets.yml when this is off. The
# bundles are built by collectstatic at container start (see newsblur_web/entrypoint.sh),
# which turns the first paint from ~200 requests into one CSS and one JS file.
DEBUG_ASSETS = env_bool("DEBUG_ASSETS", False)

# Free-word search matches story bodies as well as titles. story_text is a plain
# text copy maintained by MStory.save and indexed with pg_trgm. On a database
# that already has stories, run `manage.py backfill_story_text` after migrating
# and before turning this on; otherwise older rows have a null search column.
SEARCH_FREE_TEXT_INCLUDES_BODY = env_bool("SEARCH_FREE_TEXT_INCLUDES_BODY", True)

SEND_BROKEN_LINK_EMAILS = False
# Story and feed timestamps are stored as naive UTC (utils/story_functions.py
# extract_story_date parses feedparser's UTC struct_time), so the whole process has to
# run in UTC: Django exports TZ from this setting, and anything that turns a stored
# datetime into an epoch (apps/rss_feeds/models.py format_story) or compares it with
# datetime.now() is only correct when local time is UTC. Each reader then sees dates in
# their own zone, converted with Profile.timezone in
# vendor/timezones/utilities.py localtime_for_timezone.
#
# This is pinned on purpose, not configurable. The codebase mixes
# datetime.datetime.now() and datetime.datetime.utcnow(), which only agree while the
# process runs in UTC, and Django copies TIME_ZONE into the TZ environment variable at
# startup. An env override (TIME_ZONE=Asia/Shanghai) would therefore shift every stored
# timestamp, every Redis scheduling score and every strftime("%s") epoch conversion by
# the UTC offset without a single error. The per-user zone belongs in Profile.timezone,
# never here.
TIME_ZONE = "UTC"
LANGUAGE_CODE = os.environ.get("LANGUAGE_CODE", "zh-hans")
USE_I18N = True
USE_TZ = False
SITE_ID = 1

LANGUAGES = [(code.lower(), name) for code, name in UI_LANGUAGES.items()]
LOCALE_PATHS = (os.path.join(NEWSBLUR_DIR, "locale"),)

LOGIN_REDIRECT_URL = "/"
LOGIN_URL = "/account/login"
LOGOUT_URL = "/account/logout"
APPEND_SLASH = False
ROOT_URLCONF = "newsblur_web.urls"
INTERNAL_IPS = ("127.0.0.1",)

MEDIA_URL = "/media/"
STATIC_URL = "/static/"
ALLOWED_HOSTS = ["*"]

CIPHER_USERNAMES = False
HOMEPAGE_USERNAME = os.environ.get("HOMEPAGE_USERNAME", "popular")

# Single user, no billing, no signup flow.
AUTO_PREMIUM = True
AUTO_PREMIUM_NEW_USERS = True
AUTO_ENABLE_NEW_USERS = True
ENFORCE_SIGNUP_CAPTCHA = False
ENABLE_PUSH = False

DATA_UPLOAD_MAX_MEMORY_SIZE = 5242880
FILE_UPLOAD_MAX_MEMORY_SIZE = 5242880
DATA_UPLOAD_MAX_NUMBER_FIELDS = None  # long /reader/complete_river calls
MAX_EMAILS_SENT_PER_DAY_PER_USER = 20

# Archive features are gone; the constants stay because story cleanup and the
# feed fetcher read them.
MAX_SECONDS_COMPLETE_ARCHIVE_FETCH = 60 * 60
MAX_SECONDS_ARCHIVE_FETCH_SINGLE_FEED = 60 * 15

# ===================
# = Sessions/Email  =
# ===================

SESSION_ENGINE = os.environ.get("SESSION_ENGINE", "django.contrib.sessions.backends.cached_db")
SESSION_COOKIE_NAME = "newsblur_sessionid"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 365 * 10  # 10 years
SESSION_COOKIE_DOMAIN = None
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", False)
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", False)
CSRF_TRUSTED_ORIGINS = [NEWSBLUR_URL]
CSRF_FAILURE_VIEW = "apps.profile.csrf.csrf_failure"

EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = env_int("EMAIL_PORT", 25)
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", False)

# ==============
# = Subdomains =
# ==============

SUBDOMAIN_URLCONFS = {
    None: "newsblur_web.urls",
    "www": "newsblur_web.urls",
    "nb": "newsblur_web.urls",
}
REMOVE_WWW_FROM_DOMAIN = False

# ==========
# = Celery =
# ==========

CELERY_TASK_DEFAULT_QUEUE = "celery"
# apps/rss_feeds/models.py task_feeds() and apps/reader/models.py publish feed fetches,
# new-story pushes and archive walks to named queues. A worker without -Q only drains
# "celery", so every feed refresh sat unpublished and the reader never saw new stories.
# "archive" is what used to be called "search_indexer". Nothing has been indexed since
# the personal edition dropped its search backend: the only tasks on that queue walk a
# feed back catalogue (apps/profile/tasks.py FetchArchiveFeeds*).
CELERY_TASK_QUEUES = (
    Queue("celery"),
    Queue("update_feeds"),
    Queue("new_feeds"),
    Queue("archive"),
)
CELERY_IMPORTS = (
    "apps.rss_feeds.tasks",
    "apps.reader.tasks",
    "apps.profile.tasks",
    "apps.feed_import.tasks",
)
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
# The worker runs --pool=solo (newsblur_web/supervisor.py), so it has no child
# processes: max_tasks_per_child, max_memory_per_child and proc_alive_timeout could
# never fire and are gone. The supervisor enforces the memory ceiling itself by
# restarting the worker when its resident set passes CELERY_WORKER_MEMORY_LIMIT_MB.
CELERY_WORKER_DISABLE_RATE_LIMITS = True
CELERY_TASK_TIME_LIMIT = 12 * 30
CELERY_WORKER_LOG_FORMAT = "%(message)s"
CELERY_WORKER_TASK_LOG_FORMAT = "%(message)s"
CELERY_BROKER_TRANSPORT_OPTIONS = {
    "max_retries": 3,
    "interval_start": 0,
    "interval_step": 0.2,
    "interval_max": 0.5,
}
SECONDS_TO_DELAY_CELERY_EMAILS = 60

CELERY_BEAT_SCHEDULE = {
    "task-feeds": {
        "task": "task-feeds",
        "schedule": datetime.timedelta(minutes=1),
    },
    "task-broken-feeds": {
        "task": "task-broken-feeds",
        "schedule": datetime.timedelta(hours=6),
    },
    "trim-abandoned-feeds": {
        "task": "trim-abandoned-feeds",
        "schedule": datetime.timedelta(hours=24),
    },
    "trim-stories": {
        "task": "trim-stories",
        "schedule": datetime.timedelta(hours=24),
    },
}

# ===========================
# = Django-specific Modules =
# ===========================

SHELL_PLUS_IMPORTS = [
    "import redis",
    "import datetime",
    "from pprint import pprint",
    "import requests",
    "import feedparser",
]

# The reader embeds /reader/page/<feed_id> in a same-origin iframe, so DENY would
# break the feed view. Django's default is DENY; SAMEORIGIN is the strictest value
# this layout supports.
X_FRAME_OPTIONS = "SAMEORIGIN"

MIDDLEWARE = (
    "django.middleware.security.SecurityMiddleware",
    "apps.profile.middleware.ContentSecurityPolicyMiddleware",
    "apps.profile.middleware.ServerTimingMiddleware",
    "apps.profile.middleware.UserAgentBanMiddleware",
    "django.middleware.gzip.GZipMiddleware",
    "apps.profile.language.LanguageCatalogMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "subdomains.middleware.SubdomainMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.profile.middleware.AttackBanMiddleware",
    "apps.profile.middleware.TimingMiddleware",
    "apps.profile.middleware.LastSeenMiddleware",
    "apps.profile.language.NewsBlurLocaleMiddleware",
)

AUTHENTICATION_BACKENDS = ("django.contrib.auth.backends.ModelBackend",)

# Every model in this tree declares an explicit integer id (or inherits one), so keep
# the historic AutoField primary keys instead of Django 5's BigAutoField default.
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

INSTALLED_APPS = (
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.sites",
    "django.contrib.admin",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_extensions",
    "apps.rss_feeds",
    "apps.reader",
    "apps.analyzer",
    "apps.feed_import",
    "apps.profile",
    "utils",  # no models, so no migrations
    "vendor",
    "pipeline",
)

# ===========
# = Logging =
# ===========

LOG_LEVEL = logging.DEBUG if DEBUG else logging.INFO

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "[%(asctime)-12s] %(message)s", "datefmt": "%b %d %H:%M:%S"},
        "simple": {"format": "%(message)s"},
    },
    "handlers": {
        "null": {"level": "DEBUG", "class": "logging.NullHandler"},
        # The console copy is capped at INFO so docker logs stays readable, while the
        # rotating file keeps the debug detail.
        "console": {"level": "INFO", "class": "logging.StreamHandler", "formatter": "verbose"},
        "log_file": {
            "level": "DEBUG",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_FILE,
            "maxBytes": 16777216,
            # Without backupCount the rollover raises TypeError on the first
            # 16 MB and the file grows forever, so keep five generations.
            "backupCount": 5,
            "formatter": "verbose",
        },
    },
    "loggers": {
        "django": {"handlers": ["console", "log_file"], "level": "ERROR", "propagate": False},
        "django.db.backends": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.security.DisallowedHost": {"handlers": ["null"], "propagate": False},
        # utils/log.py logs every app line under this name. Without this entry the records
        # reach no handler and the app's own log lines disappear.
        "newsblur": {"handlers": ["console", "log_file"], "level": LOG_LEVEL, "propagate": False},
        "apps": {"handlers": ["log_file"], "level": "DEBUG", "propagate": True},
        "readability": {"handlers": ["console", "log_file"], "level": "WARNING", "propagate": False},
        "subdomains.middleware": {"level": "ERROR", "propagate": False},
    },
}

logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

# ==========================
# = Miscellaneous Settings =
# ==========================

DAYS_OF_UNREAD = env_int("DAYS_OF_UNREAD", 90)
DAYS_OF_UNREAD_FREE = env_int("DAYS_OF_UNREAD_FREE", 90)
DAYS_OF_UNREAD_ARCHIVE = 9999
DAYS_OF_STORY_HASHES = DAYS_OF_UNREAD
DAYS_OF_STORY_HASHES_ARCHIVE = DAYS_OF_UNREAD_ARCHIVE

# Story retention. Feed.story_retention keeps the newest stories up to a count that scales
# with the feed's subscribers, and the trim after each fetch enforces it. These close what
# the count alone leaves open: a feed that hands over its whole archive in one response
# used to keep every item, and nothing ever expired by age. A feed always keeps its newest
# STORY_RETENTION_MIN_PER_FEED stories, however old they are.
STORY_RETENTION_DAYS = env_int("STORY_RETENTION_DAYS", 180)
STORY_RETENTION_MIN_PER_FEED = env_int("STORY_RETENTION_MIN_PER_FEED", 30)
STORY_RETENTION_MAX_PER_FEED = env_int("STORY_RETENTION_MAX_PER_FEED", 1000)
STORY_RETENTION_MAX_PER_FEED_ARCHIVE = env_int("STORY_RETENTION_MAX_PER_FEED_ARCHIVE", 10000)

# Cached translations are keyed by a hash of the source text and only serve stories still
# on hand, so rows older than the story retention are pruned by the daily trim.
TRANSLATION_CACHE_DAYS = env_int("TRANSLATION_CACHE_DAYS", 180)

# Days after which a user who has not logged in is no longer an active subscriber.
SUBSCRIBER_EXPIRE = 7

# How often Pro feeds are fetched. A single user instance does not need 5 minutes.
PRO_MINUTES_BETWEEN_FETCHES = env_int("PRO_MINUTES_BETWEEN_FETCHES", 15)

DOMAIN_FETCHES_PER_MINUTE = env_int("DOMAIN_FETCHES_PER_MINUTE", 30)
DOMAIN_FETCHES_PER_MINUTE_OVERRIDES = {}

# The fetch worker runs a single thread (newsblur_web/supervisor.py), so the
# scheduler hands it a few feeds per minute instead of every feed that came due.
# See apps/rss_feeds/scheduling.py and apps/rss_feeds/tasks.py TaskFeeds.
FEED_TASKING_PER_MINUTE = env_int("FEED_TASKING_PER_MINUTE", 4)

# A feed every reader has muted is still fetched, because unmuting should not
# open on a hole, but nobody is looking at it in the meantime. Slow it to this
# many minutes; 0 disables the floor and keeps every feed on the reader's
# interval. See Feed.has_unmuted_subscriber in apps/rss_feeds/models.py.
MUTED_FEED_FETCH_MINUTES = env_int("MUTED_FEED_FETCH_MINUTES", 360)

# ============
# = Translate =
# ============

# One-click translation of a feed's headlines and story bodies. The reader posts batches
# of plain text to /reader/translate; apps/reader/translation.py does the splitting,
# caching and provider fallback.
TRANSLATE_ENABLED = env_bool("TRANSLATE_ENABLED", True)
# auto tries the DLX sidecar first and falls back to Bing when DeepL rate limits the
# whole IP range, which is the usual case for a home connection.
TRANSLATE_PROVIDER = os.environ.get("TRANSLATE_PROVIDER", "auto").strip().lower()
TRANSLATE_ENDPOINT = os.environ.get("TRANSLATE_ENDPOINT", "http://newsblur_deeplx:1188/translate")
TRANSLATE_TOKEN = os.environ.get("TRANSLATE_TOKEN", "")
TRANSLATE_TARGET_LANG = os.environ.get("TRANSLATE_TARGET_LANG", "ZH").upper()
TRANSLATE_TIMEOUT = env_int("TRANSLATE_TIMEOUT", 25)
TRANSLATE_MAX_TEXTS = env_int("TRANSLATE_MAX_TEXTS", 60)
TRANSLATE_MAX_REQUEST_CHARS = env_int("TRANSLATE_MAX_REQUEST_CHARS", 12000)
TRANSLATE_CALLS_PER_MINUTE = env_int("TRANSLATE_CALLS_PER_MINUTE", 90)

# ===========
# = Postgres =
# ===========

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "newsblur"),
        "USER": os.environ.get("POSTGRES_USER", "newsblur"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "newsblur"),
        "HOST": os.environ.get("POSTGRES_HOST", "newsblur_db_postgres"),
        "PORT": env_int("POSTGRES_PORT", 5432),
        "CONN_MAX_AGE": 60,
    }
}

# =========
# = Mongo =
# =========

# Every document that used to live in Mongo is now a Postgres model (utils/documents.py).
# The analytics database went with it, so the fetch-history circuit breaker never opens.

# =========
# = Redis =
# =========

REDIS_HOST = os.environ.get("REDIS_HOST", "newsblur_db_redis")
REDIS_PORT = env_int("REDIS_PORT", 6579)
REDIS_USER = {"host": REDIS_HOST, "port": REDIS_PORT}
REDIS_STORY = {"host": REDIS_HOST, "port": REDIS_PORT}
REDIS_SESSIONS = {"host": REDIS_HOST, "port": REDIS_PORT}
REDIS_PUBSUB = {"host": REDIS_HOST, "port": REDIS_PORT}
REDIS_STORY_SECONDARY = None

CELERY_REDIS_DB_NUM = 4
SESSION_REDIS_DB = 5
CELERY_BROKER_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/{CELERY_REDIS_DB_NUM}"
CELERY_RESULT_BACKEND = CELERY_BROKER_URL

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": f"redis://{REDIS_HOST}:{REDIS_PORT}/6",
    },
}

SESSION_REDIS = {
    "host": REDIS_HOST,
    "port": REDIS_PORT,
    "db": SESSION_REDIS_DB,
    "prefix": "",
    "socket_timeout": 10,
    "retry_on_timeout": True,
}

REDIS_POOL = redis.ConnectionPool(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)
REDIS_ANALYTICS_POOL = redis.ConnectionPool(host=REDIS_HOST, port=REDIS_PORT, db=2, decode_responses=True)
REDIS_STATISTICS_POOL = redis.ConnectionPool(host=REDIS_HOST, port=REDIS_PORT, db=3, decode_responses=True)
REDIS_FEED_UPDATE_POOL = redis.ConnectionPool(host=REDIS_HOST, port=REDIS_PORT, db=4, decode_responses=True)
REDIS_STORY_HASH_TEMP_POOL = redis.ConnectionPool(
    host=REDIS_HOST, port=REDIS_PORT, db=10, decode_responses=True
)
REDIS_STORY_HASH_POOL = redis.ConnectionPool(host=REDIS_HOST, port=REDIS_PORT, db=1, decode_responses=True)
REDIS_STORY_HASH_REPLICA_POOL = REDIS_STORY_HASH_POOL
REDIS_FEED_READ_POOL = redis.ConnectionPool(host=REDIS_HOST, port=REDIS_PORT, db=1, decode_responses=True)
REDIS_FEED_SUB_POOL = redis.ConnectionPool(host=REDIS_HOST, port=REDIS_PORT, db=2, decode_responses=True)
REDIS_SESSION_POOL = redis.ConnectionPool(host=REDIS_HOST, port=REDIS_PORT, db=5, decode_responses=True)
REDIS_PUBSUB_POOL = redis.ConnectionPool(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)

# ==================
# = IP Rate Limits =
# ==================

IP_RATE_LIMITING_ENABLED = False
# utils/ratelimit.py: the per-view @ratelimit decorators (load_feeds, refresh_feeds,
# feed statistics, login) are meant for a public multi-tenant server. A single user on
# a private network trips them just by opening a few tabs, which answers 429 and leaves
# the reader half-rendered, so they are off unless this flag is turned back on.
RATE_LIMITING_ENABLED = False
IP_RATE_LIMIT_THRESHOLD = 500
IP_RATE_WINDOW_MINUTES = 5
IP_RATE_TTL_SECONDS = 3600

# ==========
# = Assets =
# ==========

# Path or command name of the esbuild binary used by the asset pipeline.
ESBUILD_BINARY = os.environ.get("ESBUILD_BINARY", "esbuild")

# Bump this when the service worker's precache list or caching logic changes.
# The worker deletes every cache whose name does not match the current version.
# apps/reader/views/pwa.py appends a hash of the built bundle URLs, so a deploy
# that only changes JS or CSS also retires the previous shell cache.
PWA_CACHE_VERSION = os.environ.get("PWA_CACHE_VERSION", "2026-11-05-1")

# Django 5.1 replaced the single STATICFILES_STORAGE setting with STORAGES.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "utils.pipeline_utils.PipelineStorage"},
}
STATICFILES_FINDERS = (
    "utils.pipeline_utils.AppDirectoriesFinder",
    "utils.pipeline_utils.FileSystemFinder",
)
STATICFILES_DIRS = [MEDIA_ROOT]

with open(os.path.join(SETTINGS_DIR, "assets.yml")) as stream:
    assets = yaml.safe_load(stream)

PIPELINE = {
    "PIPELINE_ENABLED": not DEBUG_ASSETS,
    "PIPELINE_COLLECTOR_ENABLED": not DEBUG_ASSETS,
    "SHOW_ERRORS_INLINE": DEBUG_ASSETS,
    "CSS_COMPRESSOR": "utils.pipeline_utils.LightningCSSCompressor",
    # esbuild instead of terser: the runtime image has no Node interpreter, and esbuild
    # is a single static binary that minifies the whole bundle in about 150 ms.
    "JS_COMPRESSOR": "utils.pipeline_utils.EsbuildCompressor",
    "JAVASCRIPT": {
        # Vendor code changes rarely, so it gets its own long-lived bundle. base.html
        # loads it before common so the concatenation order matches the old single bundle.
        "common_vendor": {
            "source_filenames": assets["javascripts"]["common_vendor"],
            "output_filename": "js/common_vendor.js",
        },
        "static_js": {
            "source_filenames": assets["javascripts"]["static_js"],
            "output_filename": "js/static.js",
        },
        "common": {
            "source_filenames": assets["javascripts"]["common"],
            "output_filename": "js/common.js",
        },
        # Feed statistics dialog only; kept separate so the reader bundle stays smaller.
        "statistics": {
            "source_filenames": assets["javascripts"]["statistics"],
            "output_filename": "js/statistics.js",
        },
    },
    "STYLESHEETS": {
        "common": {
            "source_filenames": assets["stylesheets"]["common"],
            "output_filename": "css/common.css",
        },
        # Public pages that do not render the reader shell (login, signup, password reset).
        "static": {
            "source_filenames": assets["stylesheets"]["static"],
            "output_filename": "css/static.css",
        },
        # base.html appends the RTL overrides when the interface language is Arabic or Hebrew.
        "rtl": {
            "source_filenames": assets["stylesheets"]["rtl"],
            "output_filename": "css/rtl.css",
        },
    },
}

# =============
# = Templates =
# =============

if DEBUG:
    template_loaders = [
        "django.template.loaders.filesystem.Loader",
        "django.template.loaders.app_directories.Loader",
    ]
else:
    template_loaders = [
        (
            "django.template.loaders.cached.Loader",
            (
                "django.template.loaders.filesystem.Loader",
                "django.template.loaders.app_directories.Loader",
            ),
        ),
    ]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [
            os.path.join(NEWSBLUR_DIR, "templates"),
        ],
        "OPTIONS": {
            "context_processors": [
                "django.contrib.auth.context_processors.auth",
                "django.template.context_processors.debug",
                "django.template.context_processors.media",
                "django.template.context_processors.request",
                "apps.profile.context_processors.preference_context",
                "apps.reader.context_processors.url_map",
                "apps.profile.language.language_context",
                "django.contrib.messages.context_processors.messages",
            ],
            "loaders": template_loaders,
        },
    }
]

# ===========================
# = Legacy compatibility    =
# ===========================
# Names that survived the app pruning. The code that reads them belongs to
# features that are being removed app by app; until then they need to exist.

SENTRY_DSN = None
FLASK_SENTRY_DSN = None
PREMIUM_PRICING_MIGRATION_ENABLED = False
PREMIUM_PRICING_PAYPAL_CANCEL_ENABLED = False
PREMIUM_PRICING_PAYPAL_CANCEL_MAX_DORMANT_DAYS = 30

STRIPE_SECRET = ""
STRIPE_PUBLISHABLE = ""
STRIPE_PRICE_TEXT_CLASSIFICATION = ""
STRIPE_PRICE_IMAGE_CLASSIFICATION = ""
PAYPAL_API_CLIENTID = ""
PAYPAL_API_SECRET = ""
PAYPAL_RECEIVER_EMAIL = ""
PAYPAL_TEST = False
ZEBRA_ENABLE_APP = True
GOOGLE_PLAY_PACKAGE_NAME = ""
GOOGLE_PLAY_SERVICE_ACCOUNT_INFO = None

S3_ACCESS_KEY = ""
S3_SECRET = ""
S3_CONN = None
S3_BACKUP_BUCKET = ""
S3_PAGES_BUCKET_NAME = ""
S3_ICONS_BUCKET_NAME = ""
S3_AVATARS_BUCKET_NAME = ""
BACKED_BY_AWS = {"pages_on_s3": False, "icons_on_s3": False, "pages_on_node": False}
PROXY_S3_PAGES = False

FACEBOOK_APP_ID = ""
FACEBOOK_SECRET = ""
FACEBOOK_NAMESPACE = ""
TWITTER_CONSUMER_KEY = ""
TWITTER_CONSUMER_SECRET = ""
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
REDDIT_CLIENT_ID = ""
REDDIT_CLIENT_SECRET = ""
SCRAPENINJA_API_KEY = ""
SCRAPINGBEE_API_KEY = ""
SCRAPINGBEE_HOST_DAILY_CREDIT_CAP = 0
SCRAPINGBEE_DORMANT_SUBSCRIBER_DAYS = 365
SCRAPINGBEE_USER_PERIOD_CREDIT_BUDGET = None
SCRAPINGBEE_USER_BUDGET_MIN_USERS = 5000

SOCIAL_APPLE_CLIENT_IDS = []
SOCIAL_APPLE_TEAM_ID = ""
SOCIAL_APPLE_KEY_ID = ""
SOCIAL_APPLE_PRIVATE_KEY_PATH = ""
SOCIAL_APPLE_WEB_CLIENT_ID = ""
SOCIAL_APPLE_REDIRECT_URI = ""
SOCIAL_GOOGLE_CLIENT_ID = ""
SOCIAL_GOOGLE_CLIENT_SECRET = ""
SOCIAL_GOOGLE_REDIRECT_URI = ""
SOCIAL_APPLE_WEB_REDIRECT_URI = ""
SOCIAL_GOOGLE_WEB_REDIRECT_URI = ""
SOCIAL_WEB_ENABLED = False

IMAGES_SECRET_KEY = ""
RECAPTCHA_SECRET_KEY = ""
DNSIMPLE_TOKEN = ""
APNS_TEAM_ID = ""
APNS_KEY_ID = ""
OPENAI_API_KEY = ""
ANTHROPIC_API_KEY = ""
GOOGLE_GEMINI_API_KEY = ""
XAI_GROK_API_KEY = ""
MAILGUN_ACCESS_KEY = ""
MAILGUN_SERVER_NAME = ""
SSRF_ALLOWED_NETWORKS = []

accept_content = ["json"]

# =========================
# = Local overrides last  =
# =========================

try:
    from newsblur_web.local_settings import *  # noqa: F401,F403
except ModuleNotFoundError:
    pass
