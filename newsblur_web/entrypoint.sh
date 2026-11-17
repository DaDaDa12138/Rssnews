#!/usr/bin/env bash

# gunicorn and the Celery worker share this container; newsblur_web/supervisor.py
# starts both, forwards signals and restarts celery if it dies.

# New front-end code is written as ES modules (media/js/modules) and bundled to
# media/js/build/modules.js, which assets.yml loads as window.NEWSBLUR_MODULES.
# Rebuild it before collectstatic when a module is newer than the bundle.
if [ ! -f media/js/build/modules.js ] || find media/js/modules -newer media/js/build/modules.js -print -quit 2>/dev/null | grep -q .; then
    echo "[entrypoint] bundling ES modules"
    if ! python3 utils/build_modules.py; then
        echo "[entrypoint] module bundle failed; window.NEWSBLUR_MODULES may be missing" >&2
    fi
fi

# Templates link the fingerprinted bundles recorded in static/staticfiles.json
# (DEBUG_ASSETS=False). Rebuild them when the manifest is missing or older than any
# asset source, so a fresh checkout still boots into a styled reader and edits to
# media/ are picked up on the next restart.
NEEDS_ASSETS=0
if [ ! -f static/staticfiles.json ]; then
    NEEDS_ASSETS=1
elif find media/css media/js newsblur_web/assets.yml -newer static/staticfiles.json -print -quit 2>/dev/null | grep -q .; then
    NEEDS_ASSETS=1
fi

if [ "$NEEDS_ASSETS" = "1" ]; then
    echo "[entrypoint] collecting static assets"
    if ! python3 manage.py collectstatic --noinput --verbosity 0; then
        echo "[entrypoint] collectstatic failed; existing bundles may be stale" >&2
    fi
fi

exec python3 newsblur_web/supervisor.py
