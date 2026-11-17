"""The ES module bundle: sources, build script, and how it reaches the page.

New front-end code is written as ES modules under media/js/modules/ and bundled
by utils/build_modules.py with esbuild into media/js/build/modules.js. These
tests keep the wiring honest: the bundle has to load before the legacy scripts
that read it, and the build has to stay a plain esbuild invocation so it works
in the runtime image, which has no Node toolchain.
"""

import os
import subprocess
import tempfile
import unittest
from unittest import mock

from django.conf import settings

from utils import build_modules

MODULES_DIR = os.path.join(settings.BASE_DIR, "media", "js", "modules")
ENTRY = os.path.join(MODULES_DIR, "index.js")
THEME = os.path.join(MODULES_DIR, "theme.js")
BUILD_SCRIPT = os.path.join(settings.BASE_DIR, "utils", "build_modules.py")
ASSETS = os.path.join(settings.BASE_DIR, "newsblur_web", "assets.yml")
ENTRYPOINT = os.path.join(settings.BASE_DIR, "newsblur_web", "entrypoint.sh")
THEME_TOGGLE = os.path.join(settings.BASE_DIR, "media", "js", "newsblur", "common", "theme_toggle.js")


def read(path):
    with open(path, encoding="utf-8") as stream:
        return stream.read()


class ModuleSourceTests(unittest.TestCase):
    def test_entry_point_publishes_exports_on_window(self):
        source = read(ENTRY)
        self.assertIn("import * as theme from './theme.js';", source)
        # django-pipeline wraps every bundle in a function, so a top-level var
        # would not be visible to the legacy scripts.
        self.assertIn("window.NEWSBLUR_MODULES", source)

    def test_theme_module_is_plain_esm(self):
        source = read(THEME)
        for name in (
            "export function read_cache",
            "export function write_cache",
            "export function system_theme",
            "export function resolve_theme",
            "export function next_theme",
            "export function apply_theme",
            "export function init_toggle",
        ):
            self.assertIn(name, source)
        self.assertNotIn("jQuery", source)
        self.assertNotIn("$(", source)

    def test_theme_toggle_delegates_to_the_bundle(self):
        source = read(THEME_TOGGLE)
        self.assertIn("window.NEWSBLUR_MODULES", source)
        self.assertIn("init_toggle", source)
        # The logic moved into the module; a second copy here would drift.
        self.assertNotIn("function read_cache", source)
        self.assertNotIn("function system_theme", source)


class ModuleBuildTests(unittest.TestCase):
    def test_assets_load_the_bundle_before_the_legacy_scripts(self):
        lines = read(ASSETS).splitlines()
        bundle = lines.index("    - js/build/modules.js")
        # theme_toggle.js is the only legacy consumer of the bundle, and it
        # comes in through the common glob, so the bundle has to load first.
        legacy = lines.index("    - js/newsblur/common/*.js")
        self.assertLess(bundle, legacy)

    def test_generated_bundle_is_not_committed(self):
        self.assertIn("media/js/build/", read(os.path.join(settings.BASE_DIR, ".gitignore")))

    def test_entrypoint_builds_modules_before_collectstatic(self):
        source = read(ENTRYPOINT)
        build_at = source.index("utils/build_modules.py")
        collect_at = source.index("collectstatic --noinput")
        self.assertLess(build_at, collect_at)

    def test_build_script_is_a_plain_esbuild_call(self):
        source = read(BUILD_SCRIPT)
        for flag in ('"--bundle"', '"--format=iife"', '"--target=es2019"', '"--outfile=" + OUTPUT'):
            self.assertIn(flag, source)
        self.assertIn('os.environ.get("ESBUILD_BINARY", "esbuild")', source)
        self.assertIn('os.path.join(ROOT, "docker", "bin", "esbuild")', source)

    def test_find_esbuild_returns_none_when_missing(self):
        original = os.environ.get("ESBUILD_BINARY")
        os.environ["ESBUILD_BINARY"] = "definitely-not-esbuild"
        try:
            with mock.patch("shutil.which", return_value=None):
                with mock.patch("os.path.exists", return_value=False):
                    self.assertIsNone(build_modules.find_esbuild())
        finally:
            if original is None:
                os.environ.pop("ESBUILD_BINARY", None)
            else:
                os.environ["ESBUILD_BINARY"] = original


class ModuleBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.esbuild = build_modules.find_esbuild()

    def test_bundle_compiles_and_exposes_the_theme_api(self):
        if not self.esbuild:
            self.skipTest("esbuild binary is not installed")

        with tempfile.TemporaryDirectory() as folder:
            output = os.path.join(folder, "modules.js")
            result = subprocess.run(
                [
                    self.esbuild,
                    ENTRY,
                    "--bundle",
                    "--format=iife",
                    "--target=es2019",
                    "--charset=utf8",
                    "--legal-comments=none",
                    "--outfile=" + output,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=120,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
            bundle = read(output)

        self.assertIn("window.NEWSBLUR_MODULES", bundle)
        self.assertIn("init_toggle", bundle)
        self.assertIn("read_cache", bundle)
