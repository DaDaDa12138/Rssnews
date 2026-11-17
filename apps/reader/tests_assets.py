"""Guard the django-pipeline manifest against renamed or duplicated vendor files.

A stale entry in newsblur_web/assets.yml fails quietly: django-pipeline skips the
file, the bundle still builds, and the page loads without jQuery until some
inline script throws. These tests turn that into a test failure instead.
"""

import glob
import os

import yaml
from django.conf import settings
from django.test import SimpleTestCase

ASSETS_FILE = os.path.join(settings.BASE_DIR, "newsblur_web", "assets.yml")
MEDIA_ROOT = str(settings.MEDIA_ROOT)


class AssetManifestTests(SimpleTestCase):
    def setUp(self):
        with open(ASSETS_FILE, encoding="utf-8") as fh:
            self.manifest = yaml.safe_load(fh)

    def test_every_javascript_entry_matches_a_file(self):
        for bundle, entries in self.manifest["javascripts"].items():
            for entry in entries:
                matches = glob.glob(os.path.join(MEDIA_ROOT, entry))
                self.assertTrue(
                    matches,
                    "%s: js/%s matches no file under %s" % (bundle, entry, MEDIA_ROOT),
                )

    def test_vendored_jquery_and_underscore_are_the_expected_versions(self):
        jquery_path = os.path.join(MEDIA_ROOT, "js", "vendor", "jquery-3.7.1.min.js")
        underscore_path = os.path.join(MEDIA_ROOT, "js", "vendor", "underscore-1.13.7.js")
        with open(jquery_path, encoding="utf-8") as fh:
            self.assertIn("jQuery v3.7.1", fh.read(200))
        with open(underscore_path, encoding="utf-8") as fh:
            self.assertIn("1.13.7", fh.read())

    def test_underscore_glob_matches_exactly_one_file(self):
        # js/vendor/underscore-*.js is a glob: leaving the previous release next
        # to the new one loads both and silently keeps whichever runs last.
        matches = glob.glob(os.path.join(MEDIA_ROOT, "js", "vendor", "underscore-*.js"))
        self.assertEqual(len(matches), 1, matches)
