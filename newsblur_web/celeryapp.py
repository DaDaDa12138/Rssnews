from __future__ import absolute_import, unicode_literals

import logging
import os
import threading

from celery import Celery
from celery.beat import Service
from celery.worker.components import Beat as BeatBootstep
from django.apps import apps

# set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "newsblur_web.settings")

app = Celery("newsblur_web")

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Load task modules from all registered Django app configs.
app.autodiscover_tasks(lambda: [n.name for n in apps.get_app_configs()])

BEAT_RESTART_DELAY = 5.0
BEAT_MAX_INTERVAL = 1

logger = logging.getLogger("celery.beat")


class EmbeddedBeatThread(threading.Thread):
    """Run the beat scheduler in a daemon thread of the worker process.

    Celery's own embedded beat (celery.beat.EmbeddedService without thread=True)
    starts a second interpreter, which imports Django a second time and costs
    about 110MB of resident memory for a timer that only pushes three task names
    into Redis every minute. See newsblur_web/supervisor.py, which starts the
    worker with -B.

    Service.start() only catches KeyboardInterrupt and SystemExit, so one
    transient error inside scheduler.tick() would end periodic tasks for good.
    The loop below rebuilds the Service instead of letting the thread die.
    """

    def __init__(self, app, **service_kwargs):
        super().__init__(name="Beat", daemon=True)
        self.app = app
        self.service_kwargs = service_kwargs
        self.service = None
        self.stopping = threading.Event()

    def run(self):
        self.app.set_current()
        while not self.stopping.is_set():
            self.service = Service(self.app, **self.service_kwargs)
            try:
                self.service.start()
                break
            except Exception:
                logger.exception("beat loop failed, restarting in %.0fs", BEAT_RESTART_DELAY)
                self.stopping.wait(BEAT_RESTART_DELAY)
        self.service = None

    def stop(self):
        self.stopping.set()
        if self.service is not None:
            self.service.stop(wait=True)


def _create_embedded_beat(bootstep, worker):
    """Replace celery.worker.components.Beat.create, which forks a process."""
    return EmbeddedBeatThread(
        worker.app,
        max_interval=BEAT_MAX_INTERVAL,
        schedule_filename=worker.schedule_filename,
        scheduler_cls=worker.scheduler,
    )


BeatBootstep.create = _create_embedded_beat


@app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    """Import task modules after Celery is fully configured."""
    if sender.conf.imports:
        for module_name in sender.conf.imports:
            try:
                __import__(module_name)
            except ImportError as e:
                print(f"Failed to import {module_name}: {e}")
