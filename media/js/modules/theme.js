/* theme.js - Theme resolution and the landing page dark mode toggle.
 *
 * The first front-end module written as an ES module. utils/build_modules.py
 * bundles media/js/modules/index.js into media/js/build/modules.js with esbuild,
 * and assets.yml loads that bundle before the legacy scripts as
 * window.NEWSBLUR_MODULES. base.html still resolves the theme inline before the
 * first paint; everything after that goes through this module.
 */

const STORAGE_KEY = 'newsblur:theme';
const DARK_CLASS = 'NB-dark';

// The cache only avoids a flash before the page can read a stored preference.
// base.html rewrites it from the server's theme on every signed-in page load, so
// it never outlives the choice it mirrors and needs no expiry.
export function read_cache() {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        if (parsed && parsed.theme) return parsed.theme;
        localStorage.removeItem(STORAGE_KEY);
    } catch (error) {
        try {
            localStorage.removeItem(STORAGE_KEY);
        } catch (ignored) {
            // Storage can be unavailable in private windows; the page still works.
        }
    }
    return null;
}

export function write_cache(theme) {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ theme: theme, ts: Date.now() }));
    } catch (error) {
        // Storage can be unavailable in private windows; the page still works.
    }
}

export function system_theme() {
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
        ? 'dark'
        : 'light';
}

// 'auto' means follow the operating system, which is what an unknown or empty
// stored value means too.
export function resolve_theme(stored) {
    if (!stored || stored === 'auto') return system_theme();
    return stored;
}

export function next_theme(stored) {
    return resolve_theme(stored) === 'dark' ? 'light' : 'dark';
}

export function apply_theme(theme, doc) {
    const root = doc || document;
    if (!root.body) return;
    if (theme === 'dark') {
        root.body.classList.add(DARK_CLASS);
    } else {
        root.body.classList.remove(DARK_CLASS);
    }
}

// Applies the cached theme on load (static pages never run reader.load_theme) and
// wires the .NB-theme-toggle buttons. A click stores the choice locally, then
// hands it to the reader when the page has one, so the account stays the truth.
export function init_toggle(doc) {
    const root = doc || document;
    const toggles = root.querySelectorAll('.NB-theme-toggle');
    if (!toggles.length) return;

    apply_theme(resolve_theme(read_cache()), root);

    Array.prototype.forEach.call(toggles, function (toggle) {
        toggle.addEventListener('click', function (event) {
            event.preventDefault();
            event.stopPropagation();
            const theme = next_theme(read_cache());
            write_cache(theme);
            apply_theme(theme, root);

            if (window.NEWSBLUR && window.NEWSBLUR.reader && window.NEWSBLUR.reader.switch_theme) {
                window.NEWSBLUR.reader.switch_theme(theme);
            }
        });
    });

    const query = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)');
    if (!query) return;

    const on_system_change = function () {
        const cached = read_cache();
        if (!cached || cached === 'auto') {
            apply_theme(system_theme(), root);
        }
    };
    try {
        query.addEventListener('change', on_system_change);
    } catch (error) {
        try {
            query.addListener(on_system_change);
        } catch (ignored) {
            // Older Safari only has addListener, and both calls can fail.
        }
    }
}
