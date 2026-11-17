"""Static and media file serving for the personal edition.

Gunicorn serves these trees itself because the stack ships no nginx (see
newsblur_web/urls.py). django.views.static.serve sends the bytes but no cache
headers, so every page load re-downloads the same assets. This wrapper adds what a
real web server would:

* fingerprinted pipeline bundles (common.0123456789ab.js) get one year of
  "immutable" caching, every other asset gets a week;
* precompressed .gz copies written by django-pipeline are sent when the client
  accepts gzip, so the 1.7 MB JS bundle travels as about 420 KB.
"""

import mimetypes
import os
import re

from django.http import FileResponse
from django.views.static import serve as django_serve

# django-pipeline appends 12 hex characters before the extension.
FINGERPRINTED = re.compile(r"\.[0-9a-f]{12}\.(?:css|js)$")
GZIP_EXTENSIONS = (".css", ".js", ".svg", ".json", ".txt", ".html")


def _cache_control(path):
    if FINGERPRINTED.search(path):
        return "public, max-age=31536000, immutable"
    return "public, max-age=604800"


def serve(request, path, document_root=None, **kwargs):
    response = django_serve(request, path, document_root=document_root, **kwargs)
    if response.status_code == 304:
        return response

    response["Cache-Control"] = _cache_control(path)
    response["Vary"] = "Accept-Encoding"
    if not path.endswith(GZIP_EXTENSIONS):
        return response

    accepts_gzip = "gzip" in request.headers.get("Accept-Encoding", "").lower()
    if not accepts_gzip:
        return response

    full_path = os.path.join(document_root or "", path)
    gz_path = full_path + ".gz"
    try:
        if os.path.getmtime(gz_path) < os.path.getmtime(full_path):
            return response
        content_type = response.get("Content-Type") or mimetypes.guess_type(path)[0]
        gz_response = FileResponse(open(gz_path, "rb"), content_type=content_type)
    except OSError:
        return response

    gz_response["Content-Encoding"] = "gzip"
    gz_response["Content-Length"] = str(os.path.getsize(gz_path))
    gz_response["Vary"] = "Accept-Encoding"
    gz_response["Cache-Control"] = response["Cache-Control"]
    return gz_response
