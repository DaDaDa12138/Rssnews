// translation_view.js: the reader-side half of one-click translation.
//
// Two surfaces are translated, on purpose:
//   * list rows get their headline and preview replaced in place (the original text is
//     kept in data-nb-original-text, so turning translation off restores it without a
//     single request);
//   * a story body gets a translated block under each paragraph, so the reader keeps the
//     source next to the translation instead of losing it.
//
// Translation is per feed and sticky: NEWSBLUR.translator remembers the feed id, so
// re-opening that feed keeps translating until the button is pressed again.

NEWSBLUR.Views.Translation = Backbone.View.extend({

    el: 'body',

    events: {
        'click .NB-toolbar-translate': 'toggle'
    },

    BLOCK_SELECTOR: 'p, li, h1, h2, h3, h4, h5, h6, blockquote, td, figcaption, dd, dt',
    MAX_BLOCKS: 40,

    initialize: function () {
        _.bindAll(this, 'handle_scroll', 'handle_feed_change', 'handle_selection',
            'handle_stories_reset', 'render_button_state', 'translate_visible_rows');

        NEWSBLUR.translator.initialize();
        this.$titles = NEWSBLUR.reader.$s.$story_titles;
        this.throttled_rows = _.throttle(this.translate_visible_rows, 250);

        this.listenTo(NEWSBLUR.reader, 'change:active_feed', this.handle_feed_change);
        this.listenTo(NEWSBLUR.assets.stories, 'reset add', this.handle_stories_reset);
        this.listenTo(NEWSBLUR.assets.stories, 'change:selected', this.handle_selection);
        this.$titles.on('scroll.nb-translate', this.throttled_rows);

        // On a cold load the feed is picked after this view is built, and the
        // change:active_feed event can fire before the listener above exists, so the
        // button state is also settled once the first story page has landed.
        this.render_button_state();
        _.defer(this.render_button_state);
    },

    is_active: function () {
        return NEWSBLUR.translator.is_enabled(NEWSBLUR.reader.active_feed);
    },

    // =========
    // = State =
    // =========

    toggle: function (e) {
        if (e) e.preventDefault();
        var feed_id = NEWSBLUR.reader.active_feed;
        if (!feed_id) return;

        if (NEWSBLUR.translator.is_enabled(feed_id)) {
            NEWSBLUR.translator.disable();
            this.restore_all();
        } else {
            NEWSBLUR.translator.enable(feed_id);
            this.translate_visible_rows({ limit: 20 });
            this.translate_selected_story();
        }
        this.render_button_state();
    },

    render_button_state: function () {
        var $button = this.$('.NB-toolbar-translate');
        if (!$button.length) return;

        var active = this.is_active();
        var feed_id = NEWSBLUR.reader.active_feed;
        var label = active ? gettext('Show original') : gettext('Translate');
        $button.toggleClass('NB-active', active)
            .attr('aria-pressed', active ? 'true' : 'false')
            // The label is hidden on narrow screens, so the accessible name has to
            // live on the button itself.
            .attr('aria-label', label)
            .toggleClass('NB-hidden', !feed_id);
        $button.find('.NB-toolbar-translate-label').text(label);
    },

    handle_stories_reset: function () {
        this.render_button_state();
        this.throttled_rows();
    },

    handle_feed_change: function () {
        this.render_button_state();
        if (!this.is_active()) {
            this.restore_all();
            return;
        }
        this.translate_visible_rows({ limit: 20 });
        this.translate_selected_story();
    },

    // ================
    // = Story titles =
    // ================

    handle_scroll: function () {
        this.translate_visible_rows();
    },

    translate_visible_rows: function (options) {
        if (!this.is_active()) return;
        var container = this.$titles && this.$titles[0];
        if (!container) return;

        options = options || {};
        var limit = options.limit || 60;
        var margin = 600;
        var rect = container.getBoundingClientRect();
        var self = this;
        var count = 0;

        this.$titles.find('.NB-story-title').each(function () {
            if (count >= limit) return false;
            var $row = $(this);
            if ($row.data('nb-translated') || $row.data('nb-translating')) return;
            var row_rect = this.getBoundingClientRect();
            if (row_rect.bottom < rect.top - margin || row_rect.top > rect.bottom + margin) return;
            count += 1;
            self.translate_row($row);
        });
    },

    translate_row: function ($row) {
        var self = this;
        var targets = [];
        var texts = [];

        _.each(['.NB-storytitles-title', '.NB-storytitles-content-preview'], function (selector) {
            var $el = $row.find(selector).first();
            if (!$el.length) return;
            var text = $.trim($el.text());
            if (!text) return;
            targets.push($el);
            texts.push(text);
        });
        if (!texts.length) return;

        $row.data('nb-translating', true);
        NEWSBLUR.translator.translate(texts).done(function (translations) {
            $row.removeData('nb-translating');
            $row.data('nb-translated', true);
            _.each(targets, function ($el, index) {
                self.replace_text($el, translations[index]);
            });
        });
    },

    // ==============
    // = Story body =
    // ==============

    handle_selection: function (story) {
        if (!story || !story.get('selected') || !this.is_active()) return;
        var view = story.story_view;
        if (!view || !view.$el) return;
        this.translate_story(view.$el);
    },

    translate_selected_story: function () {
        var story = NEWSBLUR.assets.stories.find(function (model) {
            return model.get('selected');
        });
        if (!story || !story.story_view) return;
        this.translate_story(story.story_view.$el);
    },

    translate_story: function ($story) {
        if (!this.is_active() || !$story || !$story.length) return;
        var self = this;

        var $title = $story.find('.NB-feed-story-title').first();
        if ($title.length && !$title.data('nb-translated')) {
            var title_text = $.trim($title.text());
            if (title_text) {
                $title.data('nb-translated', true);
                NEWSBLUR.translator.translate([title_text]).done(function (translations) {
                    self.replace_text($title, translations[0]);
                });
            }
        }

        var $content = $story.find('.NB-feed-story-content').first();
        if (!$content.length || $content.data('nb-translated')) return;

        var blocks = this.collect_blocks($content);
        if (!blocks.length) return;
        $content.data('nb-translated', true);

        var texts = _.map(blocks, function (block) {
            return $.trim($(block).text());
        });
        NEWSBLUR.translator.translate(texts).done(function (translations) {
            _.each(blocks, function (block, index) {
                var translation = translations[index];
                if (!translation) return;
                var $block = $(block);
                if ($.trim(translation) === $.trim($block.text())) return;
                $block.after($('<div class="NB-translation" dir="auto"></div>').text(translation));
            });
        });
    },

    // Only outermost blocks are translated, and never one that carries code, a figure or
    // a player: those read as media, and a translated caption underneath them is noise.
    collect_blocks: function ($content) {
        var selector = this.BLOCK_SELECTOR;
        var max_blocks = this.MAX_BLOCKS;
        var blocks = [];

        $content.find(selector).each(function () {
            var $block = $(this);
            if (blocks.length >= max_blocks) return false;
            // Only the outermost block is translated. parentsUntil stops at the story
            // body itself, because the story view is a <li> and would otherwise count
            // as a list-item ancestor of every paragraph.
            if ($block.parentsUntil($content).is(selector)) return;
            if ($block.closest('pre, code, figure').length) return;
            if ($block.find('pre, code, img, video, iframe').length) return;
            if ($.trim($block.text()).length < 12) return;
            blocks.push(this);
        });

        return blocks;
    },

    // ========
    // = Text =
    // ========

    replace_text: function ($el, translation) {
        if (!translation) return;
        if ($.trim(translation) === $.trim($el.text())) return;
        if (!$el.attr('data-nb-original-text')) {
            $el.attr('data-nb-original-text', $el.text());
        }
        $el.text(translation).addClass('NB-translated');
    },

    restore_all: function () {
        this.$('.NB-translation').remove();
        this.$('[data-nb-original-text]').each(function () {
            var $el = $(this);
            $el.text($el.attr('data-nb-original-text'));
            $el.removeAttr('data-nb-original-text').removeClass('NB-translated');
        });
        this.$('.NB-story-title, .NB-feed-story-content, .NB-feed-story-title')
            .removeData('nb-translated')
            .removeData('nb-translating');
    }
});
