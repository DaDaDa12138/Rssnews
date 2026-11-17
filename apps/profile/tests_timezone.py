import datetime
import os
import subprocess
import sys
import time

from django.conf import settings
from django.test import SimpleTestCase

from vendor.timezones.utilities import localtime_for_timezone


class Test_ProcessTimeZone(SimpleTestCase):
    """The whole app assumes one clock: naive UTC.

    Story and feed timestamps are stored as naive UTC, and the codebase mixes
    datetime.datetime.now() with datetime.datetime.utcnow(). Those two only agree while
    the process runs in UTC, and Django copies settings.TIME_ZONE into the TZ environment
    variable at startup. These tests lock that invariant so a stray TIME_ZONE env var
    can never silently shift stored timestamps and Redis scheduling scores.
    """

    def test_settings_time_zone_is_utc(self):
        self.assertEqual(settings.TIME_ZONE, "UTC")
        self.assertFalse(settings.USE_TZ)

    def test_process_runs_in_utc(self):
        self.assertEqual(time.strftime("%Z"), "UTC")
        offset = datetime.datetime.now().astimezone().utcoffset()
        self.assertEqual(offset, datetime.timedelta(0))

    def test_now_and_utcnow_agree(self):
        drift = abs(datetime.datetime.now() - datetime.datetime.utcnow())
        self.assertLess(drift, datetime.timedelta(seconds=5))

    def test_environment_cannot_override_time_zone(self):
        env = dict(os.environ)
        env["TIME_ZONE"] = "Asia/Shanghai"
        env["DJANGO_SETTINGS_MODULE"] = "newsblur_web.settings"
        script = (
            "import django; django.setup();"
            "from django.conf import settings;"
            "import time;"
            "print(settings.TIME_ZONE, time.strftime('%Z'))"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=settings.BASE_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "UTC UTC")


class Test_LocaltimeForTimezone(SimpleTestCase):
    def test_converts_utc_to_reader_zone(self):
        noon_utc = datetime.datetime(2026, 1, 1, 12, 0)
        shanghai = localtime_for_timezone(noon_utc, "Asia/Shanghai")
        self.assertEqual(shanghai.replace(tzinfo=None), datetime.datetime(2026, 1, 1, 20, 0))
        self.assertEqual(shanghai.utcoffset(), datetime.timedelta(hours=8))
        new_york = localtime_for_timezone(noon_utc, "America/New_York")
        self.assertEqual(new_york.replace(tzinfo=None), datetime.datetime(2026, 1, 1, 7, 0))
