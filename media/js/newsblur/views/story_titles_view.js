NEWSBLUR.Views.StoryTitlesView = Backbone.View.extend({

    el: '.NB-story-titles',

    events: {
        "click .NB-classifier-filter-empty-clear": function (e) {
            e.preventDefault();
            NEWSBLUR.reader.close_classifier_filter();
        },
        "click .NB-classifier-filter-empty-widen": function (e) {
            e.preventDefault();
            this.widen_classifier_filter();
        },
        "click .NB-search-empty-clear": function (e) {
            e.preventDefault();
            NEWSBLUR.app.toolbar.perform_search('');
        }
    },

    initialize: function () {
        _.bindAll(this, 'scroll');
        // console.log(['initialize story titles view', this.collection]);
        this.collection.bind('reset', this.render, this);
        this.collection.bind('add', this.add, this);
        this.collection.bind('change:selected', this.scroll_to_selected_story, this);
        this.$story_titles = this.options.$story_titles || NEWSBLUR.reader.$s.$story_titles;
        this.$story_titles.scroll(this.scroll);
        this.stories = [];

        // Sits above the list, outside the ul, so it survives every re-render of
        // the rows and stays visible while the results scroll.
        this.$search_summary = $('<div class="NB-search-summary" role="status"></div>').hide();
        this.$search_summary.on('click', '.NB-search-summary-clear', function (e) {
            e.preventDefault();
            NEWSBLUR.app.toolbar.perform_search('');
        });
        this.$story_titles.prepend(this.$search_summary);
    },

    // ==========
    // = Render =
    // ==========

    render: function (options) {
        // console.log(['render story_titles', this.options.override_layout, this.collection.length, this.$story_titles[0]]);
        this.clear();
        this.$story_titles.scrollTop(0);
        var collection = this.collection;
        var story_layout = this.options.override_layout ||
            NEWSBLUR.assets.view_setting(NEWSBLUR.reader.active_feed, 'layout');
        var on_dashboard = this.options.on_dashboard;
        var on_discover_feed = this.options.on_discover_feed;
        var on_discover_story = this.options.on_discover_story;
        var in_popover = this.options.in_popover;
        var in_add_site_view = this.options.in_add_site_view;
        var override_layout = this.options.override_layout;
        var pane_anchor = this.options.pane_anchor;
        var stories = this.collection.map(function (story) {
            return new NEWSBLUR.Views.StoryTitleView({
                model: story,
                collection: collection,
                is_list: story_layout == 'list',
                is_grid: story_layout == 'grid',
                is_magazine: story_layout == 'magazine',
                override_layout: override_layout,
                pane_anchor: pane_anchor,
                on_dashboard: on_dashboard,
                on_discover_feed: on_discover_feed,
                on_discover_story: on_discover_story,
                in_popover: in_popover,
                in_add_site_view: in_add_site_view
            }).render();
        });
        this.stories = stories;
        var $stories = _.map(stories, function (story) {
            return story.el;
        });
        this.$el.html($stories);
        // console.log(['Rendered story titles', this.$el, $stories]);
        this.end_loading();
        this.fill_out();
        this.override_grid();
        this.show_search_empty_if_needed();
        this.show_view_empty_if_needed();
        this.update_search_summary();

        this.scroll_to_selected_story(null, options);

        return this;
    },

    add: function (options) {
        // console.log(['add story_titles', options]);
        var collection = this.collection;
        if (options.added) {
            var on_dashboard = this.options.on_dashboard;
            var on_discover_feed = this.options.on_discover_feed;
            var on_discover_story = this.options.on_discover_story;
            var in_popover = this.options.in_popover;
            var in_add_site_view = this.options.in_add_site_view;
            var override_layout = this.options.override_layout;
            var pane_anchor = this.options.pane_anchor;
            var story_layout = this.options.override_layout ||
                NEWSBLUR.assets.view_setting(NEWSBLUR.reader.active_feed, 'layout');
            var stories = _.compact(_.map(this.collection.models.slice(-1 * options.added), function (story) {
                if (story.story_title_view) return;
                return new NEWSBLUR.Views.StoryTitleView({
                    model: story,
                    collection: collection,
                    is_list: story_layout == 'list',
                    is_grid: story_layout == 'grid',
                    is_magazine: story_layout == 'magazine',
                    override_layout: override_layout,
                    pane_anchor: pane_anchor,
                    on_dashboard: on_dashboard,
                    on_discover_feed: on_discover_feed,
                    on_discover_story: on_discover_story,
                    in_popover: in_popover,
                    in_add_site_view: in_add_site_view
                }).render();
            }));
            this.stories = this.stories.concat(stories);
            var $stories = _.map(stories, function (story) {
                return story.el;
            });
            this.$el.append($stories);
            if (this.options.on_dashboard || this.options.on_discover_feed || this.options.on_discover_story) {
                var $extras = this.$el.find('.NB-story-title-container .NB-story-title:not(.NB-hidden)').slice(5);
                $extras.addClass('NB-hidden');
            }
        }
        this.end_loading();
        this.fill_out();
        this.update_search_summary();
    },

    // A search result is not an unlabeled list: say how many matched and how
    // to clear the search.
    update_search_summary: function () {
        if (!this.$search_summary) return;

        var reader = NEWSBLUR.reader;
        var count = this.collection.length;

        if (!reader || !reader.flags.searching || !count) {
            this.$search_summary.hide();
            return;
        }

        // no_more_stories only turns true once a page comes back empty, so an
        // unknown tail is marked with a plus rather than promised in words.
        var label = this.collection.no_more_stories ?
            interpolate(gettext('%(count)s matches'), { count: count }, true) :
            interpolate(gettext('%(count)s+ matches'), { count: count }, true);

        this.$search_summary.empty().append([
            $.make('span', { className: 'NB-search-summary-count' }, label),
            $.make('button', { type: 'button', className: 'NB-search-summary-clear' }, gettext('Clear search'))
        ]).show();
    },

    clear: function () {
        // console.log(['clear story titles', this.stories.length, this.$el]);
        _.invoke(this.stories, 'destroy');
        this.cache = {};
        this.collection.page_fill_outs = 0;
        this.collection.no_more_stories = false;
    },

    override_grid: function () {
        if (!NEWSBLUR.reader.active_feed) return;

        var story_layout = this.options.override_layout ||
            NEWSBLUR.assets.view_setting(NEWSBLUR.reader.active_feed, 'layout');
        if (story_layout != 'grid') return;

        var columns = NEWSBLUR.assets.preference('grid_columns');
        var height = NEWSBLUR.assets.preference('grid_height');
        var $layout = this.$story_titles;
        $layout.removeClass('NB-grid-columns-1')
            .removeClass('NB-grid-columns-2')
            .removeClass('NB-grid-columns-3')
            .removeClass('NB-grid-columns-4');

        $layout.removeClass('NB-grid-height-xs')
            .removeClass('NB-grid-height-s')
            .removeClass('NB-grid-height-m')
            .removeClass('NB-grid-height-l')
            .removeClass('NB-grid-height-xl');

        if (columns > 0) {
            $layout.addClass('NB-grid-columns-' + columns);
        }
        $layout.addClass('NB-grid-height-' + height);
    },

    // ===========
    // = Actions =
    // ===========

    fill_out: function (options) {
        this.snap_back_scroll_position();
        if (this.collection.no_more_stories ||
            !this.collection.length ||
            NEWSBLUR.reader.flags.story_titles_closed) {
            return;
        }

        options = options || {};
        // console.log(['fill out story titles', this.options.on_dashboard ? "dashboard" : "stories", options, NEWSBLUR.assets.flags['no_more_stories'], NEWSBLUR.assets.stories.length, NEWSBLUR.reader.flags.story_titles_closed]);

        if (this.collection.page_fill_outs < NEWSBLUR.reader.constants.FILL_OUT_PAGES &&
            !this.collection.no_more_stories) {
            // story_titles_view.js: this used to probe the last visible row and the
            // container height on every fill-out, which forced a layout flush on the
            // scroll path (up to 50 `:visible` tests per call). Nothing read the values.
            this.collection.page_fill_outs += 1;
            _.delay(_.bind(function () {
                this.scroll();
            }, this), 10);
        }
    },

    show_loading: function (options) {
        options = options || {};
        if (this.collection.no_more_stories) return;

        var $story_titles = this.$story_titles;
        this.$('.NB-end-line').remove();
        var $endline = $.make('div', { className: "NB-end-line NB-load-line NB-short" });
        $endline.css({ 'background': '#FFF' });
        this.$el.append($endline);

        if (options.scroll_to_loadbar) {
            this.pre_load_page_scroll_position = $('#story_titles').scrollTop();
            if (this.pre_load_page_scroll_position > 0) {
                this.pre_load_page_scroll_position += $endline.outerHeight();
            }
            $story_titles.stop().scrollTo($endline, {
                duration: 0,
                axis: 'y',
                easing: 'easeInOutQuint',
                offset: 0,
                queue: false
            });
            this.post_load_page_scroll_position = $('#story_titles').scrollTop();
        } else {
            this.pre_load_page_scroll_position = null;
            this.post_load_page_scroll_position = null;
        }
    },

    end_loading: function () {
        var $endbar = this.$story_titles.find('.NB-end-line');
        $endbar.remove();

        if (this.collection.no_more_stories) {
            this.show_no_more_stories();
        }
    },

    show_fetching_indicator: function () {
        this.$('.NB-feed-fetching-indicator').remove();
        var $indicator = $.make('div', { className: 'NB-feed-fetching-indicator' }, [
            $.make('div', { className: 'NB-feed-fetching-spinner' }),
            $.make('div', { className: 'NB-feed-fetching-text' }, gettext('Fetching stories...'))
        ]);
        this.$el.prepend($indicator);
        _.defer(function () {
            $indicator.addClass('NB-active');
        });
    },

    hide_fetching_indicator: function () {
        var $indicator = this.$('.NB-feed-fetching-indicator');
        if (!$indicator.length) return;
        $indicator.removeClass('NB-active');
        setTimeout(function () {
            $indicator.remove();
        }, 1000);
    },

    show_no_more_stories: function () {
        this.$('.NB-end-line, .NB-classifier-filter-empty, .NB-search-empty').remove();
        var filter = NEWSBLUR.reader.flags['classifier_filter'];
        if (filter && !this.collection.length) {
            this.show_classifier_filter_empty(filter);
            return;
        }
        // A search with no hits used to leave the pane blank, which reads as a
        // broken page rather than "nothing matched".
        if (NEWSBLUR.reader.flags.searching && !this.collection.length) {
            this.show_search_empty();
            return;
        }
        if (!this.collection.length) {
            this.show_view_empty();
            return;
        }
        var $end_stories_line = $.make('div', { className: "NB-end-line" }, [
            $.make('div', { className: 'NB-fleuron' })
        ]);
        var story_layout = this.options.override_layout ||
            NEWSBLUR.assets.view_setting(NEWSBLUR.reader.active_feed, 'layout');
        if (_.contains(['list', 'grid', 'magazine'], story_layout) || NEWSBLUR.assets.preference('mark_read_on_scroll_titles')) {
            var pane_height = this.$story_titles.height();
            var endbar_height = 20;
            var last_story_height = 80;
            endbar_height = pane_height - last_story_height;
            if (endbar_height <= 20) endbar_height = 20;

            var empty_space = pane_height - last_story_height - endbar_height;
            if (empty_space > 0) endbar_height += empty_space + 1;

            // endbar_height /= 2; // Splitting padding between top and bottom
            $end_stories_line.css('paddingBottom', endbar_height);
            // $end_stories_line.css('paddingTop', endbar_height);
            // console.log(["endbar height list", endbar_height, empty_space, pane_height, last_story_height]);
        }

        this.$el.append($end_stories_line);
    },

    // A feed, folder or saved list with nothing in it used to end at a fleuron
    // line, which reads as a truncated page. These states say what is empty and
    // offer the one action that can fill it.
    show_view_empty_if_needed: function () {
        var reader = NEWSBLUR.reader;
        if (!reader) return;
        if (reader.flags.searching || reader.flags['classifier_filter']) {
            this.$('.NB-view-empty').remove();
            return;
        }
        if (this.collection.length) {
            this.$('.NB-view-empty').remove();
            return;
        }
        // An opening feed has no stories yet either; only claim emptiness once
        // the server has answered.
        if (reader.flags.opening_feed || !reader.flags['story_titles_loaded']) return;

        this.show_view_empty();
    },

    show_view_empty: function () {
        this.$('.NB-view-empty').remove();
        var reader = NEWSBLUR.reader;
        var active_feed = reader.active_feed;
        var read_filter = NEWSBLUR.assets.view_setting(active_feed, 'read_filter');
        var active_folder = reader.active_folder;
        var folder_title = active_folder && _.isFunction(active_folder.get) &&
            active_folder.get('folder_title');
        var title, copy, action;

        var is_feed = _.isNumber(active_feed) || /^\d+$/.test(String(active_feed));
        // A feed opened from a folder keeps the folder in active_folder, so the
        // feed id has to win the naming.
        var context = is_feed ? reader.feed_title(active_feed) : folder_title;
        var refresh = {
            label: gettext("Refresh"),
            handler: function () { NEWSBLUR.app.toolbar.handle_refresh(); }
        };

        if (active_feed === 'starred') {
            title = gettext("You have no saved stories.");
            copy = gettext("Stories you star show up here.");
            action = {
                label: gettext("All Site Stories"),
                handler: function () { NEWSBLUR.reader.open_river_stories(); }
            };
        } else if (active_feed === 'read') {
            title = gettext("No stories to read");
            copy = gettext("Stories you have read show up here.");
            action = {
                label: gettext("All Site Stories"),
                handler: function () { NEWSBLUR.reader.open_river_stories(); }
            };
        } else if (read_filter === 'unread') {
            title = gettext("You have no unread stories.");
            copy = gettext("Switch to all stories to see what you have already read.");
            action = {
                label: gettext("All stories"),
                handler: function () { NEWSBLUR.reader.toggle_read_filter(); }
            };
        } else {
            title = gettext("No stories yet");
            copy = context ?
                interpolate(gettext("Nothing has been published in %(context)s yet."), { context: context }, true) :
                gettext("Your sites have not published anything new.");
            action = refresh;
        }

        var $icon = $.make('div', { className: 'NB-classifier-filter-empty-icon', 'aria-hidden': 'true' });
        $icon.html('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6h16M4 12h16M4 18h10"/></svg>');

        var $button = $.make('button', { type: 'button', className: 'NB-view-empty-action' }, action.label);
        $button.on('click', function (e) {
            e.preventDefault();
            action.handler();
        });

        this.$el.append($.make('div', { className: 'NB-classifier-filter-empty NB-view-empty' }, [
            $icon,
            $.make('div', { className: 'NB-classifier-filter-empty-title' }, title),
            $.make('div', { className: 'NB-classifier-filter-empty-copy' }, copy),
            $.make('div', { className: 'NB-classifier-filter-empty-actions' }, [$button])
        ]));
    },

    show_classifier_filter_empty: function (filter) {
        var active_feed = NEWSBLUR.reader.active_feed;
        var can_widen = active_feed !== 'river:';
        var context = NEWSBLUR.reader.feed_title(active_feed);
        // story_titles_view.js: One complete sentence per filter type, with and without a view name.
        var copy_with_context = {
            'tag': gettext("Tag filters found no stories in %(context)s."),
            'author': gettext("Author filters found no stories in %(context)s."),
            'title': gettext("Title filters found no stories in %(context)s."),
            'url': gettext("URL filters found no stories in %(context)s."),
            'text': gettext("Text filters found no stories in %(context)s.")
        };
        var copy_without_context = {
            'tag': gettext("Tag filters found no stories in this view."),
            'author': gettext("Author filters found no stories in this view."),
            'title': gettext("Title filters found no stories in this view."),
            'url': gettext("URL filters found no stories in this view."),
            'text': gettext("Text filters found no stories in this view.")
        };
        var empty_copy = context ?
            interpolate(copy_with_context[filter.type] || gettext("Filters found no stories in %(context)s."), { context: context }, true) :
            (copy_without_context[filter.type] || gettext("Filters found no stories in this view."));

        var $actions = $.make('div', { className: 'NB-classifier-filter-empty-actions' });
        if (can_widen) {
            $actions.append($.make('button', {
                type: 'button',
                className: 'NB-classifier-filter-empty-widen'
            }, gettext('Search All Site Stories')));
        }
        $actions.append($.make('button', {
            type: 'button',
            className: 'NB-classifier-filter-empty-clear'
        }, gettext('Clear filter')));

        var $icon = $.make('div', { className: 'NB-classifier-filter-empty-icon', 'aria-hidden': 'true' });
        $icon.html('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg>');
        this.$el.append($.make('div', { className: 'NB-classifier-filter-empty' }, [
            $icon,
            $.make('div', { className: 'NB-classifier-filter-empty-title' }, interpolate(gettext("No matches for “%(value_1)s”"), {value_1: filter.value}, true)),
            $.make('div', { className: 'NB-classifier-filter-empty-copy' }, empty_copy),
            $actions
        ]));
    },

    // A zero-result search never sets no_more_stories, so end_loading() alone
    // leaves the pane blank. This runs after every render instead.
    show_search_empty_if_needed: function () {
        if (!NEWSBLUR.reader.flags.searching || this.collection.length) {
            this.$('.NB-search-empty').remove();
            return;
        }
        this.show_search_empty();
    },

    // story_titles_view.js: mirrors the classifier empty state so a fruitless
    // search still says what was searched and offers a way back.
    show_search_empty: function () {
        this.$('.NB-search-empty').remove();
        var term = NEWSBLUR.reader.flags.search || '';
        if (term.length > 60) term = term.slice(0, 57) + '...';

        var $icon = $.make('div', { className: 'NB-classifier-filter-empty-icon', 'aria-hidden': 'true' });
        $icon.html('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg>');

        this.$el.append($.make('div', { className: 'NB-classifier-filter-empty NB-search-empty' }, [
            $icon,
            $.make('div', { className: 'NB-classifier-filter-empty-title' },
                interpolate(gettext("No matches for “%(value_1)s”"), { value_1: term }, true)),
            $.make('div', { className: 'NB-classifier-filter-empty-copy' },
                gettext("No stories match this search.")),
            $.make('div', { className: 'NB-classifier-filter-empty-actions' }, [
                $.make('button', { type: 'button', className: 'NB-search-empty-clear' }, gettext('Clear search'))
            ])
        ]));
    },

    widen_classifier_filter: function (e) {
        var filter = NEWSBLUR.reader.flags['classifier_filter'];
        if (!filter) return;
        NEWSBLUR.reader.open_river_stories(null, null, {
            classifier_filter: filter
        });
    },

    snap_back_scroll_position: function () {
        var $story_titles = this.$story_titles;
        if (this.post_load_page_scroll_position == $story_titles.scrollTop() &&
            this.pre_load_page_scroll_position != null &&
            !NEWSBLUR.reader.flags['select_story_in_feed']) {
            $story_titles.stop().scrollTo(this.pre_load_page_scroll_position, {
                duration: 0,
                axis: 'y',
                offset: 0,
                queue: false
            });
        }
    },

    // ============
    // = Bindings =
    // ============

    scroll_to_selected_story: function (story, options) {
        options = options || {};
        var story_title_view = (story && story.story_title_view) ||
            (this.collection.active_story && this.collection.active_story.story_title_view);
        var story_layout = this.options.override_layout ||
            NEWSBLUR.assets.view_setting(NEWSBLUR.reader.active_feed, 'layout');
        var is_always_scroll_layout = _.contains(['list', 'grid', 'magazine'], story_layout);
        if (!story_title_view) return;
        if (story &&
            !story.get('selected') &&
            !options.force &&
            story_layout != 'grid') return;

        var $selected_story = options.scroll_to_comments
            ? story_title_view.$el.find('.NB-feed-story-comments').first()
            : story_title_view.$el.children('.NB-story-title').first();

        if (!$selected_story.length) {
            $selected_story = options.scroll_to_comments
                ? story_title_view.$el.find('.NB-feed-story-comments').first()
                : story_title_view.$el.find('.NB-story-title').first();
        }
        if (!$selected_story.length) return;

        var scroll = $selected_story.position().top;
        var position = NEWSBLUR.story_titles_scroll_utils &&
            NEWSBLUR.story_titles_scroll_utils.compute_selected_story_scroll_position({
                element_top: scroll,
                element_height: $selected_story.outerHeight(),
                viewport_height: this.$story_titles.outerHeight(),
                container_scroll: this.$story_titles.scrollTop(),
                force: options.force,
                always_scroll: is_always_scroll_layout,
                scroll_up_only: options.scroll_up_only
            });

        if (position == null) return;

        NEWSBLUR.reader.flags['opening_story'] = true;
        this.$story_titles.stop().scrollTo(position, {
            duration: !options.immediate && NEWSBLUR.assets.preference('animations') ? 260 : 0,
            queue: false,
            onAfter: function () {
                NEWSBLUR.reader.flags['opening_story'] = false;
            }
        });
    },

    // ==========
    // = Events =
    // ==========

    scroll: function () {
        var $story_titles = this.$story_titles;
        var scroll_y = $story_titles.scrollTop();

        if (this.options.on_discover_feed || this.options.on_discover_story) {
            return;
        }

        if (!this.options.on_dashboard) {
            if (NEWSBLUR.reader.flags['opening_feed']) return;
            // if (NEWSBLUR.reader.flags['opening_story']) return;
            if (NEWSBLUR.assets.preference('mark_read_on_scroll_titles')) {
                this.mark_read_stories_above_scroll(scroll_y);
            }
            if (this.collection.no_more_stories) return;
        }

        var position = $story_titles.position();
        if (!position) return;

        var container_offset = position.top;
        var visible_height = $story_titles.height() * 2;
        var total_height = this.$el.outerHeight() + NEWSBLUR.reader.$s.$feedbar.innerHeight();

        // console.log(["scroll titles", this.options.on_dashboard ? "dashboard" : "stories", visible_height, scroll_y, ">", total_height, this.$el, container_offset]);
        if (visible_height + scroll_y >= total_height) {
            NEWSBLUR.reader.load_page_of_feed_stories({ scroll_to_loadbar: false });
        }
    },

    mark_read_stories_above_scroll: function (scroll_y) {
        var $story_titles = this.$story_titles;
        var score = NEWSBLUR.reader.get_unread_view_score();
        var unread_stories = [];
        var story_layout = this.options.override_layout ||
            NEWSBLUR.assets.view_setting(NEWSBLUR.reader.active_feed, 'layout');
        var grid = story_layout == 'grid';
        var point = this.$story_titles.offset();
        var offset = grid ? { top: 100, left: 100 } : { top: 30, left: 30 };
        var $story_title = $(document.elementFromPoint(point.left + offset.left,
            point.top + offset.top
        )).closest('.' + NEWSBLUR.Views.StoryTitleView.prototype.className);
        var reached_bottom = this.collection.no_more_stories &&
            this.$el.height() - $story_titles.height() - scroll_y <= 0;
        var topstory = _.detect(this.stories, function (view) {
            if (!reached_bottom && view.el == $story_title[0]) return true;
            if (view.model.get('read_status') == 0 && view.model.score() >= score) {
                unread_stories.push(view.model);
            }
        });
        if (!topstory && !reached_bottom) {
            // console.log(['no closest', topstory, $story_title[0], document.elementFromPoint(offset.left + 20, offset.top + 20)]);
            return;
        }
        // console.log(['closest', $story_title[0], topstory && topstory.model.get('story_title'), unread_stories]);
        if (NEWSBLUR.reader.flags['opening_story']) {
            console.log(['opening story, not marking read', unread_stories]);
            return;
        }
        _.invoke(unread_stories, 'mark_read');
    }

});
