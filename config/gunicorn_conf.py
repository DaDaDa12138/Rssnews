"""Gunicorn configuration for the personal edition.

One worker with a thread pool. Every Python process that imports Django's
settings and calls django.setup() costs about 113 MB RSS (1,512 modules), and a
single reader's traffic is I/O bound, so threads buy the concurrency that extra
worker processes used to. Sixteen threads also absorb the browser's parallel
XHR burst that two sync workers used to queue (measured single request 15 ms,
six parallel 47 ms).

Tune with GUNICORN_WORKERS / GUNICORN_THREADS / GUNICORN_RELOAD if the box ever
serves more than one reader.
"""

import os

bind = "0.0.0.0:8000"

pidfile = "/srv/newsblur/logs/gunicorn.pid"
# Gunicorn has no log rotation, and the access log wrote 76 MB in one day of
# use, so requests are not logged at all. Errors still go to errors.log and
# Django writes its own rotated logs/newsblur.log.
logfile = None
accesslog = None
errorlog = "/srv/newsblur/logs/errors.log"

# Gunicorn 26 opens a control socket under $HOME, and the container has no home
# directory, so it tried to create /.gunicorn and logged a permission error on
# every start. Put the socket somewhere writable.
control_socket = "/tmp/gunicorn.ctl"
loglevel = "info"
name = "newsblur"

# A feed fetch triggered by a view (add_url) can take 30 s on a slow feed.
timeout = 120
x_forwarded_for_header = "X-FORWARDED-FOR"
forwarded_allow_ips = "*"
limit_request_line = 16000
limit_request_fields = 1000
worker_tmp_dir = "/dev/shm"

worker_class = "gthread"
workers = int(os.environ.get("GUNICORN_WORKERS", "1"))
threads = int(os.environ.get("GUNICORN_THREADS", "16"))

# No worker recycling. gthread workers hold their memory flat (measured ~130 MB
# after a day of use), and with a single worker a recycle is a visible outage.
max_requests = 0
max_requests_jitter = 0

# Off by default: the reloader watches every .py file and re-imports the app,
# which doubles the module set. Use `make reload-web` after Python edits.
reload = os.environ.get("GUNICORN_RELOAD", "0") in ("1", "true", "True")
