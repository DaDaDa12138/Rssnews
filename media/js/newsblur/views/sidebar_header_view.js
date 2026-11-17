NEWSBLUR.Views.SidebarHeader = Backbone.View.extend({

    options: {
        el: '.left-north'
    },

    events: {
        'click .NB-feeds-header-collapse-sidebar': 'collapse_sidebar',
        'click .NB-feedlist-toggle-all-icon': 'toggle_all_folders',
        'mouseenter .NB-feeds-selector': 'update_toggle_all_folders_icon'
    },

    initialize: function () {
        _.bindAll(this, 'render', 'defer_render');
        this.feed_collection = this.options.feed_collection;

        this.feed_collection.bind('reset', this.defer_render);
        this.feed_collection.bind('add', this.defer_render);
        this.feed_collection.bind('remove', this.defer_render);
        this.feed_collection.bind('change:ps', this.defer_render);
        this.feed_collection.bind('change:nt', this.defer_render);
        this.feed_collection.bind('change:ng', this.defer_render);
    },

    defer_render: function () {
        _.defer(this.render);
    },

    render: function () {
        this.count();

        var hide_read_feeds = NEWSBLUR.assets.preference('hide_read_feeds');
        // NEWSBLUR.log(["render feed list header", this.feed_collection.length, this.feeds_count, hide_read_feeds]);
        // sidebar_header_view.js: the NB-empty test has to read the raw number. Passing
        // Inflector.commas() made "0" a truthy string, so the zero counts never hid.
        var $header = _.template('\
            <div class="NB-feeds-header-left">\
                <span class="NB-feeds-header-count NB-feeds-header-negative <% if (!negative_count_raw) { %>NB-empty<% } %>"><%= negative_count %></span>\
                <span class="NB-feeds-header-count NB-feeds-header-neutral <% if (!neutral_count_raw) { %>NB-empty<% } %>"><%= neutral_count %></span>\
                <span class="NB-feeds-header-count NB-feeds-header-positive <% if (!positive_count_raw) { %>NB-empty<% } %>"><%= positive_count %></span>\
            </div>\
        ')({
            positive_count: Inflector.commas(this.unread_counts['ps']),
            neutral_count: Inflector.commas(this.unread_counts['nt']),
            negative_count: Inflector.commas(this.unread_counts['ng']),
            positive_count_raw: this.unread_counts['ps'],
            neutral_count_raw: this.unread_counts['nt'],
            negative_count_raw: this.unread_counts['ng'],
            hide_read_feeds: !!hide_read_feeds
        });

        this.$('.NB-feeds-header-dashboard').html($header);
        // The filter row replaced the removed "All Site Stories" row, so it owns the
        // placeholder now. The msgid lives in the JavaScript catalog (djangojs.po).
        this.$('.NB-feeds-selector-input').attr('placeholder', gettext('Filter sites...'));

        this.toggle_hide_read_preference();
        // Keep the collapse-all arrow in step with the saved folder state without
        // waiting for the first hover on the filter row.
        this.update_toggle_all_folders_icon();
        NEWSBLUR.reader.toggle_focus_in_slider();

        return this;
    },

    toggle_hide_read_preference: function () {
        var hide_read_feeds = NEWSBLUR.assets.preference('hide_read_feeds');
        if (NEWSBLUR.reader.flags['feed_list_showing_starred']) hide_read_feeds = true;
        this.$('.NB-feeds-header-sites').toggleClass('NB-feedlist-hide-read-feeds', !!hide_read_feeds);
        $("body").toggleClass("NB-feedlist-hide-read-feeds", !!hide_read_feeds);
    },

    count: function () {
        this.unread_counts = NEWSBLUR.assets.folders.unread_counts();

        if (!NEWSBLUR.Globals.is_authenticated) return;
        if (!NEWSBLUR.assets.preference('title_counts')) return;

        var counts = [];
        var unread_view = _.isNumber(this.options.unread_view) && this.options.unread_view || NEWSBLUR.assets.preference('unread_view');
        if (unread_view <= -1) {
            counts.push(Inflector.commas(this.unread_counts['ng']));
        }
        if (unread_view <= 0) {
            counts.push(Inflector.commas(this.unread_counts['nt']));
        }
        if (unread_view <= 1) {
            counts.push(Inflector.commas(this.unread_counts['ps']));
        }
        if (!this.unread_counts['ps']) {
            counts = [Inflector.commas(this.unread_counts['nt'])];
        }
        var title = "NewsBlur";
        if (_.any(counts)) {
            title = '(' + counts.join('/') + ') ' + title;
        }
        document.title = title;
    },

    count_feeds: function () {
        return this.feed_collection.select(function (f) {
            return f.get('active');
        }).length;
    },

    // ==============
    // = Folder all =
    // ==============

    toggle_all_folders: function (e) {
        e.stopPropagation();
        var $feed_list = NEWSBLUR.reader.$s.$feed_list;
        var $toggle_icon = NEWSBLUR.reader.$s.$folders_toggle;
        // Skip the root folder - only get folders that have a named title
        var $folders = $feed_list.find('li.folder').filter(function () {
            var $title = $(this).children('.folder_title').find('.folder_title_text');
            return $title.length && $title.text().trim().length > 0;
        });
        var folder_names = NEWSBLUR.assets.folders.child_folder_names();

        // Determine current state: are all folders collapsed?
        var all_collapsed = folder_names.length > 0 && _.all(folder_names, function (name) {
            return _.contains(NEWSBLUR.Preferences.collapsed_folders, name);
        });

        if (all_collapsed) {
            // Expand all folders (only when everything is collapsed)
            NEWSBLUR.Preferences.collapsed_folders = _.difference(
                NEWSBLUR.Preferences.collapsed_folders,
                folder_names
            );

            NEWSBLUR.assets.make_request(NEWSBLUR.URLs['profile-set-collapsed-folders'], {
                'collapsed_folders': JSON.stringify(NEWSBLUR.Preferences.collapsed_folders)
            });

            $folders.each(function () {
                var $folder = $(this);
                var $children = $folder.children('ul.folder');

                if ($children.length && !$children.eq(0).is(':visible')) {
                    $folder.removeClass('NB-folder-collapsed');
                    $children.css({ 'opacity': 0 }).slideDown({
                        'duration': 240,
                        'easing': 'easeInOutCubic',
                        'complete': function () {
                            $children.animate({ 'opacity': 1 }, { 'queue': false, 'duration': 200 });
                        }
                    });
                }
            });

            $toggle_icon.removeClass('NB-all-folders-collapsed').attr('title', gettext('Collapse All Folders'));
        } else {
            // Collapse all folders (when any folder is expanded)
            _.each(folder_names, function (folder_name) {
                if (!_.contains(NEWSBLUR.Preferences.collapsed_folders, folder_name)) {
                    NEWSBLUR.Preferences.collapsed_folders.push(folder_name);
                }
            });

            NEWSBLUR.assets.make_request(NEWSBLUR.URLs['profile-set-collapsed-folders'], {
                'collapsed_folders': JSON.stringify(NEWSBLUR.Preferences.collapsed_folders)
            });

            $folders.each(function () {
                var $folder = $(this);
                var $children = $folder.children('ul.folder');

                if ($children.length && $children.eq(0).is(':visible')) {
                    $folder.addClass('NB-folder-collapsed');
                    $children.animate({ 'opacity': 0 }, {
                        'queue': false,
                        'duration': 200,
                        'complete': function () {
                            $children.slideUp({
                                'duration': 270,
                                'easing': 'easeOutQuart'
                            });
                        }
                    });
                }
            });

            $toggle_icon.addClass('NB-all-folders-collapsed').attr('title', gettext('Expand All Folders'));
        }

        return false;
    },

    update_toggle_all_folders_icon: function () {
        var $toggle_icon = NEWSBLUR.reader.$s.$folders_toggle;
        if (!$toggle_icon || !$toggle_icon.length) return;

        var folder_names = NEWSBLUR.assets.folders.child_folder_names();
        var all_collapsed = folder_names.length > 0 && _.all(folder_names, function (name) {
            return _.contains(NEWSBLUR.Preferences.collapsed_folders, name);
        });

        if (all_collapsed) {
            $toggle_icon.addClass('NB-all-folders-collapsed').attr('title', gettext('Expand All Folders'));
        } else {
            $toggle_icon.removeClass('NB-all-folders-collapsed').attr('title', gettext('Collapse All Folders'));
        }
    },

    // ==========
    // = Events =
    // ==========

    collapse_sidebar: function () {
        if (!NEWSBLUR.reader.flags['splash_page_frontmost']) {
            NEWSBLUR.reader.close_sidebar();
        }
    }

});
