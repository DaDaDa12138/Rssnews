"""Translate story titles and paragraphs on demand.

The reader translates a batch of plain strings and keeps the result in memory, so this
endpoint is deliberately dumb: check the shape, hand the strings to
apps.reader.translation, and return one entry per input in the same order. Errors travel
in the body's code field, the way every other reader endpoint reports them.
"""

import json as jsonlib

from ._base import *  # noqa: F401,F403

from apps.reader import translation


@ajax_login_required
@json.json_view
def translate_text(request):
    if request.method != "POST":
        return dict(code=-1, message="translate takes a POST")

    if not getattr(settings, "TRANSLATE_ENABLED", False):
        return dict(code=-1, message="translation is disabled")

    try:
        payload = jsonlib.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, ValueError):
        return dict(code=-1, message="malformed request body")
    if not isinstance(payload, dict):
        return dict(code=-1, message="malformed request body")

    texts = payload.get("texts")
    if not isinstance(texts, list) or not texts:
        return dict(code=-1, message="texts must be a non-empty list")
    if len(texts) > settings.TRANSLATE_MAX_TEXTS:
        return dict(code=-1, message=f"at most {settings.TRANSLATE_MAX_TEXTS} texts per request")
    if not all(isinstance(text, str) for text in texts):
        return dict(code=-1, message="texts must be strings")
    if sum(len(text) for text in texts) > settings.TRANSLATE_MAX_REQUEST_CHARS:
        return dict(code=-1, message="request is too large")

    try:
        result = translation.translate_texts(texts, payload.get("target_lang"))
    except translation.TranslationError as error:
        return dict(code=error.code, message=error.message)

    return dict(code=0, **result)
