"""CSRF failure handler.

Reader pages fetch the token from the csrftoken cookie and send it back in the
X-CSRFToken header, so a rejected request is almost always a stale tab that was
opened before the last login rotated the token. Answer XHR with JSON the reader
can show, and browsers with a small page that asks for a reload.
"""

from django.http import JsonResponse
from django.shortcuts import render
from django.utils.translation import gettext as _


def csrf_failure(request, reason=""):
    requested_with = request.headers.get("x-requested-with")
    accepts_json = "application/json" in request.headers.get("accept", "")
    if requested_with == "XMLHttpRequest" or accepts_json:
        return JsonResponse(
            {"code": -1, "message": _("This page expired. Reload it and try again.")},
            status=403,
        )
    return render(request, "profile/csrf_failure.html", {"reason": reason}, status=403)
