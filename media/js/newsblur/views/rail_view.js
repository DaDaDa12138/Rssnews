// ======================================
// = The icon rail (media/js/newsblur/views/rail_view.js) =
// ======================================

// The rail is the primary navigation: dashboard, all stories, saved stories and
// add site, plus theme / preferences / account at the bottom. Search lives in the
// story toolbar, which is visible at every breakpoint, so it is not repeated here.
// Badges read the same collections the sidebar uses, so they never drift.
NEWSBLUR.Views.Rail = Backbone.View.extend({

    el: '#NB-rail',

    events: {
        'click .NB-rail-item': 'handle_item_click'
    },

    initialize: function () {
        this.listenTo(NEWSBLUR.assets.folders, 'reset change add remove', this.update_counts);
        this.listenTo(NEWSBLUR.assets.feeds, 'reset change add remove', this.update_counts);
        this.listenTo(NEWSBLUR.assets.stories, 'change:read_status', this.update_counts);
        this.update_counts();
        this.track_navigation();
    },

    // The rail has to follow every route, not just its own clicks: opening a
    // feed from the sidebar, following a link or pressing back all move the
    // reader without going through handle_item_click. Wrapping pushState keeps
    // this in one place instead of patching every reader entry point.
    track_navigation: function () {
        var self = this;

        if (NEWSBLUR.router) {
            this.listenTo(NEWSBLUR.router, 'route', this.update_active);
        }

        if (!NEWSBLUR.Views.Rail.tracking_history) {
            NEWSBLUR.Views.Rail.tracking_history = true;

            var push_state = window.history.pushState;

            window.history.pushState = function () {
                var result = push_state.apply(window.history, arguments);
                _.defer(function () {
                    if (NEWSBLUR.app && NEWSBLUR.app.rail) {
                        NEWSBLUR.app.rail.update_active();
                    }
                });
                return result;
            };

            var replace_state = window.history.replaceState;

            window.history.replaceState = function () {
                var result = replace_state.apply(window.history, arguments);
                _.defer(function () {
                    if (NEWSBLUR.app && NEWSBLUR.app.rail) {
                        NEWSBLUR.app.rail.update_active();
                    }
                });
                return result;
            };
        }

        $(window).on('popstate.nb-rail', function () {
            _.defer(function () {
                self.update_active();
            });
        });

        this.update_active();
    },

    // Which rail item owns the current location. Feeds and folders belong to no
    // rail item, so they clear the highlight instead of leaving a stale one.
    update_active: function () {
        var path = window.location.pathname;
        var action = null;

        if (path === '/' || path === '') {
            action = 'dashboard';
        } else if (path.indexOf('/saved') === 0 || path.indexOf('/folder/saved') === 0) {
            action = 'saved';
        } else if (path === '/folder/everything') {
            action = 'all';
        } else if (path.indexOf('/add') === 0) {
            action = 'add';
        }

        if (action) {
            this.set_active(action);
        } else {
            this.$('.NB-rail-item').removeClass('NB-active');
        }
    },

    handle_item_click: function (e) {
        e.preventDefault();
        e.stopPropagation();

        var action = $(e.currentTarget).data('rail-action');
        var reader = NEWSBLUR.reader;

        this.set_active(action);

        switch (action) {
            case 'dashboard':
                reader.show_splash_page();
                break;
            case 'all':
                reader.open_river_stories();
                break;
            case 'saved':
                reader.open_starred_stories();
                break;
            case 'add':
                // The rail owns the add entry now; the sidebar row and footer "+"
                // are gone. The popover carries a link to the full Add Site page.
                reader.open_add_feed_modal();
                break;
            case 'theme':
                this.toggle_theme();
                break;
            case 'filters':
                NEWSBLUR.Views.FilterDialog.open();
                break;
            case 'preferences':
                reader.open_preferences_modal();
                break;
            case 'account':
                reader.open_account_modal();
                break;
        }
    },

    toggle_theme: function () {
        var current = NEWSBLUR.assets.theme();
        NEWSBLUR.reader.switch_theme(current === 'dark' ? 'light' : 'dark');
    },

    set_active: function (action) {
        this.$('.NB-rail-item').removeClass('NB-active');
        this.$('.NB-rail-item[data-rail-action="' + action + '"]').addClass('NB-active');
    },

    update_counts: function () {
        var counts = NEWSBLUR.assets.folders.unread_counts();
        var unread = (counts.ps || 0) + (counts.nt || 0);
        var saved = NEWSBLUR.assets.starred_count || 0;

        this.set_badge('all', unread);
        this.set_badge('saved', saved);
    },

    set_badge: function (name, count) {
        var $badge = this.$('.NB-rail-badge[data-rail-badge="' + name + '"]');

        if (!count) {
            $badge.addClass('NB-hidden').text('');
            return;
        }

        // The count is a caption under the glyph, so it never covers the icon and
        // any number of digits fits. media/js/newsblur/views/rail_view.js
        $badge.removeClass('NB-hidden').text(count);
    }
});