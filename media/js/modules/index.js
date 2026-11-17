/* index.js - Entry point for the ES module bundle.
 *
 * utils/build_modules.py bundles this file into media/js/build/modules.js, which
 * assets.yml loads before the legacy scripts. django-pipeline wraps every bundle
 * in (function () { ... }).call(this), so a top-level var is not global: publish
 * the exports on window explicitly and let legacy scripts read
 * window.NEWSBLUR_MODULES. Add new modules to the object below as they are
 * written.
 */

import * as theme from './theme.js';

window.NEWSBLUR_MODULES = Object.assign(window.NEWSBLUR_MODULES || {}, {
    theme: theme,
});
