NEWSBLUR.Views.AddSiteView = Backbone.View.extend({

    className: "NB-add-site-view",

    events: {
        "click .NB-add-site-view-toggle": "toggle_view_mode",
        "click .NB-add-site-style-button": "open_style_popover",
        "input .NB-add-site-search-input": "handle_search_input",
        "keypress .NB-add-site-search-input": "handle_search_keypress",
        "click .NB-add-site-search-tab .NB-add-site-search-clear": "clear_search",
        "click .NB-add-site-search-tab .NB-add-site-search-btn": "force_search",
        "click .NB-add-site-try-btn": "try_feed",
        "click .NB-add-site-subscribe-btn": "subscribe_to_feed",
        "click .NB-add-site-open-btn": "open_subscribed_feed",
        "click .NB-add-site-stats-btn": "open_feed_stats"
    },

    TABS: [
        { id: 'search', label: gettext('Search'), icon: '/media/img/icons/nouns/search.svg', mono: true }
    ],

    initialize: function (options) {
        this.options = options || {};
        this.model = NEWSBLUR.assets;
        this.active_tab = 'search';
        this.view_mode = NEWSBLUR.assets.preference('add_site_view_mode') || 'grid';
        this.search_query = '';
        this.search_debounced = _.debounce(_.bind(this.perform_search, this), 300);
        this.search_version = 0;  // Track search version to cancel stale responses

        this.init_tab_states();

        // Pre-fill search query from popover redirect
        if (this.options.initial_query) {
            this.search_query = this.options.initial_query;
        }

        this.render();

        // Auto-trigger search if pre-filled from popover
        if (this.options.initial_query) {
            _.defer(_.bind(this.perform_search, this));
        }
    },

    init_tab_states: function () {
        var default_search_state = {
            results: [],
            page: 1,
            has_more: true,
            is_loading: false,
            query: ''
        };

        this.search_state = _.extend({}, default_search_state);
    },

    close: function () {
        this.$el.remove();
    },

    // =============
    // = Rendering =
    // =============

    render: function () {
        var self = this;

        this.$el.html($.make('div', { className: 'NB-add-site-container' }, [
            this.render_header(),
            $.make('div', { className: 'NB-add-site-tab-content' },
                _.map(this.TABS, function(tab) {
                    return $.make('div', {
                        className: 'NB-add-site-tab-pane NB-add-site-' + tab.id + '-tab' +
                                   (self.active_tab === tab.id ? ' NB-active' : '')
                    });
                })
            )
        ]));

        this.render_active_tab();
        this.$el.data('view', this);

        return this;
    },

    render_header: function () {
        return $.make('div', { className: 'NB-add-site-header' }, [
            $.make('div', { className: 'NB-add-site-tabs-row', style: 'justify-content: flex-end' }, [
                $.make('div', { className: 'NB-add-site-controls' }, [
                    $.make('div', { className: 'NB-add-site-view-toggles' }, [
                        this.make_view_toggle('grid', gettext('Grid view'), '/media/img/icons/nouns/layout-grid.svg'),
                        this.make_view_toggle('list', gettext('List view'), '/media/img/icons/nouns/layout-list.svg')
                    ]),
                    $.make('div', {
                        className: 'NB-add-site-style-button',
                        title: gettext('Sort, filter, and display options')
                    }, [
                        $.make('img', { src: '/media/img/icons/nouns/settings.svg' }),
                        $.make('span', { className: 'NB-add-site-style-label' }, gettext('Options'))
                    ])
                ])
            ])
        ]);
    },

    make_view_toggle: function (mode, title, icon) {
        var label = mode === 'grid' ? gettext('Grid') : gettext('List');
        return $.make('div', {
            className: 'NB-add-site-view-toggle' + (this.view_mode === mode ? ' NB-active' : ''),
            'data-mode': mode,
            title: title
        }, [
            $.make('img', { src: icon }),
            $.make('span', { className: 'NB-add-site-view-toggle-label' }, label)
        ]);
    },

    get_stories_limit: function () {
        var limit = NEWSBLUR.assets.preference('add_site_stories_count');
        if (limit === undefined || limit === null) {
            return 3; // Default
        }
        return parseInt(limit, 10);
    },

    limit_stories: function (stories_collection) {
        var limit = this.get_stories_limit();
        if (limit === 0) {
            return new Backbone.Collection([]);
        }
        if (stories_collection && stories_collection.models) {
            return new Backbone.Collection(stories_collection.models.slice(0, limit));
        }
        return stories_collection;
    },

    sort_feeds: function (feeds) {
        var sort_order = NEWSBLUR.assets.preference('add_site_sort_order') || 'subscribers';
        if (!_.contains(['subscribers', 'stories', 'name'], sort_order)) sort_order = 'subscribers';

        return _.sortBy(feeds, function(feed) {
            if (sort_order === 'subscribers') {
                return -(feed.num_subscribers || 0);
            } else if (sort_order === 'stories') {
                return -(feed.average_stories_per_month || 0);
            } else if (sort_order === 'name') {
                return (feed.feed_title || feed.title || '').toLowerCase();
            }
            return 0;
        });
    },

    // add_site_view.js - get_filter_params: the Style popover "Show" + "Updated"
    // filters, sent to the discover endpoints so filtering happens server-side
    // and each fetched page stays full.
    get_filter_params: function () {
        var params = {};
        var staleness = NEWSBLUR.assets.preference('add_site_staleness') || 'any';
        if (_.contains(['5years', 'year', 'month'], staleness)) {
            params.staleness = staleness;
        }
        if (NEWSBLUR.assets.preference('add_site_hide_subscribed')) {
            params.exclude_subscribed = 'true';
        }
        return params;
    },

    // add_site_view.js - reload_active_tab: re-fetch the active tab's feeds after a
    // Style filter change. Server-side filtering means a plain re-render is not enough.
    reload_active_tab: function () {
        if (this.search_query) {
            this.perform_search();
        } else {
            this.render_search_tab();
        }
    },

    render_active_tab: function () {
        var tab_renderers = {
            'search': 'render_search_tab'
        };

        var renderer = tab_renderers[this.active_tab];
        if (renderer && this[renderer]) {
            this[renderer]();
        }
    },

    // ==============
    // = Search Tab =
    // ==============

    render_search_tab: function (options) {
        options = options || {};
        var $tab = this.$('.NB-add-site-search-tab');
        var state = this.search_state;

        // Check if we can do a partial update (results only) to preserve input focus
        var $existing_results = $tab.find('.NB-add-site-tab-results');
        var can_update_results_only = options.results_only && $existing_results.length > 0;

        var $content;

        if (state.is_loading && state.results.length === 0) {
            $content = this.make_loading_indicator();
        } else if (state.results.length === 0 && !this.search_query) {
            $content = this.render_search_empty_state();
        } else if (state.results.length === 0 && this.search_query) {
            if (this.is_url(this.search_query)) {
                $content = this.render_url_subscribe_card(this.search_query);
            } else {
                $content = this.make_no_results_message(
                    '\ud83d\udd0d',
                    gettext('No feeds found'),
                    gettext('Try a different search term or paste a URL directly.')
                );
            }
        } else {
            // Sort results based on user preference before rendering
            var sorted_results = this.sort_feeds(state.results);

            // List view with stories
            if (this.view_mode === 'list' && sorted_results.length > 0 && sorted_results[0].stories) {
                var pane_anchor = NEWSBLUR.assets.preference('story_pane_anchor');
                var image_preview = NEWSBLUR.assets.preference('image_preview') || 'large-right';
                var $list = $.make('div', { className: 'NB-trending-feed-badges NB-story-pane-' + pane_anchor + ' NB-image-preview-' + image_preview });

                _.each(sorted_results, function(feed_data) {
                    var feed_model = new NEWSBLUR.Models.Feed(feed_data);

                    var stories_limit = this.get_stories_limit();
                    var $badge_content = [
                        new NEWSBLUR.Views.FeedBadge({
                            model: feed_model,
                            show_folders: true,
                            in_add_site_view: this,
                            load_feed_after_add: false
                        })
                    ];

                    if (stories_limit > 0) {
                        var $story_titles = $.make('div', { className: 'NB-story-titles' });
                        var stories = new NEWSBLUR.Collections.Stories(feed_data.stories || []);
                        var limited_stories = this.limit_stories(stories);
                        var story_titles_view = new NEWSBLUR.Views.StoryTitlesView({
                            el: $story_titles,
                            collection: limited_stories,
                            $story_titles: $story_titles,
                            override_layout: 'split',
                            pane_anchor: pane_anchor,
                            on_search_feed: feed_model,
                            in_add_site_view: this
                        });
                        $badge_content.push(story_titles_view.render().el);
                    }

                    var $badge = $.make('div', { className: 'NB-trending-feed-badge' }, $badge_content);
                    $list.append($badge);
                }, this);

                if (state.is_loading) {
                    $list.append(this.make_loading_indicator());
                }
                $content = $list;
            } else {
                // Grid view - render feed cards
                var $results = this.make_results_container();
                _.each(sorted_results, function(feed) {
                    $results.append(this.render_feed_card(feed));
                }, this);

                if (state.is_loading) {
                    $results.append(this.make_loading_indicator());
                }
                $content = $results;
            }
        }

        if (can_update_results_only) {
            // Only update results, preserving search input focus
            $existing_results.html($content);
            // Update spinner visibility
            $tab.find('.NB-add-site-search-spinner').toggleClass('NB-hidden', !state.is_loading);
        } else {
            // Full render needed
            var $search_bar = this.render_tab_search_bar({
                input_class: 'NB-add-site-search-input',
                placeholder: gettext('Search by name, keyword, or paste a URL...'),
                value: this.search_query,
                is_loading: state.is_loading
            });

            $tab.html($.make('div', { className: 'NB-add-site-tab-with-search' }, [
                $search_bar,
                $.make('div', { className: 'NB-add-site-tab-results' }, [$content])
            ]));
        }
    },

    render_tab_search_bar: function (config) {
        var is_loading = config.is_loading || false;
        return $.make('div', { className: 'NB-add-site-tab-search-bar' }, [
            $.make('div', { className: 'NB-add-site-search-wrapper' }, [
                $.make('img', {
                    src: '/media/img/icons/lucide/search.svg',
                    className: 'NB-add-site-search-icon'
                }),
                $.make('input', {
                    type: 'text',
                    className: config.input_class,
                    placeholder: config.placeholder,
                    value: config.value || ''
                }),
                $.make('div', {
                    className: 'NB-add-site-search-spinner' + (is_loading ? '' : ' NB-hidden')
                }),
                $.make('div', {
                    className: 'NB-add-site-search-clear' + (config.value ? '' : ' NB-hidden')
                }, '\u00d7')
            ]),
            $.make('div', { className: 'NB-add-site-search-btn NB-add-site-tab-search-btn' }, gettext('Search'))
        ]);
    },

    render_search_empty_state: function () {
        return $.make('div', { className: 'NB-add-site-discover-container' });
    },

    // ==================
    // = Shared Methods =
    // ==================

    render_feed_card: function (feed, stories) {
        var self = this;
        stories = stories || [];

        // Check if already subscribed. Use feed.feed (actual Feed FK from popular_feeds API)
        // or feed.feed_id (from search results), NOT feed.id (which may be PopularFeed PK).
        // Only check feeds collection, not temp_feeds (which contains try feeds).
        var feed_id = feed.feed || feed.feed_id || feed.id;
        var feed_model = feed_id && NEWSBLUR.assets.feeds.get(feed_id);
        var subscribed = feed_model && !feed_model.get('temp');

        // Get display preferences
        var image_preview = NEWSBLUR.assets.preference('add_site_image_preview') || 'large';
        var content_preview = NEWSBLUR.assets.preference('add_site_content_preview') || 'medium';

        var $stories_preview = null;
        if (stories.length > 0) {
            $stories_preview = $.make('div', { className: 'NB-add-site-card-stories' },
                _.map(stories.slice(0, 3), function(story) {
                    var story_elements = [];

                    // Add story image if preference allows and image exists
                    if (image_preview !== 'none') {
                        var image_url = story.image_urls && story.image_urls.length > 0 ? story.image_urls[0] : null;
                        if (!image_url && story.story_content) {
                            // Try to extract first image from content
                            var img_match = story.story_content.match(/<img[^>]+src=["']([^"']+)["']/i);
                            if (img_match) image_url = img_match[1];
                        }
                        if (image_url) {
                            var image_class = 'NB-add-site-card-story-image';
                            if (image_preview === 'small') {
                                image_class += ' NB-image-small';
                            } else {
                                image_class += ' NB-image-large';
                            }
                            story_elements.push($.make('img', {
                                src: image_url,
                                className: image_class,
                                onerror: "this.style.display='none'"
                            }));
                        }
                    }

                    // add_site_view.js: dir="auto" isolates feed-provided titles and previews for LTR and RTL readers.

                    story_elements.push($.make('div', { className: 'NB-add-site-card-story-title', dir: 'auto' },
                        story.story_title || story.title || gettext('Untitled')));

                    // Add story content preview based on preference
                    if (content_preview !== 'title' && story.story_content) {
                        var content_text = self.strip_html(story.story_content);
                        if (content_text) {
                            var max_lines = content_preview === 'small' ? 1 : (content_preview === 'medium' ? 2 : 3);
                            var max_chars = max_lines * 80; // Approximate chars per line
                            var preview_text = self.truncate_text(content_text, max_chars);
                            var preview_class = 'NB-add-site-card-story-preview NB-preview-lines-' + max_lines;
                            story_elements.push($.make('div', { className: preview_class, dir: 'auto' }, preview_text));
                        }
                    }

                    return $.make('div', { className: 'NB-add-site-card-story' }, story_elements);
                })
            );
        }

        var meta_parts = [];
        if (feed.num_subscribers) {
            var subscriber_count = Math.max(0, parseInt(feed.num_subscribers, 10));
            if (subscriber_count > 0) {
                meta_parts.push(interpolate(ngettext('%(count)s subscriber', '%(count)s subscribers', subscriber_count), {count: subscriber_count.toLocaleString()}, true));
            }
        }
        if (feed.average_stories_per_month) {
            var stories_count = parseInt(feed.average_stories_per_month, 10);
            meta_parts.push(interpolate(ngettext('%(count)s story/month', '%(count)s stories/month', stories_count), {count: stories_count.toLocaleString()}, true));
        }
        var $freshness = this.make_freshness_indicator(feed.last_story_date, { show_empty: true });

        // Feed tagline/description always shown
        var $description = null;
        if (feed.tagline) {
            $description = $.make('div', { className: 'NB-add-site-card-desc' },
                this.truncate_text(feed.tagline, 150));
        }

        // Build actions based on subscription status
        var $actions;
        var $stats_btn = $.make('div', {
            className: 'NB-add-site-stats-btn NB-modal-submit-button NB-modal-submit-grey',
            'data-feed-id': feed_id
        }, [
            $.make('img', {
                src: '/media/embed/icons/nouns/dialog-statistics.svg',
                className: 'NB-add-site-stats-icon'
            }),
            gettext('Stats')
        ]);

        if (subscribed) {
            $actions = $.make('div', { className: 'NB-add-site-card-actions NB-add-site-card-actions-subscribed' }, [
                $.make('div', { className: 'NB-subscribed-badge' }, [
                    $.make('span', { className: 'NB-subscribed-badge-check' }, '\u2713'),
                    gettext('Subscribed')
                ]),
                $.make('div', { className: 'NB-add-site-card-actions-row' }, [
                    $stats_btn,
                    $.make('div', {
                        className: 'NB-add-site-open-btn NB-modal-submit-button NB-modal-submit-green',
                        'data-feed-id': feed_id
                    }, gettext('Open'))
                ])
            ]);
        } else {
            $actions = $.make('div', { className: 'NB-add-site-card-actions' }, [
                $.make('div', { className: 'NB-add-site-card-actions-row' }, [
                    $.make('div', {
                        className: 'NB-add-site-try-btn NB-modal-submit-button NB-modal-submit-green',
                        'data-feed-id': feed_id
                    }, gettext('Try')),
                    $stats_btn
                ]),
                $.make('div', { className: 'NB-add-site-card-add-group' }, [
                    this.make_folder_selector(feed),
                    $.make('div', {
                        className: 'NB-add-site-subscribe-btn NB-modal-submit-button NB-modal-submit-grey',
                        'data-feed-id': feed_id,
                        'data-feed-url': feed.feed_address || feed.address
                    }, gettext('Add'))
                ])
            ]);
        }

        // Single DOM structure for both grid and list - CSS Grid handles layout
        return $.make('div', {
            className: 'NB-add-site-card' + (subscribed ? ' NB-add-site-card-subscribed' : ''),
            'data-feed-id': feed_id
        }, [
            $.make('div', { className: 'NB-add-site-card-header' }, [
                $.make('img', {
                    src: feed.favicon_url || feed.favicon || '/media/img/icons/lucide/rss.svg',
                    className: 'NB-add-site-card-icon',
                    onerror: "this.src='/media/img/icons/lucide/rss.svg'"
                }),
                $.make('div', { className: 'NB-add-site-card-info' }, [
                    $.make('div', { className: 'NB-add-site-card-title', dir: 'auto' },
                        feed.feed_title || feed.title || gettext('Unknown Feed')),
                    $.make('div', { className: 'NB-add-site-card-meta' },
                        meta_parts.join(' \u2022 ')
                    ),
                    $freshness
                ].filter(Boolean))
            ]),
            $description,
            $stories_preview,
            $actions
        ].filter(Boolean));
    },

    make_folder_selector: function (selected_folder) {
        var folders = NEWSBLUR.utils.make_folders(selected_folder);
        var $select = $(folders).addClass('NB-add-site-folder-select');
        return $select;
    },

    make_loading_indicator: function () {
        return this.make_skeleton_cards();
    },

    make_skeleton_card: function () {
        return $.make('div', { className: 'NB-add-site-skeleton-card' }, [
            $.make('div', { className: 'NB-add-site-skeleton-header' }, [
                $.make('div', { className: 'NB-add-site-skeleton-icon' }),
                $.make('div', { className: 'NB-add-site-skeleton-info' }, [
                    $.make('div', { className: 'NB-add-site-skeleton-title' }),
                    $.make('div', { className: 'NB-add-site-skeleton-meta' })
                ])
            ]),
            $.make('div', { className: 'NB-add-site-skeleton-desc' }),
            $.make('div', { className: 'NB-add-site-skeleton-desc' }),
            $.make('div', { className: 'NB-add-site-skeleton-actions' }, [
                $.make('div', { className: 'NB-add-site-skeleton-btn' }),
                $.make('div', { className: 'NB-add-site-skeleton-btn' }),
                $.make('div', { className: 'NB-add-site-skeleton-btn NB-skeleton-wide' })
            ])
        ]);
    },

    make_skeleton_cards: function (count) {
        count = count || 6;
        var $container = this.make_results_container();
        for (var i = 0; i < count; i++) {
            $container.append(this.make_skeleton_card());
        }
        return $container;
    },

    make_results_container: function () {
        var columns = NEWSBLUR.assets.preference('add_site_grid_columns') || 'auto';
        var class_name = 'NB-add-site-results NB-add-site-results-' + this.view_mode;
        if (columns !== 'auto') {
            class_name += ' NB-add-site-columns-' + columns;
        }
        return $.make('div', { className: class_name });
    },

    make_no_results_message: function (icon, title, desc) {
        return $.make('div', { className: 'NB-add-site-no-results' }, [
            $.make('div', { className: 'NB-add-site-no-results-icon' }, icon),
            $.make('div', { className: 'NB-add-site-no-results-title' }, title),
            $.make('div', { className: 'NB-add-site-no-results-desc' }, desc)
        ]);
    },

    truncate_text: function (text, max_length) {
        if (!text || text.length <= max_length) return text;
        return text.substring(0, max_length) + '...';
    },

    strip_html: function (html) {
        if (!html) return '';
        // Remove HTML tags and decode entities
        var tmp = document.createElement('div');
        tmp.innerHTML = html;
        var text = tmp.textContent || tmp.innerText || '';
        // Normalize whitespace
        return text.replace(/\s+/g, ' ').trim();
    },

    make_freshness_indicator: function (last_story_date, options) {
        options = options || {};
        var freshness_class = 'NB-add-site-card-freshness';
        var freshness_label;

        if (!last_story_date) {
            if (!options.show_empty) return null;
            freshness_class += ' NB-freshness-none';
            freshness_label = gettext('No stories yet');
            return $.make('div', { className: freshness_class }, [
                $.make('span', { className: 'NB-freshness-dot' }),
                $.make('span', { className: 'NB-freshness-label' }, freshness_label)
            ]);
        }

        var last_date = new Date(last_story_date);
        if (isNaN(last_date.getTime())) return null;

        var now = new Date();
        var days_ago = Math.floor((now - last_date) / (1000 * 60 * 60 * 24));
        var date_str = last_date.toLocaleDateString(undefined, {
            month: 'short', day: 'numeric', year: 'numeric'
        });

        if (days_ago < 365) {
            freshness_class += ' NB-freshness-active';
            if (days_ago < 1) {
                freshness_label = gettext('Updated today');
            } else if (days_ago < 7) {
                freshness_label = interpolate(ngettext('Updated %(count)s day ago', 'Updated %(count)s days ago', days_ago), {count: days_ago}, true);
            } else if (days_ago < 30) {
                var weeks = Math.floor(days_ago / 7);
                freshness_label = interpolate(ngettext('Updated %(count)s week ago', 'Updated %(count)s weeks ago', weeks), {count: weeks}, true);
            } else {
                var months = Math.floor(days_ago / 30);
                freshness_label = interpolate(ngettext('Updated %(count)s month ago', 'Updated %(count)s months ago', months), {count: months}, true);
            }
        } else {
            freshness_class += ' NB-freshness-stale';
            freshness_label = interpolate(gettext('Stale \u2014 last story %(date)s'), {date: date_str}, true);
        }

        return $.make('div', { className: freshness_class }, [
            $.make('span', { className: 'NB-freshness-dot' }),
            $.make('span', { className: 'NB-freshness-label' }, freshness_label)
        ]);
    },

    is_url: function (str) {
        if (!str) return false;
        return /^(https?:\/\/|www\.)/i.test(str) ||
               /\.(com|org|net|io|co|me|tv|blog|news|rss|xml|feed)(\/.*)?\s*$/i.test(str);
    },

    render_url_subscribe_card: function (url) {
        var normalized_url = url;
        if (!/^https?:\/\//i.test(url)) {
            normalized_url = 'https://' + url.replace(/^www\./i, '');
        }

        var domain = normalized_url.replace(/^https?:\/\//i, '').split('/')[0];

        return $.make('div', { className: 'NB-add-site-url-subscribe' }, [
            $.make('div', { className: 'NB-add-site-url-card NB-add-site-card' }, [
                $.make('div', { className: 'NB-add-site-card-header' }, [
                    $.make('div', { className: 'NB-add-site-card-icon NB-add-site-url-icon' }, [
                        $.make('img', { src: '/media/img/icons/nouns/add.svg' })
                    ]),
                    $.make('div', { className: 'NB-add-site-card-info' }, [
                        $.make('div', { className: 'NB-add-site-card-title' }, interpolate(gettext("Subscribe to %(value_1)s"), {value_1: _.escape(domain)}, true)),
                        $.make('div', { className: 'NB-add-site-card-meta' }, normalized_url)
                    ])
                ]),
                $.make('div', { className: 'NB-add-site-card-desc' },
                    gettext('NewsBlur will automatically find the RSS feed for this site.')),
                $.make('div', { className: 'NB-add-site-card-actions' }, [
                    this.make_folder_selector(),
                    $.make('div', {
                        className: 'NB-add-site-card-subscribe NB-add-site-subscribe-btn',
                        'data-feed-url': normalized_url
                    }, gettext('Subscribe'))
                ])
            ])
        ]);
    },

    // ===========
    // = Actions =
    // ===========

    toggle_view_mode: function (e) {
        var $toggle = $(e.currentTarget);
        var mode = $toggle.data('mode');

        console.log('[AddSite] toggle_view_mode clicked, mode:', mode, 'current:', this.view_mode);

        if (!mode || mode === this.view_mode) return;

        this.view_mode = mode;

        // Save preference
        NEWSBLUR.assets.save_preferences({ 'add_site_view_mode': mode });

        this.$('.NB-add-site-view-toggle').removeClass('NB-active');
        $toggle.addClass('NB-active');

        // Re-render the active tab to switch view mode
        this.render_active_tab();
    },

    open_style_popover: function (e) {
        e.preventDefault();
        e.stopPropagation();

        if (this.style_popover && this.style_popover.is_open) {
            this.style_popover.close();
            return;
        }

        this.style_popover = new NEWSBLUR.AddSiteStylePopover({
            anchor: this.$('.NB-add-site-style-button'),
            add_site_view: this
        });
    },

    handle_search_input: function (e) {
        var query = $(e.currentTarget).val().trim();
        this.search_query = query;

        this.$('.NB-add-site-search-clear').toggleClass('NB-hidden', query.length === 0);
        this.search_debounced();
    },

    handle_search_keypress: function (e) {
        if (e.which === 13) {
            this.perform_search();
        }
    },

    force_search: function () {
        this.search_query = this.$('.NB-add-site-search-input').val().trim();
        this.perform_search();
    },

    clear_search: function () {
        this.$('.NB-add-site-search-input').val('');
        this.$('.NB-add-site-search-tab .NB-add-site-search-clear').addClass('NB-hidden');
        this.search_query = '';
        this.search_state.results = [];
        this.render_search_tab();
    },
    perform_search: function () {
        var self = this;
        var query = this.search_query;

        if (!query || query.length < 2) {
            this.search_state.results = [];
            this.render_search_tab({ results_only: true });
            return;
        }

        // Increment search version to track this request
        this.search_version++;
        var current_version = this.search_version;

        this.search_state.is_loading = true;
        this.search_state.results = [];
        this.render_search_tab({ results_only: true });

        this.model.make_request('/discover/autocomplete', _.extend({
            query: query,
            format: 'full',
            v: 2,
            include_stories: 'true'
        }, this.get_filter_params()), function (data) {
            // Ignore stale responses from previous searches
            if (current_version !== self.search_version) {
                return;
            }
            self.search_state.is_loading = false;
            var results = [];
            if (data && _.isArray(data)) {
                results = data;
            } else if (data && data.feeds) {
                results = data.feeds;
            }
            // Apply sort preference to search results
            self.search_state.results = self.sort_feeds(results);
            self.render_search_tab({ results_only: true });
        }, function () {
            // Ignore stale error responses
            if (current_version !== self.search_version) {
                return;
            }
            self.search_state.is_loading = false;
            self.render_search_tab({ results_only: true });
        }, { request_type: 'GET' });
    },

    try_feed: function (e) {
        var $btn = $(e.currentTarget);
        var feed_id = $btn.data('feed-id');
        var discover_origin = this.get_discover_origin();
        var $card = $btn.closest('.NB-add-site-card');
        var feed_data = {
            feed_title: $card.find('.NB-add-site-card-title').text(),
            favicon_url: $card.find('.NB-add-site-card-icon').attr('src')
        };

        if (feed_id) {
            NEWSBLUR.reader.load_feed_in_tryfeed_view(feed_id, {
                discover_origin: discover_origin,
                feed: feed_data
            });
        }
    },

    get_discover_origin: function () {
        var tab = this.active_tab;
        var tab_info = _.find(this.TABS, function (t) { return t.id === tab; });
        var tab_label = tab_info ? tab_info.label : tab;
        var origin = { tab: tab, tab_label: tab_label };

        if (this.search_query) {
            origin.query = this.search_query;
        }

        return origin;
    },

    subscribe_to_feed: function (e) {
        var $btn = $(e.currentTarget);
        var $card = $btn.closest('.NB-add-site-card');
        var $folder_select = $card.find('.NB-add-site-folder-select');
        var feed_url = $btn.data('feed-url');
        var folder = $folder_select.val() || '';

        if (!feed_url) {
            console.log('No feed URL found');
            return;
        }

        $btn.addClass('NB-loading').text(gettext('Adding...'));

        NEWSBLUR.assets.save_add_url(feed_url, folder, function (data) {
            if (data.code > 0 || data.feed) {
                $card.addClass('NB-subscribed');

                // Refresh feed list without opening the feed
                NEWSBLUR.assets.load_feeds();

                // Convert button to "Open Site" with feed ID stored for later
                $btn.removeClass('NB-loading NB-add-site-subscribe-btn NB-modal-submit-grey')
                    .addClass('NB-add-site-open-btn NB-modal-submit-green')
                    .text(gettext('Open Site'))
                    .data('feed-id', data.feed ? data.feed.id : null);
            } else {
                $btn.removeClass('NB-loading').addClass('NB-error').text(gettext('Error'));
                console.log('Subscribe error:', data.message);
                setTimeout(function () {
                    $btn.removeClass('NB-error').text(gettext('Add'));
                }, 2000);
            }
        });
    },

    open_subscribed_feed: function (e) {
        var $btn = $(e.currentTarget);
        var feed_id = $btn.data('feed-id');

        if (feed_id) {
            NEWSBLUR.reader.open_feed(feed_id);
        }
    },

    open_feed_stats: function (e) {
        var $btn = $(e.currentTarget);
        var feed_id = $btn.data('feed-id');

        if (feed_id) {
            NEWSBLUR.assets.load_canonical_feed(feed_id, function () {
                NEWSBLUR.reader.open_feed_statistics_modal(feed_id);
            });
        }
    },

    // ================
    // = URL Routing  =
    // ================

    // add_site_view.js - update_url: push the add-site route into the URL
    update_url: function () {
        NEWSBLUR.router.navigate('/add');
    },

    // add_site_view.js - navigate_to_state: called on back/forward when view is already open
    navigate_to_state: function (tab, category, subcategory) {
        if (this.active_tab !== 'search') {
            this.active_tab = 'search';

            this.$('.NB-add-site-tab-pane').removeClass('NB-active');
            this.$('.NB-add-site-search-tab').addClass('NB-active');
        }

        this.render_active_tab();
        this.update_url();
    },

});
