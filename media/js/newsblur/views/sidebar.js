NEWSBLUR.Views.Sidebar = Backbone.View.extend({

    el: '.NB-sidebar',

    events: {
        "click .NB-feeds-header-starred .NB-feedlist-collapse-icon": "collapse_starred_stories",
        "click .NB-feeds-header-starred": "open_starred_stories",
        "click .NB-feeds-header-read": "open_read_stories",
        "click .NB-feeds-header-river-infrequent": "open_river_infrequent_stories"
    },

    initialize: function () { },

    // ===========
    // = Actions =
    // ===========

    check_starred_collapsed: function (options) {
        options = options || {};
        var collapsed = _.contains(NEWSBLUR.Preferences.collapsed_folders, 'starred');

        if (collapsed) {
            this.show_collapsed_starred(options);
        }

        return collapsed;
    },

    show_collapsed_starred: function (options) {
        options = options || {};
        var $header = NEWSBLUR.reader.$s.$starred_header;
        var $folder = this.$('.NB-starred-folder');

        $header.addClass('NB-folder-collapsed');

        if (!options.skip_animation) {
            $header.addClass('NB-feedlist-folder-title-recently-collapsed');
            $header.one('mouseover', function () {
                $header.removeClass('NB-feedlist-folder-title-recently-collapsed');
            });
        } else {
            $folder.css({
                display: 'none',
                opacity: 0
            });
        }
    },

    // ==========
    // = Events =
    // ==========

    open_starred_stories: function () {
        return NEWSBLUR.reader.open_starred_stories();
    },

    open_read_stories: function () {
        return NEWSBLUR.reader.open_read_stories();
    },

    open_river_infrequent_stories: function () {
        return NEWSBLUR.reader.open_river_stories(null, null, { 'infrequent': NEWSBLUR.assets.preference('infrequent_stories_per_month') });
    },

    collapse_starred_stories: function (e, options) {
        e.stopPropagation();
        options = options || {};

        var $header = NEWSBLUR.reader.$s.$starred_header;
        var $folder = this.$('.NB-starred-folder');

        // Hiding / Collapsing
        if (options.force_collapse ||
            ($folder.length &&
                $folder.eq(0).is(':visible'))) {
            NEWSBLUR.assets.collapsed_folders('starred', true);
            $header.addClass('NB-folder-collapsed');
            $folder.animate({ 'opacity': 0 }, {
                'queue': false,
                'duration': options.force_collapse ? 0 : 200,
                'complete': _.bind(function () {
                    this.show_collapsed_starred();
                    $folder.slideUp({
                        'duration': 270,
                        'easing': 'easeOutQuart'
                    });
                }, this)
            });
        }
        // Showing / Expanding
        else if ($folder.length &&
            (!$folder.eq(0).is(':visible'))) {
            NEWSBLUR.assets.collapsed_folders('starred', false);
            $header.removeClass('NB-folder-collapsed');
            $folder.css({ 'opacity': 0 }).slideDown({
                'duration': 240,
                'easing': 'easeInOutCubic',
                'complete': function () {
                    $folder.animate({ 'opacity': 1 }, { 'queue': false, 'duration': 200 });
                }
            });
        }

        return false;
    },

});
