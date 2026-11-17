"""Delete hashed CSS/JS bundles that staticfiles.json no longer references.

django-pipeline writes a new content-hashed bundle on every collectstatic and
never removes the previous ones, so a checkout that has been redeployed a few
times accumulates hundreds of megabytes of dead files in STATIC_ROOT. This
command keeps exactly what the current manifest points at.
"""

import json
import os
import re

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

HASHED = re.compile(r"\.[0-9a-f]{12}\.(css|js)$")


class Command(BaseCommand):
    help = "Delete hashed CSS/JS bundles that staticfiles.json no longer references."

    def add_arguments(self, parser):
        parser.add_argument(
            "--write",
            action="store_true",
            help="Delete the stale files instead of only listing them.",
        )
        parser.add_argument(
            "--root",
            default=None,
            help="Static root to prune. Defaults to settings.STATIC_ROOT.",
        )

    def handle(self, *args, **options):
        root = options["root"] or settings.STATIC_ROOT
        manifest_path = os.path.join(root, "staticfiles.json")
        if not os.path.exists(manifest_path):
            raise CommandError("No staticfiles.json in %s. Run collectstatic first." % root)

        with open(manifest_path) as manifest_file:
            manifest = json.load(manifest_file)

        # Both sides of the manifest matter: keys are the source names, values
        # are the hashed names the templates actually reference.
        live = set()
        for source_name, hashed_name in manifest.get("paths", {}).items():
            live.add(os.path.normpath(source_name))
            live.add(os.path.normpath(hashed_name))

        stale = []
        stale_bytes = 0
        for dirpath, _dirnames, filenames in os.walk(root):
            for filename in filenames:
                # A .gz sibling has the same base name, so it lives or dies with it.
                base_name = filename[:-3] if filename.endswith(".gz") else filename
                if not HASHED.search(base_name):
                    continue
                relative_path = os.path.normpath(os.path.relpath(os.path.join(dirpath, filename), root))
                # The manifest lists css/common.<hash>.css but never its .gz
                # sibling, so a compressed copy inherits the fate of its base.
                base_relative_path = relative_path[:-3] if relative_path.endswith(".gz") else relative_path
                if relative_path in live or base_relative_path in live:
                    continue
                stale.append(relative_path)
                stale_bytes += os.path.getsize(os.path.join(dirpath, filename))

        if not stale:
            self.stdout.write("No stale bundles in %s." % root)
            return

        if not options["write"]:
            for relative_path in sorted(stale):
                self.stdout.write(relative_path)
            self.stdout.write(
                "%s stale files, %s bytes. Pass --write to delete them."
                % (len(stale), stale_bytes)
            )
            return

        for relative_path in stale:
            os.remove(os.path.join(root, relative_path))
        self.stdout.write(
            "Deleted %s stale files, %s bytes." % (len(stale), stale_bytes)
        )
