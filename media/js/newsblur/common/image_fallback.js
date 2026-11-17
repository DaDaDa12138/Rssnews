/* image_fallback.js - retry story images that the publisher's CDN refused.
 *
 * Story images are loaded straight from the publisher (IMAGES_URL is empty in the
 * personal edition). A CDN that blocks hotlinking answers 403/418 and the browser
 * paints a broken-image glyph. The first error re-requests the picture through
 * /imageproxy, which fetches it server side with a Referer the CDN accepts (see
 * apps/rss_feeds/views.py:image_proxy). When that also fails the image is marked as
 * failed and the view decides what to show instead.
 */

(function (window, $) {
    var NEWSBLUR = (window.NEWSBLUR = window.NEWSBLUR || {});

    var PROXY_PATH = '/imageproxy?url=';
    var FAILED_EVENT = 'nb-image-failed';
    var TRIED_ATTRIBUTE = 'data-nb-image-proxy-tried';

    // Same-origin images are served by this app (favicons, icons, static bundles),
    // so they never need the proxy. data: and blob: cannot be fetched by a server.
    // A favicon is an icon, not a story picture. Publishers that refuse it answer 403
    // with an HTML page, so a second request through the proxy only adds a 502 to the
    // console.
    var is_icon = function (src) {
        return /\/favicon\.(ico|png|svg|gif|webp)(\?|#|$)/i.test(src);
    };

    var is_proxyable = function (src) {
        if (!src) return false;
        if (/^(data|blob|about):/i.test(src)) return false;
        if (is_icon(src)) return false;
        if (src.indexOf('//') === 0) return true;
        if (src.charAt(0) === '/') return false;
        return /^https?:/i.test(src);
    };

    // Views that fetch a picture into an off-screen <img> retry the same way, so the
    // rule for what may go through the proxy lives here.
    NEWSBLUR.image_should_proxy = is_proxyable;

    NEWSBLUR.image_proxy_url = function (url) {
        if (!url) return url;
        return PROXY_PATH + encodeURIComponent(url);
    };

    NEWSBLUR.handle_image_error = function (img) {
        if (!img || img.tagName !== 'IMG') return;
        var src = img.getAttribute('src');
        if (!src) return;

        if (!img.getAttribute(TRIED_ATTRIBUTE) && is_proxyable(src)) {
            img.setAttribute(TRIED_ATTRIBUTE, '1');
            img.setAttribute('src', NEWSBLUR.image_proxy_url(src));
            return;
        }

        $(img).trigger(FAILED_EVENT);
    };

    // Capture phase so the swap happens before any view-level error handler runs.
    document.addEventListener(
        'error',
        function (event) {
            var img = event.target;
            if (img && img.tagName === 'IMG') NEWSBLUR.handle_image_error(img);
        },
        true
    );
})(window, jQuery);
