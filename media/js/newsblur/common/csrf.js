/* global NEWSBLUR, $ */

// Django checks X-CSRFToken on every unsafe request. Reader pages are rendered
// with @ensure_csrf_cookie, so the token is already in the csrftoken cookie and
// no extra round trip is needed. Requests that install their own beforeSend
// (assetmodel's queue) call NEWSBLUR.set_csrf_header directly, because jQuery
// replaces the global hook instead of chaining it.

NEWSBLUR = NEWSBLUR || {};

NEWSBLUR.csrf_token = function () {
    var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
};

NEWSBLUR.set_csrf_header = function (xhr) {
    var token = NEWSBLUR.csrf_token();
    if (token && xhr && xhr.setRequestHeader) {
        xhr.setRequestHeader('X-CSRFToken', token);
    }
};

$.ajaxSetup({
    beforeSend: function (xhr) {
        NEWSBLUR.set_csrf_header(xhr);
    }
});
