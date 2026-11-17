"""utils/log.py writes every app line to the "newsblur" logger, which needs a handler.

Without the logger entry in LOGGING the records reach no handler and vanish, which is
how the feed fetcher's "Processed in" lines went missing. newsblur_web/tests_logging.py
"""

import logging

from django.conf import settings
from django.test import SimpleTestCase

from utils import log as logging_utils


class Test_NewsblurLogger(SimpleTestCase):
    def test_settings_give_the_logger_a_console_and_a_file_handler(self):
        config = settings.LOGGING["loggers"]["newsblur"]

        self.assertEqual(config["handlers"], ["console", "log_file"])
        self.assertFalse(config["propagate"])
        self.assertEqual(config["level"], settings.LOG_LEVEL)

    def test_django_attached_the_handlers_at_startup(self):
        logger = logging.getLogger("newsblur")

        self.assertEqual(len(logger.handlers), 2, "utils.log lines would reach no handler")

    def test_a_line_written_through_utils_log_is_kept(self):
        with self.assertLogs("newsblur", level="INFO") as captured:
            logging_utils.info("processed feed 35")

        self.assertTrue(any("processed feed 35" in line for line in captured.output))
