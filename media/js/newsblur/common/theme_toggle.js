/* theme_toggle.js - Hands the landing page toggle to the ES module bundle.
 *
 * The logic lives in media/js/modules/theme.js, which utils/build_modules.py
 * bundles to media/js/build/modules.js as window.NEWSBLUR_MODULES. This file
 * only waits for the DOM and starts it, so the toggle keeps working while the
 * rest of the reader is still legacy scripts.
 */

function init_theme_toggle() {
    var modules = window.NEWSBLUR_MODULES;
    if (!modules || !modules.theme || !modules.theme.init_toggle) return;
    modules.theme.init_toggle();
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init_theme_toggle);
} else {
    init_theme_toggle();
}
