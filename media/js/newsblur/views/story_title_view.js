NEWSBLUR.Views.StoryTitleView = Backbone.View.extend({

    className: 'NB-story-title-container',

    events: {
        "dblclick .NB-story-title": "open_story_in_story_view",
        "click .NB-story-title": "click_card",
        "contextmenu .NB-story-title": "show_manage_menu_rightclick",
        "click .NB-story-manage-icon": "show_manage_menu",
        "click .NB-storytitles-sentiment": "show_manage_menu",
        "click .NB-grid-card-save": "click_save",
        "click .NB-grid-card-train": "click_train",
        "click .NB-grid-card-more": "click_more",
        "mouseenter .NB-story-title": "mouseenter_manage_icon",
        "mouseleave .NB-story-title": "mouseleave_manage_icon"
    },

    initialize: function () {
        this.model.bind('change', this.toggle_classes, this);
        this.model.bind('change:read_status', this.toggle_read_status, this);
        this.model.bind('change:selected', this.switch_story_view, this);
        this.model.bind('change:selected', this.toggle_selected, this);
        this.model.bind('change:starred', this.toggle_starred, this);
        this.model.bind('change:intelligence', this.toggle_intelligence, this);
        this.collection.bind('render:intelligence', this.render_intelligence, this);
        this.model.story_title_view = this;

        // Listen for feed title changes to update grid/list/magazine views in real time
        this.story_feed = NEWSBLUR.assets.get_feed(this.model.get('story_feed_id'));
        if (this.story_feed) {
            this.listenTo(this.story_feed, 'change:feed_title', this.update_feed_title);
        }
    },

    update_feed_title: function () {
        if (this.story_feed) {
            this.$('.feed_title').text(this.story_feed.get('feed_title'));
        }
    },

    render: function () {
        var template_name = 'template';
        var story_layout = this.options.override_layout || NEWSBLUR.assets.view_setting(NEWSBLUR.reader.active_feed, 'layout');
        var pane_anchor = this.options.pane_anchor || (this.options.override_layout ? "west" : NEWSBLUR.assets.preference('story_pane_anchor'));

        if (this.options.is_list) template_name = "list_template";
        if (story_layout == 'split' && _.contains(['north', 'south'], pane_anchor)) template_name = "list_template";;
        if (this.options.is_grid) template_name = "grid_template";
        if (this.options.is_magazine) template_name = "magazine_template";
        if (this.options.is_list || this.options.is_grid || this.options.is_magazine) {
            if (this.model.get('selected')) template_name = "list_template";
        }

        // console.log(['render story title', template_name, this.$el[0], this.options.is_grid, this.show_image_preview(), this.options.override_layout, NEWSBLUR.assets.get_feed(this.model.get('story_feed_id'))]);
        this.$el.html(this[template_name]({
            story: this.model,
            feed: (this.options.override_layout == 'split' ||
                NEWSBLUR.reader.flags.river_view) &&
                NEWSBLUR.assets.get_feed(this.model.get('story_feed_id')),
            // grid_template always shows its source row, even outside a river.
            card_feed: NEWSBLUR.assets.get_feed(this.model.get('story_feed_id')),
            options: this.options,
            show_content_preview: this.show_content_preview(template_name),
            content_preview_class: this.get_content_preview_class(),
            show_image_preview: this.show_image_preview(),
            // story_title_view.js: a story without a picture gets no cover slot at all.
            has_card_image: this.has_card_image(),
            show_inline_author: story_layout == "list",
            pane_anchor: this.options.pane_anchor || (this.options.override_layout ? "west" : NEWSBLUR.assets.preference('story_pane_anchor'))
        }));
        this.$st = this.$(".NB-story-title");
        this.toggle_classes();
        this.toggle_read_status();
        this.color_feedbar();
        this.color_feed_name();
        this.load_youtube_embeds();
        this.apply_classifier_filter_highlight();
        this.apply_search_highlight();
        if (this.options.is_grid) this.bind_grid_card_image();
        if (_.contains(['list', 'magazine'], story_layout) && this.show_image_preview()) this.watch_grid_image();
        if (_.contains(['split'], story_layout) && this.show_image_preview() && NEWSBLUR.assets.preference('feed_view_single_story')) this.watch_grid_image();

        return this;
    },

    bind_grid_card_image: function () {
        var $image = this.$('.NB-grid-card-image');
        var $media = this.$('.NB-grid-card-media');
        var self = this;

        // Only a card whose picture died after rendering reaches this tint: cards
        // without a picture never get a cover slot in the first place.
        var tint = function () {
            var feed = NEWSBLUR.assets.get_feed(self.model.get('story_feed_id'));
            var color = feed && (feed.get('favicon_color') || feed.get('favicon_fade'));
            if (color && $media.length) {
                $media[0].style.setProperty('--nb-card-media-tint', '#' + color);
            }
        };

        if (!$image.length) return;

        // image_fallback.js already retried the URL through /imageproxy. When that
        // failed too, keep the cover slot and swap in the placeholder so the card
        // does not reflow under the reader's cursor.
        $image.on('nb-image-failed', function () {
            $(this).remove();
            if (!$media.find('.NB-grid-card-placeholder').length) {
                $media.prepend('<div class="NB-grid-card-placeholder"><span class="NB-grid-card-placeholder-mark"></span></div>');
            }
            tint();
        });
        if ($image[0].complete && $image[0].naturalWidth === 0) $image.trigger('nb-image-failed');
    },

    // A search result shows why it matched: every typed word is marked in the
    // headline, the author and the preview, using the same mark plugin the
    // classifier filter already relies on.
    apply_search_highlight: function () {
        var reader = NEWSBLUR.reader;
        if (!reader || !reader.flags.searching || !reader.flags.search) return;

        var $targets = this.$('.NB-storytitles-title, .NB-storytitles-content-preview, .NB-storytitles-author');
        if (!$targets.length) return;

        _.each(String(reader.flags.search).split(/\s+/), function (term) {
            if (term.length < 2) return;
            $targets.mark(term, {
                className: 'NB-search-highlight',
                separateWordSearch: false,
                acrossElements: true,
                caseSensitive: false
            });
        });
    },

    apply_classifier_filter_highlight: function () {
        var filter = NEWSBLUR.reader.flags['classifier_filter'];
        if (!filter || !filter.value || !NEWSBLUR.classifier_filter_utils) return;

        var selector = NEWSBLUR.classifier_filter_utils.story_title_highlight_selector(filter.type);
        if (selector) {
            this.$(selector).mark(filter.value, {
                className: 'NB-classifier-filter-highlight',
                separateWordSearch: false,
                acrossElements: true,
                caseSensitive: false
            });
        }

        if (filter.type !== 'url') return;
        var permalink = this.model.get('story_permalink') || '';
        var match_index = permalink.toLowerCase().indexOf(String(filter.value).toLowerCase());
        if (match_index === -1) return;

        var before = permalink.slice(0, match_index);
        var match = permalink.slice(match_index, match_index + String(filter.value).length);
        var after = permalink.slice(match_index + String(filter.value).length);
        var $url_match = $.make('div', { className: 'NB-storytitles-classifier-url' }, [
            $.make('span', { className: 'NB-storytitles-classifier-url-label' }, gettext('URL')),
            $.make('span', before),
            $.make('mark', { className: 'NB-classifier-filter-highlight' }, match),
            $.make('span', after)
        ]);
        this.$('.story_title').first().append($url_match);
    },

    // story_title_view.js: dir="auto" isolates feed titles, story titles, authors, previews and
    // dates, so mixed scripts keep their punctuation and truncate at the end of their own text
    // in both LTR and RTL interfaces (see media/css/reader/reader_rtl.css).
    template: _.template('\
        <div class="NB-story-title NB-story-title-split <% if (!show_content_preview) { %>NB-story-title-hide-preview<% } %> <% if (show_image_preview) { %>NB-has-image<% } %> ">\
            <div class="NB-storytitles-feed-border-inner"></div>\
            <div class="NB-storytitles-feed-border-outer"></div>\
            <a href="<%= story.get("story_permalink") %>" class="story_title NB-hidden-fade">\
                <div class="NB-storytitles-sentiment" role="button"></div>\
                <div class="NB-story-manage-icon" role="button"></div>\
                <% if (show_image_preview && story.image_url()) { %>\
                    <div class="NB-storytitles-story-image-container">\
                        <div class="NB-storytitles-story-image" <% if (story.image_url()) { %>style="background-image: none, url(\'<%= story.image_url() %>\');"<% } %>></div>\
                    </div>\
                <% } %>\
                <% if (feed) { %>\
                    <div class="NB-story-feed">\
                        <%= $.favicon_html(feed) %>\
                        <span class="feed_title" dir="auto"><%= feed.get("feed_title") %></span>\
                    </div>\
                <% } %>\
                <div class="NB-storytitles-star"></div>\
                <span class="NB-storytitles-title" dir="auto"><%= story.get("story_title") %></span>\
                <% if (pane_anchor != "west") { %>\
                    <% if (story.story_authors()) { %><span class="NB-middot">&middot;</span><% } %>\
                    <span class="NB-storytitles-author" dir="auto"><%= story.story_authors() %></span>\
                <% } %>\
                <% if (show_content_preview) { %>\
                    <div class="NB-storytitles-content-preview <%= content_preview_class %>" dir="auto"><%= show_content_preview %></div>\
                <% } %>\
                <div class="NB-story-title-split-bottom">\
                    <span class="story_date NB-hidden-fade" dir="auto"><%= story.formatted_short_date() %></span>\
                    <% if (pane_anchor == "west") { %>\
                        <% if (story.story_authors()) { %><span class="NB-middot">&middot;</span><% } %>\
                        <span class="NB-storytitles-author" dir="auto"><%= story.story_authors() %></span>\
                    <% } %>\
                </div>\
            </a>\
        </div>\
        <div class="NB-story-detail"></div>\
    '),

    list_template: _.template('\
        <div class="NB-story-title NB-story-title-list <% if (!show_content_preview) { %>NB-story-title-hide-preview<% } %> <% if (show_image_preview) { %>NB-has-image<% } %> ">\
            <div class="NB-storytitles-feed-border-inner"></div>\
            <div class="NB-storytitles-feed-border-outer"></div>\
            <a href="<%= story.get("story_permalink") %>" class="story_title NB-hidden-fade">\
                <div class="NB-storytitles-sentiment" role="button"></div>\
                <div class="NB-story-manage-icon" role="button"></div>\
                <% if (show_image_preview && story.image_url()) { %>\
                    <div class="NB-storytitles-story-image-container">\
                        <div class="NB-storytitles-story-image" <% if (story.image_url()) { %>style="background-image: none, url(\'<%= story.image_url() %>\');"<% } %>></div>\
                    </div>\
                <% } %>\
                <% if (feed) { %>\
                    <div class="NB-story-feed">\
                        <%= $.favicon_html(feed) %>\
                        <span class="feed_title" dir="auto"><%= feed.get("feed_title") %></span>\
                        <span class="NB-middot">&middot;</span>\
                        <span class="story_date NB-hidden-fade" dir="auto"><%= story.formatted_short_date() %></span>\
                    </div>\
                <% } %>\
                <div class="NB-storytitles-star"></div>\
                <span class="NB-storytitles-title" dir="auto"><%= story.get("story_title") %></span>\
                <% if (story.story_authors()) { %><span class="NB-middot">&middot;</span><% } %>\
                <span class="NB-storytitles-author" dir="auto"><%= story.story_authors() %></span>\
                <% if (show_content_preview) { %>\
                    <div class="NB-storytitles-content-preview <%= content_preview_class %>" dir="auto"><%= show_content_preview %></div>\
                <% } %>\
            </a>\
            <div class="NB-story-title-list-bottom">\
                <% if (!feed) { %>\
                    <span class="story_date NB-hidden-fade" dir="auto"><%= story.formatted_short_date() %></span>\
                <% } %>\
            </div>\
        </div>\
        <div class="NB-story-detail"></div>\
    '),

    // story_title_view.js: the grid card is a self-contained card: optional cover
    // image, source row, title, optional preview and a footer with the relative age.
    // The whole card is one link; the buttons in the corner are the only in-card
    // actions (grid_reader_view.js handles the click-to-read overlay). Stories with
    // no picture in their content get no cover slot at all, so the card is sized by
    // its text instead of a forced empty frame.
    grid_template: _.template('\
        <div class="NB-story-title NB-story-title-grid NB-grid-card<% if (!show_content_preview) { %> NB-story-title-hide-preview<% } %><% if (has_card_image) { %> NB-grid-card-has-media<% } else { %> NB-grid-card-no-media<% } %>">\
            <div class="NB-storytitles-feed-border-inner"></div>\
            <div class="NB-storytitles-feed-border-outer"></div>\
            <% if (has_card_image) { %>\
                <div class="NB-grid-card-media">\
                    <img class="NB-grid-card-image" src="<%= story.image_url() %>" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer">\
                </div>\
            <% } %>\
            <span class="NB-grid-card-unread"></span>\
            <div class="NB-grid-card-actions">\
                <button type="button" class="NB-grid-card-action NB-grid-card-save" title="<%= gettext("Save story") %>"><span class="NB-grid-card-icon NB-grid-card-icon-save"></span></button>\
                <button type="button" class="NB-grid-card-action NB-grid-card-train" title="<%= gettext("Train this story") %>"><span class="NB-grid-card-icon NB-grid-card-icon-train"></span></button>\
                <button type="button" class="NB-grid-card-action NB-grid-card-more" title="<%= gettext("More actions") %>"><span class="NB-grid-card-icon NB-grid-card-icon-more"></span></button>\
            </div>\
            <div class="NB-grid-card-body">\
                <% if (card_feed) { %>\
                    <div class="NB-story-feed">\
                        <%= $.favicon_html(card_feed) %>\
                        <span class="feed_title" dir="auto"><%= card_feed.get("feed_title") %></span>\
                    </div>\
                <% } %>\
                <a href="<%= story.get("story_permalink") %>" class="story_title NB-hidden-fade">\
                    <div class="NB-storytitles-star"></div>\
                    <div class="NB-storytitles-sentiment"></div>\
                    <div class="NB-story-manage-icon" role="button"></div>\
                    <span class="NB-storytitles-title" dir="auto"><%= story.get("story_title") %></span>\
                    <% if (show_content_preview) { %>\
                        <div class="NB-storytitles-content-preview <%= content_preview_class %>" dir="auto"><%= show_content_preview %></div>\
                    <% } %>\
                </a>\
            </div>\
            <div class="NB-storytitles-grid-bottom NB-grid-card-footer">\
                <span class="story_date NB-hidden-fade" dir="auto"><%= story.formatted_relative_date() %></span>\
                <% if (story.story_authors()) { %><span class="NB-middot">&middot;</span><span class="NB-storytitles-author" dir="auto"><%= story.story_authors() %></span><% } %>\
            </div>\
        </div>\
        <div class="NB-story-detail"></div>\
    '),

    magazine_template: _.template('\
        <div class="NB-story-title NB-story-title-magazine <% if (!show_content_preview) { %>NB-story-title-hide-preview<% } %>">\
            <div class="NB-storytitles-feed-border-inner"></div>\
            <div class="NB-storytitles-feed-border-outer"></div>\
            <% if (story.image_url()) { %>\
                <div class="NB-storytitles-story-image-container">\
                    <div class="NB-storytitles-story-image" <% if (story.image_url()) { %>style="background-image: none, url(\'<%= story.image_url() %>\');"<% } %>></div>\
                </div>\
            <% } %>\
            <div class="NB-storytitles-content">\
                <% if (feed) { %>\
                    <div class="NB-story-feed">\
                        <%= $.favicon_html(feed) %>\
                        <span class="feed_title" dir="auto"><%= feed.get("feed_title") %></span>\
                    </div>\
                <% } %>\
\
                <a href="<%= story.get("story_permalink") %>" class="story_title NB-hidden-fade">\
                    <div class="NB-storytitles-star"></div>\
                    <div class="NB-storytitles-sentiment"></div>\
                    <div class="NB-story-manage-icon" role="button"></div>\
                    <span class="NB-storytitles-title" dir="auto"><%= story.get("story_title") %></span>\
                    <% if (show_content_preview) { %>\
                        <div class="NB-storytitles-content-preview <%= content_preview_class %>" dir="auto"><%= show_content_preview %></div>\
                    <% } %>\
                </a>\
            </div>\
            <div class="NB-storytitles-magazine-bottom">\
                <span class="story_date NB-hidden-fade" dir="auto"><%= story.formatted_short_date() %></span>\
                <% if (story.story_authors()) { %><span class="NB-middot">&middot;</span><% } %>\
                <span class="NB-storytitles-author" dir="auto"><%= story.story_authors() %></span>\
            </div>\
        </div>\
        <div class="NB-story-detail"></div>\
    '),

    render_inline_story_detail: function (temporary_text) {
        // console.log(['render_inline_story_detail', this.model.get('story_title')]);
        if (NEWSBLUR.reader.story_view == 'text' || temporary_text) {
            this.text_view = new NEWSBLUR.Views.TextTabView({
                el: null,
                inline_story_title: true,
                temporary: !!temporary_text
            });
            this.text_view.fetch_and_render(this.model, temporary_text);
            this.$(".NB-story-detail").html(this.text_view.$el);
            this.text_view.story_detail.attach_handlers();
            this.text_view.setElement(this.text_view.$el);
            this.text_view.story_detail.setElement(this.text_view.story_detail.$el);
        } else {
            this.story_detail = new NEWSBLUR.Views.StoryDetailView({
                model: this.model,
                collection: this.model.collection,
                tagName: 'div',
                inline_story_title: true
            }).render();
            this.$(".NB-story-detail").html(this.story_detail.$el);
            this.story_detail.attach_handlers();
            this.story_detail.setElement(this.story_detail.$el);
        }
    },

    render_magazine_story_detail: function () {
        this.render_inline_story_detail();
    },

    destroy: function () {
        // console.log(["destroy story title", this.model.get('story_title')]);
        if (this.text_view) {
            this.text_view.destroy();
        }
        if (this.story_detail) {
            this.story_detail.destroy();
        }
        this.model.unbind(null, null, this);
        this.collection.unbind(null, null, this);
        this.remove();
    },

    destroy_inline_story_detail: function () {
        if (this.story_detail) {
            this.story_detail.destroy();
        }
        if (this.text_view) {
            this.text_view.destroy();
        }
        // this.$(".NB-story-detail").empty();
    },

    collapse_story: function () {
        this.model.set('selected', false);
        NEWSBLUR.app.story_titles.fill_out();
    },

    render_intelligence: function (options) {
        options = options || {};
        var score = this.model.score();
        var unread_view = NEWSBLUR.reader.get_unread_view_score();
        // console.log(['render_intelligence', score, unread_view, this.model.get('visible'), this.model.get('story_title')]);

        if (score >= unread_view) {
            this.$el.removeClass('NB-hidden');
            this.$st.removeClass('NB-hidden');
            this.model.set('visible', true);
        } else {
            this.$el.addClass('NB-hidden');
            this.$st.addClass('NB-hidden');
            this.model.set('visible', false);
        }
    },

    show_content_preview: function (template_name) {
        var preference = NEWSBLUR.assets.preference('show_content_preview');
        if (!preference || preference === 'title') return false;

        // For add site view, return full content - CSS will handle line clamping
        if (this.options.in_add_site_view) {
            var full_content = this.model.content_preview('story_content', 2000) || " ";
            var pruned_title = this.model.content_preview('story_title');
            var add_site_content = this.strip_repeated_title(full_content, pruned_title);
            if (add_site_content === false) return false;
            if (add_site_content.length < 30) return false;
            return add_site_content;
        }

        var max_length = preference == 'small' ? 300 : preference == 'medium' ? 600 : 1000;

        if (_.contains(['grid_template', 'magazine_template'], template_name)) {
            max_length = preference == 'small' ? 500 : preference == 'medium' ? 1000 : 1500;
            // A card without a cover has the whole body for text, so give it more
            // of the story instead of leaving a hole above the footer.
            if (template_name == 'grid_template' && !this.has_card_image()) max_length = 2000;
            var preserve_paragraphs = true;
            return this.model.content_preview('story_content', max_length, preserve_paragraphs) || " ";
        }
        var pruned_description = this.model.content_preview('story_content', max_length) || " ";
        var pruned_title = this.model.content_preview('story_title');
        var deduped = this.strip_repeated_title(pruned_description, pruned_title);

        if (deduped === false) return false;
        if (deduped.length < 30) return false;

        return deduped;
    },

    // Telegram channels and newsletter mirrors open the body with the headline,
    // so the preview repeated the sentence the reader had just read. The old
    // check compared the first 30 characters of each string, which missed
    // titles shorter than that and bodies that spell the title with different
    // spacing, such as "Datura OS ( @OldA )" against "Datura OS (@OldA)".
    // story_title_view.js: strip the repeated headline and keep what the body
    // actually adds. Returns the description unchanged, false when nothing is
    // left worth showing, or the remainder.
    strip_repeated_title: function (description, title) {
        var body = (description || '').replace(/\s+/g, ' ').trim();
        var headline = (title || '').replace(/\s+/g, ' ').trim();
        if (!body || !headline) return description;

        // Walk both strings, ignoring whitespace, so the parenthesis and
        // spacing drift between the title and the body does not end the match.
        var body_index = 0;
        var title_index = 0;
        var matched = 0;
        while (body_index < body.length && title_index < headline.length) {
            var body_char = body.charAt(body_index);
            var title_char = headline.charAt(title_index);
            if (/\s/.test(body_char)) { body_index++; continue; }
            if (/\s/.test(title_char)) { title_index++; continue; }
            if (body_char !== title_char) break;
            body_index++;
            title_index++;
            matched++;
        }

        var compact_title_length = headline.replace(/\s+/g, '').length;
        var is_repeated = matched >= 20 || (compact_title_length && matched >= compact_title_length * 0.8);
        if (!is_repeated) return description;

        var remainder = body.substr(body_index).replace(/^[\s\-\u2013\u2014|\u00b7:：,，。.、]+/, '').trim();
        if (remainder.length < 30) return false;

        return remainder;
    },

    get_content_preview_class: function () {
        if (!this.options.in_add_site_view) return '';
        var preference = NEWSBLUR.assets.preference('show_content_preview') || 'medium';
        return 'NB-content-preview-' + preference;
    },

    has_card_image: function () {
        return !!(this.show_image_preview() && this.model.image_url());
    },

    show_image_preview: function () {
        var show_image_preview = NEWSBLUR.assets.preference('image_preview');
        if (!show_image_preview || show_image_preview == "none") {
            return false;
        }

        // Always show image preview in add site view if preference is set
        if (this.options.in_add_site_view) {
            return !!this.model.image_url();
        }

        var story_layout = this.options.override_layout ||
            NEWSBLUR.assets.view_setting(NEWSBLUR.reader.active_feed, 'layout');
        var pane_anchor = this.options.override_layout ? "west" : NEWSBLUR.assets.preference('story_pane_anchor');
        if (_.contains(['list', 'grid', 'magazine'], story_layout)) return true;
        if (story_layout == 'split' && _.contains(['north', 'south'], pane_anchor)) return true;

        return !!this.model.image_url();
    },

    // ============
    // = Bindings =
    // ============

    color_feedbar: function () {
        var $inner = this.$st.find(".NB-storytitles-feed-border-inner");
        var $outer = this.$st.find(".NB-storytitles-feed-border-outer");
        var feed = NEWSBLUR.assets.get_feed(this.model.get('story_feed_id'));
        if (!feed) return;

        $inner.css('background-color', '#' + feed.get('favicon_fade'));
        $outer.css('background-color', '#' + feed.get('favicon_color'));
    },

    // story_title_view.js: hand the row its feed hue. modern.css turns that hue into a
    // colour for the caption, so a folder river shows at a glance which sources are in
    // the list, and the light and dark themes each keep the name readable.
    color_feed_name: function () {
        var feed = NEWSBLUR.assets.get_feed(this.model.get('story_feed_id'));
        if (!feed || !this.$st || !this.$st[0]) return;

        this.$st[0].style.setProperty('--nb-feed-hue', NEWSBLUR.utils.feed_hue(feed));
    },

    found_largest_image: function (image_url) {
        if (this.load_youtube_embeds()) {
            return;
        }

        this.$(".NB-storytitles-story-image").css({
            'background-image': "none, url(\'" + image_url + "\')",
            'display': 'block'
        });
    },

    watch_grid_image: function (index) {
        if (!index) index = 0;
        var self = this;
        if (!index && this.load_youtube_embeds()) {
            return;
        }
        if (!this.model.image_url(index)) {
            // console.log(["no more image urls", index, this.model.get('story_title').substr(0, 30)]);
            return;
        }
        // console.log(["watch_grid_image", index, this.model.image_url(index), this.model.get('story_title').substr(0, 30)]);
        // this.model == NEWSBLUR.assets.stories.at(5) && console.log(["Watching images", index, this.model.image_url(index), this.model.get('story_title').substr(0, 30)]);
        var $img = $("<img>").attr('referrerpolicy', 'no-referrer');
        // Publishers that guard hotlinks reject this probe as well, so a failed load
        // is retried through the image proxy before the picture is given up on.
        $img.on('error', function () {
            var src = $img.attr('src');
            if (!src || $img.attr('data-nb-image-proxy-tried')) return;
            if (!NEWSBLUR.image_should_proxy(src)) return;
            $img.attr('data-nb-image-proxy-tried', '1').attr('src', NEWSBLUR.image_proxy_url(src));
        });
        $img.imagesLoaded(function () {
            // console.log(["Loaded", index, $img[0].width, $img.attr('src'), self.model.get('story_title').substr(0, 30)]);
            if ($img[0].width > 60 && $img[0].height > 60) {
                self.$(".NB-storytitles-story-image").css({
                    'background-image': "none, url(\'" + $img.attr('src') + "\')",
                    'display': 'block'
                });
            } else {
                self.watch_grid_image(index + 1);
            }
        }).attr('src', this.model.image_url(index)).each(function () {
            // fail-safe for cached images which sometimes don't trigger "load" events
            if (this.complete) $(this).trigger('load');
        });
    },

    select_regex: function (query, url) {
        if (url == null) {
            return;
        }
        var results = query.exec(url);
        if (results && results.length) {
            return results[1];
        } else {
            return;
        }
    },

    load_youtube_embeds: function () {
        var text = this.model.get('story_content');
        var g = /youtube\.com\/embed\/([A-Za-z0-9\-_]+)/gi;
        var f = /youtube\.com\/v\/([A-Za-z0-9\-_]+)/gi;
        var e = /ytimg\.com\/vi\/([A-Za-z0-9\-_]+)/gi;
        var d = /youtube\.com\/watch\?v=([A-Za-z0-9\-_]+)/gi;
        var i = this.select_regex(g, text) ||
            this.select_regex(f, text) ||
            this.select_regex(e, text) ||
            this.select_regex(d, text);
        if (i) {
            // this.$(".NB-storytitles-story-image").css({
            //     'display': 'block',
            //     'background-image': "url("+NEWSBLUR.Globals.MEDIA_URL+"img/reader/youtube_play.png), url(" + "https://img.youtube.com/vi/" + i + "/0.jpg" + ")"
            // });
            return true;
        }
    },

    toggle_classes: function () {
        if (!this.$st) return;
        var changes = this.model.changedAttributes();

        if (changes && _.all(_.keys(changes), function (change) {
            return _.contains(['intelligence', 'read_status', 'selected'], change);
        })) return;

        var story = this.model;
        var unread_view = NEWSBLUR.reader.get_unread_view_score();

        this.$st.toggleClass('NB-story-starred', !!story.get('starred'));
        this.$st.toggleClass('NB-story-shared', !!story.get('shared'));
        this.toggle_intelligence();
        this.render_intelligence();

        if (NEWSBLUR.assets.preference('show_tooltips')) {
            this.$('.NB-story-sentiment').tipsy({
                delayIn: 375,
                gravity: 's'
            });
        }
    },

    toggle_intelligence: function () {
        var score = this.model.score();
        this.$st.removeClass('NB-story-negative NB-story-neutral NB-story-postiive')
            .addClass('NB-story-' + this.model.score_name(score));
    },

    toggle_read_status: function (model, read_status, options) {
        options = options || {};
        this.$st.toggleClass('read', !!this.model.get('read_status'));

        if (options.error_marking_unread) {
            var pane_alignment = NEWSBLUR.assets.preference('story_pane_anchor');
            var $star = this.$('.NB-storytitles-sentiment');
            $star.stop().css('opacity', null);
            $star.attr({ 'title': options.message || gettext('Failed to mark as unread') });
            $star.tipsy({
                gravity: pane_alignment == 'north' ? 'nw' : 'sw',
                fade: true,
                trigger: 'manual',
                offsetOpposite: -1
            });
            var tipsy = $star.data('tipsy');
            _.defer(function () {
                tipsy.enable();
                tipsy.show();
                _.delay(function () {
                    if (tipsy.enabled) {
                        tipsy.hide();
                        tipsy.disable();
                    }
                }, 1800);
            });
        }
    },

    toggle_selected: function (model, selected, options) {
        var story_layout = this.options.override_layout ||
            NEWSBLUR.assets.view_setting(NEWSBLUR.reader.active_feed, 'layout');
        if (this.options.is_grid) this.render();

        this.$st.toggleClass('NB-selected', !!this.model.get('selected'));
        this.$el.toggleClass('NB-selected', !!this.model.get('selected'));

        if (!!this.model.get('selected')) {
            if (_.contains(['list', 'grid'], story_layout)) {
                this.render_inline_story_detail();
            } else if (_.contains(['magazine'], story_layout)) {
                this.render_magazine_story_detail();
            } else {
                this.destroy_inline_story_detail();
            }
            // NEWSBLUR.app.story_titles.scroll_to_selected_story(this.model, options);
        } else {
            this.destroy_inline_story_detail();
            if (_.contains(['list', 'magazine'], story_layout)) {
                NEWSBLUR.app.story_titles.scroll_to_selected_story(this.model, {force: true, scroll_up_only: true});
            }
        }
    },

    toggle_starred: function () {
        var story_titles_visible = _.contains(['split', 'full'], this.options.override_layout ||
            NEWSBLUR.assets.view_setting(NEWSBLUR.reader.active_feed, 'layout'));
        var pane_alignment = NEWSBLUR.assets.preference('story_pane_anchor');
        var $star = this.$('.NB-storytitles-star');

        if (story_titles_visible) {
            NEWSBLUR.app.story_titles.scroll_to_selected_story(this.model);
        }

        if (this.model.get('starred')) {
            $star.attr({ 'title': gettext('Saved!') });
            $star.tipsy({
                gravity: pane_alignment == 'north' ? 'nw' : 'sw',
                fade: true,
                trigger: 'manual',
                offsetOpposite: -1
            });
            var tipsy = $star.data('tipsy');
            _.defer(function () {
                tipsy.enable();
                tipsy.show();
            });

            $star.animate({
                'opacity': 1
            }, {
                'duration': 850,
                'queue': false,
                'complete': function () {
                    if (tipsy.enabled) {
                        tipsy.hide();
                        tipsy.disable();
                    }
                }
            });
        } else {
            this.$st.one('mouseout', _.bind(function () {
                this.$st.removeClass('NB-unstarred');
            }, this));
            $star.attr({ 'title': gettext('Removed') });

            $star.tipsy({
                gravity: pane_alignment == 'north' ? 'nw' : 'sw',
                fade: true,
                trigger: 'manual',
                offsetOpposite: -1
            });
            var tipsy = $star.data('tipsy');
            tipsy.enable();
            tipsy.show();

            _.delay(function () {
                if (tipsy.enabled) {
                    tipsy.hide();
                    tipsy.disable();
                }
            }, 850);

        }
    },

    // ==========
    // = Events =
    // ==========

    // grid_reader_view.js: a grid card opens the in-page article overlay instead
    // of selecting the story, so quick actions never leave the grid. Cmd/Ctrl
    // and middle clicks keep the browser's own new-tab behaviour.
    click_card: function (e) {
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.which === 2) return;
        if ($(e.target).closest('.NB-grid-card-actions, .NB-story-manage-icon, .NB-storytitles-star, .NB-storytitles-sentiment').length) {
            return;
        }
        // The rendered card, not the view option, decides: a story that is
        // already selected renders as a list row inside a grid, and that row
        // must keep the old reading-pane behaviour.
        if (!$(e.target).closest('.NB-grid-card').length) return this.select_story(e);
        e.preventDefault();
        e.stopPropagation();
        // grid_reader_view.js: recreate the overlay if it is ever missing, so a
        // card click can never fall back to the reading pane.
        if (!NEWSBLUR.app.grid_reader) {
            NEWSBLUR.app.grid_reader = new NEWSBLUR.Views.GridReaderView();
            $('body').append(NEWSBLUR.app.grid_reader.el);
        }
        NEWSBLUR.app.grid_reader.open(this.model, this);
    },

    click_save: function (e) {
        e.preventDefault();
        e.stopPropagation();
        this.model.toggle_starred();
    },

    click_train: function (e) {
        e.preventDefault();
        e.stopPropagation();
        NEWSBLUR.reader.open_story_trainer(this.model.id, this.model.get('story_feed_id'));
    },

    click_more: function (e) {
        this.show_manage_menu(e);
    },

    select_story: function (e) {
        if (NEWSBLUR.hotkeys.shift) return;

        e.preventDefault();
        e.stopPropagation();
        if (e.which == 1 && $('.NB-menu-manage-container:visible').length) return;

        if (this.options.on_dashboard) {
            console.log(['clicked story on dashboard', this.model]);
            this.options.on_dashboard.open_story(this.model);
            return;
        } else if (this.options.on_discover_feed) {
            console.log(['clicked story in discover feed', this.model, this.options.on_discover_feed, this.options.in_popover]);
            var is_subscribed = this.options.on_discover_feed.feed && this.options.on_discover_feed.feed.is_subscribed();
            if (is_subscribed) {
                NEWSBLUR.reader.open_feed(this.model.get('story_feed_id'), {
                    'story_id': this.model.get('story_hash')
                });
            } else {
                NEWSBLUR.reader.load_feed_in_tryfeed_view(this.model.get('story_feed_id'), {
                    'feed': this.options.on_discover_feed.feed,
                    'select_story_in_feed': this.model.get('story_hash')
                });
            }
            if (this.options.in_popover && this.options.in_popover.close) {
                this.options.in_popover.close();
            }
        } else if (this.options.on_discover_story) {
            console.log(['clicked story in discover stories', this.model, this.options.on_discover_story, this.options.in_popover]);
            var is_subscribed = NEWSBLUR.assets.get_feed(this.model.get('story_feed_id'));
            if (is_subscribed) {
                if (NEWSBLUR.reader.active_feed == this.model.get('story_feed_id')) {
                    NEWSBLUR.reader.select_story_in_feed({
                        'story_id': this.model.get('story_hash'),
                        'story_title': this.model.get('story_title')
                    });
                } else {
                    NEWSBLUR.reader.open_feed(this.model.get('story_feed_id'), {
                        'story_id': this.model.get('story_hash'),
                        'story_title': this.model.get('story_title')
                    });
                }
            } else {
                NEWSBLUR.reader.load_feed_in_tryfeed_view(this.model.get('story_feed_id'), {
                    'feed': this.options.on_discover_story.feed,
                    'select_story_in_feed': this.model.get('story_hash'),
                    'story_title': this.model.get('story_title')
                });
            }
            if (this.options.in_popover && this.options.in_popover.close) {
                this.options.in_popover.close();
            }
        } else if (this.options.on_popular_feed) {
            var feed = this.options.on_popular_feed.get("feed");
            var is_subscribed = NEWSBLUR.assets.get_feed(this.model.get('story_feed_id'));
            if (is_subscribed) {
                NEWSBLUR.reader.open_feed(this.model.get('story_feed_id'), {
                    'story_id': this.model.get('story_hash'),
                    'story_title': this.model.get('story_title')
                });
            } else {
                NEWSBLUR.reader.load_feed_in_tryfeed_view(this.model.get('story_feed_id'), {
                    'feed': feed,
                    'select_story_in_feed': this.model.get('story_hash'),
                    'story_title': this.model.get('story_title')
                });
            }
            if (this.options.in_add_site_view) {
                $.modal.close();
            }
            return;
        }

        if (_.contains(['list', 'grid', 'magazine'], this.options.override_layout ||
            NEWSBLUR.assets.view_setting(NEWSBLUR.reader.active_feed, 'layout')) &&
            this.model.get('selected')) {
            this.collapse_story();
        } else {
            this.model.set('selected', true, { 'click_on_story_title': true });
        }

        if (NEWSBLUR.hotkeys.command) {
            this.model.open_story_in_new_tab(true);
        }
    },

    show_manage_menu_rightclick: function (e) {
        if (!NEWSBLUR.assets.preference('show_contextmenus')) return;

        return this.show_manage_menu(e);
    },

    show_manage_menu: function (e) {
        e.preventDefault();
        e.stopPropagation();
        if (this.options.on_dashboard || this.options.on_discover_feed || this.options.on_discover_story) {
            return this.select_story(e);
        }
        NEWSBLUR.reader.show_manage_menu('story', this.$st, {
            story_id: this.model.id,
            feed_id: this.model.get('story_feed_id'),
            rightclick: e.which >= 2
        });
        return false;
    },

    mouseenter_manage_icon: function () {
        var menu_height = 270;
        // console.log(["mouseenter_manage_icon", this.$el.offset().top, $(window).height(), menu_height]);
        if (this.$el.offset().top > $(window).height() - menu_height) {
            this.$st.addClass('NB-hover-inverse');
        }
    },

    mouseleave_manage_icon: function () {
        this.$st.removeClass('NB-hover-inverse');
    },

    open_story_in_story_view: function (e) {
        e.preventDefault();
        e.stopPropagation();
        if (this.options.on_dashboard || this.options.on_discover_feed || this.options.on_discover_story) {
            return this.select_story(e);
        }

        NEWSBLUR.app.story_tab_view.prepare_story(this.model, true);
        NEWSBLUR.app.story_tab_view.open_story(this.model);
        return false;
    },

    switch_story_view: function (story, selected, options) {
        // console.log(['switch_story_view title', story, selected, options]);
        if (selected && !options.selected_by_scrolling) {
            var story_view = NEWSBLUR.assets.view_setting(story.get('story_feed_id'), 'view');
            if (story_view != NEWSBLUR.reader.story_view) {
                console.log(['story title, switch story view', NEWSBLUR.reader.story_view]);
                NEWSBLUR.reader.set_correct_story_view_for_feed();
                NEWSBLUR.reader.switch_to_correct_view();
                NEWSBLUR.reader.switch_taskbar_view();
            }
        }
    }

});
