# Reader UI layer

The reader shell was refreshed to an Inoreader-style layout: a dark icon rail,
a light sidebar, one fixed toolbar row, and card/list/magazine reading views.
That work lives in three layers, in this order.

| File | Role |
| --- | --- |
| `core/` | The original 24k-line sheet, cut by surface into 15 parts (`01-base.css` … `15-popovers.css`). Owns every legacy surface: modals, menus, story rows, sideoptions. |
| `dark/` | The original dark theme, cut the same way into 4 parts (`01-base.css` … `04-modals.css`). |
| `grid.css` | Grid/magazine card layout, added before this refresh. |
| `tokens.css` | Every color, radius, space, type size and shadow used by the new shell. Light values on `:root`, dark values on `body.NB-dark`. |
| `modern.css` | The refresh itself: shell geometry, rail, sidebar rows, toolbar, story list/content, responsive rules, dark overrides, popovers. Reads only `--nb-*` tokens. |

All of them are registered in `newsblur_web/assets.yml` under `stylesheets.common`
in that order, so `modern.css` wins against legacy rules on plain selectors.
Two caveats:

* `assets.yml` is read at Django import time, so changing it needs
  `docker restart newsblur_web`. Editing the CSS files themselves does not.
* With `DEBUG_ASSETS=True` the templates link the raw files under `/media/`,
  so no `collectstatic` run is needed while developing.
## The legacy sheets

`core/` and `dark/` are each one sheet, cut at its own section banners. The
numeric prefix is the load order, and `assets.yml` lists the parts in that
order, so the split changes no cascade: concatenated in sequence they reproduce
the original `reader.css` (24,325 lines) and `darkmode.css` (5,431 lines) byte
for byte, and the built `common.<hash>.css` keeps the hash it had before the
split. Comments that used to cite `reader.css:1234` were rewritten to
`core/NN-name.css:1234`.

| Part | Surface |
| --- | --- |
| `core/01-base.css` | Global, Splash page, Callouts, Content Pane |
| `core/02-feed-list.css` | Feed List, Unread Counts, Feeds Progress Bar |
| `core/03-story-titles.css` | Story Titles, Discover Feeds, story rows, Story Detail in list and grid view, Content Panes, Styling & Themes |
| `core/04-story-content.css` | Story Content, its modifications and expansion, Text View, Comments |
| `core/05-sideoptions.css` | Sideoption sharing, save and discover, River Progress Bar, Feed Error |
| `core/06-headers.css` | Feeds Header, every Header variant, Task Bar, Feed Taskbar, Tryfeed banner, Search Indexing banner |
| `core/07-panes.css` | Pane Customizations, Feed Frame, Splash Pane |
| `core/08-classifier.css` | Classifier Trainer, Manage Training Tab, Intelligence Slider |
| `core/09-manage.css` | Add Feeds/Folders, Manage Feeds, Mark Read, Classifier Tags, Super Downvote, Match Type, Mouse Indicator |
| `core/10-modules.css` | Page Modules, Main Page, How it Works, Getting Started |
| `core/11-menus.css` | Menus |
| `core/13-modals.css` | Statistics, Auto-Mark Read, Mute, Mark as Unread, Feed Recommendation, Carousel, Notifications, Feedchooser, Unified Header Card, Account Dialog |
| `core/14-static-pages.css` | Static Pages, About, Friends, Folder Icon Editor, Custom Feed Icons, Organizer, Feed Selector, Search, Delete Account, OAuth, Signup and Login |
| `core/15-popovers.css` | Feed Options Popover, Popover, Curated River Explainer, Bidi isolation, Fetch interval pickers |
| `dark/01-base.css` | Global, Scrollbars, Splash Pane, Pop-up Menus |
| `dark/02-panes.css` | Task bars, Feed Pane, Stories Pane, Selected Story Pane, Blog, Forum |
| `dark/04-modals.css` | Getting Started, Trial, Custom Folder Icons, Manage Training Tab |

Add a rule to the part that owns the surface. A new part needs a prefix that
keeps it where it belongs: anything listed after `15-popovers.css` lands below
`splash.css`, `modals.css` and the whole `dark/` group, which is rarely what you
want.

## Retheming

Nothing in `modern.css` hardcodes a color. Users can retheme the whole shell
from Preferences > Custom CSS, which is injected as `<style id="NB-custom-css">`
after every other sheet:

```css
#NB-custom-css {
    --nb-accent: #0A7D4F;
    --nb-accent-soft: #E6F4EC;
    --nb-radius-md: 4px;
}
```

To add a token, define it in `tokens.css` for both themes and use it from
`modern.css`. Do not add raw hex values to `modern.css`.

## JavaScript

Two Backbone views drive the new chrome, both instantiated in
`media/js/newsblur/reader/reader.js`:

* `media/js/newsblur/views/rail_view.js` - the icon rail (`#NB-rail`):
  navigation, theme toggle, unread badges from `folders.unread_counts()`.
* `media/js/newsblur/views/toolbar_view.js` - the single toolbar row
  (`.NB-feedbar`): story search, and the sidebar drawer on narrow screens.

The toolbar keeps the legacy ids inside it (`#story_taskbar`), because
`reader.js`, `reader_taskbar_info.js` and `feed_list_view.js` still address
them. The layout switches stay global delegated handlers in `reader.js`, so
the same buttons work in the toolbar and in the story header.

## Breakpoints

| Width | Behavior |
| --- | --- |
| > 1180 | Full toolbar: search field, view switches, layout switches, Style. |
| 1180-1025 | Search shrinks to 168px; the mark-as-read cluster and view switches are dropped so the feed title keeps its room. |
| 1024-769 | Search collapses to an icon that expands on focus. |
| <= 768 | The rail moves to the bottom, the sidebar becomes a drawer opened by the toolbar button, and `NEWSBLUR.reader.close_sidebar()` is called so jLayout gives the content the full width. |
| <= 620 | Layout switches, prev/next and search are hidden; the toolbar keeps the title, the read filter and Style. A feed saved as Full or Split renders as List, without touching the saved preference. |
| <= 380 | The mark-as-read cluster and the Style pill are dropped as well, leaving the drawer button, the title and the read filter. |

The drawer is drawn outside the jLayout flow: jLayout still owns the pane
geometry, and `modern.css` re-positions `.left-pane` with physical properties
and `!important` once the west pane is hidden.

## Phones

Below 768px a story opens inline inside `#story_titles`, so there is no pane
edge to close and the reader used to have no way back to the list. Section 31
of `modern.css` adds `.NB-story-mobile-bar`, a 44px sticky row at the top of
the open story: back to the list, the feed title, and the next unread story.
The markup lives in `media/js/newsblur/views/story_detail_view.js` and is only
rendered when the story is inline (not the grid overlay, the Text tab, or a
skipped body).

Full and Split put the story in `#story_pane` instead, and their layout buttons
are hidden on a phone, which left the reader with no way back to the list.
`NEWSBLUR.reader.is_phone_width()` (max-width 620px) makes
`NEWSBLUR.assets.view_setting(feed, 'layout')` answer `list` for those two
layouts, so every caller agrees. `NEWSBLUR.assets.saved_view_setting()` still
returns what the user picked, which is what `switch_story_layout()` checks
before writing, so the preference survives the phone and comes back on a
desktop.

## Tryfeed placeholders

A site the reader has not subscribed to gets a placeholder feed. It belongs in
`temp_feeds`, not in the main collection: a placeholder that lands in `feeds`
wins the id, and the real feed arriving later is dropped by Backbone, leaving
the subscribe banner on a feed the user already follows.
`drop_stale_temp_feeds()` sweeps up placeholders that have since been replaced,
called from the `load_feeds` pre-callback. `load_feed()` looks the feed up with
`get_feed()` rather than `feeds.get()` so the tryfeed view still loads stories.

## Feed reordering

The sidebar order is derived, not stored in the DOM: `media/js/newsblur/models/folders.js`
sorts the collection with a comparator that reads the `feed_order` preference
(`ALPHABETICAL`, `MOSTUSED`, `ORGANIZER`, `MANUAL`). Dragging therefore only sticks
because `MANUAL` exists: `_prepareModel` stamps every model with `manual_rank` as it
arrives, the comparator's manual branch sorts feeds by that rank (folders stay
alphabetical), and `NEWSBLUR.reader.sync_manual_order()` writes the on-screen order
back into the collection before `save_feed_order()` posts the tree.

`load_sortable_feeds()` attaches a separate jQuery UI sortable to each `ul.folder`
instead of the old single `#feed_list` widget, and without `connectWith`, so a feed can
only move inside its own folder. `folder_view.js` wraps the whole tree in
`li.folder > ul.folder.NB-root`, and that wrapper has no `.folder_title`; walking from
`#feed_list` therefore reads the first child folder's title and nests everything under it.
`save_feed_order()` starts at `ul.folder.NB-root` and trims every folder title.

Section 32 of `modern.css` styles the drag: `li.feed` gets `cursor: grab`, the dragged row
takes `.NB-feed-sorting` (surface + shadow), and jQuery UI's placeholder li
(`.NB-feeds-list-highlight`, 3px tall) becomes an accent line with a dot on its start edge.

## Empty states

Three lists can be legitimately empty and each used to end at a bare fleuron line:
a saved list with nothing in it, a feed or folder with no stories, and a view whose
unread filter hides everything. `show_view_empty()` in
`media/js/newsblur/views/story_titles_view.js` renders one card with a title, a
sentence naming what is missing and a single action, and it is asked for from three
places: after `render()`, from the empty branch of `show_no_more_stories()`, and
from `reader.check_empty_view()` inside each `post_open_*` handler. That last hook
matters because the first page arrives after the list has already rendered, so a
render-time check alone never fires on a cold load.

The card reuses the classifier empty state's markup (`.NB-classifier-filter-empty`),
which keeps one look for search, filters and plain emptiness. Section 39 of
`modern.css` repaints it with tokens; legacy had it in the old purple palette.
Watch the cascade when restyling these: `core/*.css` scopes several of them
through `.NB-statistics-stat` and `.segmented-control li`, so a shorter selector
silently loses.
