NEWSBLUR.Views.Toolbar = Backbone.View.extend({

    el: '.NB-feedbar',

    events: {
        'keydown .NB-toolbar-search-input': 'handle_search_keydown',
        'search .NB-toolbar-search-input': 'handle_search_input',
        'click .NB-toolbar-search': 'handle_search_open',
        'click .NB-toolbar-search-cancel': 'handle_search_cancel',
        'click .NB-toolbar-refresh': 'handle_refresh',
        'click .NB-toolbar-sidebar-toggle': 'handle_sidebar_toggle'
    },

    initialize: function () {
        _.bindAll(this, 'handle_search_keydown', 'handle_search_input',
            'handle_search_open', 'handle_sidebar_toggle', 'handle_document_click',
            'sync_search_state', 'perform_search', 'sync_sidebar_mode',
            'handle_phone_layout', 'handle_refresh', 'sync_url_search',
            'handle_pull_start', 'handle_pull_move', 'handle_pull_end',
            'handle_pull_cancel', 'watch_router');

        this.listenTo(NEWSBLUR.reader, 'change:active_feed', this.sync_search_state);
        this.watch_router();

        // Capture phase: the feed and folder views stop click propagation, so a
        // bubbling listener on document never sees the taps that close the drawer.
        document.addEventListener('click', this.handle_document_click, true);
        this.sync_search_state();

        // On a cold load the router sets flags.search before this view exists,
        // so the first sync above runs against empty flags. Re-run once the
        // rest of the reader is built.
        _.defer(this.sync_search_state);

        this.track_feed_pane_width();
        this.setup_pull_to_refresh();

        this.narrow_query = window.matchMedia('(max-width: 768px)');
        if (this.narrow_query.addEventListener) {
            this.narrow_query.addEventListener('change', this.sync_sidebar_mode);
        } else if (this.narrow_query.addListener) {
            this.narrow_query.addListener(this.sync_sidebar_mode);
        }

        this.phone_query = window.matchMedia('(max-width: 620px)');
        if (this.phone_query.addEventListener) {
            this.phone_query.addEventListener('change', this.handle_phone_layout);
        } else if (this.phone_query.addListener) {
            this.phone_query.addListener(this.handle_phone_layout);
        }
    },

    // The router is built by the feed list after the toolbar, and starting
    // Backbone.history fires the first route right away. Waiting for it here
    // means a cold load with ?search= keeps the field open and filled.
    watch_router: function (attempts) {
        attempts = attempts || 0;

        if (NEWSBLUR.router) {
            this.listenTo(NEWSBLUR.router, 'route', this.sync_search_state);
            this.sync_search_state();
            return;
        }

        if (attempts >= 50) return;
        _.delay(_.bind(this.watch_router, this, attempts + 1), 100);
    },

    // A phone renders full and split as list (see NEWSBLUR.assets.view_setting),
    // so crossing 620px has to rebuild the panes. Without this a desktop window
    // dragged narrow keeps the two-pane layout, and the layout buttons that would
    // leave it are hidden at that width.
    handle_phone_layout: function () {
        var reader = NEWSBLUR.reader;
        if (!reader || !reader.layout || !reader.layout.outerLayout) return;
        if (!reader.layout.outerLayout.state || !reader.layout.outerLayout.state.initialized) return;
        if (!NEWSBLUR.app || !NEWSBLUR.app.story_titles) return;
        reader.switch_story_layout(null, true);
    },

    // Below the drawer breakpoint the sidebar is an overlay instead of a pane,
    // so it is toggled with a body class rather than through jLayout.
    is_narrow: function () {
        return window.matchMedia('(max-width: 768px)').matches;
    },

    // The dashboard splash is offset from the sidebar edge, so it needs the
    // rendered pane width rather than the stored preference. A ResizeObserver
    // keeps --nb-feed-pane-w correct while the pane is dragged or toggled.
    track_feed_pane_width: function () {
        var $pane = $('.left-pane');
        if (!$pane.length) return;

        var pane = $pane[0];
        var update = function () {
            var width = Math.round(pane.getBoundingClientRect().width);
            if (width > 0) {
                document.documentElement.style.setProperty('--nb-feed-pane-w', width + 'px');
            }
        };

        update();
        if (this.feed_pane_observer || !window.ResizeObserver) return;
        this.feed_pane_observer = new ResizeObserver(update);
        this.feed_pane_observer.observe(pane);
    },

    // jLayout always reserves a west pane for the sidebar, which on a phone
    // leaves the story pane a few dozen pixels wide. Below the drawer breakpoint
    // the pane is closed for good and the drawer is drawn by CSS instead; above
    // it the pane comes back at the width the reader saved.
    // Called by the reader once a layout is applied, and whenever the breakpoint
    // is crossed. It only acts when the pane state is actually wrong, so it is
    // safe to call as often as needed.
    sync_sidebar_mode: function () {
        this.track_feed_pane_width();

        var reader = NEWSBLUR.reader;
        var outer_layout = reader.layout && reader.layout.outerLayout;
        var state = outer_layout && outer_layout.state;
        var sidebar_edge = NEWSBLUR.utils.layout_edge('west');
        if (!state || !state.initialized || !state[sidebar_edge]) return;

        // resize_window() talks to the taskbar views, which are built after the
        // toolbar itself, so closing the pane during init would throw.
        if (!NEWSBLUR.app || !NEWSBLUR.app.taskbar_info) return;

        if (this.is_narrow()) {
            if (!state[sidebar_edge].isHidden && !reader.flags.sidebar_closed) {
                reader.close_sidebar();
            }
        } else if (state[sidebar_edge].isHidden) {
            $('body').removeClass('NB-sidebar-open');
            reader.open_sidebar();
        }
    },

    // ==========
    // = Search =
    // ==========

    // The field rests as a 32px magnifier; clicking anywhere on the pill opens it.
    // On a phone the pill is one of four header controls, so opening it takes the
    // whole row (NB-search-open) instead of growing a 220px field in place.
    handle_search_open: function (e) {
        if (e.target === this.$('.NB-toolbar-search-input')[0]) return;
        e.preventDefault();
        if (this.is_narrow()) {
            this.$el.addClass('NB-search-open');
        }
        this.$('.NB-toolbar-search-input').trigger('focus');
    },

    // The phone field covers the header, so it needs a visible way out. Cancel
    // only puts the header back; a running search stays and the story list keeps
    // its own "clear search" link, so the results are not thrown away by a tap
    // that was meant to close the keyboard.
    handle_search_cancel: function (e) {
        e.preventDefault();
        e.stopPropagation();
        this.close_search();
    },

    close_search: function () {
        this.$el.removeClass('NB-search-open');
        this.blur_search();
    },

    handle_search_keydown: function (e) {
        var $input = $(e.currentTarget);
        var term = $.trim($input.val());

        // The document-level hotkeys treat Escape as "go to the dashboard" and
        // Enter as "open the selected story", so the field swallows both.
        if (e.which === 13) {          // Enter
            e.preventDefault();
            e.stopPropagation();
            this.perform_search(term);
            this.close_search();
        } else if (e.which === 27) {   // Escape
            e.preventDefault();
            e.stopPropagation();
            $input.val('');
            this.perform_search('');
            this.close_search();
        }
    },

    // Re-rendering the story list can leave the field focused, and a focused
    // field keeps the pill expanded, so drop focus on the element itself.
    blur_search: function () {
        var input = this.$('.NB-toolbar-search-input')[0];
        if (input && input.blur) {
            input.blur();
        }
    },

    // The native clear button of <input type="search"> fires a 'search' event.
    handle_search_input: function (e) {
        var $input = $(e.currentTarget);
        if (!$input.val()) {
            this.perform_search('');
        }
    },

    // The router already reads ?search= on every story route, so writing the
    // term here makes a search refreshable, linkable and reachable with the
    // back button. open_feed() has already navigated by the time this runs.
    sync_url_search: function (term) {
        if (!window.history || !window.history.replaceState) return;

        var url = new URL(window.location.href);
        if (term) {
            url.searchParams.set('search', term);
        } else {
            url.searchParams.delete('search');
        }

        var next = url.pathname + url.search;
        if (next === window.location.pathname + window.location.search) return;
        window.history.replaceState(window.history.state, '', next);
    },

    // A river (All Site Stories, a folder, the dashboard) is not a feed, so
    // open_feed() sends it down the tryfeed path and empties the list. Rivers
    // carry the search term through flags.search instead, so they are reloaded
    // with open_river_stories(). The dashboard has no feed at all and searches
    // every subscribed site.
    is_river_view: function () {
        var feed_id = NEWSBLUR.reader.active_feed;
        return !feed_id || (_.isString(feed_id) && feed_id.indexOf('river:') === 0);
    },

    open_current_view: function (options) {
        var reader = NEWSBLUR.reader;

        if (this.is_river_view()) {
            var folder = reader.active_folder || NEWSBLUR.assets.folders;
            reader.open_river_stories(null, folder, _.extend({
                infrequent: reader.active_feed === 'river:infrequent'
            }, options));
            return;
        }

        reader.open_feed(reader.active_feed, options);
    },

    // Searching stories reuses the reader's search flags: reset_feed() clears
    // them whenever open_feed() is called without a search option, so passing
    // an empty term is how a search gets dismissed.
    perform_search: function (term) {
        var reader = NEWSBLUR.reader;

        if (!term) {
            if (!reader.flags.searching) return;
            reader.flags.searching = false;
            reader.flags.search = null;
            this.sync_search_state();
            this.open_current_view({});
            this.sync_url_search('');
            return;
        }

        if (reader.flags.searching && reader.flags.search === term) return;

        reader.flags.searching = true;
        reader.flags.search = term;
        this.sync_search_state();
        this.open_current_view({ search: term });
        this.sync_url_search(term);
    },

    // Keep the field in sync with a search started from a story title, but
    // never overwrite what the reader is typing.
    sync_search_state: function () {
        var reader = NEWSBLUR.reader;
        var searching = Boolean(reader.flags.searching);
        var term = (searching && reader.flags.search) || '';

        this.$el.toggleClass('NB-search-active', searching);

        var $input = this.$('.NB-toolbar-search-input');
        if (!$input.length || $input.is(':focus')) return;

        if ($input.val() !== term) {
            $input.val(term);
        }

        // Navigating to another feed means the drawer has done its job.
        if (this.is_narrow()) {
            $('body').removeClass('NB-sidebar-open');
        }
    },

    // ===========
    // = Refresh =
    // ===========

    // The reading list has no reload of its own: until now stories only changed
    // when the clock fetched them or a view was reopened. This pulls fresh
    // unread counts from the server and then re-fetches the open view, keeping
    // any search term so a refresh never silently widens the result set.
    handle_refresh: function () {
        if (this.refreshing) return;

        this.refreshing = true;
        this.$el.addClass('NB-refreshing');
        this.hide_pull_indicator();

        var self = this;
        var done = _.once(function () {
            self.refreshing = false;
            self.$el.removeClass('NB-refreshing');

            var reader = NEWSBLUR.reader;
            var options = { force: true };
            if (reader.flags.searching && reader.flags.search) {
                options.search = reader.flags.search;
            }
            reader.reload_feed(options);
        });

        // A hung request must not leave the spinner turning forever.
        _.delay(done, 6000);
        NEWSBLUR.reader.force_feeds_refresh(done, false, null, done);
    },

    // Touch devices have no reload gesture either, so the list can be pulled
    // down from its very top. The indicator follows the finger, and releasing
    // past the threshold refreshes; anything shorter snaps back.
    setup_pull_to_refresh: function () {
        var pane = document.getElementById('story_titles');
        if (!pane || !window.addEventListener) return;

        this.pull = { start: 0, distance: 0, pulling: false, pane: pane };
        pane.addEventListener('touchstart', this.handle_pull_start, { passive: true });
        pane.addEventListener('touchmove', this.handle_pull_move, { passive: false });
        pane.addEventListener('touchend', this.handle_pull_end);
        pane.addEventListener('touchcancel', this.handle_pull_cancel);
    },

    pull_threshold: 44,

    handle_pull_start: function (e) {
        this.pull.pulling = false;
        if (!this.is_narrow() || this.refreshing) return;
        if (e.touches.length !== 1) return;
        if (this.pull.pane.scrollTop > 0) return;

        this.pull.start = e.touches[0].clientY;
        this.pull.distance = 0;
        this.pull.pulling = true;
    },

    handle_pull_move: function (e) {
        if (!this.pull.pulling) return;

        var dy = e.touches[0].clientY - this.pull.start;
        if (dy <= 0 || this.pull.pane.scrollTop > 0) {
            this.pull.pulling = false;
            this.pull.distance = 0;
            this.hide_pull_indicator();
            return;
        }

        // Damping keeps the pull feeling like a rubber band rather than a drag.
        this.pull.distance = Math.min(dy * 0.55, 84);
        e.preventDefault();
        this.show_pull_indicator(this.pull.distance);
    },

    handle_pull_end: function () {
        if (!this.pull.pulling) return;

        var distance = this.pull.distance;
        this.pull.pulling = false;
        this.pull.distance = 0;

        if (distance >= this.pull_threshold) {
            this.handle_refresh();
        } else {
            this.hide_pull_indicator();
        }
    },

    handle_pull_cancel: function () {
        this.pull.pulling = false;
        this.pull.distance = 0;
        this.hide_pull_indicator();
    },

    show_pull_indicator: function (distance) {
        if (!this.$pull_indicator) {
            this.$pull_indicator = $('<div class="NB-pull-refresh" role="status"></div>')
                .append('<span class="NB-pull-refresh-icon" aria-hidden="true"></span>')
                .append($('<span class="NB-pull-refresh-label"></span>').text(gettext('Refresh')))
                .appendTo('body');
        }

        var ready = distance >= this.pull_threshold;
        this.$pull_indicator
            .toggleClass('NB-pull-ready', ready)
            .css({
                opacity: Math.min(distance / this.pull_threshold, 1),
                transform: 'translate(-50%, ' + (distance - 56) + 'px)'
            });
    },

    hide_pull_indicator: function () {
        if (!this.$pull_indicator) return;
        this.$pull_indicator.css({ opacity: 0, transform: 'translate(-50%, -56px)' });
    },

    // ===========
    // = Sidebar =
    // ===========

    handle_sidebar_toggle: function (e) {
        e.preventDefault();

        if (this.is_narrow()) {
            $('body').toggleClass('NB-sidebar-open');
            return;
        }

        NEWSBLUR.reader.open_sidebar();
    },

    // Tapping the scrim closes the drawer, and so does picking a feed, folder or
    // dashboard link inside it, since the reader is about to replace the story
    // list anyway.
    handle_document_click: function (e) {
        if (!this.is_narrow() || !$('body').hasClass('NB-sidebar-open')) return;

        var $target = $(e.target);
        if (!$target.closest('.left-pane, .NB-toolbar-sidebar-toggle').length) {
            $('body').removeClass('NB-sidebar-open');
            return;
        }

        if ($target.closest('.NB-feedlist .feed, .NB-feedlist .folder_title, .NB-feeds-header, .NB-splash-link, a').length) {
            $('body').removeClass('NB-sidebar-open');
        }
    }

});
