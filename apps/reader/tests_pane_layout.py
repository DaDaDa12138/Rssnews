import os

from django.conf import settings
from django.test import SimpleTestCase

BASE_DIR = settings.BASE_DIR


def read(relative_path):
    with open(os.path.join(BASE_DIR, relative_path), encoding="utf-8") as handle:
        return handle.read()


def walk_files(relative_directory, extension):
    for root, _directories, files in os.walk(os.path.join(BASE_DIR, relative_directory)):
        for name in files:
            if name.endswith(extension):
                yield os.path.join(root, name)


class PaneLayoutAssetsTests(SimpleTestCase):
    """The reader used to be laid out by jquery.layout. These lock in its removal."""

    def test_assets_yml_no_longer_bundles_jquery_layout(self):
        assets = read("newsblur_web/assets.yml")
        self.assertNotIn("jquery.layout", assets)
        self.assertNotIn("slideOffscreen", assets)
        # The common bundle picks pane_layout.js up through this glob.
        self.assertIn("js/newsblur/common/*.js", assets)

    def test_vendor_jquery_layout_and_its_effect_are_gone(self):
        for name in ("jquery.layout.js", "jquery.effects.slideOffscreen.js"):
            self.assertFalse(
                os.path.exists(os.path.join(BASE_DIR, "media/js/vendor", name)),
                "%s should have been deleted with the CSS grid rewrite" % name,
            )

    def test_reader_code_no_longer_calls_the_old_layout_plugin(self):
        offenders = []
        for path in walk_files("media/js/newsblur", ".js"):
            with open(path, encoding="utf-8") as handle:
                for number, line in enumerate(handle, 1):
                    if ".layout(" in line or "slideOffscreen" in line:
                        offenders.append("%s:%s" % (os.path.relpath(path, BASE_DIR), number))
        self.assertEqual(offenders, [])

    def test_reader_builds_every_pane_with_the_grid_layout(self):
        reader = read("media/js/newsblur/reader/reader.js")
        self.assertEqual(reader.count(".nbLayout("), 11)

    def test_no_stylesheet_targets_the_old_layout_plugin(self):
        offenders = []
        for path in walk_files("media/css", ".css"):
            with open(path, encoding="utf-8") as handle:
                for number, line in enumerate(handle, 1):
                    if "ui-layout" in line:
                        offenders.append("%s:%s" % (os.path.relpath(path, BASE_DIR), number))
        self.assertEqual(offenders, [])

    def test_panes_stylesheet_defines_the_grid_layout(self):
        panes = read("media/css/reader/core/07-panes.css")
        for selector in (".NB-pane-layout", ".NB-pane-resizer", ".NB-pane-hidden"):
            self.assertIn(selector, panes)

    def test_feed_list_pane_is_shown_by_the_grid(self):
        # core/01-base.css hides .left-center-content with display:none because
        # jquery.layout wrote display:block inline on every pane it managed. The
        # grid only places panes, so 07-panes.css has to show this one or the
        # sidebar renders empty.
        panes = read("media/css/reader/core/07-panes.css")
        self.assertRegex(
            panes, r"\.NB-pane-layout > \.left-center-content \{\s*display: block;"
        )

    def test_story_pane_is_only_shown_when_the_grid_places_it(self):
        # core/03-story-titles.css hides #story_pane because jquery.layout used to
        # show it inline. In the list, grid and magazine layouts the story titles
        # own the centre, so showing the pane there leaves an unplaced grid item
        # whose absolutely positioned children float over the feed list and
        # swallow every click. Only split and full give it the NB-pane class.
        panes = read("media/css/reader/core/07-panes.css")
        self.assertRegex(
            panes,
            r"\.NB-pane-layout > #story_titles,\s*\.NB-pane-layout > #story_pane\.NB-pane \{\s*display: block;",
        )

    def test_story_pane_is_a_containing_block_for_its_strip(self):
        # The absolute strip inside #story_pane sizes itself against its nearest
        # positioned ancestor. #story_pane is static in core/03-story-titles.css, so
        # without this rule the strip measures .content-pane and every story view
        # renders one content-width off to the side.
        panes = read("media/css/reader/core/07-panes.css")
        self.assertRegex(panes, r"\.NB-pane-layout > #story_pane \{\s*position: relative;")

    def test_sidebar_toggle_placeholder_is_gone(self):
        skeleton = read("templates/reader/feeds_skeleton.xhtml")
        self.assertNotIn("NB-taskbar-sidebar-toggle-open", skeleton)


class PaneLayoutScriptTests(SimpleTestCase):
    def test_pane_layout_exposes_the_layout_api(self):
        script = read("media/js/newsblur/common/pane_layout.js")
        self.assertIn("$.fn.nbLayout", script)
        for method in (
            "open",
            "hide",
            "show",
            "close",
            "toggle",
            "sizePane",
            "resizeAll",
            "destroy",
        ):
            self.assertIn(
                "PaneLayout.prototype.%s = function" % method,
                script,
                "PaneLayout is missing %s()" % method,
            )

    def test_pane_layout_keeps_the_container_measurements(self):
        # reader.js position_mouse_indicator reads state.container.innerHeight,
        # which jquery.layout published as a hash of measurements.
        script = read("media/js/newsblur/common/pane_layout.js")
        self.assertIn("update_container_state", script)
        self.assertIn("innerHeight", script)
        self.assertIn("state.container", script)

    def test_every_layout_edge_gets_a_track(self):
        # A layout can have several panes on the same axis (the left column has
        # a north header and a south footer), so apply() must walk all edges.
        script = read("media/js/newsblur/common/pane_layout.js")
        self.assertIn("LEADING_EDGES", script)
        self.assertIn("minmax(0, 1fr)", script)

    def test_hidden_panes_use_a_class_instead_of_display_none(self):
        # The phone sidebar drawer shows .left-pane through a CSS transform, so
        # hiding a pane must not set display:none on it.
        script = read("media/js/newsblur/common/pane_layout.js")
        self.assertIn("NB-pane-hidden", script)
        self.assertNotIn(".hide()", script)
        self.assertNotIn(".show()", script)
