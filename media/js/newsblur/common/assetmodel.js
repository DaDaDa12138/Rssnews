NEWSBLUR.AssetModel = Backbone.Router.extend({

    // assetmodel.js translates the generic actions; service names stay as their brands.
    third_party_sharing_services: {
        "copyurl": gettext("Copy URL"),
        "copytext": gettext("Copy Text"),
        "print": gettext("Print"),
        "facebook": "Facebook",
        "twitter": "X / Twitter",
        "reddit": "Reddit",
        "readitlater": "Pocket",
        "tumblr": "Tumblr",
        "delicious": "Delicious",
        "blogger": "Blogger",
        "pinboard": "Pinboard",
        "raindrop": "Raindrop",
        "whatsapp": "WhatsApp",
        "bluesky": "Bluesky",
        "mastodon": "Mastodon",
        "pinterest": "Pinterest",
        "buffer": "Buffer",
        "diigo": "Diigo",
        "evernote": "Evernote",
        "instapaper": "Instapaper",
        "livejournal": "LiveJournal",
        "flipboard": "Flipboard",
        "lineme": "Line.me",
        "hackernews": "Hacker News",
        "telegram": "Telegram",
        "linkedin": "LinkedIn",
        "readwise": "Readwise",
        "wallabag": "Wallabag"
    },

    initialize: function () {
        this.defaults = {
            classifiers: {
                titles: {},
                title_regex: {},
                texts: {},
                text_regex: {},
                tags: {},
                authors: {},
                author_regex: {},
                feeds: {},
                urls: {},
                url_regex: {},
                prompts: {},
                image_prompts: {}
            }
        };
        this.feeds = new NEWSBLUR.Collections.Feeds();
        this.temp_feeds = new NEWSBLUR.Collections.Feeds();
        this.folders = new NEWSBLUR.Collections.Folders([]);
        this.favicons = {};
        this.stories = new NEWSBLUR.Collections.Stories();
        this.starred_feeds = new NEWSBLUR.Collections.StarredFeeds();
        this.queued_read_stories = {};
        this.classifiers = {};
        this.friends = {};
        this.profile = {};
        this.user_profile = new NEWSBLUR.Models.User();
        this.user_profiles = new NEWSBLUR.Collections.Users();
        this.follower_profiles = new NEWSBLUR.Collections.Users();
        this.following_profiles = new NEWSBLUR.Collections.Users();
        this.dashboard_rivers = new NEWSBLUR.Collections.DashboardRivers();
        this.starred_stories = [];
        this.starred_count = 0;
        this.folder_icons = {};
        this.feed_icons = {};
        this.folder_auto_mark_read = {};
        this.playback_state = null;
        this.flags = {
            'favicons_fetching': false,
            'has_chosen_feeds': false
        };

        this.ajax = {};
        this.ajax['rapid'] = $.manageAjax.create('rapid', { queue: false });
        this.ajax['queue'] = $.manageAjax.create('queue', { queue: true });
        this.ajax['queue_clear'] = $.manageAjax.create('queue_clear', { queue: 'clear' });
        this.ajax['feed'] = $.manageAjax.create('feed', {
            queue: 'clear', abortOld: true,
            domCompleteTrigger: true
        });
        this.ajax['feed_page'] = $.manageAjax.create('feed_page', {
            queue: 'clear', abortOld: true,
            abortIsNoSuccess: false,
            domCompleteTrigger: true
        });
        this.ajax['statistics'] = $.manageAjax.create('statistics', { queue: 'clear', abortOld: true });
        this.ajax['interactions'] = $.manageAjax.create('interactions', { queue: 'clear', abortOld: true });
        this.ajax['dashboard'] = $.manageAjax.create('dashboard', { queue: false });
        $.ajaxSettings.traditional = true;
    },

    make_request: function (url, data, callback, error_callback, options) {
        var self = this;
        var options = $.extend({
            'ajax_group': 'queue',
            'traditional': true,
            'domSuccessTrigger': true,
            'preventDoubleRequests': false,
            'timeout': 15000,
            'retry': true
        }, options);
        var request_type = options.request_type || 'POST';
        var clear_queue = false;

        if (options['ajax_group'] == 'feed') {
            clear_queue = true;
        }
        if (options['ajax_group'] == 'statistics') {
            clear_queue = true;
        }
        if (options['ajax_group'] == 'interactions') {
            clear_queue = true;
        }

        if (clear_queue) {
            this.ajax[options['ajax_group']].clear(true);
        }
        if (request_type == 'GET') {
            var params = data && JSON.stringify(data);
            if (params && params.length > 2000) {
                request_type = 'POST';
            }
        }

        var ajax_options = {
            url: url,
            type: request_type,
            cache: false,
            cacheResponse: false,
            beforeSend: function (xhr) {
                NEWSBLUR.set_csrf_header(xhr);
                // NEWSBLUR.log(['beforeSend', options]);
                $.isFunction(options['beforeSend']) && options['beforeSend']();
                return true;
            },
            success: function (o) {
                // NEWSBLUR.log(['make_request 1', o]);

                var lost_authentication = self.check_authentication_lost(o);
                if (lost_authentication) {
                    if (options.retry) {
                        console.log(['Retrying due to lost auth cookie', o]);
                        options.retry = false;
                        self.make_request(url, data, callback, error_callback, options);
                    } else {
                        console.log(['Woah! Lost auth cookie, letting user know...']);
                        // NEWSBLUR.reader.show_authentication_lost();
                    }
                    return;
                }

                if (o && o.code < 0 && error_callback) {
                    error_callback(o, data);
                } else if ($.isFunction(callback)) {
                    callback(o, data);
                }

            },
            error: function (e, textStatus, errorThrown) {
                if (errorThrown == 'abort') {
                    return;
                }
                NEWSBLUR.log(['AJAX Error', e, e.status, textStatus, errorThrown,
                    !!error_callback, error_callback, $.isFunction(callback)]);

                if (options.retry && !NEWSBLUR.Globals.debug) {
                    NEWSBLUR.log(['Retrying...', url, data, !!callback, !!error_callback, options]);
                    options.retry = false;
                    self.make_request(url, data, callback, error_callback, options);
                    return;
                }
                if (errorThrown == "timeout") textStatus = "NewsBlur timed out trying<br />to connect. Just try again.";
                if (error_callback && _.isFunction(error_callback)) {
                    error_callback(e, data, textStatus, errorThrown);
                } else if ($.isFunction(callback)) {
                    var message = "Please create an account. Not much<br />to do without an account.";
                    if (NEWSBLUR.Globals.is_authenticated) {
                        message = "Sorry, there was an unhandled error.";
                    }
                    callback({ 'message': message, status_code: e.status }, data);
                }
            }
        };

        // Handle JSON body requests
        if (options.request_body_type === 'json') {
            ajax_options.data = JSON.stringify(data);
            ajax_options.contentType = 'application/json';
        } else {
            ajax_options.data = data;
        }

        this.ajax[options['ajax_group']].add(_.extend(ajax_options, options));

    },

    theme: function () {
        var theme = this.preference('theme');
        var is_auto = theme == 'auto';

        if (is_auto) {
            if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
                // dark mode
                theme = "dark";
            } else {
                theme = "light";
            }
        }

        return theme;
    },

    mark_story_hash_as_read: function (story, callback, error_callback, data) {
        var self = this;

        if (!story.get('read_status')) {
            story.set('read_status', 1);

            if (NEWSBLUR.Globals.is_authenticated) {
                if (!('hashes' in this.queued_read_stories)) { this.queued_read_stories['hashes'] = []; }
                this.queued_read_stories['hashes'].push(story.get('story_hash'));
                // NEWSBLUR.log(['Marking Read', this.queued_read_stories, story.id]);

                data = _.extend({
                    story_hash: this.queued_read_stories['hashes']
                }, data);

                this.make_request(NEWSBLUR.URLs['mark-story-hashes-as-read'], data, function (resp) {
                    if (callback) callback(resp);
                }, error_callback, {
                    'ajax_group': 'queue_clear',
                    'beforeSend': function (xhr) {
                        NEWSBLUR.set_csrf_header(xhr);
                        self.queued_read_stories = {};
                    }
                });
            }
        }
    },


    mark_story_as_unread: function (story_id, feed_id, callback, error_callback) {
        var self = this;
        var read = true;
        var story = this.get_story(story_id);
        story.set('read_status', 0);

        if (NEWSBLUR.Globals.is_authenticated) {
            this.make_request(NEWSBLUR.URLs['mark-story-hash-as-unread'], {
                story_hash: story.get('story_hash')
            }, null, error_callback, {});
        }

        $.isFunction(callback) && callback();
    },

    mark_stories_as_unread: function (days, feed_id, folder, callback, error_callback) {
        var data = { days: days };
        if (feed_id) data.feed_id = feed_id;
        if (folder) data.folder = folder;
        this.make_request(NEWSBLUR.URLs['mark-stories-as-unread'], data, callback, error_callback);
    },

    mark_story_as_starred: function (story_id, callback) {
        var self = this;
        var story = this.get_story(story_id);
        var selected = this.starred_feeds.selected();

        var pre_callback = function (data) {
            if (data.starred_counts) {
                self.starred_feeds.reset(data.starred_counts, { parse: true });
                var feed = self.get_feed(story.get('story_feed_id'));
                if (feed && feed.views) _.invoke(feed.views, 'render');
            }

            if (selected) {
                self.starred_feeds.get(selected).set('selected', true);
            }

            if (callback) callback(data);
        };

        this.make_request(NEWSBLUR.URLs['mark-story-hash-as-starred'], {
            story_hash: story.get('story_hash'),
            user_tags: story.get('user_tags'),
            highlights: story.get('highlights'),
            user_notes: story.get('user_notes')
        }, pre_callback);
    },

    mark_story_as_unstarred: function (story_id, callback) {
        var self = this;
        var story = this.get_story(story_id);
        var selected = this.starred_feeds.selected();

        var pre_callback = function (data) {
            if (data.starred_counts) {
                self.starred_feeds.reset(data.starred_counts, { parse: true, update: true });
                var feed = self.get_feed(story.get('story_feed_id'));
                if (feed && feed.views) _.invoke(feed.views, 'render');
            }

            if (selected && self.starred_feeds.get(selected)) {
                self.starred_feeds.get(selected).set('selected', true);
            }

            if (callback) callback(data);
        };

        this.make_request(NEWSBLUR.URLs['mark-story-hash-as-unstarred'], {
            story_hash: story.get('story_hash')
        }, pre_callback);
    },

    update_starred_counts: function (callback) {
        var pre_callback = _.bind(function (data) {
            this.starred_feeds.reset(data.starred_counts, { parse: true, update: true });
            this.starred_count = data.starred_count;

            if (callback) callback(data);
        }, this);

        this.make_request(NEWSBLUR.URLs['starred-counts'], {}, pre_callback, pre_callback, { request_type: 'GET' });
    },

    rename_starred_tag: function (old_tag_name, new_tag_name, callback, error_callback) {
        if (NEWSBLUR.Globals.is_authenticated) {
            this.make_request(NEWSBLUR.URLs['rename-starred-tag'], {
                'old_tag_name': old_tag_name,
                'new_tag_name': new_tag_name
            }, callback, error_callback);
        } else {
            if ($.isFunction(callback)) callback({ code: -1, message: gettext('Not authenticated') });
        }
    },

    delete_starred_tag: function (tag_name, callback, error_callback) {
        if (NEWSBLUR.Globals.is_authenticated) {
            this.make_request(NEWSBLUR.URLs['delete-starred-tag'], {
                'tag_name': tag_name
            }, callback, error_callback);
        } else {
            if ($.isFunction(callback)) callback({ code: -1, message: gettext('Not authenticated') });
        }
    },

    mark_feed_as_read: function (feed_id, cutoff_timestamp, direction, options, callback) {
        var self = this;
        var feed_ids = _.isArray(feed_id)
            ? _.select(feed_id, function (f) { return f; })
            : [feed_id];

        this.stories.each(function (story) {
            if (!_.contains(feed_ids, story.get('story_feed_id'))) return;
            if (direction == "older" &&
                cutoff_timestamp &&
                story.get('story_timestamp') > cutoff_timestamp) {
                return;
            } else if (direction == "newer" &&
                cutoff_timestamp &&
                story.get('story_timestamp') < cutoff_timestamp) {
                return;
            }
            if (!story.get('read_status')) {
                story.set('read_status', true);
                var score = story.score();
                var feed = self.get_feed(story.get('story_feed_id'));
                if (!feed) return;
                if (score > 0) {
                    feed.set('ps', feed.get('ps') - 1);
                } else if (score == 0) {
                    feed.set('nt', feed.get('nt') - 1);
                } else if (score < 0) {
                    feed.set('ng', feed.get('ng') - 1);
                }
            }
        });

        if (!cutoff_timestamp) {
            _.each(feed_ids, function (feed_id) {
                var feed = self.get_feed(feed_id);
                if (!feed) return;

                feed.set({ 'ps': 0, 'nt': 0, 'ng': 0 });
            });
        }

        options = $.extend({
            feed_id: feed_ids,
            cutoff_timestamp: cutoff_timestamp,
            direction: direction
        }, options);

        this.make_request(NEWSBLUR.URLs['mark-feed-as-read'], options, callback);
    },

    add_user_profiles: function (user_profiles) {
        var profiles = _.reject(user_profiles, _.bind(function (profile) {
            return profile.id in this.user_profiles._byId;
        }, this));
        this.user_profiles.add(profiles);
    },

    load_feeds: function (callback, error_callback) {
        var self = this;
        var selected = this.feeds.selected();

        var pre_callback = function (feeds, subscriptions) {
            self.flags['favicons_fetching'] = self.feeds.any(function (feed) { return feed.get('favicons_fetching'); });

            self.folders.reset(_.compact(subscriptions.folders), { parse: true });
            self.starred_count = subscriptions.starred_count;
            self.starred_feeds.reset(subscriptions.starred_counts, { parse: true });
            self.dashboard_rivers.reset(subscriptions.dashboard_rivers);
            self.folder_icons = subscriptions.folder_icons || {};
            self.feed_icons = subscriptions.feed_icons || {};
            self.folder_auto_mark_read = subscriptions.folder_auto_mark_read || {};
            self.playback_state = subscriptions.playback_state || null;

            if (selected && self.feeds.get(selected)) {
                self.feeds.get(selected).set('selected', true);
            }
            if (!_.isEqual(self.favicons, {})) {
                self.feeds.each(function (feed) {
                    if (self.favicons[feed.id]) {
                        feed.set('favicon', self.favicons[feed.id]);
                    }
                });
            }

            self.drop_stale_temp_feeds();

            self.flags['has_chosen_feeds'] = self.feeds.has_chosen_feeds();

            self.feeds.trigger('reset');

            callback && callback();
        };

        this.feeds.fetch({
            success: pre_callback,
            error: error_callback
        });
    },

    load_feed_favicons: function (callback, loaded_once) {
        var pre_callback = _.bind(function (favicons) {
            this.favicons = favicons;
            if (!_.isEqual(this.feeds, {})) {
                this.feeds.each(function (feed) {
                    if (favicons[feed.id]) {
                        feed.set('favicon', favicons[feed.id]);
                    }
                });
            }
            callback();
        }, this);
        var data = {};
        if (loaded_once) {
            data['feed_ids'] = _.compact(this.feeds.map(function (feed) {
                return !feed.get('favicon') && feed.id;
            }));
        }
        this.make_request(NEWSBLUR.URLs['load-feed-favicons'], data, pre_callback, pre_callback, { request_type: 'GET' });
    },

    load_feed: function (feed_id, page, first_load, callback, error_callback) {
        var self = this;

        var pre_callback = function (data) {
            return self.load_feed_precallback(data, feed_id, callback, first_load);
        };

        this.feed_id = feed_id;
        // media/js/newsblur/common/assetmodel.js — a tryfeed placeholder lives in
        // temp_feeds, so ask get_feed instead of the subscribed collection or the
        // request is skipped and the reader stays on its loading state.
        var feed = this.get_feed(feed_id);

        if (feed_id && feed) {
            // media/js/newsblur/common/assetmodel.js — classifier_filter flag is
            // read by apps/reader/views.py:load_single_feed the same way the
            // river endpoint handles it.
            var cf = NEWSBLUR.reader.flags['classifier_filter'];
            this.make_request(NEWSBLUR.URLs['load-single-feed'].replace('{feed_id}', feed_id),
                {
                    page: page,
                    feed_address: feed.get('feed_address'),
                    order: this.view_setting(feed_id, 'order'),
                    read_filter: NEWSBLUR.classifier_filter_utils.read_filter_for_matching_view(
                        this.view_setting(feed_id, 'read_filter'),
                        cf
                    ),
                    date_filter_start: NEWSBLUR.reader.flags.date_filter_start,
                    date_filter_end: NEWSBLUR.reader.flags.date_filter_end,
                    query: NEWSBLUR.reader.flags.search,
                    classifier_filter_type: cf ? cf.type : null,
                    classifier_filter_value: cf ? cf.value : null,
                    classifier_filter_scope: cf ? cf.scope : null,
                    include_hidden: true
                }, pre_callback,
                error_callback,
                {
                    'ajax_group': (page > 1 ? 'feed_page' : 'feed'),
                    'request_type': 'GET'
                }
            );
        }
    },

    load_feed_precallback: function (data, feed_id, callback, first_load) {
        var self = this;

        if (data.dupe_feed_id && this.feed_id == data.dupe_feed_id) {
            feed_id = data.dupe_feed_id;
        }
        if (feed_id == this.feed_id) {
            if (data.feeds) {
                var river = _.any(['river:'], function (prefix) {
                    return _.isString(feed_id) && _.string.startsWith(feed_id, prefix);
                });
                if (river) _.each(data.feeds, function (feed) { feed.temp = true; });
                this.feeds.add(data.feeds);
            }
            if (data.classifiers) {
                if (_.string.include(feed_id, ':')) { // is_river
                    _.extend(this.classifiers, data.classifiers);
                } else if (first_load || !this.classifiers[feed_id]) {
                    this.classifiers[feed_id] = _.extend({}, this.defaults['classifiers'], data.classifiers);
                }
            }

            if (data.user_profiles) {
                var profiles = _.reject(data.user_profiles, _.bind(function (profile) {
                    return profile.id in this.user_profiles._byId;
                }, this));
                this.user_profiles.add(profiles);
            }

            if (data.updated) {
                var feed = this.get_feed(feed_id);
                feed.set('updated', data.updated);
            }

            if (data.stories && first_load) {
                // console.log(['first load river', data.stories.length, ' stories']);
                this.feed_tags = data.feed_tags || {};
                this.feed_authors = data.feed_authors || {};
                this.active_feed = this.get_feed(feed_id);
                if (this.active_feed) {
                    var feed_updates = {
                        feed_title: data.feed_title || this.active_feed.get('feed_title'),
                        updated: data.updated || this.active_feed.get('updated'),
                        feed_address: data.feed_address || this.active_feed.get('feed_address')
                    };
                    if ('not_yet_fetched' in data) {
                        feed_updates.not_yet_fetched = data.not_yet_fetched;
                        feed_updates.fetched_once = data.fetched_once;
                    }
                    this.active_feed.set(feed_updates);
                }
                this.feed_id = feed_id;
                this.starred_stories = data.starred_stories;
                this.stories.reset(data.stories, { added: data.stories.length });
            } else if (data.stories) {
                // console.log(['adding to river', data.stories.length, ' stories']);
                this.stories.add(data.stories, { silent: true });
                this.stories.trigger('add', { added: data.stories.length });
            }

            if (data.stories && !data.stories.length) {
                this.stories.no_more_stories = true;
                this.stories.trigger('no_more_stories');
            }
            var attrs = {};
            var feed_attrs = ["num_subscribers", "is_push", "min_to_decay", "favicon_color", "favicon_border", "favicon_fade", "favicon_textg_color", "updated_seconds_ago"];
            for (var attr in feed_attrs) {
                var feed_attr = feed_attrs[attr];
                if (data[feed_attr] || !_.isUndefined(data[feed_attr])) {
                    attrs[feed_attr] = data[feed_attr];
                }
            }
            if (this.active_feed) this.active_feed.set(attrs);

            $.isFunction(callback) && callback(data, first_load);
        }
    },

    check_authentication_lost: function (data) {
        if (!NEWSBLUR.Globals.is_authenticated) return false;
        if (_.isUndefined(data.authenticated)) return false;
        if (NEWSBLUR.Globals.is_authenticated != data.authenticated && data.authenticated === false) {
            return true;
        }
        return false;
    },

    load_canonical_feed: function (feed_id, callback) {
        var pre_callback = _.bind(function (data) {
            var feed = this.feeds.get(data.id);
            if (feed) {
                feed.set(data);
            } else {
                this.feeds.add(data);
            }
            this.feed_tags = data.feed_tags || {};
            this.feed_authors = data.feed_authors || {};
            this.feed_id = feed_id;
            this.classifiers[feed_id] = data.classifiers || this.defaults['classifiers'];
            callback && callback();
        }, this);

        this.make_request(NEWSBLUR.URLs['feed-info'].replace('{feed_id}', feed_id), {}, pre_callback, $.noop, {
            request_type: 'GET'
        });
    },

    fetch_starred_stories: function (page, tag, highlights, callback, error_callback, first_load) {
        var self = this;

        var pre_callback = function (data) {
            return self.load_feed_precallback(data, 'starred', callback, first_load);
        };

        this.feed_id = 'starred';

        this.make_request(NEWSBLUR.URLs['load-starred-stories'], {
            page: page,
            query: NEWSBLUR.reader.flags.search,
            order: this.view_setting('starred', 'order'),
            tag: tag,
            highlights: highlights,
            date_filter_start: NEWSBLUR.reader.flags.date_filter_start,
            date_filter_end: NEWSBLUR.reader.flags.date_filter_end,
            v: 2
        }, pre_callback, error_callback, {
            'ajax_group': (page ? 'feed_page' : 'feed'),
            'request_type': 'GET'
        });
    },

    fetch_read_stories: function (page, callback, error_callback, first_load) {
        var self = this;

        var pre_callback = function (data) {
            return self.load_feed_precallback(data, 'read', callback, first_load);
        };

        this.feed_id = 'read';

        this.make_request(NEWSBLUR.URLs['load-read-stories'], {
            page: page,
            query: NEWSBLUR.reader.flags.search,
            order: this.view_setting('read', 'order'),
            date_filter_start: NEWSBLUR.reader.flags.date_filter_start,
            date_filter_end: NEWSBLUR.reader.flags.date_filter_end
        }, pre_callback, error_callback, {
            'ajax_group': (page ? 'feed_page' : 'feed'),
            'request_type': 'GET'
        });
    },

    fetch_river_stories: function (feed_id, feeds, page, options, callback, error_callback, first_load) {
        var self = this;
        // media/js/newsblur/common/assetmodel.js — classifier_filter params come
        // from NEWSBLUR.reader.flags.classifier_filter (see reader.js:open_classifier_filter).
        // When set, the backend (apps/reader/views.py:load_river_stories__redis)
        // short-circuits the normal read-filter aggregation and returns only
        // stories matching the chosen classifier value.
        var cf = NEWSBLUR.reader.flags['classifier_filter'];
        options = $.extend({
            feeds: feeds,
            page: page,
            order: this.view_setting(feed_id, 'order'),
            read_filter: this.view_setting(feed_id, 'read_filter'),
            date_filter_start: NEWSBLUR.reader.flags.date_filter_start,
            date_filter_end: NEWSBLUR.reader.flags.date_filter_end,
            query: NEWSBLUR.reader.flags.search,
            classifier_filter_type: cf ? cf.type : null,
            classifier_filter_value: cf ? cf.value : null,
            classifier_filter_scope: cf ? cf.scope : null,
            include_hidden: true,
            infrequent: false
        }, options);
        options.read_filter = NEWSBLUR.classifier_filter_utils.read_filter_for_matching_view(
            options.read_filter,
            cf
        );

        var pre_callback = function (data) {
            self.load_feed_precallback(data, feed_id, callback, first_load);
        };

        this.feed_id = feed_id;

        this.make_request(NEWSBLUR.URLs['load-river-stories'], options, pre_callback, error_callback, {
            'ajax_group': (page ? 'feed_page' : 'feed'),
            'request_type': 'GET'
        });

    },

    complete_river: function (feed_id, feeds, page, callback) {
        this.make_request(NEWSBLUR.URLs['complete-river'], {
            feeds: feeds,
            page: page,
            read_filter: this.view_setting(feed_id, 'read_filter')
        }, callback, callback, {
            'ajax_group': 'dashboard'
        });
    },

    fetch_dashboard_stories: function (feed_id, feeds, page, dashboard_stories, options, callback, error_callback) {
        var self = this;
        options = $.extend({
            feeds: feeds,
            page: page,
            order: this.view_setting(feed_id, 'order'),
            read_filter: this.view_setting(feed_id, 'read_filter'),
            date_filter_start: options.date_filter_start,
            date_filter_end: options.date_filter_end,
            query: options.query,
            limit: 5,
            infrequent: false,
            include_hidden: false,
            dashboard: true,
            on_dashboard: true
        }, options);

        dashboard_stories.comparator = function (a, b) {
            var a_time = parseInt(a.get('story_timestamp'), 10);
            var b_time = parseInt(b.get('story_timestamp'), 10);
            if (options.order == "newest")
                return a_time < b_time ? 1 : (a_time == b_time) ? 0 : -1;
            else
                return a_time > b_time ? 1 : (a_time == b_time) ? 0 : -1;
        };

        var pre_callback = function (data) {
            if (data.user_profiles) {
                self.add_user_profiles(data.user_profiles);
            }
            var count = parseInt(NEWSBLUR.assets.view_setting(feed_id, 'dashboard_count'), 10);
            if (page > 1) {
                dashboard_stories.add(data.stories, { silent: true });
                dashboard_stories.limit_visible_on_dashboard(count);
                // dashboard_stories.trigger('add', { added: data.stories.length });
                dashboard_stories.trigger('reset', { added: data.stories.length });
            } else {
                dashboard_stories.reset(data.stories, { added: data.stories.length, silent: true });
                dashboard_stories.limit_visible_on_dashboard(count);
                dashboard_stories.trigger('reset', { added: data.stories.length });
            }

            if (data.feeds) {
                var river = _.any(['river:'], function (prefix) {
                    return _.isString(feed_id) && _.string.startsWith(feed_id, prefix);
                });
                if (river) _.each(data.feeds, function (feed) { feed.temp = true; });
                self.feeds.add(data.feeds);
            }
            // self.load_feed_precallback(data, feed_id, callback);
            callback(data);
        };

        if (_.string.startsWith(feed_id, 'river:') || _.string.startsWith(feed_id, 'feed:') || _.string.startsWith(feed_id, 'search:')) {
            this.make_request(NEWSBLUR.URLs['load-river-stories'], options, pre_callback, error_callback, {
                'ajax_group': 'dashboard',
                'request_type': 'GET'
            });
        }

    },

    fetch_story_changes: function (story_hash, show_changes, callback, error_callback) {
        this.make_request(NEWSBLUR.URLs['story-changes'], {
            story_hash: story_hash,
            show_changes: show_changes
        }, callback, error_callback, {
            'request_type': 'GET'
        });
    },

    get_feeds_trainer: function (feed_id, callback) {
        var self = this;
        var params = {};

        if (feed_id) {
            params['feed_id'] = feed_id;
        }

        this.make_request(NEWSBLUR.URLs['feeds-trainer'], params, callback, null, { 'ajax_group': 'feed', 'request_type': 'GET' });
    },

    get_all_classifiers: function (callback, error_callback) {
        this.make_request(NEWSBLUR.URLs['all-classifiers'], {}, callback, error_callback, { 'ajax_group': 'feed', 'request_type': 'GET' });
    },

    retrain_all_sites: function (callback) {
        var self = this;
        var params = {};

        if (NEWSBLUR.Globals.is_authenticated) {
            this.make_request(NEWSBLUR.URLs['retrain-all-sites'], params, callback, null);
        } else {
            if ($.isFunction(callback)) callback();
        }
    },

    refresh_feeds: function (callback, has_unfetched_feeds, feed_id, error_callback) {
        var self = this;

        var pre_callback = function (data) {
            self.post_refresh_feeds(data, callback, {
                'refresh_feeds': true
            });
        };

        var data = {};
        if (has_unfetched_feeds) {
            data['check_fetch_status'] = has_unfetched_feeds;
        }
        if (this.flags['favicons_fetching']) {
            var favicons_fetching = _.pluck(this.feeds.select(function (feed, k) {
                return feed.get('favicon_fetching') && feed.get('active');
            }), 'id');
            if (favicons_fetching.length) {
                data['favicons_fetching'] = favicons_fetching;
            } else {
                this.flags['favicons_fetching'] = false;
            }
        }
        if (feed_id) {
            data['feed_id'] = feed_id;
        }

        if (NEWSBLUR.Globals.is_authenticated || feed_id) {
            this.make_request(NEWSBLUR.URLs['refresh-feeds'], data, pre_callback, error_callback);
        }
    },

    feed_unread_count: function (feed_id, callback, error_callback) {
        var self = this;

        var pre_callback = function (data) {
            self.post_refresh_feeds(data, callback, {
                'refresh_feeds': false
            });
        };

        if (NEWSBLUR.Globals.is_authenticated || feed_id) {
            this.make_request(NEWSBLUR.URLs['feed-unread-count'], {
                'feed_id': feed_id
            }, pre_callback, error_callback, { request_type: 'GET' });
        }
    },

    post_refresh_feeds: function (data, callback, options) {
        if (!data.feeds) return;

        options = options || {};

        _.each(data.feeds, _.bind(function (feed, feed_id) {
            var existing_feed = this.feeds.get(feed_id);
            if (!existing_feed) {
                console.log(["Trying to refresh unsub feed", feed_id, feed, this.feeds.length]);
                return;
            }
            if ((feed['has_exception'] && !existing_feed.get('has_exception')) ||
                (existing_feed.get('has_exception') && !feed['has_exception'])) {
                existing_feed.set('has_exception', !!feed['has_exception']);
            }
            if (feed['favicon'] && existing_feed.get('favicon') != feed['favicon']) {
                existing_feed.set({
                    'favicon': feed['favicon'],
                    'favicon_color': feed['favicon_color'],
                    'favicon_fetching': false
                });
            }

            if (existing_feed.get('selected') && options.refresh_feeds) {
                existing_feed.force_update_counts();
            } else {
                existing_feed.set(feed, options);
            }
        }, this));

        callback && callback(data);
    },

    refresh_feed: function (feed_id, callback) {
        var self = this;
        var feed = this.feeds.get(feed_id);
        if (!feed) return;

        var pre_callback = function (data) {
            // NEWSBLUR.log(['refresh_feed pre_callback', data]);
            self.load_feed_precallback(data, feed_id, callback);
        };

        // NEWSBLUR.log(['refresh_feed', feed_id, page, first_load, callback, pre_callback]);
        if (feed_id) {
            this.make_request(NEWSBLUR.URLs['load-single-feed'].replace('{feed_id}', feed_id),
                {
                    page: 0,
                    feed_address: feed.get('feed_address')
                }, pre_callback,
                null,
                {
                    'ajax_group': 'feed_page',
                    'request_type': 'GET'
                }
            );
        }
    },


    count_unfetched_feeds: function () {
        var counts = this.feeds.reduce(function (counts, feed) {
            if (feed.get('active')) {
                if (feed.get('fetched_once') || feed.get('has_exception')) {
                    counts['fetched_feeds'] += 1;
                } else {
                    counts['unfetched_feeds'] += 1;
                }
            }
            return counts;
        }, {
            'unfetched_feeds': 0,
            'fetched_feeds': 0
        });

        return counts;
    },

    unfetched_feeds: function () {
        return this.feeds.filter(function (feed) {
            return feed.get('active') && !feed.get('fetched_once') && !feed.get('has_exception');
        });
    },

    set_feed: function (feed_id, feed) {
        if (!feed) {
            feed = feed_id;
            feed_id = feed.id;
        }
        if (!this.feeds.get(feed)) {
            this.feeds.add(feed);
        } else {
            this.feeds.get(feed_id).set(feed);
        }

        return this.feeds.get(feed_id);
    },

    set_temp_feed: function (feed_id, feed) {
        if (!feed) {
            feed = feed_id;
            feed_id = feed.id;
        }
        feed.temp = true;
        if (!this.temp_feeds.get(feed)) {
            this.temp_feeds.add(feed);
        } else {
            this.temp_feeds.get(feed_id).set(feed);
        }

        return this.temp_feeds.get(feed_id);
    },

    get_feed: function (feed_id) {
        var self = this;

        if (_.string.startsWith(feed_id, 'starred:')) {
            return this.starred_feeds.get(feed_id);
        } else if (_.string.startsWith(feed_id, 'river:')) {
            return this.get_folder(feed_id);
        } else if (_.string.startsWith(feed_id, 'feed:')) {
            return this.feeds.get(parseInt(feed_id.replace('feed:', ''), 10));
        } else {
            var feed = this.feeds.get(feed_id);
            if (!feed) {
                feed = this.temp_feeds.get(feed_id);
            }
            return feed;
        }
    },

    // The tryfeed view (a site the reader has not subscribed to) keeps its
    // placeholder feed in temp_feeds. Older builds put it in the main
    // collection, and a subscribed feed that arrived afterwards could not take
    // its place, so the reader kept showing the subscribe banner for a feed it
    // already followed. Sweep up anything the main collection has since learned
    // about, and reopen the feed so the tryfeed chrome goes away.
    drop_stale_temp_feeds: function () {
        var self = this;
        var stale = [];

        this.temp_feeds.each(function (feed) {
            if (self.feeds.get(feed.id)) stale.push(feed);
        });
        if (!stale.length) return;

        _.each(stale, function (feed) {
            self.temp_feeds.remove(feed);
        });

        var reader = NEWSBLUR.reader;
        if (!reader) return;

        var stale_active = _.any(stale, function (feed) {
            return feed.id == reader.active_feed;
        });
        if (stale_active && reader.flags['showing_feed_in_tryfeed_view']) {
            reader.hide_tryfeed_view();
            _.defer(function () {
                reader.open_feed(reader.active_feed, { force: true, router: true });
            });
        }
    },

    get_feeds: function () {
        var self = this;

        return this.feeds;
    },

    get_starred_feeds: function () {
        var self = this;

        return this.starred_feeds;
    },

    get_folders: function () {
        var self = this;

        return this.folders;
    },

    get_folder: function (folder_name) {
        if (_.string.startsWith(folder_name, 'river:')) {
            folder_name = folder_name.replace('river:', '');
        }
        return this.folders.find_folder(folder_name.toLowerCase());
    },

    get_feed_tags: function () {
        return this.feed_tags;
    },

    get_feed_authors: function () {
        return this.feed_authors;
    },

    get_story: function (story_id) {
        var self = this;
        var story = this.stories.get(story_id);
        if (!story) {
            story = this.stories.detect(function (story) {
                return story.get('story_hash') == story_id;
            });
        }
        return story;
    },

    get_user: function (user_id) {
        var user = this.user_profiles.find(user_id);
        if (!user && user_id == this.user_profile.get('user_id')) {
            user = this.profile;
        }

        return user;
    },

    save_classifier: function (data, callback) {
        if (NEWSBLUR.Globals.is_authenticated) {
            this.make_request(NEWSBLUR.URLs['classifier-save'], data, callback);
        } else {
            if ($.isFunction(callback)) callback();
        }
    },

    // Optimistically update the per-feed classifier cache for a single
    // value so recalculate_story_scores can see the change without a full
    // refetch. score === 0 (or null/undefined) clears the value. Returns
    // false when there's nothing cached for the feed.
    update_cached_classifier_score: function (feed_id, classifier_type, value, score) {
        var cache = this.classifiers[feed_id];
        if (!cache) return false;
        var bucket_key = classifier_type + 's';
        cache[bucket_key] = cache[bucket_key] || {};
        if (!score) {
            delete cache[bucket_key][value];
        } else {
            cache[bucket_key][value] = score;
        }
        return true;
    },




    save_all_classifiers: function (classifiers_by_feed, callback, error_callback) {
        if (NEWSBLUR.Globals.is_authenticated) {
            this.make_request(NEWSBLUR.URLs['classifier-save-all'], {
                classifiers: classifiers_by_feed
            }, callback, error_callback, {
                request_type: 'POST',
                request_body_type: 'json'
            });
        } else {
            if ($.isFunction(callback)) callback();
        }
    },

    get_feed_classifier: function (feed_id, callback) {
        this.make_request(NEWSBLUR.URLs['classifier-index'] + feed_id, {}, callback, null, {
            'ajax_group': 'feed',
            'request_type': 'GET'
        });
    },

    delete_feed: function (feed_id, in_folder, callback) {
        if (NEWSBLUR.Globals.is_authenticated) {
            this.make_request(NEWSBLUR.URLs['delete-feed'], {
                'feed_id': feed_id,
                'in_folder': in_folder
            }, callback, null);
        } else {
            if ($.isFunction(callback)) callback();
        }
    },

    delete_feeds_by_folder: function (feeds_by_folder, callback, error_callback) {
        var pre_callback = _.bind(function (data) {
            _.each(feeds_by_folder, _.bind(function (feed_in_folder) {
                this.feeds.remove(feed_in_folder[0]);
            }, this));
            this.folders.reset(_.compact(data.folders), { parse: true });
            return callback();
        }, this);

        this.make_request(NEWSBLUR.URLs['delete-feeds-by-folder'], {
            'feeds_by_folder': JSON.stringify(feeds_by_folder)
        }, pre_callback, error_callback);
    },

    delete_feed_by_url: function (url, in_folder, callback) {
        this.make_request(NEWSBLUR.URLs['delete-feed-by-url'], {
            'url': url,
            'in_folder': in_folder || ''
        }, callback, function () {
            callback({ 'message': NEWSBLUR.Globals.is_anonymous ? gettext('Please create an account. Not much to do without an account.') : gettext('There was a problem trying to add this site. Please try a different URL.') });
        });
    },

    delete_folder: function (folder_name, in_folder, feeds, callback) {
        var self = this;
        var pre_callback = function (data) {
            self.folders.reset(_.compact(data.folders), { parse: true });
            self.feeds.trigger('reset');

            callback(data);
        };
        if (NEWSBLUR.Globals.is_authenticated) {
            this.make_request(NEWSBLUR.URLs['delete-folder'], {
                'folder_name': folder_name,
                'in_folder': in_folder,
                'feed_id': feeds
            }, pre_callback, null);
        } else {
            if ($.isFunction(callback)) callback();
        }
    },

    rename_feed: function (feed_id, feed_title, callback) {
        if (NEWSBLUR.Globals.is_authenticated) {
            this.make_request(NEWSBLUR.URLs['rename-feed'], {
                'feed_id': feed_id,
                'feed_title': feed_title
            }, callback, null);
        } else {
            if ($.isFunction(callback)) callback();
        }
    },

    rename_folder: function (folder_name, new_folder_name, in_folder, callback) {
        if (NEWSBLUR.Globals.is_authenticated) {
            this.make_request(NEWSBLUR.URLs['rename-folder'], {
                'folder_name': folder_name,
                'new_folder_name': new_folder_name,
                'in_folder': in_folder
            }, callback, null);
        } else {
            if ($.isFunction(callback)) callback();
        }
    },

    save_add_url: function (url, folder, callback, options) {
        options = _.extend({ 'auto_active': true }, options);
        this.make_request(NEWSBLUR.URLs['add-url'], {
            'url': url,
            'folder': folder,
            'auto_active': options.auto_active
        }, callback, function (data) {
            callback({ 'message': NEWSBLUR.Globals.is_anonymous ? gettext('Please create an account. Not much to do without an account.') : data.message || 'There was a problem trying to add this site. Please try a different URL.' });
        });
    },

    save_add_folder: function (folder, parent_folder, callback) {
        this.make_request(NEWSBLUR.URLs['add-folder'], {
            'folder': folder,
            'parent_folder': parent_folder
        }, callback, function (data) {
            callback({ 'message': NEWSBLUR.Globals.is_anonymous ? gettext('Please create an account. Not much to do without an account.') : data.message || 'There was a problem trying to add this folder.' });
        });
    },

    move_feed_to_folder: function (feed_id, in_folder, to_folder, callback) {
        var pre_callback = _.bind(function (data) {
            this.folders.reset(_.compact(data.folders), { parse: true });
            return callback();
        }, this);

        this.make_request(NEWSBLUR.URLs['move-feed-to-folder'], {
            'feed_id': feed_id,
            'in_folder': in_folder,
            'to_folder': to_folder
        }, pre_callback);
    },

    move_feed_to_folders: function (feed_id, in_folders, to_folders, callback) {
        var pre_callback = _.bind(function (data) {
            this.folders.reset(_.compact(data.folders), { parse: true });
            return callback();
        }, this);

        this.make_request(NEWSBLUR.URLs['move-feed-to-folders'], {
            'feed_id': feed_id,
            'in_folders': in_folders,
            'to_folders': to_folders
        }, pre_callback);
    },

    move_folder_to_folder: function (folder_name, in_folder, to_folder, callback) {
        var pre_callback = _.bind(function (data) {
            this.folders.reset(_.compact(data.folders), { parse: true });
            return callback();
        }, this);

        this.make_request(NEWSBLUR.URLs['move-folder-to-folder'], {
            'folder_name': folder_name,
            'in_folder': in_folder,
            'to_folder': to_folder
        }, pre_callback);
    },

    move_feeds_by_folder: function (feeds_by_folder, to_folder, new_folder, callback, error_callback) {
        var pre_callback = _.bind(function (data) {
            this.folders.reset(_.compact(data.folders), { parse: true });
            return callback();
        }, this);

        this.make_request(NEWSBLUR.URLs['move-feeds-by-folder-to-folder'], {
            'feeds_by_folder': JSON.stringify(feeds_by_folder),
            'to_folder': to_folder,
            'new_folder': new_folder
        }, pre_callback, error_callback);
    },

    preference: function (preference, value, callback) {
        if (typeof value == 'undefined') {
            var pref = NEWSBLUR.Preferences[preference];
            if ((/^\d+$/).test(pref)) return parseInt(pref, 10);
            return pref;
        }

        if (NEWSBLUR.Preferences[preference] == value) {
            return $.isFunction(callback) && callback();
        }

        NEWSBLUR.Preferences[preference] = value;
        var preferences = {};
        preferences[preference] = value;
        if (NEWSBLUR.Globals.is_authenticated) {
            this.make_request(NEWSBLUR.URLs['profile-set-preference'], preferences, callback, null);
        } else {
            if (callback) callback();
        }
    },

    save_preferences: function (preferences, callback) {
        _.each(preferences, function (value, preference) {
            NEWSBLUR.Preferences[preference] = value;
        });

        this.make_request(NEWSBLUR.URLs['profile-set-preference'], preferences, callback, null);
    },

    save_account_settings: function (settings, callback) {
        this.make_request(NEWSBLUR.URLs['profile-set-account-settings'], settings, function (data) {
            callback(data);
        }, null);
    },

    // Reads a view setting exactly as it was stored, without the phone width
    // downgrade applied in view_setting(). Callers that write settings back use
    // this so a layout chosen on a desktop is not overwritten from a phone.
    saved_view_setting: function (feed_id, setting) {
        setting = setting || 'view';
        var s = setting.substr(0, 1);
        var feed = NEWSBLUR.Preferences.view_settings[feed_id + ''];
        var default_setting = NEWSBLUR.Preferences['default_' + setting];
        if (setting == 'layout') default_setting = NEWSBLUR.Preferences['story_layout'];
        if (setting == 'read_filter' && _.string.contains(feed_id, 'river:')) {
            default_setting = 'unread';
        }
        return feed && feed[s] || default_setting;
    },

    view_setting: function (feed_id, setting, callback) {
        if (NEWSBLUR.reader.flags['feed_list_showing_starred'] &&
            setting == 'read_filter') return "starred";
        if (_.isUndefined(setting) || _.isString(setting)) {
            setting = setting || 'view';
            var view_setting = this.saved_view_setting(feed_id, setting);
            // Full and split open a second pane, and the layout buttons are
            // hidden below 620px, so a layout saved on a desktop would leave a
            // phone reader with no way back to the story list. Only what the
            // reader renders changes; the stored value is left alone.
            if (setting == 'layout' && (view_setting == 'full' || view_setting == 'split') &&
                NEWSBLUR.reader.is_phone_width && NEWSBLUR.reader.is_phone_width()) {
                return 'list';
            }
            // if (view_setting == "magazine") view_setting = "list";
            return view_setting;
        }

        var view_settings = _.clone(NEWSBLUR.Preferences.view_settings[feed_id + '']) || {};
        if (_.isString(view_settings)) {
            view_settings = { 'view': view_settings };
        }
        var params = { 'feed_id': feed_id + '' };
        _.each([
            'view',
            'order',
            'read_filter',
            'layout',
            'dashboard_count',
            'stories_discover'
        ], function (facet) {
            if (setting.hasOwnProperty(facet)) {
                var key = facet.substr(0, 1);
                view_settings[key] = setting[facet];
                params['feed_' + facet + '_setting'] = setting[facet];
            }
        });

        if (!_.isEqual(NEWSBLUR.Preferences.view_settings[feed_id + ''], view_settings)) {
            NEWSBLUR.Preferences.view_settings[feed_id + ''] = view_settings;
            this.make_request(NEWSBLUR.URLs['profile-set-view-setting'], params, callback, null);
            return true;
        }
    },

    clear_view_settings: function (view_setting_type, callback) {
        var pre_callback = _.bind(function (data) {
            if (data.view_settings) {
                NEWSBLUR.Preferences.view_settings = data.view_settings;
            }
            callback(data);
        }, this);

        this.make_request(NEWSBLUR.URLs['profile-clear-view-setting'], {
            view_setting_type: view_setting_type
        }, pre_callback, null);

    },

    collapsed_folders: function (folder_title, is_collapsed, callback) {
        var folders = NEWSBLUR.Preferences.collapsed_folders;
        var changed = false;

        if (is_collapsed && !_.contains(NEWSBLUR.Preferences.collapsed_folders, folder_title)) {
            NEWSBLUR.Preferences.collapsed_folders.push(folder_title);
            changed = true;
        } else if (!is_collapsed && _.contains(NEWSBLUR.Preferences.collapsed_folders, folder_title)) {
            NEWSBLUR.Preferences.collapsed_folders = _.without(folders, folder_title);
            changed = true;
        }

        if (changed) {
            this.make_request(NEWSBLUR.URLs['profile-set-collapsed-folders'], {
                'collapsed_folders': JSON.stringify(NEWSBLUR.Preferences.collapsed_folders)
            }, callback, null);
        }
    },

    save_mark_read: function (days, callback) {
        this.make_request(NEWSBLUR.URLs['mark-all-as-read'], { 'days': days }, callback);
    },

    find_story_by_permalink: function (story_url, callback, error_callback) {
        this.make_request(NEWSBLUR.URLs['find-story-by-permalink'], {
            'story_url': story_url
        }, callback, error_callback, {
            'ajax_group': 'queue',
            request_type: 'GET'
        });
    },



    save_feed_order: function (folders, callback) {
        this.make_request(NEWSBLUR.URLs['save-feed-order'], { 'folders': JSON.stringify(folders) }, callback);
    },

    save_feed_fetch_interval: function (feed_id, fetch_interval, callback) {
        this.make_request(NEWSBLUR.URLs['save-feed-fetch-interval'], {
            'feed_id': feed_id,
            'fetch_interval': fetch_interval
        }, callback);
    },

    get_feed_statistics: function (feed_id, callback) {
        this.make_request(NEWSBLUR.URLs['feed-statistics'].replace('{feed_id}', feed_id), {}, callback, callback, {
            'ajax_group': 'statistics',
            'request_type': 'GET'
        });
    },

    get_feed_settings: function (feed_id, callback) {
        this.make_request(NEWSBLUR.URLs['feed-settings'].replace('{feed_id}', feed_id), {}, callback, callback, {
            'ajax_group': 'statistics',
            'request_type': 'GET'
        });
    },

    save_exception_retry: function (feed_id, callback, error_callback) {
        var self = this;
        var feed = this.feeds.get(feed_id);
        if (!feed) return;

        var pre_callback = function (data) {
            // NEWSBLUR.log(['refresh_feed pre_callback', data]);
            self.post_refresh_feeds(data, callback);
        };

        this.make_request(NEWSBLUR.URLs['exception-retry'], {
            'feed_id': feed_id,
            'reset_fetch': !!(feed.get('has_feed_exception') ||
                feed.get('has_page_exception'))
        }, pre_callback, error_callback);
    },

    save_exception_change_feed_link: function (feed_id, feed_link, callback, error_callback) {
        var self = this;

        if (NEWSBLUR.Globals.is_authenticated) {
            this.make_request(NEWSBLUR.URLs['exception-change-feed-link'], {
                'feed_id': feed_id,
                'feed_link': feed_link
            }, function (data) {
                // NEWSBLUR.log(['save_exception_change_feed_link pre_callback', feed_id, feed_link, data]);
                if (data.code < 0 || data.status_code != 200) {
                    return callback(data);
                }
                self.post_refresh_feeds(data, callback);
            }, error_callback);
        } else {
            if ($.isFunction(callback)) callback();
        }
    },

    save_exception_change_feed_address: function (feed_id, feed_address, callback, error_callback) {
        var self = this;

        if (NEWSBLUR.Globals.is_authenticated) {
            this.make_request(NEWSBLUR.URLs['exception-change-feed-address'], {
                'feed_id': feed_id,
                'feed_address': feed_address
            }, function (data) {
                // NEWSBLUR.log(['save_exception_change_feed_address pre_callback', feed_id, feed_address, data]);
                if (data.code < 0 || data.status_code != 200) {
                    return callback(data);
                }
                self.post_refresh_feeds(data, callback);
            }, error_callback);
        } else {
            if ($.isFunction(callback)) callback();
        }
    },

    save_feed_chooser: function (approved_feeds, callback) {
        if (NEWSBLUR.Globals.is_authenticated) {
            this.make_request(NEWSBLUR.URLs['save-feed-chooser'], {
                'approved_feeds': approved_feeds && _.select(approved_feeds, function (f) { return f; })
            }, callback);
        } else {
            if ($.isFunction(callback)) callback();
        }
    },

    set_feed_mute: function (feed_id, mute, mute_duration_days, callback) {
        if (NEWSBLUR.Globals.is_authenticated) {
            var params = { 'feed_id': feed_id, 'mute': mute };
            if (mute_duration_days) params['mute_duration_days'] = mute_duration_days;
            this.make_request(NEWSBLUR.URLs['set-feed-mute'], params, callback);
        } else {
            if ($.isFunction(callback)) callback();
        }
    },


    search_for_feeds: function (query, callback) {
        this.make_request('/discover/autocomplete', {
            'query': query,
            'format': 'full',
            'v': 2
        }, callback, callback, {
            ajax_group: 'feed',
            request_type: 'GET'
        });
    },

    // ===================
    // = Folder Icons =
    // ===================

    get_folder_icon: function (folder_title) {
        return this.folder_icons[folder_title] || null;
    },

    save_folder_icon: function (folder_title, icon_type, icon_data, icon_color, icon_set, callback, error_callback) {
        this.make_request(NEWSBLUR.URLs['save-folder-icon'], {
            folder_title: folder_title,
            icon_type: icon_type,
            icon_data: icon_data,
            icon_color: icon_color,
            icon_set: icon_set || 'lucide'
        }, _.bind(function (response) {
            this.folder_icons = response.folder_icons || {};
            callback && callback(response);
        }, this), error_callback);
    },

    remove_folder_icon: function (folder_title, callback, error_callback) {
        this.save_folder_icon(folder_title, 'none', null, null, null, callback, error_callback);
    },

    // ===================
    // = Feed Icons =
    // ===================

    get_feed_icon: function (feed_id) {
        return this.feed_icons[feed_id] || null;
    },

    save_feed_icon: function (feed_id, icon_type, icon_data, icon_color, icon_set, callback, error_callback) {
        var self = this;
        this.make_request(NEWSBLUR.URLs['save-feed-icon'], {
            feed_id: feed_id,
            icon_type: icon_type,
            icon_data: icon_data,
            icon_color: icon_color,
            icon_set: icon_set
        }, function (response) {
            self.feed_icons = response.feed_icons || {};
            callback && callback(response);
        }, error_callback);
    },

    remove_feed_icon: function (feed_id, callback, error_callback) {
        this.save_feed_icon(feed_id, 'none', null, null, null, callback, error_callback);
    },

    // =============================
    // = Auto Mark Read Settings =
    // =============================

    get_feed_folders: function (feed_id) {
        // Find the immediate folder containing a given feed_id
        // Returns folder titles (not full nested paths) to match folder_auto_mark_read keys
        var folders = [];
        feed_id = parseInt(feed_id, 10);

        var search_collection = function (collection, current_folder_title) {
            if (!collection || !collection.each) return;

            collection.each(function (item) {
                if (item.is_feed && item.is_feed()) {
                    // This is a feed - check if it matches
                    // FeedInFolder stores the feed reference in item.feed
                    var item_feed_id = item.feed ? item.feed.id : item.get('feed_id');
                    if (item_feed_id === feed_id) {
                        // Return the immediate folder title, not the full path
                        folders.push(current_folder_title || '');
                    }
                } else if (item.is_folder && item.is_folder()) {
                    // This is a folder - recurse into it with this folder's title
                    var folder_title = item.get('folder_title') || '';
                    if (item.folders) {
                        search_collection(item.folders, folder_title);
                    }
                }
            });
        };

        // Start from the root folders collection
        if (this.folders) {
            search_collection(this.folders, '');
        }

        return folders;
    },

    get_folder_auto_mark_read: function (folder_title) {
        var setting = this.folder_auto_mark_read[folder_title];
        return setting ? setting.auto_mark_read_days : null;
    },

    save_feed_auto_mark_read: function (feed_id, days, callback, error_callback) {
        var self = this;
        var feed = this.get_feed(feed_id);
        this.make_request(NEWSBLUR.URLs['save-feed-auto-mark-read'], {
            feed_id: feed_id,
            auto_mark_read_days: days
        }, function (response) {
            if (response.code == 1 && feed) {
                if (days === null || days === '') {
                    feed.unset('auto_mark_read_days');
                } else {
                    feed.set('auto_mark_read_days', parseInt(days, 10));
                }
            }
            callback && callback(response);
        }, error_callback);
    },

    save_folder_auto_mark_read: function (folder_title, days, callback, error_callback) {
        var self = this;
        this.make_request(NEWSBLUR.URLs['save-folder-auto-mark-read'], {
            folder_title: folder_title,
            auto_mark_read_days: days
        }, function (response) {
            if (response.code == 1) {
                self.folder_auto_mark_read = response.folder_auto_mark_read || {};
            }
            callback && callback(response);
        }, error_callback);
    },

    get_auto_mark_read_settings: function (callback, error_callback) {
        var self = this;
        this.make_request(NEWSBLUR.URLs['get-auto-mark-read-settings'], {}, function (response) {
            if (response.code == 1) {
                self.folder_auto_mark_read = response.folder_auto_mark_read || {};
            }
            callback && callback(response);
        }, error_callback, { request_type: 'GET' });
    },

    save_dashboard_river: function (river_id, river_side, river_order, callback, error_callback) {
        this.make_request(NEWSBLUR.URLs['save-dashboard-river'], {
            river_id: river_id,
            river_side: river_side,
            river_order: river_order
        }, _.bind(function (response) {
            this.dashboard_rivers.reset(response.dashboard_rivers);
            callback && callback(response);
        }, this), error_callback);
    },

    remove_dashboard_river: function (river_id, river_side, river_order, callback, error_callback) {
        this.make_request(NEWSBLUR.URLs['remove-dashboard-river'], {
            river_id: river_id,
            river_side: river_side,
            river_order: river_order
        }, _.bind(function (response) {
            this.dashboard_rivers.reset(response.dashboard_rivers);
            callback && callback(response);
        }, this), error_callback);
    },

    delete_saved_stories: function (timestamp, callback, error_callback) {
        var self = this;
        var pre_callback = function (data) {
            if (data.starred_counts) {
                self.starred_feeds.reset(data.starred_counts, { parse: true });
            }
            self.starred_count = data.starred_count;

            if (callback) callback(data);
        };

        this.make_request(NEWSBLUR.URLs['profile-delete-starred-stories'], {
            timestamp: timestamp
        }, pre_callback, error_callback);
    },

    count_saved_stories: function (timestamp, callback, error_callback) {
        this.make_request(NEWSBLUR.URLs['profile-count-starred-stories'], {
            timestamp: timestamp
        }, callback, error_callback);
    },



    count_classifiers: function (callback, error_callback) {
        this.make_request(NEWSBLUR.URLs['profile-count-classifiers'], {}, callback, error_callback);
    },

    delete_classifiers: function (categories, callback, error_callback) {
        this.make_request(NEWSBLUR.URLs['profile-delete-classifiers'], {
            'categories': categories
        }, callback, error_callback);
    },

    delete_all_sites: function (callback, error_callback) {
        this.make_request(NEWSBLUR.URLs['profile-delete-all-sites'], {}, callback, error_callback);
    },

    fetch_original_text: function (story_hash, callback, error_callback) {
        var story = this.get_story(story_hash);
        this.make_request(NEWSBLUR.URLs['original-text'], {
            story_hash: story_hash
        }, function (data) {
            story.set('original_text', data.original_text);
            story.set('image_urls', data.image_urls);
            story.set('secure_image_urls', data.secure_image_urls);
            callback(data);
        }, error_callback, {
            request_type: 'GET',
            ajax_group: 'statistics'
        });
    },

    recalculate_story_scores: function (feed_id, options) {
        options = options || {};

        this.stories.each(_.bind(function (story, i) {
            if (story.get('story_feed_id') != feed_id) return;
            var intelligence = {
                author: 0,
                author_regex: 0,
                feed: 0,
                tags: 0,
                title: 0,
                title_regex: 0,
                text: 0,
                text_regex: 0,
                url: 0,
                url_regex: 0
            };

            _.each(this.classifiers[feed_id].titles, function (classifier_score, classifier_title) {
                if (classifier_score <= -2 || (intelligence.title > -2 && intelligence.title <= 0)) {
                    // media/js/newsblur/common/assetmodel.js: Match title classifiers at word starts,
                    // while allowing trained stems to continue through the end of a word.
                    if (NEWSBLUR.title_classifier_utils.find_match_position(
                        story.get('story_title', ''), classifier_title
                    ) != -1) {
                        intelligence.title = classifier_score;
                    }
                }
            });

            _.each(this.classifiers[feed_id].authors, function (classifier_score, classifier_author) {
                if ((classifier_score <= -2 || (intelligence.author > -2 && intelligence.author <= 0)) &&
                    story.get('story_authors', '').indexOf(classifier_author) != -1) {
                    intelligence.author = classifier_score;
                }
            });

            _.each(this.classifiers[feed_id].tags, function (classifier_score, classifier_tag) {
                if ((classifier_score <= -2 || (intelligence.tags > -2 && intelligence.tags <= 0)) &&
                    story.get('story_tags') && _.contains(story.get('story_tags'), classifier_tag)) {
                    intelligence.tags = classifier_score;
                }
            });

            _.each(this.classifiers[feed_id].feeds, function (classifier_score, classifier_feed_id) {
                if ((classifier_score <= -2 || (intelligence.feed > -2 && intelligence.feed <= 0)) &&
                    story.get('story_feed_id') == classifier_feed_id) {
                    intelligence.feed = classifier_score;
                }
            });

            _.each(this.classifiers[feed_id].texts, function (classifier_score, classifier_text) {
                if (classifier_score <= -2 || (intelligence.text > -2 && intelligence.text <= 0)) {
                    // Standard substring matching against RSS body and full article text
                    var ct = classifier_text.toLowerCase();
                    if (story.get('story_content', '').toLowerCase().indexOf(ct) != -1 ||
                        (story.get('original_text') && story.get('original_text').toLowerCase().indexOf(ct) != -1)) {
                        intelligence.text = classifier_score;
                    }
                }
            });

            // URL exact phrase classifiers
            _.each(this.classifiers[feed_id].urls, function (classifier_score, classifier_url) {
                if (classifier_score <= -2 || (intelligence.url > -2 && intelligence.url <= 0)) {
                    var permalink = story.get('story_permalink') || '';
                    if (permalink.toLowerCase().indexOf(classifier_url.toLowerCase()) != -1) {
                        intelligence.url = classifier_score;
                    }
                }
            });

            story.set('intelligence', intelligence, options);
        }, this));
    },

    // ===================
    // = Media Playback  =
    // ===================

});
