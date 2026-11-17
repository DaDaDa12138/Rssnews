// mobile_sheet.js: below 768px the header keeps four controls (drawer, title,
// search, more) and everything that used to sit beside them moves into this
// bottom sheet.
//
// The sheet does not re-implement any behaviour. Each row clicks the toolbar
// button that is still in the DOM but hidden by CSS, so reader.js stays the one
// place that knows what a view mode, a layout or a refresh does. That also means
// a row cannot drift out of sync with its desktop twin.

NEWSBLUR.Views.MobileSheet = Backbone.View.extend({

    el: '#NB-mobile-sheet',

    events: {
        'click [data-sheet-dismiss]': 'handle_dismiss',
        'click .NB-sheet-row': 'handle_row',
        'click .NB-sheet-segment button': 'handle_segment'
    },

    initialize: function () {
        _.bindAll(this, 'handle_more', 'handle_keydown', 'handle_navigate',
            'handle_dismiss', 'handle_row', 'handle_segment');

        // A fixed overlay inside the jLayout pane is only fixed until an ancestor
        // grows a transform, so the sheet lives on the body.
        this.$el.appendTo('body');

        this.$more = $('.NB-toolbar-more');
        this.$panel = this.$('.NB-sheet-panel');
        this.is_open = false;
        this.last_focus = null;

        this.$more.on('click', this.handle_more);
        // Capture phase: the reader's global hotkeys treat Escape as "go to the
        // dashboard" and run on document too, so a bubbling listener would close
        // the sheet and hide the reader behind it in the same keypress.
        document.addEventListener('keydown', this.handle_keydown, true);
        this.listenTo(NEWSBLUR.reader, 'change:active_feed', this.handle_navigate);
    },

    // =============
    // = Open/close =
    // =============

    handle_more: function (e) {
        e.preventDefault();
        e.stopPropagation();

        if (this.is_open) {
            this.close();
        } else {
            this.open();
        }
    },

    handle_dismiss: function (e) {
        e.preventDefault();
        this.close();
    },

    // Picking another feed from the drawer while the sheet is up would otherwise
    // leave it floating over the new feed's stories.
    handle_navigate: function () {
        this.close();
    },

    open: function () {
        if (this.is_open) return;

        this.is_open = true;
        this.last_focus = document.activeElement;
        this.sync_state();

        this.$el.removeAttr('hidden');
        $('body').addClass('NB-sheet-open');
        this.$more.attr('aria-expanded', 'true').addClass('NB-active');

        // The panel transitions from translateY(100%), which only runs if the
        // element is laid out first.
        _.defer(_.bind(function () {
            this.$el.addClass('NB-sheet-visible');
            this.$panel.trigger('focus');
        }, this));
    },

    close: function () {
        if (!this.is_open) return;

        this.is_open = false;
        this.$el.removeClass('NB-sheet-visible');
        $('body').removeClass('NB-sheet-open');
        this.$more.attr('aria-expanded', 'false').removeClass('NB-active');

        _.delay(_.bind(function () {
            if (!this.is_open) {
                this.$el.attr('hidden', 'hidden');
            }
        }, this), 200);

        if (this.last_focus && this.last_focus.focus) {
            try { this.last_focus.focus(); } catch (err) {}
        }
        this.last_focus = null;
    },

    // ==============
    // = Interactions =
    // ==============

    handle_segment: function (e) {
        e.preventDefault();
        var $button = $(e.currentTarget);
        var layout = $button.attr('data-sheet-layout');
        var view = $button.attr('data-sheet-view');

        this.close();

        if (layout) {
            $('.NB-feedbar .NB-taskbar-layout .NB-task-layout-' + layout).trigger('click');
        } else if (view) {
            $('.NB-feedbar .NB-taskbar-view .task_view_' + view).trigger('click');
        }
    },

    handle_row: function (e) {
        e.preventDefault();
        var action = $(e.currentTarget).attr('data-sheet-action');

        this.close();

        if (action == 'refresh') {
            $('.NB-feedbar .NB-toolbar-refresh').trigger('click');
        } else if (action == 'translate') {
            $('.NB-feedbar .NB-toolbar-translate').trigger('click');
        } else if (action == 'mark-read') {
            $('.NB-feedbar .NB-feedbar-mark-feed-read').trigger('click');
        } else if (action == 'style') {
            // story_options_popover.js normally hangs off the Style pill, which
            // the phone header hides, so anchor it to the button that is there.
            NEWSBLUR.StoryOptionsPopover.create({ anchor: this.$more });
            // ReaderPopover.render() marks its anchor expanded. The more button
            // reports the sheet, not the popover, so put its own state back.
            _.defer(_.bind(function () {
                this.$more.attr('aria-expanded', this.is_open ? 'true' : 'false');
            }, this));
        }
    },

    // ==========
    // = State =
    // ==========

    sync_state: function () {
        var reader = NEWSBLUR.reader;
        var layout = NEWSBLUR.assets.view_setting(reader.active_feed, 'layout');
        var view = ($('.NB-taskbar-view .NB-active').attr('class') || '').match(/task_view_(\w+)/);
        view = view ? view[1] : 'feed';

        this.$('[data-sheet-layout]').each(function () {
            var active = $(this).attr('data-sheet-layout') == layout;
            $(this).toggleClass('NB-active', active).attr('aria-pressed', active ? 'true' : 'false');
        });

        this.$('[data-sheet-view]').each(function () {
            var active = $(this).attr('data-sheet-view') == view;
            $(this).toggleClass('NB-active', active).attr('aria-pressed', active ? 'true' : 'false');
        });

        var translating = $('.NB-feedbar .NB-toolbar-translate').attr('aria-pressed') == 'true';
        this.$('[data-sheet-action="translate"]')
            .toggleClass('NB-active', translating)
            .attr('aria-pressed', translating ? 'true' : 'false');

        // Only rivers and folders carry the mark-read control; a single feed
        // has nothing to mark, so the row disappears instead of doing nothing.
        var has_mark_read = $('.NB-feedbar .NB-feedbar-mark-feed-read').length > 0;
        this.$('[data-sheet-action="mark-read"]').toggleClass('NB-sheet-row-hidden', !has_mark_read);
    },

    // ==================
    // = Keyboard support =
    // ==================

    handle_keydown: function (e) {
        if (!this.is_open) return;

        if (e.key == 'Escape') {
            e.preventDefault();
            e.stopPropagation();
            this.close();
            return;
        }

        if (e.key != 'Tab') return;

        // A dialog has to keep Tab inside itself, otherwise focus walks into the
        // story list behind the scrim and the sheet looks frozen.
        var $focusable = this.$panel.find('button:not([disabled])').filter(':visible');
        if (!$focusable.length) return;

        var first = $focusable[0];
        var last = $focusable[$focusable.length - 1];

        var active = document.activeElement;
        var in_panel = this.$panel[0].contains(active);

        // Shift+Tab from the panel itself (tabindex=-1) would otherwise walk
        // backwards into the page behind the scrim.
        if (e.shiftKey && (active === first || active === this.$panel[0])) {
            e.preventDefault();
            last.focus();
        } else if (!e.shiftKey && active === last) {
            e.preventDefault();
            first.focus();
        } else if (!in_panel) {
            e.preventDefault();
            first.focus();
        }
    }
});
