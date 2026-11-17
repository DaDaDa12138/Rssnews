// pwa.js: register the service worker that makes the reader installable and
// gives it an offline shell. The worker only caches static assets and the public
// /offline/ page; authenticated reader HTML is never written to a cache.
(function () {
  "use strict";

  if (!("serviceWorker" in navigator)) return;
  // The reader embeds /reader/page/<id> in a same-origin iframe. Registration
  // belongs to the top-level document, not to every story iframe.
  if (window.top !== window.self) return;

  var urls = (window.NEWSBLUR && window.NEWSBLUR.URLs) || {};
  var worker_url = urls["pwa-service-worker"];
  if (!worker_url) return;

  // A service worker outlives a development reload and can serve yesterday's
  // bundle. Keep it out of DEBUG unless the page explicitly asks for it with
  // ?pwa=1, which is how the local install/offline checks run.
  var debug = !!(window.NEWSBLUR && window.NEWSBLUR.Globals && window.NEWSBLUR.Globals.debug);
  var forced = /(?:^|[?&])pwa=1(?:&|$)/.test(window.location.search);
  if (debug && !forced) return;

  window.addEventListener("load", function () {
    navigator.serviceWorker.register(worker_url, { scope: "/" }).catch(function () {
      // Installation is an enhancement. A browser that refuses it (private
      // mode, an insecure origin, an unsupported engine) still gets the reader.
    });
  });
})();
