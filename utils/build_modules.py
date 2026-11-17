#!/usr/bin/env python3
"""Bundle media/js/modules into one ES module bundle with esbuild.

New front-end code is written as ES modules under media/js/modules/ and bundled
by esbuild, the same single static binary that minifies the reader bundle at
collectstatic time (see utils/pipeline_utils.py). Legacy scripts keep loading
from assets.yml and read the bundle through window.NEWSBLUR_MODULES.

The output (media/js/build/modules.js) is generated, not committed: the container
entrypoint rebuilds it whenever a module is newer than the bundle.
"""

import argparse
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENTRY = os.path.join(ROOT, "media", "js", "modules", "index.js")
OUTPUT = os.path.join(ROOT, "media", "js", "build", "modules.js")


def find_esbuild():
    """Return the esbuild binary, or None when it is not installed."""
    configured = os.environ.get("ESBUILD_BINARY", "esbuild") or "esbuild"
    found = shutil.which(configured)
    if found:
        return found
    if os.path.exists(configured):
        return configured
    # Development checkouts that have not rebuilt the image keep the binary in the
    # repo (docker/bin/esbuild, gitignored) instead of /usr/local/bin.
    local = os.path.join(ROOT, "docker", "bin", "esbuild")
    return local if os.path.exists(local) else None


def build(force=False):
    """Write OUTPUT from ENTRY. Returns the bundle path, or None on failure."""
    if not os.path.exists(ENTRY):
        print("[modules] no entry point at %s" % ENTRY, file=sys.stderr)
        return None

    if not force and os.path.exists(OUTPUT):
        newest = max(
            os.path.getmtime(os.path.join(folder, name))
            for folder, _, names in os.walk(os.path.join(ROOT, "media", "js", "modules"))
            for name in names
        )
        if newest <= os.path.getmtime(OUTPUT):
            print("[modules] %s is up to date" % os.path.relpath(OUTPUT, ROOT))
            return OUTPUT

    binary = find_esbuild()
    if not binary:
        print(
            "[modules] esbuild binary not found; install it or set ESBUILD_BINARY",
            file=sys.stderr,
        )
        return None

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    command = [
        binary,
        ENTRY,
        "--bundle",
        "--format=iife",
        "--target=es2019",
        "--charset=utf8",
        "--legal-comments=none",
        "--outfile=" + OUTPUT,
    ]
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print("[modules] esbuild failed: %s" % exc, file=sys.stderr)
        return None

    if result.returncode != 0:
        print(
            "[modules] esbuild failed: " + result.stderr.decode("utf-8", "replace")[:500],
            file=sys.stderr,
        )
        return None

    print(
        "[modules] built %s (%d bytes)" % (os.path.relpath(OUTPUT, ROOT), os.path.getsize(OUTPUT))
    )
    return OUTPUT


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="rebuild even when the bundle is newer than every module",
    )
    args = parser.parse_args(argv)
    return 0 if build(force=args.force) else 1


if __name__ == "__main__":
    sys.exit(main())
