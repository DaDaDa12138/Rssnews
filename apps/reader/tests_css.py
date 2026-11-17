import os
import re
from collections import Counter

from django.conf import settings
from django.test import SimpleTestCase

BASE_DIR = settings.BASE_DIR
READER_CSS = os.path.join(BASE_DIR, "media", "css", "reader")
TOKENS = os.path.join(READER_CSS, "tokens.css")

HEX = re.compile(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
LEGACY_VAR = re.compile(r"var\((--nb-legacy-[0-9a-f]+)\)")
LEGACY_DEF = re.compile(r"^\s*(--nb-legacy-[0-9a-f]+)\s*:", re.MULTILINE)

# A colour used this often is part of the design, not a one-off, so it belongs in
# the palette instead of being repeated by hand. The palette in tokens.css was
# generated with this threshold.
REPEAT_THRESHOLD = 6

# Budgets for the stylesheets that predate the tokens. Lower them when you remove
# debt, never raise them: new rules read the tokens in tokens.css.
MAX_DISTINCT_HEX = 646
MAX_IMPORTANT = 108

# The pane bootstrap in core/01-base.css overrides the inline sizes that
# media/js/newsblur/common/pane_layout.js writes, so those nine declarations need
# the flag. The other two files carry theirs from the 2024 refresh and are being
# cleaned up separately; drop them from this list as that lands.
IMPORTANT_ALLOWED = {
    os.path.join("media", "css", "reader", "core", "01-base.css"),
    os.path.join("media", "css", "reader", "core", "15-popovers.css"),
    os.path.join("media", "css", "reader", "modern.css"),
}


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def declarations(path):
    """The stylesheet without comments: prose mentions colours, rules define them."""
    return COMMENT.sub("", read(path))


def css_files():
    for root, _directories, files in os.walk(READER_CSS):
        for name in sorted(files):
            if name.endswith(".css"):
                yield os.path.join(root, name)


def legacy_tokens():
    return set(LEGACY_DEF.findall(read(TOKENS)))


def legacy_literals():
    return {name[len("--nb-legacy-"):] for name in legacy_tokens()}


class ColourTokenTests(SimpleTestCase):
    def test_every_legacy_colour_token_is_defined(self):
        defined = legacy_tokens()
        used = set()
        for path in css_files():
            used.update(LEGACY_VAR.findall(declarations(path)))
        self.assertTrue(defined, "tokens.css has no legacy palette")
        self.assertEqual(sorted(used - defined), [], "used but undefined legacy tokens")

    def test_legacy_palette_has_no_unused_entries(self):
        used = set()
        for path in css_files():
            used.update(LEGACY_VAR.findall(declarations(path)))
        self.assertEqual(sorted(legacy_tokens() - used), [], "palette entries nothing references")

    def test_tokenised_colours_are_not_hardcoded_again(self):
        # The palette only earns its keep if the literal is gone everywhere else.
        defined = legacy_literals()
        offenders = []
        for path in css_files():
            if path == TOKENS:
                continue
            for number, line in enumerate(declarations(path).splitlines(), 1):
                for literal in HEX.findall(line):
                    if literal.lower() in defined:
                        offenders.append(
                            "%s:%s %s" % (os.path.relpath(path, BASE_DIR), number, literal)
                        )
        self.assertEqual(offenders, [])

    def test_no_colour_is_repeated_beyond_the_threshold(self):
        # Any colour repeated this often should have been moved into the palette.
        defined = legacy_literals()
        counts = Counter()
        for path in css_files():
            if path == TOKENS:
                continue
            for literal in HEX.findall(declarations(path)):
                counts[literal.lower()] += 1
        repeated = {
            literal: count
            for literal, count in counts.items()
            if count >= REPEAT_THRESHOLD and literal not in defined
        }
        self.assertEqual(repeated, {}, "colours repeated %d+ times without a token" % REPEAT_THRESHOLD)


class StyleBudgetTests(SimpleTestCase):
    def literals(self):
        literals = set()
        for path in css_files():
            if path == TOKENS:
                continue
            literals.update(literal.lower() for literal in HEX.findall(declarations(path)))
        return literals

    def test_distinct_colour_literals_stay_under_budget(self):
        self.assertLessEqual(len(self.literals()), MAX_DISTINCT_HEX)

    def test_important_declarations_stay_under_budget(self):
        total = sum(
            declarations(path).count("!important") for path in css_files() if path != TOKENS
        )
        self.assertLessEqual(total, MAX_IMPORTANT)

    def test_important_flags_do_not_spread_to_new_files(self):
        # Most of the old flags turned out to be redundant: removing 87 of them
        # changed no computed style in any layout or theme. New rules should win
        # on specificity, not on the flag.
        offenders = []
        for path in css_files():
            relative = os.path.relpath(path, BASE_DIR)
            if "!important" in declarations(path) and relative not in IMPORTANT_ALLOWED:
                offenders.append(relative)
        self.assertEqual(sorted(offenders), [])


DARK_CSS = os.path.join(READER_CSS, "dark")

# Features that no longer exist in the reader. Keeping their dark rules around
# makes the theme look larger than it is and hides the next real regression.
DEAD_DARK_SELECTORS = (
    ".NB-goodies",
    ".NB-modal-goodies",
    ".NB-referral",
    ".NB-gift",
    ".NB-modal-page-text",
    ".NB-modal-newsletters",
    ".NB-newsletters",
    ".NB-feedchooser-info-counts",
    ".NB-feedchooser-premium",
    ".NB-feedchooser-dollar",
    ".NB-modal-submit-paypal",
    ".NB-feedchooser-tier-badge",
    ".NB-media-",
    ".NB-queue-",
    ".NB-dashboard-river-options",
    ".NB-feedbar-discover-container",
    ".NB-searching",
    ".NB-searches-folder",
    ".NB-feed-story-endbar",
    ".NB-search-header",
    ".NB-staff-badge",
    ".NB-classifier-staff-badge",
    ".NB-sideoption-share",
    ".NB-feed-story-share",
    ".NB-tryout-signup",
    ".NB-search-indexing",
    ".NB-module-hide",
    ".NB-modal-premium-upgrade",
    ".NB-provider-button-change",
    ".NB-folder-icon-current-preview",
    ".NB-popover-section-folder-icon",
    ".NB-staff-only-badge",
    ".NB-manage-filter-label",
    ".NB-story-titles-explainer",
    # The dashboard feature/recommended/premium modules were replaced by the
    # module framework; their dark rules survived because every selector was
    # namespaced under a dead module class.
    ".NB-module-features",
    ".NB-module-feature",
    ".NB-module-recommended",
    ".NB-recommended-",
    ".NB-module-premium",
    ".NB-module-account-subscription",
    ".NB-module-search-input",
    ".NB-module-stats-count-description",
    ".NB-graph-",
    ".NB-daysofunread-upgrade-notice",
    ".NB-feeds-header-user-interactions",
    ".NB-feeds-header-searches",
    ".NB-menu-manage-feed-info",
    ".NB-feed-notification",
    ".NB-notification-scope",
    ".NB-renewal-notify",
    ".NB-classifier-notification-value",
    ".NB-account-disconnect-provider",
    ".NB-feed-title",
    ".NB-static-alert",
    ".NB-mute-settings-slider-value",
    ".NB-tag-problem",
    ".NB-tag-praise",
    ".NB-tag-idea",
    ".NB-tag-question",
)


def dark_css_files():
    for name in sorted(os.listdir(DARK_CSS)):
        if name.endswith(".css"):
            yield os.path.join(DARK_CSS, name)


class DarkThemeTests(SimpleTestCase):
    def test_dark_selectors_do_not_nest_the_theme_class(self):
        # body.NB-dark is the only theme root. A second .NB-dark in the same
        # selector can never match, so the rule silently does nothing.
        offenders = []
        for path in dark_css_files():
            for selector in re.findall(r"([^{}]+)\{", declarations(path)):
                if ".NB-dark .NB-dark" in selector:
                    offenders.append("%s: %s" % (os.path.relpath(path, BASE_DIR), selector.strip()))
        self.assertEqual(offenders, [])

    def test_dark_theme_has_no_dead_feature_selectors(self):
        offenders = []
        for path in dark_css_files():
            for number, line in enumerate(declarations(path).splitlines(), 1):
                for selector in DEAD_DARK_SELECTORS:
                    if selector in line:
                        offenders.append(
                            "%s:%s %s" % (os.path.relpath(path, BASE_DIR), number, selector)
                        )
        self.assertEqual(sorted(offenders), [])
