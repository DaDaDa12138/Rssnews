NEWSBLUR.Views.StoryDetailView = Backbone.View.extend({

    tagName: 'li',

    className: 'NB-feed-story',

    FUDGE_CONTENT_HEIGHT_OVERAGE: 260,

    STORY_CONTENT_MAX_HEIGHT: 460, // ALSO CHANGE IN css/reader/core/04-story-content.css: .NB-story-content-wrapper-height-truncated

    events: {
        "click": "mark_read",
        // Bound before the anchor handler below so stopPropagation() keeps an
        // image inside <a class="lightbox"> from opening in a new window.
        "click .NB-feed-story-content img": "open_image_viewer",
        "click .NB-video-embed-play": "play_inline_video",
        "click .NB-story-tag-add": "add_story_tag",
        "click .NB-story-tag-remove": "remove_story_tag",
        "click .NB-story-mobile-back": "close_mobile_story",
        "click .NB-story-mobile-next": "next_unread_from_bar",
        "click .NB-feed-story-content a": "click_link_in_story",
        "click .NB-feed-story-title": "click_link_in_story",
        "mouseenter .NB-feed-story-manage-icon": "mouseenter_manage_icon",
        "mouseleave .NB-feed-story-manage-icon": "mouseleave_manage_icon",
        "mouseenter .NB-feed-story-train": "mouseenter_sideoption_train",
        "mouseleave .NB-feed-story-train": "mouseleave_sideoption_train",
        "contextmenu .NB-feed-story-header": "show_manage_menu_rightclick",
        "mouseup .NB-story-content-wrapper": "mouseup_check_selection",
        "click .NB-feed-story-manage-icon": "show_manage_menu",
        "click .NB-feed-story-show-changes": "show_story_changes",
        "click .NB-feed-story-header-feed .NB-feedlist-manage-icon": "show_feed_manage_menu",
        "contextmenu .NB-feed-story-header-feed": "show_feed_manage_menu_rightclick",
        "mouseenter .NB-feed-story-header-feed .NB-feedlist-manage-icon": "mouseenter_feed_manage_icon",
        "mouseleave .NB-feed-story-header-feed .NB-feedlist-manage-icon": "mouseleave_feed_manage_icon",
        "click .NB-feed-story-header-title": "open_feed",
        "click .NB-feed-story-tag": "save_classifier",
        "click .NB-feed-story-author": "save_classifier",
        "click .NB-feed-story-url": "save_url_classifier",
        "mousemove .NB-pill-view-classifier": "show_classifier_filter_tooltip",
        "mouseleave .NB-pill-view-classifier": "hide_classifier_filter_tooltip",
        "focus .NB-pill-view-classifier": "show_classifier_filter_tooltip",
        "blur .NB-pill-view-classifier": "hide_classifier_filter_tooltip",
        "click .NB-pill-view-classifier": "open_classifier_filter_from_pill",
        "click .NB-feed-story-ai-classifier": "open_trainer_from_ai_pill",
        "click .NB-feed-story-train": "open_story_trainer",
        "click .NB-feed-story-save": "toggle_starred",
        "click .NB-story-content-expander": "expand_story",
        "click .NB-highlight-selection": "highlight_selected_text",
        "click .NB-unhighlight-selection": "unhighlight_selected_text",
        "click .NB-train-selection": "train_selected_text",
        "click .NB-classifier-highlight-positive": "show_classifier_highlight_menu",
        "click .NB-classifier-highlight-negative": "show_classifier_highlight_menu",
        "click .NB-classifier-highlight-super-negative": "show_classifier_highlight_menu",
        "click .NB-search-highlight": "show_search_highlight_menu",
        "click .NB-search-site-selection": "search_selected_text_site",
        "click .NB-search-folder-selection": "search_selected_text_folder"
    },

    initialize: function () {
        _.bindAll(this, 'mouseleave', 'mouseenter', 'mouseup_check_selection', 'highlight_selected_text', 'unhighlight_selected_text', 'search_selected_text_site', 'search_selected_text_folder');
        // Round 4 perf: image load events land one per image (dozens per story).
        // Coalesce the sticky-sideoptions layout work into one pass instead of
        // recalculating the layout after every single image.
        this._sticky_state_timer = null;
        this._sticky_sideoptions_applied = false;
        this.model.bind('change', this.toggle_classes, this);
        this.model.bind('change:read_status', this.toggle_read_status, this);
        this.model.bind('change:selected', this.toggle_selected, this);
        this.model.bind('change:starred', this.render_starred, this);
        this.model.bind('change:intelligence', this.render_header, this);
        this.model.bind('change:intelligence', this.toggle_intelligence, this);
        this.model.bind('change:story_content', this.render_story_content, this);
        if (this.collection) {
            this.collection.bind('render:intelligence', this.render_intelligence, this);
        }

        // Listen for feed title changes to update story header in real time
        this.story_feed = NEWSBLUR.assets.get_feed(this.model.get('story_feed_id'));
        if (this.story_feed) {
            this.listenTo(this.story_feed, 'change:feed_title', this.update_feed_title);
        }

        // Binding directly instead of using event delegation. Need for speed.
        // this.$el.bind('mouseenter', this.mouseenter);
        // this.$el.bind('mouseleave', this.mouseleave);

        if (this.options.overlay_reader) {
            // grid_reader_view.js: the overlay keeps its own detail view and must
            // not replace the card's inline view or the latest-view pointers.
        } else if (!this.options.feed_floater &&
            !this.options.text_view &&
            !this.options.inline_story_title) {
            this.model.story_view = this;
        } else if (this.options.inline_story_title) {
            this.model.story_view = this;
            this.model.inline_story_detail_view = this;
        }
        if (!this.options.feed_floater && !this.options.overlay_reader) {
            this.model.latest_story_detail_view = this;
        }
    },

    // =============
    // = Rendering =
    // =============

    render: function () {
        var params = this.get_render_params();
        params['story_header'] = this.story_header_template(params);
        this.sideoptions_view = new NEWSBLUR.Views.StorySideoptionsView({
            model: this.model,
            el: this.el
        });
        this.sideoptions_view.story_view = this;
        this.save_view = this.sideoptions_view.save_view;
        params['story_save_view'] = this.sideoptions_view.save_view.render();
        // Round 4 perf: add loading="lazy" and decoding="async" to every story image
        // in the HTML string, so the browser never queues the whole article's images
        // at once and never decodes them on the main thread.
        var story_html = this.template(params).replace(
            /<img (?![^>]*\bloading=)/gi,
            '<img loading="lazy" decoding="async" '
        );
        this.$el.html(story_html);

        if (this.feed) {
            this.$el.toggleClass('NB-inverse', this.feed.is_light());
        }

        this.setup_classes();
        this.toggle_classes();
        this.toggle_read_status();
        this.toggle_intelligence();
        this.generate_gradients();
        this.attach_handlers();
        // if (!this.model.get('image_urls') || (this.model.get('image_urls') && this.model.get('image_urls').length == 0)) {
        // }

        return this;
    },

    render_starred_tags: function () {
        if (this.model.get('starred')) {
            this.save_view.toggle_feed_story_save_dialog();
        }
    },

    resize_starred_tags: function () {
        if (this.model.get('starred')) {
            this.save_view.reset_height({ immediate: true });
        }
    },

    attach_handlers: function () {
        this.lazy_load_story_images();
        this.attach_media_enhancements();
        this.watch_images_for_story_height();
        this.update_sideoptions_sticky_state();
        this.attach_syntax_highlighter_handler();
        this.attach_fitvid_handler();
        this.render_starred_tags();
        this.apply_starred_story_selections();
        this.watch_images_load();
        this.attach_custom_handler();
        this.render_story_tags();
        this.setup_swipe_back();

        // translation_view.js: only the story on screen is worth translating; in the
        // split and full layouts every story has a view but just one is selected.
        if (NEWSBLUR.app.translation && this.model.get('selected')) {
            NEWSBLUR.app.translation.translate_story(this.$el);
        }
    },

    // Story tags (apps/reader/models.py StoryTag): a per-reader label that the
    // search syntax can match with tag:name. The row lives in the header so it is
    // visible in every layout, including the grid overlay.
    render_story_tags: function () {
        var self = this;
        var hash = this.model.get('story_hash');
        var $header = this.$('.NB-feed-story-header-info').first();

        if (!hash || !$header.length) return;

        if (!$header.find('.NB-story-tags').length) {
            $header.append(
                '<div class="NB-story-tags">' +
                    '<span class="NB-story-tags-list"></span>' +
                    '<button type="button" class="NB-story-tag-add">' +
                        _.escape(gettext('Add tag')) + '</button>' +
                '</div>'
            );
        }

        $.get(NEWSBLUR.URLs['load-story-tags'], { story_hash: hash }, function (data) {
            var html = '';

            if (!data || data.code !== 0) return;

            _.each(data.tags || [], function (tag) {
                html += '<span class="NB-story-tag">' + _.escape(tag) +
                    '<button type="button" class="NB-story-tag-remove" data-tag="' +
                    _.escape(tag) + '" title="' + _.escape(gettext('Delete')) + '">&times;</button></span>';
            });

            self.$('.NB-story-tags-list').html(html);
        });
    },

    add_story_tag: function (e) {
        e.preventDefault();
        e.stopPropagation();

        var self = this;
        var hash = this.model.get('story_hash');
        var tag = window.prompt(gettext('Add tag'), '');

        if (!hash || !tag) return;

        $.post(NEWSBLUR.URLs['add-story-tag'], { story_hash: hash, tag: tag }, function () {
            self.render_story_tags();
        });
    },

    remove_story_tag: function (e) {
        e.preventDefault();
        e.stopPropagation();

        var self = this;
        var $button = $(e.currentTarget);

        $.post(NEWSBLUR.URLs['remove-story-tag'], {
            story_hash: this.model.get('story_hash'),
            tag: $button.attr('data-tag')
        }, function () {
            self.render_story_tags();
        });
    },

    attach_custom_handler: function () {
        // Use this to create your own story_content handler.
        // Add this to your Manage > Account > Custom CSS:
        // 
        // NEWSBLUR.Views.StoryDetailView.prototype.attach_custom_handler = () => { console.log(['Story selected', NEWSBLUR.reader.active_story.get('story_title'), NEWSBLUR.reader.active_story.get('story_content').length + " bytes"]); }
    },

    watch_images_load: function () {
        var pane_width;
        if (this.options.inline_story_title) {
            pane_width = this.$el.width();
        }
        if (!pane_width) {
            pane_width = NEWSBLUR.reader.$s.$story_pane.width()
        }
        if (!pane_width) {
            pane_width = NEWSBLUR.reader.$s.$story_titles.width();
        }
        pane_width = pane_width - (28 + 2); // 28px to compensate for both margins
        var has_tables = this.$("table").length;
        // The widen class pulls a large image 28px into each margin
        // (media/css/reader/core/04-story-content.css:456-461), so it only works
        // while the reading column leaves that much margin on each side. On a
        // phone the column is the pane, and the image ran off both screen edges.
        var column_width = this.$('.NB-feed-story-content').width() || pane_width;
        var auto_widen_images = pane_width < 900 && (pane_width - column_width) >= 60;

        this.$el.imagesLoaded(_.bind(function () {
            var largest = 0;
            var $largest;
            // console.log(["Images loaded", this.model.get('story_title').substr(0, 30), this.$("img")]);
            this.$("img:not([data-nb-media-poster])").each(function () {
                // console.log(["Largest?", this.width, this.naturalWidth, this.height, this.naturalHeight, largest, pane_width, this.src]);
                if (this.width > 60 && this.width > largest) {
                    largest = this.width;
                    $largest = $(this);
                }
                $(this)
                    .removeClass('NB-large-image')
                    .removeClass('NB-large-image-widen')
                    .removeClass('NB-medium-image')
                    .removeClass('NB-medium-image-widen')
                    .removeClass('NB-small-image')
                    .removeClass('NB-small-image-widen');
                var auto_widen = auto_widen_images;

                if (has_tables) {
                    // Can't even calculate widths because with tables, nothing fits
                    $(this).addClass('NB-table-image');
                }
                if (this.naturalWidth >= pane_width && this.naturalHeight >= 50) {
                    $(this).addClass('NB-large-image');
                    if (auto_widen) {
                        $(this).addClass('NB-large-image-widen');
                    }
                } else if (this.naturalWidth >= 100 && this.naturalHeight >= 50) {
                    $(this).addClass('NB-medium-image');
                    if (auto_widen) {
                        $(this).addClass('NB-medium-image-widen');
                    }
                } else {
                    $(this).addClass('NB-small-image');
                    if (auto_widen) {
                        $(this).addClass('NB-small-image-widen');
                    }
                }
            });
            if ($largest) {
                // console.log(["Largest!", $largest, this.model.get('story_title').substr(0, 30), this.model, $largest.attr('src')]);
                if (this.model.story_title_view) {
                    this.model.story_title_view.found_largest_image($largest.attr('src'));
                }
            }
        }, this));
    },

    render_header: function (model, value, options) {
        var params = this.get_render_params();
        this.$('.NB-feed-story-header-feed').remove();
        this.$('.NB-feed-story-header').replaceWith($(this.story_header_template(params)));
        this.generate_gradients();
    },

    update_feed_title: function () {
        if (this.story_feed) {
            this.$('.NB-feed-story-header-title').text(this.story_feed.get('feed_title'));
        }
    },

    get_render_params: function () {
        this.feed = NEWSBLUR.assets.get_feed(this.model.get('story_feed_id'));
        this.classifiers = NEWSBLUR.assets.classifiers[this.model.get('story_feed_id')];
        var show_feed_title = NEWSBLUR.reader.flags.river_view ||
            this.options.show_feed_title;
        return {
            story: this.model,
            feed: show_feed_title && this.feed,
            tag: _.first(this.model.get("story_tags")),
            title: this.make_story_title(),
            authors_score: this.classifiers &&
                this.classifiers.authors[this.model.get('story_authors')],
            tags_score: this.classifiers && this.classifiers.tags,
            score_icon_html: this.score_icon_html,
            classifier_filter_button_html: this.classifier_filter_button_html,
            prompt_classifiers: this.model.get('prompt_classifiers') || [],
            url_match: this.get_url_match(),
            options: this.options,
            truncatable: this.is_truncatable(),
            inline_story_title: this.options.inline_story_title,
            mobile_feed_title: this.feed && this.feed.get('feed_title'),
            // The grid overlay carries save/train in its own header, so it asks
            // for a clean reading pane instead of the floating side column.
            show_sideoption_train: !this.options.hide_sideoptions && NEWSBLUR.assets.preference("show_sideoption_train"),
            show_sideoption_save: !this.options.hide_sideoptions && NEWSBLUR.assets.preference("show_sideoption_save"),
        };
    },

    get_url_match: function () {
        if (!this.classifiers) return null;

        var permalink = this.model.get('story_permalink') || '';
        var url_match = null;
        var max_display_length = 80;

        // Check exact URL matches
        _.each(this.classifiers.urls, function (classifier_score, classifier_url) {
            if (url_match) return;
            var index = permalink.toLowerCase().indexOf(classifier_url.toLowerCase());
            if (index !== -1) {
                var matched = permalink.substr(index, classifier_url.length);
                url_match = this.format_url_match(permalink, index, matched.length, classifier_score, classifier_url, false, max_display_length);
            }
        }, this);

        // Check regex URL matches
        if (!url_match && this.classifiers.url_regex) {
            _.each(this.classifiers.url_regex, function (classifier_score, pattern) {
                if (url_match) return;
                try {
                    var regex = new RegExp(pattern, 'i');
                    var match = permalink.match(regex);
                    if (match) {
                        var index = match.index;
                        var matched = match[0];
                        url_match = this.format_url_match(permalink, index, matched.length, classifier_score, pattern, true, max_display_length);
                    }
                } catch (e) {
                    // Invalid regex, skip
                }
            }, this);
        }

        return url_match;
    },

    format_url_match: function (permalink, index, matched_length, score, pattern, is_regex, max_display_length) {
        var matched = permalink.substr(index, matched_length);
        var before = permalink.substr(0, index);
        var after = permalink.substr(index + matched_length);

        // Calculate how much space we have for before/after
        var available_for_context = max_display_length - matched.length;
        var before_max = Math.floor(available_for_context / 2);
        var after_max = available_for_context - before_max;

        // Truncate if needed
        if (before.length > before_max) {
            before = '…' + before.substr(before.length - before_max + 1);
        }
        if (after.length > after_max) {
            after = after.substr(0, after_max - 1) + '…';
        }

        return {
            score: score,
            pattern: pattern,
            is_regex: is_regex,
            before: before,
            matched: matched,
            after: after
        };
    },

    // story_detail_view.js: dir="auto" on feed titles, story titles, dates, authors, tags and the
    // story content lets each take the direction of its own text, so an English story reads
    // correctly in an Arabic interface and vice versa (see media/css/reader/reader_rtl.css).
    story_header_template: _.template('\
        <div class="NB-feed-story-header-feed">\
            <% if (feed) { %>\
                <div class="NB-feed-story-feed">\
                    <div class="NB-feedlist-manage-icon" role="button"></div>\
                    <%= $.favicon_html(feed) %>\
                    <span class="NB-feed-story-header-title" dir="auto"><%= feed.get("feed_title") %></span>\
                </div>\
            <% } %>\
        </div>\
        <div class="NB-feed-story-header">\
            <div class="NB-feed-story-header-info">\
                <div class="NB-feed-story-title-container">\
                    <div class="NB-feed-story-sentiment"></div>\
                    <div class="NB-feed-story-manage-icon"></div>\
                    <a class="NB-feed-story-title" dir="auto" href="<%= story.get("story_permalink") %>"><%= title %></a>\
                </div>\
                <div class="NB-feed-story-date-line">\
                    <% if (story.get("has_modifications")) { %>\
                        <div class="NB-feed-story-show-changes">\
                            <span class="NB-feed-story-show-changes-text">\
                                <%- story.get("showing_diff") ? gettext("Hide story changes") : gettext("Show story changes") %>\
                            </span>\
                            <span class="NB-middot">&middot;</span>\
                        </div>\
                    <% } %>\
                    <div class="NB-feed-story-date" dir="auto">\
                        <%= story.formatted_long_date() %>\
                    </div>\
                    <% if (story.story_authors()) { %>\
                        <div class="NB-feed-story-author-wrapper">\
                            <span class="NB-middot">&middot;</span>\
                            <span dir="auto" class="NB-feed-story-author <% if (authors_score) { %>NB-score-<%= authors_score %><% } %>">\
                                <%= story.story_authors() %><% if (authors_score) { %><%= score_icon_html(authors_score) %><% } %>\
                                <%= classifier_filter_button_html("author", story.story_authors()) %>\
                            </span>\
                        </div>\
                    <% } %>\
                    <% if (story.get("story_tags", []).length) { %>\
                        <div class="NB-feed-story-tags">\
                            <span class="NB-middot">&middot;</span>\
                            <% _.each(story.get("story_tags"), function(tag) { %>\
                                <div dir="auto" class="NB-feed-story-tag <% if (tags_score && tags_score[tag]) { %>NB-score-<%= tags_score[tag] %><% } %>">\
                                    <%= tag %><% if (tags_score && tags_score[tag]) { %><%= score_icon_html(tags_score[tag]) %><% } %>\
                                    <%= classifier_filter_button_html("tag", tag) %>\
                                </div>\
                            <% }) %>\
                        </div>\
                    <% } %>\
                    <% if (url_match && url_match.score) { %>\
                        <div class="NB-feed-story-url-match">\
                            <span class="NB-feed-story-url NB-score-<%= url_match.score %>">\
                                <span class="NB-feed-story-url-content"><span class="NB-feed-story-url-label"><%- gettext("URL:") %> </span><span class="NB-feed-story-url-before"><%= url_match.before %></span><span class="NB-feed-story-url-matched"><%= url_match.matched %></span><span class="NB-feed-story-url-after"><%= url_match.after %></span></span>\
                                <%= classifier_filter_button_html("url", story.get("story_permalink")) %>\
                            </span>\
                        </div>\
                    <% } %>\
                    <% if (prompt_classifiers && prompt_classifiers.length) { %>\
                        <div class="NB-feed-story-ai-classifiers">\
                            <span class="NB-middot">&middot;</span>\
                            <% _.each(prompt_classifiers, function(pc) { %>\
                                <div class="NB-feed-story-ai-classifier NB-score-<%= pc.score %>" data-prompt-type="<%= pc.include_images ? \'image\' : \'content\' %>">\
                                    <span class="NB-feed-story-ai-classifier-label"><%- pc.include_images ? gettext("Image Filter") : gettext("Content Filter") %></span>: <%= pc.prompt %>\
                                </div>\
                            <% }) %>\
                        </div>\
                    <% } %>\
                </div>\
                <% if (story.get("starred_date")) { %>\
                    <div class="NB-feed-story-starred-date">\
                        <span class="NB-icon"></span>\
                        <span class="NB-title"><%- gettext("Saved:") %> </span>\
                        <span class="NB-date" dir="auto"><%= story.get("starred_date") %></span>\
                    </div >\
                <% } %>\
            </div>\
        </div>\
    '),

    template: _.template('\
        <% if (!options.overlay_reader && !options.text_view && !options.skip_content) { %>\
            <div class="NB-story-mobile-bar">\
                <button type="button" class="NB-story-mobile-back" aria-label="<%- gettext(\"Back to stories\") %>">\
                    <span class="NB-story-mobile-icon NB-story-mobile-icon-back" aria-hidden="true"></span>\
                    <span class="NB-story-mobile-label"><%- gettext(\"Back to stories\") %></span>\
                </button>\
                <div class="NB-story-mobile-feed" dir="auto"><%- mobile_feed_title || \"\" %></div>\
                <button type="button" class="NB-story-mobile-next" aria-label="<%- gettext(\"Next unread story\") %>">\
                    <span class="NB-story-mobile-icon NB-story-mobile-icon-next" aria-hidden="true"></span>\
                </button>\
            </div>\
        <% } %>\
        <%= story_header %>\
        <div class="NB-story-content-container">\
            <div class="NB-story-content-wrapper <% if (truncatable) { %>NB-story-content-truncatable<% } %>">\
                <div class="NB-story-content-positioning-wrapper">\
                    <div dir="auto" class="NB-feed-story-content <% if (feed && feed.get("is_newsletter")) { %>NB-newsletter<% } %>">\
                        <% if (!options.skip_content) { %>\
                            <%= story.story_content() %>\
                        <% } %>\
                    </div>\
                </div>\
                <div class="NB-story-content-expander" role="button">\
                    <div class="NB-story-content-expander-inner">\
                        <div class="NB-story-cutoff"></div>\
                        <div class="NB-story-content-expander-text"><%- gettext("Read the whole story") %></div>\
                        <div class="NB-story-content-expander-pages"></div>\
                    </div>\
                </div>\
            </div>\
            <div class="NB-feed-story-sideoptions-container">\
                <div class="NB-feed-story-sideoptions">\
                    <% if (show_sideoption_train) { %>\
                        <div class="NB-sideoption NB-feed-story-train" role="button">\
                            <div class="NB-sideoption-title"><%- gettext("Train") %></div>\
                            <div class="NB-sideoption-icon NB-sideoption-icon-train">&nbsp;</div>\
                            <div class="NB-sideoption-writerules">\
                                <div class="NB-sideoption-thirdparty NB-sideoption-thirdparty-writerules" data-action="write-rules" role="button">\
                                </div>\
                            </div>\
                        </div>\
                    <% } %>\
                    <% if (show_sideoption_save) { %>\
                        <div class="NB-sideoption NB-feed-story-save" role="button">\
                            <div class="NB-sideoption-title"><%- story.get("starred") ? gettext("Saved") : gettext("Save") %></div>\
                            <div class="NB-sideoption-icon">&nbsp;</div>\
                        </div>\
                        <%= story_save_view %>\
                        <% } %>\
                </div>\
            </div>\
        </div>\
        <% if (inline_story_title) { %>\
            <div class="NB-feed-story-header-feed">\
            </div>\
        <% } %>\
    '),

    generate_gradients: function () {
        var $header = this.$('.NB-feed-story-header-feed');

        if (!this.feed) return;

        var favicon_color = this.feed.get('favicon_color');
        if (favicon_color) {
            $header.css('backgroundColor', '#' + favicon_color);
            $header.css('background-image', 'none');
        }
        $header.css('background-image', NEWSBLUR.utils.generate_gradient(this.feed, 'webkit'));
        $header.css('background-image', NEWSBLUR.utils.generate_gradient(this.feed, 'moz'));
        // $header.css('borderTop',        NEWSBLUR.utils.generate_gradient(this.feed, 'border'));
        // $header.css('borderBottom',     NEWSBLUR.utils.generate_gradient(this.feed, 'border'));
        $header.css('textShadow', NEWSBLUR.utils.generate_shadow(this.feed));
    },

    is_truncatable: function () {
        // grid_reader_view.js: the overlay always shows the whole article.
        if (this.options.full_story) return false;
        return NEWSBLUR.assets.preference("truncate_story") == 'all';
    },

    score_icon_html: function (score) {
        if (score >= 1) {
            return '<img src="/media/embed/icons/nouns/thumbs-up.svg" class="NB-score-icon NB-score-icon-like" />';
        } else if (score <= -2) {
            return '<span class="NB-score-icon-double"><img src="/media/embed/icons/nouns/thumbs-down.svg" class="NB-score-icon NB-score-icon-super-dislike NB-score-icon-super-dislike-back" /><img src="/media/embed/icons/nouns/thumbs-down.svg" class="NB-score-icon NB-score-icon-super-dislike" /></span>';
        } else if (score <= -1) {
            return '<img src="/media/embed/icons/nouns/thumbs-down.svg" class="NB-score-icon NB-score-icon-dislike" />';
        }
        return '';
    },

    make_story_title: function (story) {
        story = story || this.model;
        var title = story.get('story_title');
        var classifiers = NEWSBLUR.assets.classifiers[story.get('story_feed_id')];
        var feed_titles = classifiers && classifiers.titles || [];
        var self = this;

        _.each(feed_titles, function (score, title_classifier) {
            var pos = NEWSBLUR.title_classifier_utils.find_match_position(title, title_classifier);
            if (pos != -1) {
                var icon = self.score_icon_html(score);
                title = title.substr(0, pos) + '<span class="NB-score-' + score + '">' + title.substr(pos, title_classifier.length) + icon + '</span>' + title.substr(pos + title_classifier.length);
            }
        });

        return title;
    },

    render_story_content: function () {
        this.$(".NB-feed-story-show-changes-text").text(this.model.get('showing_diff') ? gettext("Hide story changes") : gettext("Show story changes"));
        this.$(".NB-feed-story-content").html(this.model.story_content());

        this.attach_handlers();
    },

    destroy: function () {
        // console.log(["destroy story detail", this.model.get('story_title')]);
        clearTimeout(this.truncate_delay_function);
        this.images_to_load = null;
        this.model.unbind(null, null, this);
        if (this.collection) this.collection.unbind(null, null, this);
        // this.sideoptions_view.destroy();
        delete this.model.inline_story_detail_view;
        this.remove();
    },

    render_intelligence: function (options) {
        options = options || {};
        var score = this.model.score();
        var unread_view = NEWSBLUR.reader.get_unread_view_score();

        if (score >= unread_view) {
            this.$el.removeClass('NB-hidden');
            this.model.set('visible', true);
        } else {
            this.$el.addClass('NB-hidden');
            this.model.set('visible', false);
        }

        // Refresh classifiers reference and reapply highlights when classifiers change
        this.classifiers = NEWSBLUR.assets.classifiers[this.model.get('story_feed_id')];
        this.apply_starred_story_selections(true);
    },

    // ============
    // = Bindings =
    // ============

    toggle_classes: function () {
        var changes = this.model.changedAttributes();
        var onlySelected = changes && _.all(_.keys(changes), function (change) {
            return _.contains(['selected', 'read', 'intelligence', 'visible'], change);
        });

        if (onlySelected) return;

        if (this.model.changedAttributes()) {
            // NEWSBLUR.log(["Story changed", this.model.changedAttributes(), this.model.previousAttributes()]);
        }

        this.setup_classes();
    },

    setup_classes: function () {
        var story = this.model;
        var unread_view = NEWSBLUR.reader.get_unread_view_score();

        this.$el.toggleClass('NB-river-story', NEWSBLUR.reader.flags.river_view);
        this.$el.toggleClass('NB-story-starred', !!story.get('starred'));
        this.$el.toggleClass('NB-story-shared', !!story.get('shared'));
        this.toggle_intelligence();
        // grid_reader_view.js: a negative-score story must still be readable in
        // the overlay, and render_intelligence would hide it and flip visible.
        if (!this.options.overlay_reader) this.render_intelligence();

        if (NEWSBLUR.assets.preference('show_tooltips')) {
            this.$('.NB-story-sentiment').tipsy({
                delayIn: 375,
                gravity: 's'
            });
            this.$('.NB-feed-story-show-changes').tipsy({
                delayIn: 375
            });
        }
    },

    toggle_read_status: function () {
        this.$el.toggleClass('read', !!this.model.get('read_status'));
    },

    toggle_intelligence: function () {
        var score = this.model.score();
        this.$el.removeClass('NB-story-negative NB-story-neutral NB-story-postiive')
            .addClass('NB-story-' + this.model.score_name(score));
    },

    toggle_selected: function (model, selected, options) {
        options = options || {};
        this.$el.toggleClass('NB-selected', !!this.model.get('selected'));
        _.defer(_.bind(this.update_sideoptions_sticky_state, this));
        NEWSBLUR.app.taskbar_info.hide_stories_error();

        if (NEWSBLUR.assets.preference('feed_view_single_story')) {
            NEWSBLUR.app.story_list.scroll_to_selected_story(model, {
                'scroll_to_top': true
            });
        } else if (selected &&
            !options.selected_by_scrolling &&
            (NEWSBLUR.reader.story_view == 'feed' ||
                (NEWSBLUR.reader.story_view == 'page' &&
                    NEWSBLUR.reader.flags['page_view_showing_feed_view']))) {
            // NEWSBLUR.app.story_list.show_stories_preference_in_feed_view();
            NEWSBLUR.app.story_list.scroll_to_selected_story(model, options);
        }

        if (NEWSBLUR.reader.flags['feed_view_showing_story_view'] ||
            NEWSBLUR.reader.flags['temporary_story_view']) {
            NEWSBLUR.reader.switch_to_correct_view();
        }
    },

    // ============
    // = Expander =
    // ============

    truncate_story_height: function () {
        if (this._truncated) return;
        if (!this.is_truncatable()) return;

        if (NEWSBLUR.assets.preference('feed_view_single_story')) return;

        // console.log(["Checking truncate", this.$el, this.images_to_load, this.truncate_delay / 1000 + " sec delay"]);
        var $expander = this.$(".NB-story-content-expander");
        var $expander_cutoff = this.$(".NB-story-cutoff");
        var $wrapper = this.$(".NB-story-content-wrapper");
        var $content = this.$(".NB-feed-story-content");
        var max_height = parseInt($wrapper.css('maxHeight'), 10) || this.STORY_CONTENT_MAX_HEIGHT;
        var content_height = $content.outerHeight(true);

        if (content_height > max_height &&
            content_height < max_height + this.FUDGE_CONTENT_HEIGHT_OVERAGE) {
            // console.log(["Height over but within fudge", this.model.get('story_title').substr(0, 30), content_height, max_height]);
            $wrapper.addClass('NB-story-content-wrapper-height-fudged');
        } else if (content_height > max_height) {
            $expander.css('display', 'block');
            $expander_cutoff.css('display', 'block');
            $wrapper.removeClass('NB-story-content-wrapper-height-fudged');
            $wrapper.addClass('NB-story-content-wrapper-height-truncated');
            var pages = Math.round(content_height / max_height, true);
            var dots = _.map(_.range(pages), function () { return '&middot;'; }).join(' ');

            // console.log(["Height over, truncating...", this.model.get('story_title').substr(0, 30), content_height, max_height, pages]);
            this.$(".NB-story-content-expander-pages").html(dots);
            this._truncated = true;
        } else {
            // console.log(["Height under.", this.model.get('story_title').substr(0, 30), content_height, max_height]);
        }

        if (this.images_to_load > 0) {
            this.truncate_delay *= 1 + Math.random();
            clearTimeout(this.truncate_delay_function);
            this.truncate_delay_function = _.delay(_.bind(this.truncate_story_height, this), this.truncate_delay);
        }
    },

    lazy_load_story_images: function () {
        // Round 4 perf: story bodies routinely carry dozens of images from remote
        // hosts. Keep any explicit loading/decoding attribute the author set.
        this.$(".NB-feed-story-content img").each(function () {
            if (!this.getAttribute('loading')) this.setAttribute('loading', 'lazy');
            if (!this.getAttribute('decoding')) this.setAttribute('decoding', 'async');
        });
    },

    schedule_sticky_state_update: function () {
        // Round 4 perf: update_sideoptions_sticky_state reads offsetHeight and then
        // writes min-height, so calling it once per loaded image thrashed layout.
        // One trailing call per image batch is enough.
        clearTimeout(this._sticky_state_timer);
        this._sticky_state_timer = setTimeout(_.bind(function () {
            this._sticky_state_timer = null;
            this.update_sideoptions_sticky_state();
        }, this), 120);
    },

    watch_images_for_story_height: function () {
        this.model.on('change:images_loaded', _.bind(function () {
            this.resize_starred_tags();
            this.schedule_sticky_state_update();
            if (NEWSBLUR.app.story_list && NEWSBLUR.app.story_list.schedule_position_refresh) {
                NEWSBLUR.app.story_list.schedule_position_refresh();
            }
        }, this));
        var is_truncatable = this.is_truncatable();

        // console.log(['truncatable', is_truncatable, this.images_to_load]);
        if (!is_truncatable) return;

        this.truncate_delay = 100;
        this.images_to_load = this.$('img').length;
        if (is_truncatable) this.truncate_story_height();
        this.$('img').on('load', _.bind(function () {
            this.images_to_load -= 1;
            if (is_truncatable) this.truncate_story_height();
            // Round 4 perf: setting images_loaded to false for every image fired a
            // Backbone change (resize_starred_tags + sticky recalculation) dozens of
            // times per story. Only flip the flag when the whole set has settled.
            if (this.images_to_load <= 0) {
                this.model.set('images_loaded', true);
                this.schedule_sticky_state_update();
            }
        }, this));
    },

    update_sideoptions_sticky_state: function () {
        // Round 4 perf: this runs after every image load. It used to clear the
        // sticky class and an inline min-height before checking whether sticky
        // sideoptions even apply, forcing a layout flush on every call.
        var sticky_story_sideoptions = NEWSBLUR.assets.preference('sticky_story_sideoptions');
        var sticky_applies = !(!NEWSBLUR.reader ||
            !NEWSBLUR.reader.$s ||
            NEWSBLUR.reader.flags.narrow_content ||
            NEWSBLUR.assets.preference('story_button_placement') != 'right' ||
            sticky_story_sideoptions === false ||
            sticky_story_sideoptions === 'false');

        if (!sticky_applies) {
            if (this._sticky_sideoptions_applied) {
                this.$el.removeClass('NB-story-sideoptions-sticky');
                this.$(".NB-story-content-container").css('min-height', '');
                this._sticky_sideoptions_applied = false;
            }
            return;
        }

        var $sideoptions_container = this.$(".NB-feed-story-sideoptions-container");
        if (!$sideoptions_container.length) return;

        var $content_container = this.$(".NB-story-content-container");
        this.$el.removeClass('NB-story-sideoptions-sticky');
        $content_container.css('min-height', '');

        var $sideoptions = this.$(".NB-feed-story-sideoptions");
        if (!$content_container.length || !$sideoptions.length) return;

        // Clear any explicit height left over from the non-sticky share/save
        // resize path; otherwise an old inline height keeps the story area tall
        // after switching to sticky mode.
        var $story_content = this.$(".NB-feed-story-content,.NB-story-content");
        if ($story_content.data('original_height')) {
            $story_content.css({ 'height': '', 'min-height': '' });
            $story_content.removeData('original_height');
        }

        var top_margin = 24;
        var bottom_margin = 42;
        var sideoptions_height = $sideoptions.outerHeight(true);
        var required_min_height = sideoptions_height + top_margin + bottom_margin;
        var base_min_height = parseInt($content_container.css('min-height'), 10) || 0;
        if (required_min_height > base_min_height) {
            $content_container.css('min-height', Math.ceil(required_min_height) + 'px');
        }

        this.$el.addClass('NB-story-sideoptions-sticky');
        this._sticky_sideoptions_applied = true;
    },

    expand_story: function (options) {
        options = options || {};
        var $expander = this.$(".NB-story-content-expander");
        var $expander_cutoff = this.$(".NB-story-cutoff");
        var $wrapper = this.$(".NB-story-content-wrapper");
        var $content = this.$(".NB-feed-story-content");
        var max_height = parseInt($wrapper.css('maxHeight'), 10) || this.STORY_CONTENT_MAX_HEIGHT;
        var content_height = $content.outerHeight(true);
        var height_ratio = content_height / max_height;

        if (content_height < max_height) return;
        // console.log(["max height", max_height, content_height, content_height / max_height]);
        clearInterval(this._fetch_interval);
        this._fetch_interval = setInterval(function () {
            NEWSBLUR.app.story_list.fetch_story_locations_in_feed_view();
        }, 250);

        $wrapper.animate({
            maxHeight: content_height
        }, {
            duration: options.instant ? 0 : Math.min(2 * 1000, parseInt(200 * height_ratio, 10)),
            easing: 'easeInOutQuart',
            complete: _.bind(function () {
                clearInterval(this._fetch_interval);
                NEWSBLUR.app.story_list.fetch_story_locations_in_feed_view();
                $wrapper.removeClass('NB-story-content-wrapper-height-truncated');
                this.update_sideoptions_sticky_state();
            }, this)
        });

        $expander.add($expander_cutoff).animate({
            bottom: -1 * $expander.outerHeight() - 76
        }, {
            duration: options.instant ? 0 : Math.min(2 * 1000, parseInt(200 * height_ratio, 10)),
            easing: 'easeInOutQuart',
            complete: function () {
                $expander.hide();
            }
        });

    },

    // ===========
    // = Actions =
    // ===========

    mark_read: function () {
        var delay = NEWSBLUR.assets.preference('read_story_delay');
        if (delay == -2) {
            this.model.mark_read({ skip_delay: true });
        } else {
            this.model.mark_read();
        }
    },

    // On a phone the story opens inline in the list, which leaves no way back
    // except scrolling up to the headline and tapping it again. The bar at the
    // top of the story collapses it and brings the headline back into view.
    close_mobile_story: function (e) {
        if (e) {
            e.preventDefault();
            e.stopPropagation();
        }

        var story_title_view = this.model.story_title_view;
        if (!story_title_view || !story_title_view.collapse_story) return;

        // The pane layouts (full, split) put the story in #story_pane with the
        // list hidden, so collapsing in place is not enough there.
        if (this.$el.closest('#story_pane').length) {
            NEWSBLUR.reader.switch_story_layout('list', true);
            return;
        }

        story_title_view.collapse_story();
        _.defer(function () {
            if (story_title_view.el && story_title_view.el.scrollIntoView) {
                story_title_view.el.scrollIntoView({ block: 'nearest' });
            }
        });
    },

    next_unread_from_bar: function (e) {
        if (e) {
            e.preventDefault();
            e.stopPropagation();
        }
        NEWSBLUR.reader.show_next_unread_story();
    },

    // A swipe from the left edge is the phone habit for going back, so it does
    // the same thing as the bar's back button. A mostly vertical drag is left
    // alone so scrolling still works, and code blocks and embeds that scroll
    // sideways themselves never start the gesture.
    SWIPE_BACK_EDGE: 36,
    SWIPE_BACK_TRIGGER: 72,

    setup_swipe_back: function () {
        if (this.swipe_back_bound) return;
        this.swipe_back_bound = true;
        this.swipe_back = null;

        var self = this;
        this.el.addEventListener('touchstart', function (e) {
            self.handle_swipe_start(e);
        }, { passive: true });
        this.el.addEventListener('touchmove', function (e) {
            self.handle_swipe_move(e);
        }, { passive: false });
        this.el.addEventListener('touchend', function () {
            self.handle_swipe_end();
        }, { passive: true });
        this.el.addEventListener('touchcancel', function () {
            self.reset_swipe_back();
        }, { passive: true });
    },

    handle_swipe_start: function (e) {
        this.swipe_back = null;
        if (!window.matchMedia('(max-width: 768px)').matches) return;
        if (!e.touches || e.touches.length !== 1) return;

        var touch = e.touches[0];
        if (touch.clientX > this.SWIPE_BACK_EDGE) return;
        if ($(e.target).closest('pre, table, iframe, video, .NB-image-viewer').length) return;

        this.swipe_back = { x: touch.clientX, y: touch.clientY, dx: 0, locked: false };
    },

    handle_swipe_move: function (e) {
        var swipe = this.swipe_back;
        if (!swipe || !e.touches || !e.touches.length) return;

        var touch = e.touches[0];
        var dx = touch.clientX - swipe.x;
        var dy = touch.clientY - swipe.y;

        if (!swipe.locked && Math.abs(dy) > 40 && Math.abs(dy) > Math.abs(dx)) {
            this.reset_swipe_back();
            return;
        }
        if (dx <= 0) {
            if (swipe.locked) this.reset_swipe_back();
            return;
        }

        swipe.locked = true;
        swipe.dx = dx;
        e.preventDefault();
        this.el.style.transition = 'none';
        this.el.style.transform = 'translateX(' + Math.min(dx * 0.55, 96) + 'px)';
    },

    handle_swipe_end: function () {
        var swipe = this.swipe_back;
        if (!swipe) return;
        var dx = swipe.dx;
        this.reset_swipe_back();
        if (dx >= this.SWIPE_BACK_TRIGGER) this.close_mobile_story();
    },

    reset_swipe_back: function () {
        this.swipe_back = null;
        if (!this.el) return;
        this.el.style.transition = 'transform 160ms cubic-bezier(.2, .7, .3, 1)';
        this.el.style.transform = '';
        _.delay(_.bind(function () {
            if (this.el) this.el.style.transition = '';
        }, this), 200);
    },

    preserve_classifier_color: function (classifier_type, value, score) {
        var $tag;
        this.$('.NB-feed-story-' + classifier_type).each(function () {
            // Clone and strip icons before comparing value
            var $clean = $(this).clone();
            $clean.find('.NB-score-icon, .NB-score-icon-double').remove();
            var el_value = classifier_type === 'tag' ? _.string.trim($clean.html()) : _.string.trim($clean.text());
            if (el_value == value) {
                $tag = $(this);
                return false;
            }
        });
        if (!$tag) return;
        $tag.removeClass('NB-score-now-1')
            .removeClass('NB-score-now--1')
            .removeClass('NB-score-now--2')
            .removeClass('NB-score-now-0')
            .addClass('NB-score-now-' + score)
            .one('mouseleave', function () {
                // console.log(["leave", score]);
                $tag.removeClass('NB-score-now-' + score);
                _.delay(function () {
                    $tag.one('mouseenter', function () {
                        // console.log(["enter", score]);
                        $tag.removeClass('NB-score-now-' + score);
                    });
                }, 100);
            });
    },

    render_starred: function () {
        var story = this.model;
        var $sideoption_title = this.$('.NB-feed-story-save .NB-sideoption-title');

        if (story.get('starred')) {
            $sideoption_title.text(gettext('Saved'));
        } else {
            $sideoption_title.text(gettext('Removed'));
            $sideoption_title.one('mouseleave', function () {
                _.delay(function () {
                    if (!story.get('starred')) {
                        $sideoption_title.text(gettext('Save'));
                    }
                }, 200);
            });
        }
    },

    attach_syntax_highlighter_handler: function () {
        _.delay(_.bind(function () {
            // hljs.configure({useBR: true}); // Don't use
            this.$('pre').each(function (i, e) {
                hljs.highlightBlock(e);
            });
        }, this), 100);
    },

    attach_fitvid_handler: function () {
        // Thanks to feedbin for the custom selector
        _.delay(_.bind(function () {
            this.$el.fitVids({
                customSelector: "iframe[src*='youtu.be'],iframe[src*='www.flickr.com'],iframe[src*='view.vzaar.com']"
            });
        }, this), 50);
    },

    attach_media_enhancements: function () {
        var $content = this.$('.NB-feed-story-content');
        if (!$content.length) return;
        NEWSBLUR.story_media.enhance($content);
    },

    // ==========
    // = Events =
    // ==========

    open_image_viewer: function (e) {
        if (NEWSBLUR.hotkeys.shift) return;

        var image = e.currentTarget;
        // Small images (avatars, tracking pixels) keep whatever behaviour the
        // feed intended, which is usually a link to the full size.
        if (!NEWSBLUR.story_media.is_viewable_image(image)) return;

        var $content = this.$('.NB-feed-story-content');
        if (!$content.length) return;

        var images = NEWSBLUR.story_media.collect_images($content);
        if (!images.length) return;

        var src = image.currentSrc || image.src;
        var index = 0;
        for (var i = 0; i < images.length; i++) {
            if (images[i].src === src) {
                index = i;
                break;
            }
        }

        e.preventDefault();
        // The delegated handlers below sit on an ancestor, so stopping here
        // also skips the view-level mark_read click. Do it explicitly.
        e.stopPropagation();
        this.mark_read();

        NEWSBLUR.Views.ImageViewer.open(images, index, $(image));
    },

    play_inline_video: function (e) {
        e.preventDefault();
        e.stopPropagation();

        var $embed = $(e.currentTarget).closest('.NB-video-embed');
        this.mark_read();
        NEWSBLUR.story_media.play_embed($embed);
        // fitVids only ran over the iframes present at render time.
        this.attach_fitvid_handler();
        $embed.find('iframe').trigger('focus');
    },

    click_link_in_story: function (e) {
        if (NEWSBLUR.hotkeys.shift) return;
        var $target = $(e.currentTarget);

        e.preventDefault();
        e.stopPropagation();
        if (e.which >= 2) return;
        if (e.which == 1 && $('.NB-menu-manage-container:visible').length) return;

        var href = $target.attr('href');

        // Fix footnotes
        if (_.string.contains(href, "#")) {
            try {
                var footnote_href = href.replace(/^.*?\#(.*?)$/, "\#$1")
                    .replace(':', "\\\:");
                var $footnote = $(footnote_href);
            } catch (err) {
                $footnote = [];
            }
            if ($footnote.length) {
                href = footnote_href;
                var offset = $(href).offset().top;
                var $scroll;
                if (_.contains(['list', 'grid', 'magazine'], NEWSBLUR.assets.view_setting(NEWSBLUR.reader.active_feed, 'layout'))) {
                    $scroll = NEWSBLUR.reader.$s.$story_titles;
                } else if (NEWSBLUR.reader.flags['temporary_story_view'] ||
                    NEWSBLUR.reader.story_view == 'text') {
                    $scroll = NEWSBLUR.reader.$s.$text_view;
                } else {
                    $scroll = NEWSBLUR.reader.$s.$feed_scroll;
                }
                offset += $scroll.scrollTop();
                $scroll.stop().scrollTo(offset - 60, {
                    duration: 340,
                    axis: 'y',
                    easing: 'easeInOutQuint'
                });
                return;
            }
        }

        if (NEWSBLUR.assets.preference('new_window') == 1) {
            window.open(href, '_blank');
        } else {
            window.open(href);
        }

        this.model.set('selected', true, { selected_by_scrolling: true });

        return false;
    },

    mouseenter_manage_icon: function () {
        var menu_height = 270;
        if (this.$el.offset().top > $(window).height() - menu_height) {
            this.$el.addClass('NB-hover-inverse');
        }
    },

    mouseleave_manage_icon: function () {
        this.$el.removeClass('NB-hover-inverse');
    },

    mouseenter: function () {
        if (this.model.get('selected')) return;

        if (NEWSBLUR.reader.flags['scrolling_by_selecting_story_title'] ||
            NEWSBLUR.assets.preference('feed_view_single_story')) {
            return;
        }

        this.model.set('selected', true, { selected_by_scrolling: true });
    },

    mouseleave: function () {

    },

    mouseenter_sideoption_train: function (event) {
        var $sideoption = $(event.currentTarget);
        $sideoption.on('mousemove.train', _.bind(function (e) {
            var $target = $(e.target);
            var $thirdparty = $target.closest('.NB-sideoption-thirdparty-writerules');

            if ($thirdparty.length) {
                $sideoption.find(".NB-sideoption-title").text(gettext("AI Filter"));
                $thirdparty.addClass("NB-hover");
                $sideoption.find(".NB-sideoption-icon-train").addClass("NB-dimmed");
            } else {
                $sideoption.find(".NB-sideoption-title").text(gettext("Train"));
                $sideoption.find('.NB-sideoption-thirdparty-writerules').removeClass("NB-hover");
                $sideoption.find(".NB-sideoption-icon-train").removeClass("NB-dimmed");
            }
        }, this));
    },

    mouseleave_sideoption_train: function (event) {
        var $sideoption = $(event.currentTarget);
        $sideoption.off('mousemove.train');
        $sideoption.find(".NB-sideoption-title").text(gettext("Train"));
        $sideoption.find('.NB-sideoption-thirdparty-writerules').removeClass("NB-hover");
        $sideoption.find(".NB-sideoption-icon-train").removeClass("NB-dimmed");
    },

    mouseup_check_selection: function (e) {
        var $doc = this.$(".NB-feed-story-content");
        // console.log(['mouseup_check_selection', e, e.which, $(e.target)]);
        if (e.which == 3) {
            // Right click
            return;
        }
        if ($(e.target).hasClass("NB-highlight")) {
            this.show_unhighlight_tooltip($(e.target));
            return;
        }
        if ($(e.target).hasClass("NB-classifier-highlight-positive") ||
            $(e.target).hasClass("NB-classifier-highlight-negative") ||
            $(e.target).hasClass("NB-classifier-highlight-super-negative") ||
            $(e.target).closest("[class*='NB-classifier-highlight-']").length) {
            // Let the click handler deal with classifier highlights
            return;
        }
        if ($(e.target).hasClass("NB-search-highlight")) {
            // Let the click handler deal with search highlights
            return;
        }

        if (!NEWSBLUR.assets.preference('highlights')) return;

        this.$(".NB-starred-story-selection-highlight,[data-tippy]").contents().unwrap();
        $doc.attr('id', 'NB-highlighting');

        var text = "";
        var selection;
        if (window.getSelection) {
            selection = window.getSelection();
            text = window.getSelection().toString();
        } else if (document.selection && document.selection.type != "Control") {
            selection = document.selection.createRange();
            text = document.selection.createRange().text;
        }
        this.serialized_highlight = _.string.trim(text);
        // console.log(['mouseup_check_selection 1', this.serialized_highlight]);

        if (this.tooltip && this.tooltip.tooltips && this.tooltip.tooltips.length) {
            this.tooltip.tooltips[0].hide();
        }
        if (!this.serialized_highlight) {
            $doc.removeAttr('id');
            this.apply_starred_story_selections();
            return;
        }

        $doc.mark(this.serialized_highlight, {
            "className": "NB-starred-story-selection-highlight",
            "separateWordSearch": false,
            "acrossElements": true,
            "filter": function (node, term, total_counter, counter) {
                if (!selection.containsNode(node)) return false;
                // Highlighting the second 'baz' will fail, and the entire 'baz quz baz' will be highlighted instead.
                //     foo bar baz quz baz bar foo
                // console.log(['filter', node, term, total_counter, counter, selection.anchorNode, selection.anchorOffset, selection.focusNode, selection.focusOffset, selection.anchorNode == node, selection.containsNode(node), node.textContent.indexOf(term)]);
                // if (node.textContent.indexOf(term) != selection.anchorOffset) return false;
                return true;
            },
            "done": _.bind(function () {
                var $selection = $(".NB-starred-story-selection-highlight", $doc);
                console.log(['$selection', $selection, $selection.first().get(0), $selection.last().get(0)]);
                $selection.attr('title', this.selection_menu_html(false));
                var $t = tippy($selection.get(0), {
                    // delay: 100,
                    appendTo: this.el,
                    arrow: true,
                    arrowType: 'round',
                    size: 'large',
                    duration: 350,
                    animation: 'scale',
                    trigger: 'click',
                    interactive: true,
                    performance: true,
                    onHide: _.bind(function () {
                        $selection.removeClass("NB-starred-story-selection-highlight");
                    }, this)
                });
                this.tooltip = $t;
                _.defer(function () {
                    if ($t.tooltips && $t.tooltips.length) $t.tooltips[0].show();
                });

                $doc.removeAttr('id');
                // this.apply_starred_story_selections();

                var doc = window.document, range;
                if (window.getSelection && doc.createRange) {
                    if ($selection.length) {
                        selection.removeAllRanges();
                        range = doc.createRange();
                        range.setStart($selection.first().get(0), 0);
                        range.setEndAfter($selection.last().get(0), 0);
                        selection.addRange(range);
                    }
                    // } else if (doc.body.createTextRange) {
                    //     range = doc.body.createTextRange();
                    //     range.moveToElementText($selection[0]);
                    //     range.select();
                }
            }, this)
        });
    },

    // story_detail_view.js: Tooltip menu for selected or highlighted story text. Labels are
    // translated and escaped because tippy renders the title attribute as HTML.
    selection_menu_html: function (is_highlighted) {
        var menu_item = function (class_name, svg, label) {
            return "<span class='" + class_name + "'>" + svg + " " + _.escape(label) + "</span>";
        };
        var first_item = is_highlighted ?
            menu_item('NB-unhighlight-selection', "<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 256 256' fill='white'><path d='M225,80.4,183.6,39a24,24,0,0,0-33.94,0L31,157.66a24,24,0,0,0,0,33.94l30.06,30.06A8,8,0,0,0,66.74,224H216a8,8,0,0,0,0-16h-84.7L225,114.34A24,24,0,0,0,225,80.4ZM213.67,103,160,156.69,107.31,104,161,50.34a8,8,0,0,1,11.32,0l41.38,41.38a8,8,0,0,1,0,11.31Z'/></svg>", gettext("Unhighlight")) :
            menu_item('NB-highlight-selection', "<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='m9 11-6 6v3h9l3-3'/><path d='m22 12-4.6 4.6a2 2 0 0 1-2.8 0l-5.2-5.2a2 2 0 0 1 0-2.8L14 4'/></svg>", gettext("Highlight"));
        return first_item +
            menu_item('NB-train-selection', "<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 150 150' fill='white'><path d='M59.1 60.5V121.2c3.6 2.7 6 4.9 11.2 4.9h42.9c8.5 0 14.2-6.8 12-13.7 4.2-4.4 5.3-9.4 2.7-14.7 3.9-5.5 4.4-11.3.2-16.8 6.3-10.1.5-21.9-13.5-21.9h-17.1c0-7.2-.4-18.9-3.4-25.5-5.9-13.5-24.6-11.9-24 .4-.5 9.7-3.3 19.3-11.1 26.6M17.6 59.2V126h34.7V59.2H17.6z'/></svg>", gettext("Train")) +
            "<br>" +
            menu_item('NB-search-site-selection', "<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='m21 21-4.34-4.34'/><circle cx='11' cy='11' r='8'/></svg>", gettext("Search site")) +
            menu_item('NB-search-folder-selection', "<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M10.7 20H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H20a2 2 0 0 1 2 2v4.1'/><path d='m21 21-1.9-1.9'/><circle cx='17' cy='17' r='3'/></svg>", gettext("Search folder"));
    },

    show_unhighlight_tooltip: function ($highlight) {
        this.$highlight = $highlight;
        this.serialized_highlight = _.string.trim($highlight.text());
        $highlight.attr('title', this.selection_menu_html(true));
        var $t = tippy($highlight.get(0), {
            // delay: 100,
            appendTo: this.el,
            arrow: true,
            arrowType: 'round',
            size: 'large',
            duration: 350,
            animation: 'scale',
            trigger: 'click',
            interactive: true,
            performance: true,
            onHide: _.bind(function () {
                // $highlight.removeClass('NB-starred-story-selection-highlight');
            }, this)
        });
        this.tooltip = $t;
        _.defer(function () {
            if ($t.tooltips && $t.tooltips.length) $t.tooltips[0].show();
        });

    },

    show_classifier_highlight_menu: function (e) {
        e.preventDefault();
        e.stopPropagation();

        var $mark = $(e.currentTarget);
        var text = $mark.text();
        console.log(['show_classifier_highlight_menu', text, $mark]);

        // Set the serialized_highlight to the text from the mark
        this.serialized_highlight = _.string.trim(text);

        // Close any existing tooltip
        if (this.tooltip && this.tooltip.tooltips && this.tooltip.tooltips.length) {
            this.tooltip.tooltips[0].hide();
        }

        // Show the highlight/train/search menu
        $mark.attr('title', this.selection_menu_html(false));
        var $t = tippy($mark.get(0), {
            appendTo: this.el,
            arrow: true,
            arrowType: 'round',
            size: 'large',
            duration: 350,
            animation: 'scale',
            trigger: 'click',
            interactive: true,
            performance: true,
            onHide: _.bind(function () {
                // Cleanup if needed
            }, this)
        });
        this.tooltip = $t;
        _.defer(function () {
            if ($t.tooltips && $t.tooltips.length) $t.tooltips[0].show();
        });
    },

    highlight_selected_text: function () {
        var highlights = this.model.get('highlights');
        if (!highlights || !$.isArray(highlights)) highlights = [];
        highlights.push(this.serialized_highlight);
        this.model.set('highlights', highlights, { silent: true });
        this.model.trigger('change:highlights');
        console.log(['highlight_selected_text', this.serialized_highlight, highlights]);

        if (this.tooltip && this.tooltip.tooltips && this.tooltip.tooltips.length) {
            this.tooltip.tooltips[0].hide();
        }

        this.apply_starred_story_selections();

        return true;
    },

    unhighlight_selected_text: function (el) {
        var highlight_index = this.$highlight.attr('data-highlight-index');
        var highlights = this.model.get('highlights');
        if (!highlights || !$.isArray(highlights)) highlights = [];

        if (highlight_index !== undefined) {
            // Remove the highlight at the specific index
            var remove_highlight = highlights[parseInt(highlight_index)];
            highlights = _.filter(highlights, function (value) { return value !== remove_highlight; });
            console.log(['Unhighlighting by index', highlight_index, remove_highlight, highlights]);
        } else {
            // Fallback to old method if no index found
            var remove_highlight = this.$highlight.text();
            highlights = _.filter(highlights, function (value) { return !_.string.contains(value, remove_highlight); });
            console.log(['Unhighlighting by text', remove_highlight, highlights]);
        }

        this.model.set('highlights', highlights, { silent: true });
        this.model.trigger('change:highlights');

        if (this.tooltip && this.tooltip.tooltips && this.tooltip.tooltips.length) {
            this.tooltip.tooltips[0].hide();
        }

        this.apply_starred_story_selections(true);

        return true;
    },

    train_selected_text: function () {
        var feed_id = this.model.get('story_feed_id');
        var options = {};
        if (this.serialized_highlight) {
            options['selected_text'] = this.serialized_highlight;
        }

        if (this.tooltip && this.tooltip.tooltips && this.tooltip.tooltips.length) {
            this.tooltip.tooltips[0].hide();
        }

        // Clear the temporary selection highlight
        var $doc = this.$(".NB-feed-story-content");

        // Remove all temporary highlight marks
        this.$(".NB-starred-story-selection-highlight").each(function () {
            $(this).contents().unwrap();
        });
        this.$("[data-tippy]").each(function () {
            $(this).contents().unwrap();
        });

        $doc.removeAttr('id');

        // Restore permanent highlights
        this.apply_starred_story_selections();

        // Clear the window selection
        if (window.getSelection) {
            window.getSelection().removeAllRanges();
        } else if (document.selection) {
            document.selection.empty();
        }

        NEWSBLUR.reader.open_story_trainer(this.model.id, feed_id, options);

        return true;
    },

    show_search_highlight_menu: function (e) {
        e.preventDefault();
        e.stopPropagation();

        var $mark = $(e.currentTarget);
        var text = $mark.text();

        // Set the serialized_highlight to the text from the mark
        this.serialized_highlight = _.string.trim(text);

        // Close any existing tooltip
        if (this.tooltip && this.tooltip.tooltips && this.tooltip.tooltips.length) {
            this.tooltip.tooltips[0].hide();
        }

        // Show the highlight/train/search menu
        $mark.attr('title', this.selection_menu_html(false));
        var $t = tippy($mark.get(0), {
            appendTo: this.el,
            arrow: true,
            arrowType: 'round',
            size: 'large',
            duration: 350,
            animation: 'scale',
            trigger: 'click',
            interactive: true,
            performance: true,
            onHide: _.bind(function () {
                // Cleanup if needed
            }, this)
        });
        this.tooltip = $t;
        _.defer(function () {
            if ($t.tooltips && $t.tooltips.length) $t.tooltips[0].show();
        });
    },

    search_selected_text_site: function () {
        // Search current site/feed for the selected text
        var search_text = this.serialized_highlight;
        if (!search_text) return false;

        // Wrap in quotes if it contains spaces (phrase search)
        if (search_text.indexOf(' ') !== -1) {
            search_text = '"' + search_text + '"';
        }

        if (this.tooltip && this.tooltip.tooltips && this.tooltip.tooltips.length) {
            this.tooltip.tooltips[0].hide();
        }

        // Clear the temporary selection highlight
        this.$(".NB-starred-story-selection-highlight").each(function () {
            $(this).contents().unwrap();
        });
        this.$("[data-tippy]").each(function () {
            $(this).contents().unwrap();
        });

        // Set search flags and reload current context (stays in current site/feed)
        NEWSBLUR.reader.flags.searching = true;
        NEWSBLUR.reader.flags.search = search_text;
        window.history.pushState({}, "", $.updateQueryString('search', search_text, window.location.pathname));
        NEWSBLUR.reader.reload_feed({ force: true, search: search_text });
        NEWSBLUR.app.story_titles_header.show_hidden_story_titles();

        return true;
    },

    search_selected_text_folder: function () {
        // Search all site stories (folder-level) for the selected text
        var search_text = this.serialized_highlight;
        if (!search_text) return false;

        // Wrap in quotes if it contains spaces (phrase search)
        if (search_text.indexOf(' ') !== -1) {
            search_text = '"' + search_text + '"';
        }

        if (this.tooltip && this.tooltip.tooltips && this.tooltip.tooltips.length) {
            this.tooltip.tooltips[0].hide();
        }

        // Clear the temporary selection highlight
        this.$(".NB-starred-story-selection-highlight").each(function () {
            $(this).contents().unwrap();
        });
        this.$("[data-tippy]").each(function () {
            $(this).contents().unwrap();
        });

        // Open river stories (all site stories / folder-level) with search query
        NEWSBLUR.reader.flags.searching = true;
        NEWSBLUR.reader.flags.search = search_text;
        window.history.pushState({}, "", $.updateQueryString('search', search_text, window.location.pathname));
        NEWSBLUR.reader.open_river_stories(null, null, { force: true, search: search_text });
        NEWSBLUR.app.story_titles_header.show_hidden_story_titles();

        return true;
    },

    apply_starred_story_selections: function (force) {
        var highlights = this.model.user_highlights();
        var text_classifiers = this.classifiers && this.classifiers.texts ? _.keys(this.classifiers.texts) : [];
        var text_regex_classifiers = this.classifiers && this.classifiers.text_regex ? _.keys(this.classifiers.text_regex) : [];
        // Support legacy 'regex' key for backward compatibility
        var legacy_regex_classifiers = this.classifiers && this.classifiers.regex ? _.keys(this.classifiers.regex) : [];
        var search_query = NEWSBLUR.reader.flags.search;

        if (!force) {
            if ((!highlights || !highlights.length) && !text_classifiers.length && !text_regex_classifiers.length && !legacy_regex_classifiers.length && !search_query) return;
        }

        var $doc = this.$(".NB-feed-story-content");
        $doc.unmark();
        // Remove orphaned score icons left behind by unmark() which unwraps
        // mark elements but preserves their children including appended icons
        $doc.find('.NB-score-icon, .NB-score-icon-double').remove();

        $doc.attr('id', 'NB-highlighting');

        // Apply user saved highlights
        _.each(highlights, _.bind(function (highlight, index) {
            $doc.mark(highlight, {
                "className": "NB-highlight",
                "separateWordSearch": false,
                "acrossElements": true,
                "each": function (element) {
                    $(element).attr('data-highlight-index', index);
                }
            });
        }, this));

        // Apply text classifier highlights
        var self = this;
        _.each(text_classifiers, _.bind(function (classifier_text) {
            var classifier_score = this.classifiers.texts[classifier_text];
            var className = classifier_score > 0 ? "NB-classifier-highlight-positive" : (classifier_score <= -2 ? "NB-classifier-highlight-super-negative" : "NB-classifier-highlight-negative");
            var icon_html = self.score_icon_html(classifier_score);
            $doc.mark(classifier_text, {
                "className": className,
                "separateWordSearch": false,
                "acrossElements": true,
                "caseSensitive": false,
                "each": function (element) {
                    if (icon_html) $(element).append(icon_html);
                }
            });
        }, this));

        // Apply text regex classifier highlights
        _.each(text_regex_classifiers, _.bind(function (pattern) {
            try {
                var classifier_score = this.classifiers.text_regex[pattern];
                var className = classifier_score > 0 ? "NB-classifier-highlight-positive" : (classifier_score <= -2 ? "NB-classifier-highlight-super-negative" : "NB-classifier-highlight-negative");
                var icon_html = self.score_icon_html(classifier_score);
                var regex = new RegExp(pattern, 'gi');
                $doc.markRegExp(regex, {
                    "className": className,
                    "acrossElements": true,
                    "each": function (element) {
                        if (icon_html) $(element).append(icon_html);
                    }
                });
            } catch (e) {
                console.log(['Invalid regex pattern for highlighting', pattern, e]);
            }
        }, this));

        // Apply legacy regex classifier highlights (backward compatibility)
        _.each(legacy_regex_classifiers, _.bind(function (pattern) {
            try {
                var classifier_score = this.classifiers.regex[pattern];
                var className = classifier_score > 0 ? "NB-classifier-highlight-positive" : (classifier_score <= -2 ? "NB-classifier-highlight-super-negative" : "NB-classifier-highlight-negative");
                var icon_html = self.score_icon_html(classifier_score);
                var regex = new RegExp(pattern, 'gi');
                $doc.markRegExp(regex, {
                    "className": className,
                    "acrossElements": true,
                    "each": function (element) {
                        if (icon_html) $(element).append(icon_html);
                    }
                });
            } catch (e) {
                console.log(['Invalid regex pattern for highlighting', pattern, e]);
            }
        }, this));

        // Apply search highlights (last, so they appear on top)
        if (search_query) {
            var search_terms = this.parse_search_query(search_query);
            _.each(search_terms, _.bind(function (term) {
                $doc.mark(term, {
                    "className": "NB-search-highlight",
                    "separateWordSearch": false,
                    "acrossElements": true,
                    "caseSensitive": false
                });
            }, this));
        }

        $doc.removeAttr('id');
    },

    parse_search_query: function (query) {
        // Extract quoted phrases and generate n-grams from unquoted terms
        // Returns terms ordered longest-first for progressive highlighting
        var terms = [];
        var remaining = query;

        // Common English stop words that shouldn't be highlighted individually
        // These are only filtered for single-word terms, not phrases
        var stop_words = [
            'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been',
            'be', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
            'could', 'should', 'may', 'might', 'must', 'shall', 'can', 'need',
            'it', 'its', 'this', 'that', 'these', 'those', 'i', 'you', 'he',
            'she', 'we', 'they', 'what', 'which', 'who', 'whom', 'when', 'where',
            'why', 'how', 'all', 'each', 'every', 'both', 'few', 'more', 'most',
            'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same',
            'so', 'than', 'too', 'very', 'just', 'also', 'now', 'here', 'there',
            'then', 'once', 'if', 'about', 'into', 'through', 'during', 'before',
            'after', 'above', 'below', 'between', 'under', 'again', 'further',
            'any', 'because', 'being', 'get', 'got', 'him', 'her', 'his', 'hers',
            'me', 'my', 'our', 'ours', 'their', 'them', 'up', 'down', 'out', 'off'
        ];

        // Extract quoted phrases first (strip the quotes)
        // Handle straight quotes (") and curly/smart quotes (" ")
        var phrase_regex = /[""\u201C\u201D]([^""\u201C\u201D]+)[""\u201C\u201D]/g;
        var match;
        while ((match = phrase_regex.exec(query)) !== null) {
            terms.push(match[1]); // match[1] is the content without quotes
            remaining = remaining.replace(match[0], '');
        }

        // Get individual words from remaining text, filtering out operators
        var operators = ['AND', 'OR', 'NOT'];
        var words = [];
        var rawWords = remaining.trim().split(/\s+/);
        _.each(rawWords, function (word) {
            word = word.trim();
            if (word && operators.indexOf(word.toUpperCase()) === -1) {
                words.push(word);
            }
        });

        // Generate all contiguous n-grams from longest to shortest
        // For "a b c d e", generate: "a b c d e", then "a b c d", "b c d e",
        // then "a b c", "b c d", "c d e", etc.
        // Single-word stop words are filtered out to avoid highlighting common words
        if (words.length > 1) {
            for (var n = words.length; n >= 1; n--) {
                for (var i = 0; i <= words.length - n; i++) {
                    var ngram = words.slice(i, i + n).join(' ');
                    // Filter out single-word stop words
                    if (n === 1 && stop_words.indexOf(ngram.toLowerCase()) !== -1) {
                        continue;
                    }
                    terms.push(ngram);
                }
            }
        } else if (words.length === 1) {
            // Only add single word if it's not a stop word
            if (stop_words.indexOf(words[0].toLowerCase()) === -1) {
                terms.push(words[0]);
            }
        }

        return terms;
    },

    show_manage_menu_rightclick: function (e) {
        if (!NEWSBLUR.assets.preference('show_contextmenus')) return;

        return this.show_manage_menu(e);
    },

    show_manage_menu: function (e) {
        e.preventDefault();
        e.stopPropagation();
        NEWSBLUR.reader.show_manage_menu('story', this.$el, {
            story_id: this.model.id,
            feed_id: this.model.get('story_feed_id'),
            rightclick: e.which >= 2
        });
        return false;
    },

    show_feed_manage_menu_rightclick: function (e) {
        if (!NEWSBLUR.assets.preference('show_contextmenus')) return;
        return this.show_feed_manage_menu(e);
    },

    show_feed_manage_menu: function (e) {
        e.preventDefault();
        e.stopPropagation();
        NEWSBLUR.reader.show_manage_menu('feed', this.$el, {
            feed_id: this.model.get('story_feed_id'),
            from_story_feed_bar: true,
            rightclick: e.which >= 2
        });
        return false;
    },

    mouseenter_feed_manage_icon: function () {
        if (this.$el.offset().top > $(window).height() / 2) {
            this.$el.addClass('NB-hover-inverse');
        }
    },

    mouseleave_feed_manage_icon: function () {
        this.$el.removeClass('NB-hover-inverse');
    },

    show_story_changes: function () {
        NEWSBLUR.assets.fetch_story_changes(this.model.get('story_hash'), !this.model.get('showing_diff'), _.bind(function (data) {
            this.model.set('showing_diff', !this.model.get('showing_diff'));
            this.model.set('story_content', data.story['story_content']);
            NEWSBLUR.app.story_list.fetch_story_locations_in_feed_view();
        }, this), function () {
            console.log(['Failed to fetch story changes']);
        });
    },

    open_feed: function () {
        NEWSBLUR.reader.open_feed(this.model.get('story_feed_id'));
    },

    save_classifier: function (e) {
        var $tag = $(e.currentTarget);
        var classifier_type = $tag.hasClass('NB-feed-story-tag') ? 'tag' : 'author';
        // Clone and strip score icons before reading value
        var $clean = $tag.clone();
        $clean.find('.NB-score-icon, .NB-score-icon-double, .NB-pill-view-classifier').remove();
        var value = classifier_type === 'tag' ? _.string.trim($clean.html()) : _.string.trim($clean.text());
        // Cycle: +1 → -1, -1 → 0, -2 → 0, neutral → +1 (skip super downvote in inline cycle)
        var score = $tag.hasClass('NB-score-1') ? -1 : ($tag.hasClass('NB-score--1') || $tag.hasClass('NB-score--2')) ? 0 : 1;
        var feed_id = this.model.get('story_feed_id');
        var data = {
            'feed_id': feed_id
        };

        if (score == 0) {
            data['remove_like_' + classifier_type] = value;
        } else if (score == 1) {
            data['like_' + classifier_type] = value;
        } else if (score == -1) {
            data['dislike_' + classifier_type] = value;
        }
        this.model.set('visible', true, { silent: true });
        NEWSBLUR.assets.classifiers[feed_id][classifier_type + 's'][value] = score;
        NEWSBLUR.assets.recalculate_story_scores(feed_id, { story_view: this });
        NEWSBLUR.assets.save_classifier(data, function (resp) {
            NEWSBLUR.reader.feed_unread_count(feed_id);
        });

        this.model.trigger('change:intelligence');
        this.preserve_classifier_color(classifier_type, value, score);
    },

    save_url_classifier: function () {
        // Open the Intelligence Trainer instead of toggling inline
        // URL classifiers are complex and benefit from the full trainer interface
        this.open_story_trainer();
    },

    classifier_filter_button_html: function (type, value) {
        if (!type || !value) return '';

        var escaped_type = _.escape(String(type));
        var escaped_value = _.escape(String(value));
        var escaped_label = _.escape(gettext('View matching stories'));
        return '<button type="button" class="NB-pill-view-classifier" ' +
            'title="' + escaped_label + '" aria-label="' + escaped_label + '" ' +
            'data-classifier-type="' + escaped_type + '" ' +
            'data-classifier-value="' + escaped_value + '">' +
            // Same glyph as the trainer rows; defined once in
            // media/js/newsblur/reader/reader_classifier.js.
            NEWSBLUR.ClassifierConstants.MATCHING_STORIES_ICON +
            '</button>';
    },

    show_classifier_filter_tooltip: function (e) {
        var $button = $(e.currentTarget);
        var tooltip = $button.data('NB-classifier-filter-tooltip');
        if (!tooltip) {
            var tooltip_instance = tippy(e.currentTarget, {
                appendTo: this.el,
                arrow: true,
                arrowType: 'round',
                size: 'small',
                duration: 150,
                animation: 'scale',
                trigger: 'manual',
                interactive: false,
                performance: true
            });
            if (tooltip_instance && tooltip_instance.tooltips && tooltip_instance.tooltips.length) {
                tooltip = tooltip_instance.tooltips[0];
                $button.data('NB-classifier-filter-tooltip', tooltip);
            }
        }
        if (tooltip) tooltip.show();
    },

    hide_classifier_filter_tooltip: function (e) {
        var tooltip = $(e.currentTarget).data('NB-classifier-filter-tooltip');
        if (tooltip) tooltip.hide();
    },

    open_classifier_filter_from_pill: function (e) {
        if (e) { e.preventDefault(); e.stopPropagation(); }
        var $trigger = $(e.currentTarget);
        var type = $trigger.attr('data-classifier-type');
        var value = $trigger.attr('data-classifier-value');
        if (!type || !value) return;
        var filter_options = NEWSBLUR.reader.classifier_filter_context_for_matching_view(
            this.model.get('story_feed_id'),
            this.model.get('story_hash')
        );
        filter_options.classifier_scope = 'feed';
        filter_options.origin = 'pill';
        NEWSBLUR.reader.open_classifier_filter(type, value, filter_options);
    },

    open_trainer_from_ai_pill: function () {
        this.open_story_trainer();
    },

    open_story_trainer: function () {
        var feed_id = this.model.get('story_feed_id');
        var options = {};
        NEWSBLUR.reader.open_story_trainer(this.model.id, feed_id, options);
    },

    toggle_starred: function () {
        this.model.toggle_starred();
    }

});
