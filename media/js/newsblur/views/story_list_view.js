NEWSBLUR.Views.StoryListView = Backbone.View.extend({

    el: '.NB-feed-stories',

    initialize: function () {
        _.bindAll(this, 'check_feed_view_scrolled_to_bottom',
            'check_feed_view_scrolling_from_top',
            'scroll');
        this.collection.bind('reset', this.reset_flags, this);
        this.collection.bind('reset', this.render, this);
        this.collection.bind('reset', this.reset_story_positions, this);
        this.collection.bind('add', this.add, this);
        this.collection.bind('add', this.reset_story_positions, this);
        this.collection.bind('change:selected', this.switch_story_view, this);
        this.collection.bind('change:selected', this.show_only_selected_story, this);
        this.collection.bind('change:selected', this.check_feed_view_scrolled_to_bottom, this);
        this.$el.bind('mousemove', _.bind(this.handle_mousemove_feed_view, this));
        NEWSBLUR.reader.$s.$feed_scroll.scroll(this.scroll);
        $(window).on('resize.story_positions', _.debounce(_.bind(this.schedule_position_refresh, this), 200));
        this.reset_flags();
    },

    reset_flags: function () {
        this.stop_maintaining_scroll();
        this.clear();
        this.cache = {
            story_pane_position: null,
            feed_title_floater_feed_id: null,
            feed_view_story_positions: {},
            feed_view_story_positions_keys: [],
            latest_mark_read_scroll_position: -1
        };
        this.flags = {
            mousemove_timeout: false,
            maintaining_scroll: null
        };
        this.counts = {
            positions_timer: 0
        };
    },

    // ==========
    // = Render =
    // ==========

    render: function () {
        // console.log(["Rendering story list", NEWSBLUR.assets.view_setting(NEWSBLUR.reader.active_feed, 'layout')]);
        if (!_.contains(['split', 'full'], NEWSBLUR.assets.view_setting(NEWSBLUR.reader.active_feed, 'layout'))) return;

        var collection = this.collection;

        if (NEWSBLUR.assets.preference('feed_view_single_story')) {
            this.stories = _.compact(this.collection.map(function (story) {
                return new NEWSBLUR.Views.StoryDetailView({
                    model: story,
                    collection: collection
                });
            }));
            this.show_correct_explainer();
            _.defer(this.check_feed_view_scrolled_to_bottom);
            this.end_loading();
            return;
        }

        // Round 4 perf: a feed carries a dozen full articles, and parsing every one
        // of them into the DOM in a single pass blocked the main thread for ~200ms
        // per feed switch on a throttled client. Render the first screenful
        // synchronously so the list appears immediately, then append the rest in
        // idle chunks. The DOM ends up identical, it just gets built in slices.
        var self = this;
        var models = this.collection.models.slice();
        var index = 0;
        var RENDER_CHUNK = 4;
        var schedule_chunk = window.requestIdleCallback
            ? function (fn) { window.requestIdleCallback(fn, { timeout: 300 }); }
            : function (fn) { _.delay(fn, 16); };

        this.stories = [];
        this.$el.empty();

        var render_chunk = function () {
            var views = _.compact(_.map(models.slice(index, index + RENDER_CHUNK), function (story) {
                if (story.story_view) return story.story_view;
                return new NEWSBLUR.Views.StoryDetailView({
                    model: story,
                    collection: collection
                }).render();
            }));
            index += RENDER_CHUNK;

            if (views.length) {
                self.$el.append(_.pluck(views, 'el'));
                _.invoke(views, 'attach_handlers');
                self.stories = self.stories.concat(views);
                self.reset_story_positions();
            }

            if (index < models.length) {
                schedule_chunk(render_chunk);
            } else {
                self.schedule_position_refresh();
            }
        };

        render_chunk();
        _.defer(this.check_feed_view_scrolled_to_bottom);
        this.end_loading();
    },

    add: function (options) {
        if (!_.contains(['split', 'full'], NEWSBLUR.assets.view_setting(NEWSBLUR.reader.active_feed, 'layout'))) return;

        if (options.added) {
            var collection = this.collection;
            var added = this.collection.models.slice(-1 * options.added);
            var stories = _.compact(_.map(added, function (story) {
                if (story.story_view) return;
                var view = new NEWSBLUR.Views.StoryDetailView({
                    model: story,
                    collection: collection
                });
                if (NEWSBLUR.assets.preference('feed_view_single_story')) {
                    return view;
                } else {
                    return view.render();
                }
            }));
            if (!NEWSBLUR.assets.preference('feed_view_single_story')) {
                this.$el.append(_.pluck(stories, 'el'));
                _.invoke(stories, 'attach_handlers');
            }

            this.stories = this.stories.concat(stories);
            _.defer(this.check_feed_view_scrolled_to_bottom);
            this.show_correct_explainer();
        } else {
            this.show_no_more_stories();
        }

        this.end_loading();
    },

    clear: function () {
        _.invoke(this.stories, 'destroy');
        this.$el.empty();
        this.collection.page_fill_outs = 0;
        this.collection.no_more_stories = false;
        this.clear_explainer();
    },

    clear_explainer: function () {
        this.$(".NB-story-list-empty").remove();
        this.$el.removeClass("NB-empty");
    },

    show_correct_explainer: function () {
        if (NEWSBLUR.assets.preference('feed_view_single_story') &&
            NEWSBLUR.assets.stories.visible().length) {
            this.show_explainer_single_story_mode();
        } else if (!NEWSBLUR.assets.stories.visible().length) {
            this.show_explainer_no_stories();
        } else {
            this.clear_explainer();
        }
    },

    show_explainer_single_story_mode: function () {
        this.clear_explainer();

        if (NEWSBLUR.reader.active_story) return;

        var $empty = $.make("div", { className: "NB-story-list-empty" }, [
            $.make('div', { className: 'NB-world' }),
            gettext('Select a story to read')
        ]);

        this.$el.append($empty);
    },

    show_explainer_no_stories: function () {
        this.clear_explainer();

        if (NEWSBLUR.reader.active_story) return;
        if (!this.collection.no_more_stories) return;

        var counts = NEWSBLUR.reader.get_unread_count();
        var unread_view_score = NEWSBLUR.reader.get_unread_view_score();
        var hidden_stories = false;
        if (unread_view_score > 0 && (counts['nt'] || counts['ng'])) {
            hidden_stories = counts['nt'] + counts['ng'];
        } else if (unread_view_score >= 0 && counts['ng']) {
            hidden_stories = counts['ng'];
        }
        if (NEWSBLUR.reader.flags.search) {
            hidden_stories = false;
        }
        var $empty = $.make("div", { className: "NB-story-list-empty" }, [
            gettext('No stories to read'),
            $.make('div', { className: 'NB-world' }),
            (hidden_stories && $.make('div', { className: 'NB-story-list-empty-subtitle' },
                interpolate(ngettext('There is %(count)s hidden story', 'There are %(count)s hidden stories', hidden_stories),
                    { count: Inflector.commas(hidden_stories) }, true)
            ))
        ]);

        this.$el.append($empty);

        this.$el.addClass("NB-empty");
    },

    // ===========
    // = Actions =
    // ===========

    scroll_to_selected_story: function (story, options) {
        options = options || {};
        if (!story) story = NEWSBLUR.reader.active_story;
        if (!story || !story.story_view) return;
        var $story = story.story_view.$el;

        if (NEWSBLUR.assets.preference('feed_view_single_story')) {
            options.immediate = true;
        }
        if (!NEWSBLUR.assets.preference('animations')) options.immediate = true;
        if (options.scroll_to_comments) {
            $story = $('.NB-feed-story-comments', $story);
        }

        if (options.only_if_hidden && NEWSBLUR.reader.$s.$feed_scroll.isScrollVisible($story, true)) {
            return;
        }

        if (!options.scroll_to_top && !$story.closest(NEWSBLUR.reader.$s.$feed_scroll).length) {
            console.log(['Story not visible, not scrolling', $story]);
            return;
        }

        this.stop_maintaining_scroll();
        clearTimeout(NEWSBLUR.reader.locks.scrolling);
        NEWSBLUR.reader.flags.scrolling_by_selecting_story_title = true;
        var self = this;
        var scroll_to = options.scroll_to_top ? 0 : $story;
        NEWSBLUR.reader.$s.$feed_scroll.stop().scrollTo(scroll_to, {
            duration: options.immediate ? 0 : 340,
            axis: 'y',
            easing: 'easeInOutQuint',
            offset: options.scroll_offset || 0,
            queue: false,
            onAfter: function () {
                NEWSBLUR.reader.locks.scrolling = setTimeout(function () {
                    NEWSBLUR.reader.flags.scrolling_by_selecting_story_title = false;
                }, 100);
                self.maintain_scroll_position(story, options);
            }
        });
    },

    show_only_selected_story: function (model) {
        if (!model) model = NEWSBLUR.reader.active_story;
        if (!NEWSBLUR.assets.preference('feed_view_single_story')) return;
        if (!_.contains(['split', 'full'], NEWSBLUR.assets.view_setting(NEWSBLUR.reader.active_feed, 'layout'))) return;
        if (!model.get('selected')) {
            return;
        }

        this.clear_explainer();

        this.collection.any(_.bind(function (story) {
            if (story && story.get('selected') && story.story_view) {
                this.$el.html(story.story_view.el);
                story.story_view.setElement(story.story_view.el);
                story.story_view.render();
                return true;
            }
        }, this));

        this.show_no_more_stories();
    },

    show_no_more_stories: function () {
        if (!this.collection.no_more_stories) return;

        if (!NEWSBLUR.assets.stories.visible().length) {
            this.show_explainer_no_stories();
            // return;
        }

        var pane_height = NEWSBLUR.reader.$s.$story_pane.height();
        var indicator_position = NEWSBLUR.assets.preference('lock_mouse_indicator');
        var endbar_height = 20;
        if (indicator_position &&
            _.contains(['full', 'split'], NEWSBLUR.assets.view_setting(NEWSBLUR.reader.active_feed, 'layout'))) {
            var last_visible_story = _.last(NEWSBLUR.assets.stories.visible());
            var last_story_height = last_visible_story && last_visible_story.story_view && last_visible_story.story_view.$el.height() || 100;
            var last_story_offset = _.last(this.cache.feed_view_story_positions_keys) || 0;
            endbar_height = pane_height - indicator_position - last_story_height;
            if (endbar_height <= 20) endbar_height = 20;

            var empty_space = pane_height - last_story_offset - last_story_height - endbar_height;
            if (empty_space > 0) endbar_height += empty_space + 1;
            // console.log(["endbar height full/split", endbar_height, empty_space, pane_height, last_story_offset, last_story_height]);
        }

        this.$('.NB-end-line').remove();
        if (NEWSBLUR.assets.preference('feed_view_single_story')) {
            var last_story = NEWSBLUR.assets.stories.last();
            if (last_story && !last_story.get('selected')) return;
        }

        endbar_height /= 2; // Splitting padding between top and bottom
        var $end_stories_line = $.make('div', {
            className: 'NB-end-line'
        }, [
            $.make('div', { className: 'NB-fleuron' })
        ]).css('paddingBottom', endbar_height).css('paddingTop', endbar_height);

        this.$el.append($end_stories_line);
    },

    show_stories_preference_in_feed_view: function (is_creating) {
        if (NEWSBLUR.reader.active_story &&
            NEWSBLUR.assets.preference('feed_view_single_story')) {
            this.$el.removeClass('NB-feed-view-feed').addClass('NB-feed-view-story');
            NEWSBLUR.reader.$s.$feed_stories.scrollTop('0px');
            this.flags['feed_view_positions_calculated'] = false;
        } else {
            this.$el.removeClass('NB-feed-view-story').addClass('NB-feed-view-feed');
            NEWSBLUR.reader.show_story_titles_above_intelligence_level({ 'animate': false });
        }
        this.cache.story_pane_position = NEWSBLUR.reader.$s.$story_pane.offset().top;;
    },

    fill_out: function (options) {
        if (this.collection.no_more_stories ||
            !NEWSBLUR.reader.flags.story_titles_closed) {
            return;
        }

        options = options || {};

        if (this.collection.page_fill_outs < NEWSBLUR.reader.constants.FILL_OUT_PAGES &&
            !this.collection.no_more_stories) {
            // var $last = this.$('.NB-feed-story:visible:last');
            // var container_height = NEWSBLUR.reader.$s.$story_titles.height();
            // NEWSBLUR.log(["fill out", $last.length && $last.position().top, container_height, $last.length, NEWSBLUR.reader.$s.$story_titles.scrollTop()]);
            this.collection.page_fill_outs += 1;
            _.delay(_.bind(function () {
                this.scroll();
            }, this), 10);
        }
    },

    show_loading: function (options) {
        options = options || {};
        if (this.collection.no_more_stories) return;

        var $feed_scroll = NEWSBLUR.reader.$s.$feed_scroll;
        this.$('.NB-end-line').remove();
        var $endline = $.make('div', { className: "NB-end-line NB-load-line NB-short" });
        $endline.css({ 'background': '#FFF' });
        $feed_scroll.append($endline);
    },

    end_loading: function () {
        var $endbar = NEWSBLUR.reader.$s.$feed_scroll.find('.NB-end-line');
        $endbar.remove();

        if (this.collection.no_more_stories) {
            this.show_no_more_stories();
        }
    },

    // =============
    // = Positions =
    // =============

    is_feed_loaded_for_location_fetch: function () {
        var images_begun = NEWSBLUR.assets.stories.any(function (s) {
            return !_.isUndefined(s.get('images_loaded'));
        });
        if (images_begun) {
            var images_loaded = NEWSBLUR.assets.stories.all(function (s) {
                return s.get('images_loaded');
            });
            return images_loaded;
        }

        return images_begun;
    },

    prefetch_story_locations_in_feed_view: function () {
        var self = this;
        var stories = NEWSBLUR.assets.stories;
        if (!_.contains(['split', 'full'], NEWSBLUR.assets.view_setting(NEWSBLUR.reader.active_feed, 'layout'))) return;
        if (NEWSBLUR.assets.preference('feed_view_single_story')) return;

        // NEWSBLUR.log(['Prefetching Feed', this.flags['feed_view_positions_calculated'],  this.is_feed_loaded_for_location_fetch()]);

        if (!NEWSBLUR.assets.stories.size()) return;

        if (!this.flags['feed_view_positions_calculated']) {

            $.extend(this.cache, {
                'feed_view_story_positions': {},
                'feed_view_story_positions_keys': []
            });

            NEWSBLUR.assets.stories.any(_.bind(function (story) {
                if (!story.story_view) return;
                this.determine_feed_view_story_position(story);
                var $story = story.story_view.$el;
                if (!$story || !$story.length || this.flags['feed_view_positions_calculated']) {
                    return true;
                }
            }, this));

            clearTimeout(this.flags['prefetch']);
            this.flags['prefetch'] = setTimeout(_.bind(function () {
                if (!this.flags['feed_view_positions_calculated']) {
                    this.prefetch_story_locations_in_feed_view();
                }
            }, this), 2000);
        }

        if (this.is_feed_loaded_for_location_fetch()) {
            this.fetch_story_locations_in_feed_view({ 'reset_timer': true });
        } else {
            // NEWSBLUR.log(['Still loading feed view...', this.cache.feed_view_story_positions_keys.length]);
        }
    },

    fetch_story_locations_in_feed_view: function (options) {
        options = options || {};
        var stories = NEWSBLUR.assets.stories;

        if (!_.contains(['split', 'full'], NEWSBLUR.assets.view_setting(NEWSBLUR.reader.active_feed, 'layout'))) return;
        if (NEWSBLUR.assets.preference('feed_view_single_story')) return;
        if (!stories || !stories.length) return;
        if (options.reset_timer) this.counts['positions_timer'] = 0;

        $.extend(this.cache, {
            'feed_view_story_positions': {},
            'feed_view_story_positions_keys': []
        });

        NEWSBLUR.assets.stories.each(_.bind(function (story) {
            this.determine_feed_view_story_position(story);
        }, this));
        this.cache.feed_view_story_positions_keys.sort(function (a, b) { return a - b; });

        this.flags['feed_view_positions_calculated'] = true;
        // Round 4 perf: this used to re-schedule itself forever (1s growing to 15s),
        // re-measuring every story in the pane on every tick. Keep the work
        // event-driven instead: schedule_position_refresh() runs after image loads,
        // story expansion and window resizes.
    },

    determine_feed_view_story_position: function (story) {
        if (!story.story_view) return;
        var el = story.story_view.el;
        // Round 4 perf: $().is(':visible') + $().position() + $().offsetParent()
        // forced three layout flushes per story on every pass, and the key list was
        // re-sorted inside the loop. offsetParent tells us whether the story is
        // displayed and offsetTop is a single layout read.
        if (!el || !el.offsetParent) return;
        var position = el.offsetTop;
        this.cache.feed_view_story_positions[position] = story;
        this.cache.feed_view_story_positions_keys.push(position);
    },

    schedule_position_refresh: function () {
        // Round 4 perf: positions only need to be recomputed after layout settles
        // (images loaded, story expanded, window resized), not on a timer forever.
        clearTimeout(this.flags['positions_refresh']);
        this.flags['positions_refresh'] = _.delay(
            _.bind(this.fetch_story_locations_in_feed_view, this), 250);
    },

    check_feed_view_scrolled_to_bottom: function (model, selected) {
        // console.log(['check_feed_view_scrolled_to_bottom', model, selected]);
        if (!_.contains(['split', 'full'], NEWSBLUR.assets.view_setting(NEWSBLUR.reader.active_feed, 'layout'))) return;
        if (NEWSBLUR.assets.preference('feed_view_single_story')) return;
        if (this.collection.no_more_stories) return;
        if (!NEWSBLUR.assets.stories.size()) return;
        if (!NEWSBLUR.reader.active_feed) return;
        if (selected === false) return;

        var last_story = _.last(NEWSBLUR.assets.stories.visible());
        if (!last_story || last_story.get('selected')) {
            NEWSBLUR.reader.load_page_of_feed_stories({ scroll_to_loadbar: false });
            return;
        }
        if (NEWSBLUR.assets.preference('feed_view_single_story')) return;

        if (!last_story.story_view) return;

        var $last_story = last_story.story_view.$el;
        var container_offset = NEWSBLUR.reader.$s.$feed_scroll.position().top;
        var full_height = ($last_story.length && $last_story.offset().top) + $last_story.height() - container_offset;
        var visible_height = NEWSBLUR.reader.$s.$feed_scroll.height() * 2;
        var scroll_y = NEWSBLUR.reader.$s.$feed_scroll.scrollTop();

        // Fudge factor is simply because it looks better at 64 pixels off.
        // NEWSBLUR.log(['check_feed_view_scrolled_to_bottom', full_height, container_offset, visible_height, scroll_y, NEWSBLUR.reader.flags['opening_feed']]);
        if ((visible_height + 2048) >= full_height) {
            // NEWSBLUR.log(['check_feed_view_scrolled_to_bottom', full_height, container_offset, visible_height, scroll_y, NEWSBLUR.reader.flags['opening_feed']]);
            NEWSBLUR.reader.load_page_of_feed_stories({ scroll_to_loadbar: false });
        }
    },

    check_feed_view_scrolling_from_top: function (scroll_top) {
        var cursor_position = NEWSBLUR.reader.cache.mouse_position_y + scroll_top;
        var positions = this.cache.feed_view_story_positions_keys;
        _.any(positions, _.bind(function (position) {
            if (position > cursor_position) return true;
            if (position <= this.cache.latest_mark_read_scroll_position) return false;

            var story = this.cache.feed_view_story_positions[position];
            if (!story.get('read_status')) story.mark_read();

            this.cache.latest_mark_read_scroll_position = position;
            return false;
        }, this));
    },

    reset_story_positions: function (models) {
        if (!_.contains(['split', 'full'], NEWSBLUR.assets.view_setting(NEWSBLUR.reader.active_feed, 'layout'))) return;
        if (NEWSBLUR.assets.preference('feed_view_single_story')) return;

        if (!models || !models.length) {
            models = NEWSBLUR.assets.stories;
        }
        if (!models.length) return;

        this.flags['feed_view_positions_calculated'] = false;

        if (this.cache.story_pane_position == null) {
            this.cache.story_pane_position = NEWSBLUR.reader.$s.$story_pane.offset().top;
        }

        models.each(_.bind(function (story) {
            if (!story.story_view) return;
            var image_count = story.story_view.$('.NB-feed-story-content img').length;
            if (!image_count) {
                // NEWSBLUR.log(["No images", story.get('story_title')]);
                story.set('images_loaded', true);
            } else if (!story.get('images_loaded')) {
                // Progressively load the images in each story, so that when one story
                // loads, the position is calculated and the next story can calculate
                // its position (after its own images are loaded).
                if (story.story_view.$el.data('image_load_bound')) {
                    return;
                }
                story.story_view.$el.data('image_load_bound', true);
                story.set('images_loaded', false);
                (function (story, image_count) {
                    story.story_view.$('.NB-feed-story-content img').on('load', function () {
                        // NEWSBLUR.log(['Loaded image', story.get('story_title'), image_count]);
                        if (image_count <= 1) {
                            story.set('images_loaded', true);
                        } else {
                            image_count--;
                        }
                        return true;
                    });
                })(story, image_count);
            }
        }, this));

        this.prefetch_story_locations_in_feed_view();
    },

    switch_story_view: function (story, selected, options) {
        // console.log(['switch_story_view list', story, selected, options]);
        if (selected && !options.selected_by_scrolling) {
            var story_view = NEWSBLUR.assets.view_setting(story.get('story_feed_id'), 'view');
            if (story_view != NEWSBLUR.reader.story_view) {
                console.log(['story list, switch story view', NEWSBLUR.reader.story_view]);
                NEWSBLUR.reader.set_correct_story_view_for_feed();
                NEWSBLUR.reader.switch_to_correct_view();
                NEWSBLUR.reader.switch_taskbar_view();
            }
        }
    },

    // ==========
    // = Events =
    // ==========

    handle_mousemove_feed_view: function (e) {
        var self = this;

        if (NEWSBLUR.assets.preference('feed_view_single_story')) {
            return NEWSBLUR.reader.hide_mouse_indicator();
        } else {
            NEWSBLUR.reader.show_mouse_indicator();
        }

        if (parseInt(NEWSBLUR.assets.preference('lock_mouse_indicator'), 10)) {
            return;
        }

        // console.log(["mousemove", e.pageY, this.cache.story_pane_position, NEWSBLUR.reader.cache.mouse_position_y]);
        NEWSBLUR.reader.cache.mouse_position_y = e.pageY - this.cache.story_pane_position;
        NEWSBLUR.reader.$s.$mouse_indicator.css('top', NEWSBLUR.reader.cache.mouse_position_y - 8);

        if (this.flags['mousemove_timeout'] ||
            NEWSBLUR.reader.flags['scrolling_by_selecting_story_title']) {
            return;
        }

        var from_top = NEWSBLUR.reader.cache.mouse_position_y + NEWSBLUR.reader.$s.$feed_scroll.scrollTop();
        var offset = this.cache.offset || 0;
        if (NEWSBLUR.assets.view_setting(NEWSBLUR.reader.active_feed, 'layout') == 'full' && !this.cache.offset) {
            offset = this.cache.offset = this.$el.siblings().height();
        }
        var position = from_top - offset;
        var positions = this.cache.feed_view_story_positions_keys;
        var closest = $.closest(position, positions);
        var story = this.cache.feed_view_story_positions[positions[closest]];
        // console.log(["mousemove", from_top, offset, position, positions]);
        if (!story) return;
        if (!story.get('selected')) {
            story.set('selected', true, { selected_by_scrolling: true, mouse: true, immediate: true });
        }
    },

    maintain_scroll_position: function (story, options) {
        if (NEWSBLUR.assets.preference('feed_view_single_story')) return;
        if (options && options.scroll_to_top) return;
        if (!story || !story.story_view) return;

        var $target = (options && options.scroll_to_comments)
            ? story.story_view.$('.NB-feed-story-comments')
            : story.story_view.$el;
        if (!$target || !$target.length) return;

        var self = this;
        var $feed_scroll = NEWSBLUR.reader.$s.$feed_scroll;
        var scroll_offset = (options && options.scroll_offset) || 0;
        var DRIFT_THRESHOLD = 10;
        var MONITORING_DURATION = 2000;

        this.flags['maintaining_scroll'] = {
            raf_handle: null,
            correcting: false,
            cancel_timeout: null
        };
        var state = this.flags['maintaining_scroll'];

        $feed_scroll.on(
            'wheel.maintain_scroll mousedown.maintain_scroll touchstart.maintain_scroll',
            function () {
                console.log(['maintain_scroll: cancelled by user interaction']);
                self.stop_maintaining_scroll();
            }
        );
        $(document).on('keydown.maintain_scroll', function () {
            console.log(['maintain_scroll: cancelled by keyboard']);
            self.stop_maintaining_scroll();
        });

        state.cancel_timeout = setTimeout(function () {
            self.stop_maintaining_scroll();
        }, MONITORING_DURATION);

        console.log(['maintain_scroll: started', story.get('story_title')]);

        var check = function () {
            var current_state = self.flags['maintaining_scroll'];
            if (!current_state) return;
            if (!$target.closest($feed_scroll).length) {
                self.stop_maintaining_scroll();
                return;
            }
            if (current_state.correcting) {
                current_state.raf_handle = requestAnimationFrame(check);
                return;
            }

            var container_top = $feed_scroll[0].getBoundingClientRect().top;
            var target_top = $target[0].getBoundingClientRect().top;
            var drift = (target_top - container_top) + scroll_offset;

            if (Math.abs(drift) > DRIFT_THRESHOLD) {
                console.log(['maintain_scroll: correcting drift', drift, story.get('story_title')]);
                current_state.correcting = true;

                clearTimeout(NEWSBLUR.reader.locks.scrolling);
                NEWSBLUR.reader.flags.scrolling_by_selecting_story_title = true;

                $feed_scroll.stop().scrollTo($target, {
                    duration: 200,
                    axis: 'y',
                    easing: 'easeOutQuint',
                    offset: scroll_offset,
                    queue: false,
                    onAfter: function () {
                        if (!self.flags['maintaining_scroll']) return;
                        self.flags['maintaining_scroll'].correcting = false;
                        NEWSBLUR.reader.locks.scrolling = setTimeout(function () {
                            NEWSBLUR.reader.flags.scrolling_by_selecting_story_title = false;
                        }, 100);
                    }
                });
            }

            current_state.raf_handle = requestAnimationFrame(check);
        };

        state.raf_handle = requestAnimationFrame(check);
    },

    stop_maintaining_scroll: function () {
        var state = this.flags && this.flags['maintaining_scroll'];
        if (!state) return;

        if (state.raf_handle) {
            cancelAnimationFrame(state.raf_handle);
        }
        if (state.cancel_timeout) {
            clearTimeout(state.cancel_timeout);
        }

        NEWSBLUR.reader.$s.$feed_scroll.off('.maintain_scroll');
        $(document).off('.maintain_scroll');
        this.flags['maintaining_scroll'] = null;
    },

    scroll: function (elem, e) {
        var self = this;
        var story_view = NEWSBLUR.reader.story_view;
        var offset = this.cache.offset || 0;
        if (NEWSBLUR.assets.view_setting(NEWSBLUR.reader.active_feed, 'layout') == 'full' && !this.cache.offset) {
            // offset = this.cache.offset = $(".NB-feed-story-view-header").outerHeight();
        }

        if ((story_view == 'feed' ||
            (story_view == 'page' && NEWSBLUR.reader.flags['page_view_showing_feed_view'])) &&
            !NEWSBLUR.reader.flags['scrolling_by_selecting_story_title'] &&
            !NEWSBLUR.assets.preference('feed_view_single_story')) {
            var scroll_top = NEWSBLUR.reader.$s.$feed_scroll.scrollTop();
            var from_top = NEWSBLUR.reader.cache.mouse_position_y + scroll_top;
            var position = from_top - offset;
            var positions = this.cache.feed_view_story_positions_keys;
            var closest = $.closest(position, positions);
            var story = this.cache.feed_view_story_positions[positions[closest]];

            if (!story) return;
            // NEWSBLUR.log(["Scroll Feed", NEWSBLUR.reader.cache.mouse_position_y, NEWSBLUR.reader.$s.$feed_scroll.scrollTop(), from_top, offset, position, closest, story.get('story_title')]);
            if (!story.get('selected')) {
                story.set('selected', true, { selected_by_scrolling: true, mouse: true, immediate: true });
            }

            this.check_feed_view_scrolled_to_bottom();
            if (scroll_top < 10 || NEWSBLUR.assets.preference('mark_read_on_scroll_titles')) {
                this.check_feed_view_scrolling_from_top(scroll_top);
            }
        }

        if (NEWSBLUR.reader.flags['river_view'] &&
            !NEWSBLUR.assets.preference('feed_view_single_story')) {
            var story;
            if (NEWSBLUR.reader.flags['scrolling_by_selecting_story_title']) {
                story = this.active_story;
            } else {
                var from_top = Math.max(1, NEWSBLUR.reader.$s.$feed_scroll.scrollTop());
                var positions = this.cache.feed_view_story_positions_keys;
                var closest = $.closest(from_top - offset, positions);
                story = this.cache.feed_view_story_positions[positions[closest]];
            }
        }
    }

});
