"""Guard the places that have to agree on Celery queue names.

A queue that is published to but never drained loses work silently: the message sits
in Redis until it is trimmed. A queue the worker drains but settings never declares
only works because the worker -Q flag happens to list it.
"""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

QUEUE_KWARG = re.compile(r"(?<![a-z_])queue=[\"']([a-z_]+)[\"']")
SUPERVISOR_QUEUES = re.compile(r'^CELERY_QUEUES = "([^"]+)"', re.MULTILINE)


class Test_Celery_Queues(SimpleTestCase):
    def test_published_queues_are_declared(self):
        declared = {queue.name for queue in settings.CELERY_TASK_QUEUES}
        published = {}
        for package in ("apps", "utils"):
            for path in sorted((Path(settings.BASE_DIR) / package).rglob("*.py")):
                lines = path.read_text(encoding="utf-8").splitlines()
                for number, line in enumerate(lines, 1):
                    for name in QUEUE_KWARG.findall(line):
                        published.setdefault(name, []).append(
                            "%s:%s" % (path.relative_to(settings.BASE_DIR), number)
                        )
        self.assertTrue(published, "no queue=... call sites found, the scan is broken")
        undeclared = {name: where for name, where in published.items() if name not in declared}
        self.assertEqual(undeclared, {}, "published to queues that CELERY_TASK_QUEUES does not declare")

    def test_worker_drains_every_declared_queue(self):
        declared = {queue.name for queue in settings.CELERY_TASK_QUEUES}
        supervisor = Path(settings.BASE_DIR) / "newsblur_web" / "supervisor.py"
        match = SUPERVISOR_QUEUES.search(supervisor.read_text(encoding="utf-8"))
        self.assertIsNotNone(match, "CELERY_QUEUES not found in newsblur_web/supervisor.py")
        drained = {name.strip() for name in match.group(1).split(",") if name.strip()}
        self.assertEqual(drained, declared, "the worker -Q list and CELERY_TASK_QUEUES disagree")
