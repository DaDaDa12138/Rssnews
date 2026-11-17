// ==========================================
// = Saved searches (media/js/newsblur/views/saved_searches_view.js) =
// ==========================================

// A saved search is a named query from the toolbar. Running one reuses the
// toolbar search path, so the reader behaves exactly as if the reader had typed
// the query: flags.search feeds reset_feed and the story titles keep showing it.
NEWSBLUR.Views.SavedSearches = Backbone.View.extend({

    el: '#NB-saved-searches',

    events: {
        'click .NB-saved-searches-row': 'open_search',
        'click .NB-saved-searches-delete': 'delete_search',
        'click .NB-saved-searches-save': 'save_current_search'
    },

    initialize: function () {
        _.bindAll(this, 'load', 'render', 'open_search', 'delete_search',
                  'save_current_search', 'sync_save_button');

        this.searches = [];
        this.load();

        if (NEWSBLUR.reader) {
            this.listenTo(NEWSBLUR.reader, 'change:active_feed', this.sync_save_button);
        }
    },

    load: function () {
        $.get(NEWSBLUR.URLs['load-saved-searches'], _.bind(function (data) {
            this.searches = (data && data.searches) || [];
            this.render();
        }, this));
    },

    render: function () {
        var $list = this.$('.NB-saved-searches-list');
        var html = '';

        _.each(this.searches, function (search) {
            html += '<li class="NB-saved-searches-row" data-id="' + search.id + '">' +
                '<span class="NB-saved-searches-name" dir="auto">' + _.escape(search.name) + '</span>' +
                '<span class="NB-saved-searches-query" dir="auto">' + _.escape(search.query) + '</span>' +
                '<button type="button" class="NB-saved-searches-delete" data-id="' + search.id + '" ' +
                'title="' + _.escape(gettext('Delete')) + '" aria-label="' + _.escape(gettext('Delete')) + '">' +
                '&times;</button></li>';
        });

        $list.html(html);
        this.$el.toggleClass('NB-hidden', !this.searches.length);
        this.sync_save_button();
    },

    // The Save button only makes sense while a search is running; the query it
    // stores is whatever the toolbar put in flags.search.
    sync_save_button: function () {
        var flags = (NEWSBLUR.reader && NEWSBLUR.reader.flags) || {};
        var query = (flags.search || '').trim();

        this.$('.NB-saved-searches-save').toggleClass('NB-hidden', !query);
    },

    save_current_search: function (e) {
        e.preventDefault();
        e.stopPropagation();

        var flags = (NEWSBLUR.reader && NEWSBLUR.reader.flags) || {};
        var query = (flags.search || '').trim();
        var name;

        if (!query) return;

        name = window.prompt(gettext('Name this search'), query);

        if (!name) return;

        $.post(NEWSBLUR.URLs['save-saved-search'], { name: name, query: query }, _.bind(function (data) {
            if (data && data.code === 0) {
                this.load();
            } else if (data && data.message) {
                NEWSBLUR.utils.show_message(data.message);
            }
        }, this));
    },

    open_search: function (e) {
        var id = parseInt($(e.currentTarget).attr('data-id'), 10);
        var search = _.find(this.searches, function (item) { return item.id === id; });
        var feed;

        if (!search) return;
        if ($(e.target).is('.NB-saved-searches-delete')) return;

        feed = (NEWSBLUR.reader && NEWSBLUR.reader.active_feed) || 'river:everything';

        NEWSBLUR.reader.flags.searching = true;
        NEWSBLUR.reader.flags.search = search.query;
        NEWSBLUR.reader.open_feed(feed, { search: search.query });
        NEWSBLUR.app.toolbar.sync_search_state();
    },

    delete_search: function (e) {
        e.preventDefault();
        e.stopPropagation();

        var id = parseInt($(e.currentTarget).attr('data-id'), 10);

        $.post(NEWSBLUR.URLs['delete-saved-search'], { id: id }, _.bind(function () {
            this.searches = _.reject(this.searches, function (item) { return item.id === id; });
            this.render();
        }, this));
    }
});
