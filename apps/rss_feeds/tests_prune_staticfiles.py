import io
import json
import os
import tempfile

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

LIVE = "css/common.aaaaaaaaaaaa.css"
STALE = "css/common.bbbbbbbbbbbb.css"


class Test_PruneStaticfiles(SimpleTestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(self._remove_root)
        os.makedirs(os.path.join(self.root, "css"))
        with open(os.path.join(self.root, "staticfiles.json"), "w") as manifest_file:
            json.dump({"paths": {"css/common.css": LIVE}, "version": "1.0"}, manifest_file)
        for relative_path in (LIVE, LIVE + ".gz", STALE, STALE + ".gz", "css/app.js", "css/notes.txt"):
            with open(os.path.join(self.root, relative_path), "w") as static_file:
                static_file.write("x")

    def _remove_root(self):
        for dirpath, _dirnames, filenames in os.walk(self.root, topdown=False):
            for filename in filenames:
                os.remove(os.path.join(dirpath, filename))
            os.rmdir(dirpath)

    def _exists(self, relative_path):
        return os.path.exists(os.path.join(self.root, relative_path))

    def test_dry_run_lists_the_stale_bundles_and_keeps_them(self):
        stdout = io.StringIO()
        call_command("prune_staticfiles", root=self.root, stdout=stdout)
        output = stdout.getvalue()

        self.assertIn(STALE, output)
        self.assertNotIn(LIVE + "\n", output)
        self.assertIn("2 stale files, 2 bytes", output)
        self.assertTrue(self._exists(STALE))
        self.assertTrue(self._exists(STALE + ".gz"))

    def test_write_deletes_only_the_bundles_the_manifest_dropped(self):
        stdout = io.StringIO()
        call_command("prune_staticfiles", root=self.root, write=True, stdout=stdout)

        self.assertIn("Deleted 2 stale files", stdout.getvalue())
        self.assertFalse(self._exists(STALE))
        self.assertFalse(self._exists(STALE + ".gz"))
        self.assertTrue(self._exists(LIVE))
        self.assertTrue(self._exists(LIVE + ".gz"))
        self.assertTrue(self._exists("css/app.js"))
        self.assertTrue(self._exists("css/notes.txt"))

    def test_missing_manifest_asks_for_collectstatic(self):
        os.remove(os.path.join(self.root, "staticfiles.json"))

        with self.assertRaisesMessage(CommandError, "Run collectstatic first."):
            call_command("prune_staticfiles", root=self.root, stdout=io.StringIO())

    def test_a_pruned_root_reports_nothing_to_do(self):
        call_command("prune_staticfiles", root=self.root, write=True, stdout=io.StringIO())

        stdout = io.StringIO()
        call_command("prune_staticfiles", root=self.root, stdout=stdout)
        self.assertEqual(stdout.getvalue().strip(), "No stale bundles in %s." % self.root)
