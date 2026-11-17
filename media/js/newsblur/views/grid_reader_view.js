// grid_reader_view.js: the in-page article overlay used by the Grid layout.
//
// A grid card opens its story here instead of swapping the whole reader into a
// single story view, so the grid stays behind the overlay and every quick
// action (save, train, manage) keeps working without leaving the card grid.
// The body is a regular StoryDetailView with overlay_reader + full_story, which
// renders the whole article and keeps the intelligence filter from hiding it.

NEWSBLUR.Views.GridReaderView = Backbone.View.extend({

    className: 'NB-grid-reader',

    events: {
        'click .NB-grid-reader-overlay': 'close',
        'click .NB-grid-reader-close': 'close',
        'click .NB-grid-reader-save': 'toggle_save',
        'click .NB-grid-reader-train': 'train_story',
        'click .NB-grid-reader-prev': 'open_previous',
        'click .NB-grid-reader-next': 'open_next'
    },

    template: _.template('\
        <div class="NB-grid-reader-overlay"></div>\
        <div class="NB-grid-reader-panel" role="document">\
            <div class="NB-grid-reader-header">\
                <div class="NB-grid-reader-source">\
                    <span class="NB-grid-reader-favicon"><%= favicon %></span>\
                    <span class="NB-grid-reader-feed-title"><%= feed_title %></span>\
                    <span class="NB-grid-reader-date"><%= date %></span>\
                </div>\
                <div class="NB-grid-reader-actions">\
                    <button type="button" class="NB-grid-reader-action NB-grid-reader-save" title="<%= save_label %>"><span class="NB-grid-reader-icon NB-grid-reader-icon-save"></span></button>\
                    <button type="button" class="NB-grid-reader-action NB-grid-reader-train" title="<%= train_label %>"><span class="NB-grid-reader-icon NB-grid-reader-icon-train"></span></button>\
                    <a class="NB-grid-reader-action NB-grid-reader-original" href="<%= permalink %>" target="_blank" rel="noopener noreferrer" title="<%= open_original_label %>"><span class="NB-grid-reader-icon NB-grid-reader-icon-original"></span></a>\
                    <button type="button" class="NB-grid-reader-action NB-grid-reader-close" title="<%= close_label %>"><span class="NB-grid-reader-icon NB-grid-reader-icon-close"></span></button>\
                </div>\
            </div>\
            <div class="NB-grid-reader-body"></div>\
        </div>\
        <button type="button" class="NB-grid-reader-nav NB-grid-reader-prev" title="<%= prev_label %>"><span class="NB-grid-reader-icon NB-grid-reader-icon-prev"></span></button>\
        <button type="button" class="NB-grid-reader-nav NB-grid-reader-next" title="<%= next_label %>"><span class="NB-grid-reader-icon NB-grid-reader-icon-next"></span></button>\
    '),

    initialize: function () {
        _.bindAll(this, 'on_keydown');
        this.story = null;
        this.origin_view = null;
        this.detail_view = null;
        this.$el.attr({ 'aria-hidden': 'true' });
    },

    // ==========
    // = Public =
    // ==========

    is_open: function () {
        return this.$el.hasClass('NB-grid-reader-open');
    },

    open: function (story, story_title_view) {
        if (!story) return false;
        this.teardown_detail();
        this.story = story;
        this.origin_view = story_title_view || null;
        this.$el.addClass('NB-grid-reader-open').attr('aria-hidden', 'false');
        $('body').addClass('NB-grid-reader-locked');
        this.render_chrome(story);
        this.render_story(story);
        this.listenTo(story, 'change:starred', this.update_save_state);
        this.update_save_state();
        this.mark_read(story);
        this.update_nav_state();
        $(document).on('keydown.NB-grid-reader', this.on_keydown);
        return true;
    },

    close: function (e) {
        if (e) e.preventDefault();
        var origin = this.origin_view;
        this.teardown_detail();
        this.$el.removeClass('NB-grid-reader-open').attr('aria-hidden', 'true').empty();
        $('body').removeClass('NB-grid-reader-locked');
        this.story = null;
        this.origin_view = null;
        // Return focus to the card that opened the overlay so keyboard users
        // keep their place in the grid.
        if (origin && origin.$el) origin.$el.find('.story_title').trigger('focus');
    },

    // ============
    // = Rendering =
    // ============

    render_chrome: function (story) {
        var feed = NEWSBLUR.assets.get_feed(story.get('story_feed_id'));
        this.$el.html(this.template({
            favicon: feed ? $.favicon_html(feed) : '',
            feed_title: _.escape(feed ? feed.get('feed_title') : ''),
            date: _.escape(story.formatted_short_date()),
            permalink: _.escape(story.get('story_permalink') || ''),
            open_original_label: _.escape(gettext('Open original')),
            save_label: _.escape(gettext('Save story')),
            train_label: _.escape(gettext('Train this story')),
            close_label: _.escape(gettext('Close')),
            prev_label: _.escape(gettext('Previous story')),
            next_label: _.escape(gettext('Next story'))
        }));
    },

    render_story: function (story) {
        var $body = this.$('.NB-grid-reader-body');
        if (!story.get('story_content')) {
            $body.html('<div class="NB-grid-reader-empty">' +
                _.escape(gettext('No article content')) + '</div>');
            return;
        }
        this.detail_view = new NEWSBLUR.Views.StoryDetailView({
            model: story,
            collection: story.collection,
            tagName: 'div',
            overlay_reader: true,
            full_story: true,
            inline_story_title: true,
            // The overlay header already shows the feed and carries save/train,
            // so keep the body clean.
            show_feed_title: false,
            hide_sideoptions: true
        });
        // Append before render so the view measures the real overlay width.
        $body.append(this.detail_view.el);
        this.detail_view.render();
        this.detail_view.$el.addClass('NB-grid-reader-story');
        // The overlay opens whatever card was clicked, which is not necessarily the
        // selected story, so translate it here instead of relying on the selection.
        if (NEWSBLUR.app.translation) {
            NEWSBLUR.app.translation.translate_story(this.detail_view.$el);
        }
        $body.scrollTop(0);
    },

    teardown_detail: function () {
        $(document).off('keydown.NB-grid-reader');
        if (this.story) this.stopListening(this.story);
        if (this.detail_view) {
            this.detail_view.destroy();
            this.detail_view = null;
        }
    },

    // ===========
    // = Actions =
    // ===========

    toggle_save: function (e) {
        e.preventDefault();
        if (!this.story) return;
        this.story.toggle_starred();
    },

    update_save_state: function () {
        var starred = !!(this.story && this.story.get('starred'));
        this.$('.NB-grid-reader-save').toggleClass('NB-grid-reader-save-on', starred);
    },

    train_story: function (e) {
        e.preventDefault();
        if (!this.story) return;
        var story = this.story;
        this.close();
        NEWSBLUR.reader.open_story_trainer(story.id, story.get('story_feed_id'));
    },

    mark_read: function (story) {
        var delay = NEWSBLUR.assets.preference('read_story_delay');
        if (delay == -1) return;
        // stories.mark_read only fires while the collection's active story is
        // this story, and a grid card is never selected, so point it here first.
        if (NEWSBLUR.assets.stories) NEWSBLUR.assets.stories.active_story = story;
        story.mark_read(delay == -2 ? { skip_delay: true } : undefined);
    },

    visible_story_views: function () {
        var views = (NEWSBLUR.app.story_titles && NEWSBLUR.app.story_titles.stories) || [];
        return _.filter(views, function (view) {
            return view && view.el && view.model && !$(view.el).hasClass('NB-hidden');
        });
    },

    update_nav_state: function () {
        var views = this.visible_story_views();
        var index = _.indexOf(views, this.origin_view);
        this.$('.NB-grid-reader-prev').prop('disabled', index <= 0);
        this.$('.NB-grid-reader-next').prop('disabled', index === -1 || index >= views.length - 1);
    },

    open_previous: function (e) {
        if (e) e.preventDefault();
        this.step(-1);
    },

    open_next: function (e) {
        if (e) e.preventDefault();
        this.step(1);
    },

    step: function (offset) {
        var views = this.visible_story_views();
        var index = _.indexOf(views, this.origin_view);
        if (index === -1) return;
        var target = views[index + offset];
        if (!target) return;
        this.open(target.model, target);
    },

    on_keydown: function (e) {
        if (e.key === 'Escape' || e.key === 'Esc') {
            e.preventDefault();
            this.close();
            return;
        }
        if ($(e.target).is('input, textarea, select, [contenteditable="true"]')) return;
        if (e.key === 'ArrowLeft' || e.key === 'k') {
            e.preventDefault();
            this.step(-1);
        } else if (e.key === 'ArrowRight' || e.key === 'j') {
            e.preventDefault();
            this.step(1);
        }
    }

});
