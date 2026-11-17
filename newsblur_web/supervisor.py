#!/usr/bin/env python3
"""Run gunicorn and the Celery worker inside one container.

The personal edition has a single reader, so the worker and beat live next to the
web process instead of in their own container: one less container, one less copy
of the Django app in memory, and no compose service to keep in sync.

newsblur_web/supervisor.py: celery is restarted when it dies (a worker that hits a
hard timeout should not take the site down with it), gunicorn is not: when the web
process exits, the container exits with it.
"""

import os
import shutil
import signal
import subprocess
import sys
import time

CELERY_QUEUES = "celery,update_feeds,new_feeds,archive"
GUNICORN_PIDFILE = "logs/gunicorn.pid"
# "make celery-restart" only has to touch this file: the image has no pkill, and a
# marker in the bind-mounted repo works from the host without docker exec.
RESTART_FLAG = "logs/restart-celery"
CELERY_RESTART_DELAY = 2.0
# --pool=solo cannot recycle itself the way max_memory_per_child does for a prefork
# pool, so the watchdog below restarts the worker when it grows past this.
CELERY_MEMORY_LIMIT_MB = int(os.environ.get("CELERY_WORKER_MEMORY_LIMIT_MB", "750"))
MEMORY_CHECK_INTERVAL = 30.0
SHUTDOWN_GRACE = 25.0

shutting_down = False


def _handle_signal(signum, frame):
    global shutting_down
    shutting_down = True


def _clear_stale_pidfile(path=GUNICORN_PIDFILE):
    # The pid file sits in the bind-mounted repo, so it outlives the container and
    # gunicorn refuses to boot while it names a pid from the previous run. Nothing
    # else can be serving in this container, so the file is always stale here.
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def _resident_mb(pid):
    """Resident set of a process in MiB, or None when it is already gone."""
    try:
        with open("/proc/%d/status" % pid) as status:
            for line in status:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024.0
    except (FileNotFoundError, ProcessLookupError, ValueError):
        return None
    return None


def _spawn(argv):
    print("[supervisor] starting: %s" % " ".join(argv), flush=True)
    return subprocess.Popen(argv)


def _stop(process, timeout=SHUTDOWN_GRACE):
    if process is None or process.poll() is not None:
        return
    process.terminate()
    deadline = time.time() + timeout
    while process.poll() is None and time.time() < deadline:
        time.sleep(0.2)
    if process.poll() is None:
        print("[supervisor] killing %s after %.0fs" % (process.pid, timeout), flush=True)
        process.kill()
        process.wait()


def main():
    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(signum, _handle_signal)

    check = subprocess.call([sys.executable, "manage.py", "check_db"])
    if check != 0:
        print("[supervisor] check_db failed with %s, starting anyway" % check, flush=True)

    celery_argv = [
        shutil.which("celery") or "celery",
        "-A",
        "newsblur_web",
        "worker",
        "-B",
        # solo runs every task in the main process: one reader on a 15 minute
        # schedule has nothing to gain from a pool, and each extra pool thread
        # grows the heap that has to stay resident.
        "--pool=solo",
        "--loglevel=INFO",
        "-Q",
        CELERY_QUEUES,
    ]
    gunicorn_argv = [
        shutil.which("gunicorn") or "gunicorn",
        "-c",
        "config/gunicorn_conf.py",
        "newsblur_web.wsgi:application",
    ]

    _clear_stale_pidfile()
    celery = _spawn(celery_argv)
    gunicorn = _spawn(gunicorn_argv)
    restarted_at = 0.0
    checked_memory_at = 0.0

    while True:
        if shutting_down:
            print("[supervisor] shutting down", flush=True)
            _stop(gunicorn)
            _stop(celery)
            return 0

        gunicorn_code = gunicorn.poll()
        if gunicorn_code is not None:
            print("[supervisor] gunicorn exited with %s, stopping" % gunicorn_code, flush=True)
            _stop(celery)
            return gunicorn_code or 1

        if os.path.exists(RESTART_FLAG):
            print("[supervisor] %s found, restarting celery" % RESTART_FLAG, flush=True)
            try:
                os.remove(RESTART_FLAG)
            except FileNotFoundError:
                pass
            _stop(celery, timeout=10)
            celery = _spawn(celery_argv)
            continue

        if time.time() - checked_memory_at > MEMORY_CHECK_INTERVAL:
            checked_memory_at = time.time()
            resident = _resident_mb(celery.pid)
            if resident is not None and resident > CELERY_MEMORY_LIMIT_MB:
                print(
                    "[supervisor] celery is at %.0fMB, over the %dMB limit, restarting"
                    % (resident, CELERY_MEMORY_LIMIT_MB),
                    flush=True,
                )
                _stop(celery, timeout=10)
                celery = _spawn(celery_argv)
                continue

        celery_code = celery.poll()
        if celery_code is not None:
            if time.time() - restarted_at < CELERY_RESTART_DELAY:
                time.sleep(CELERY_RESTART_DELAY)
            print("[supervisor] celery exited with %s, restarting" % celery_code, flush=True)
            restarted_at = time.time()
            celery = _spawn(celery_argv)

        time.sleep(0.5)


if __name__ == "__main__":
    sys.exit(main())
