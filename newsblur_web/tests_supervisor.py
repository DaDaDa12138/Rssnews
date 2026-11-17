"""The supervisor stands in for Celery's prefork memory recycling, so test its parts.

--pool=solo runs every task in the worker's own process, which means Celery's
max_memory_per_child can never fire. newsblur_web/supervisor.py watches the resident
set itself; these tests cover the reading and the fallback when the process is gone.
"""

import os
import unittest

from newsblur_web import supervisor


class Test_Supervisor_Memory(unittest.TestCase):
    def test_resident_mb_reads_the_current_process(self):
        resident = supervisor._resident_mb(os.getpid())
        self.assertIsNotNone(resident)
        self.assertGreater(resident, 1.0)
        self.assertLess(resident, 1024 * 1024.0)

    def test_resident_mb_returns_none_for_a_missing_process(self):
        self.assertIsNone(supervisor._resident_mb(2**22))

    def test_memory_limit_is_positive(self):
        self.assertGreater(supervisor.CELERY_MEMORY_LIMIT_MB, 0)
        self.assertEqual(supervisor.MEMORY_CHECK_INTERVAL, 30.0)
