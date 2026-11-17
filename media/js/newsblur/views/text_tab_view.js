NEWSBLUR.Views.TextTabView = Backbone.View.extend({

    initialize: function () {
        _.bindAll(this, 'render', 'error');

        if (this.collection) {
            this.collection.bind('change:selected', this.select_story, this);
        }
    },

    destroy: function () {
        this.remove();
    },

    // ===========
    // = Actions =
    // ===========

    fetch_and_render: function (story, is_temporary) {
        if (!story) story = NEWSBLUR.reader.active_story;
        if (!story && is_temporary) {
            NEWSBLUR.reader.show_next_story(1);
            story = NEWSBLUR.reader.active_story;
        }
        if (!story) return;

        if (is_temporary && _.contains(['split', 'full'], NEWSBLUR.assets.view_setting(NEWSBLUR.reader.active_feed, 'layout'))) {
            NEWSBLUR.reader.switch_taskbar_view('text', {
                skip_save_type: is_temporary ? 'text' : false
            });
        }

        if (this.story == story) return;

        this.story = story;
        this.story_detail = new NEWSBLUR.Views.StoryDetailView({
            model: this.story,
            collection: this.story.collection,
            show_feed_title: true,
            skip_content: true,
            text_view: true,
            tagName: 'div',
            inline_story_title: this.options.inline_story_title
        }).render();
        this.$el.html(this.story_detail.el);
        this.$el.scrollTop(0);
        this.story_detail.attach_handlers();
        this.show_loading();
        NEWSBLUR.assets.fetch_original_text(story.get('story_hash'), this.render, this.error);

        return this;
    },

    render: function (data) {
        if (!this.story) return;

        if (data && (data.story_id != this.story.get('id') ||
            data.feed_id != this.story.get('story_feed_id'))) {
            return;
        }

        this.hide_loading();
        var $content = this.$('.NB-feed-story-content');

        if (!this.story.get('original_text')) {
            this.error();
        } else {
            $content.html(this.story.original_text());
            this.story_detail.attach_handlers();
            this.resize_starred_tags();
        }
        $content.css('opacity', 0);
        $content.show();
        $content.animate({
            'opacity': 1
        }, {
            duration: 250,
            queue: false
        });
    },

    unload: function () {
        this.story = null;
        this.$el.empty();
    },

    show_loading: function () {
        NEWSBLUR.app.taskbar_info.hide_stories_error();
        NEWSBLUR.app.taskbar_info.show_stories_progress_bar(10, gettext("Fetching text"));
    },

    hide_loading: function () {
        NEWSBLUR.app.taskbar_info.hide_stories_progress_bar();
    },

    error: function () {
        this.hide_loading();
        NEWSBLUR.app.taskbar_info.show_stories_error({}, gettext("Sorry, the story\'s text<br />could not be extracted."));

        var $content = this.$('.NB-feed-story-content');
        $content.html(this.story.story_content());
        this.story_detail.attach_handlers();
    },

    show_explainer_single_story_mode: function () {
        var $empty = $.make("div", { className: "NB-story-list-empty" }, [
            $.make('div', { className: 'NB-world' }),
            gettext('Select a story to read')
        ]);

        this.$(".NB-story-list-empty").remove();
        this.$el.append($empty);
    },

    resize_starred_tags: function () {
        if (this.story.get('starred')) {
            this.story_detail.save_view.reset_height({ immediate: true });
        }
    },


    // ==========
    // = Events =
    // ==========

    select_story: function (story, selected) {
        if (!selected) return;

        // this.hide_loading(); // Not sure why this is here?

        if ((NEWSBLUR.reader.story_view == 'text' &&
            _.contains(['split', 'full'], NEWSBLUR.assets.view_setting(NEWSBLUR.reader.active_feed, 'layout')))) {
            if (NEWSBLUR.reader.flags['temporary_story_view']) {
                NEWSBLUR.reader.switch_to_correct_view();
            }
            this.fetch_and_render(story);
        }
    }

});
