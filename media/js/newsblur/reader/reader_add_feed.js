NEWSBLUR.ReaderAddFeed = NEWSBLUR.ReaderPopover.extend({

    className: "NB-add-popover",

    options: {
        'width': 608,
        'popover_class': 'NB-add-popover-container',
        'anchor': function () {
            return NEWSBLUR.reader.$s.$add_button;
        },
        // The anchor is the icon rail button now. jquery.newsblur's align() has no
        // "right of the anchor" placement, so render() aligns against the rail
        // itself and offsets past it (see align_to_rail below).
        'placement': '-left -bottom',
        offset: {
            top: 0,
            left: 0
        },
        'onOpen': _.bind(function () {
            this.focus_add_feed();
        }, this)
    },

    events: {
        "click .NB-modal-cancel": "close",
        "click .NB-add-url-submit": "save_add_url",
        "click .NB-add-browse": "open_browse_all",
        "click .NB-add-folder-icon": "open_add_folder",
        "click .NB-add-folder-submit": "save_add_folder",
        "focus .NB-add-url": "handle_focus_add_site",
        "blur .NB-add-url": "handle_blur_add_site",
        "change .NB-folders": "update_folder_placeholder"
    },

    initialize: function (options) {
        this.options = _.extend({}, this.options, options);
        NEWSBLUR.ReaderPopover.prototype.initialize.call(this);
        this.model = NEWSBLUR.assets;
        this.render();
        this.handle_keystrokes();
        this.setup_autocomplete();
        this.focus_add_feed();
    },

    on_show: function () {
        this.options.onOpen();
    },

    on_hide: function () {

    },

    render: function () {
        var self = this;

        NEWSBLUR.ReaderPopover.prototype.render.call(this);

        this.$el.html($.make('div', { className: 'NB-add' }, [
            $.make('div', { className: 'NB-add-form' }, [
                $.make('div', { className: 'NB-fieldset NB-modal-submit' }, [
                    $.make('div', { className: 'NB-add-header' }, [
                        $.make('span', { className: 'NB-add-header-icon' }, '+'),
                        $.make('span', gettext('Add any site or feed')),
                        $.make('div', { className: 'NB-add-folder-row' }, [
                            $.make('span', { className: 'NB-add-folder-label' }, gettext('in')),
                            NEWSBLUR.utils.make_folders(this.options.folder_title),
                            $.make('div', { className: 'NB-add-folder-icon', title: gettext("New folder"), role: "button" })
                        ])
                    ]),
                    $.make('div', { className: 'NB-add-input-row' }, [
                        $.make('input', { type: 'text', id: 'NB-add-url', className: 'NB-add-url', name: 'url', value: self.options.url, placeholder: gettext('Site URL or search by name...') }),
                        $.make('div', { className: 'NB-loading' }),
                        $.make('div', { className: 'NB-add-url-submit' }, gettext('Add site'))
                    ]),
                    $.make('div', { className: 'NB-add-browse-row' }, [
                        // reader_add_feed.js: the sidebar "Add Site" row is gone, so the
                        // full discovery page needs an entry point from the popover.
                        $.make('span', { className: 'NB-add-browse', role: 'button' }, gettext('Browse all sites'))
                    ]),
                    $.make('div', { className: "NB-add-folder NB-hidden" }, [
                        $.make('div', { className: 'NB-add-folder-input-row' }, [
                            $.make('input', { type: 'text', id: 'NB-add-folder', className: 'NB-add-folder-input', name: 'new_folder_name', placeholder: gettext("New folder name...") }),
                            $.make('div', { className: 'NB-loading' }),
                            $.make('div', { className: 'NB-add-folder-submit' }, gettext('Create'))
                        ])
                    ]),
                    $.make('div', { className: 'NB-group NB-error' }, [
                        $.make('div', { className: 'NB-error-message' })
                    ])
                ]),
            ])
        ]));

        if (NEWSBLUR.Globals.is_anonymous) {
            this.$el.addClass('NB-signed-out');
        }

        this.align_to_rail();

        return this;
    },

    // align() can only place an element left of, inside, or centered on its
    // target, so the panel is aligned to the rail box and then offset past it.
    // Aligning to the 46px button instead would overlap the 76px rail.
    align_to_rail: function () {
        var $rail = $('#NB-rail');
        var $button = this.anchor();
        if (!$rail.length || !$button || !$button.length || !this.$popover) return;

        var rail_rect = $rail[0].getBoundingClientRect();
        var button_rect = $button[0].getBoundingClientRect();
        var gap = 8;
        var is_rtl = NEWSBLUR.utils.is_rtl();

        this.$popover.align($rail, '-left -bottom', {
            top: Math.round(button_rect.top),
            left: is_rtl
                ? Math.round(rail_rect.left) - this.$popover.outerWidth() - gap
                : Math.round(rail_rect.right) + gap
        });
    },

    open_browse_all: function (e) {
        e.preventDefault();
        this.close();
        NEWSBLUR.reader.open_add_site();
    },

    focus_add_feed: function () {
        var $add = this.options.init_folder ?
            this.$('.NB-add-folder-input') :
            this.$('.NB-add-url');
        if (!NEWSBLUR.Globals.is_anonymous) {
            // Defer by a tick so the popover is in the DOM, but do not wait 200ms:
            // the input has to be typeable as soon as the panel appears.
            _.defer(_.bind(function () {
                if (this.options.init_folder) {
                    this.open_add_folder();
                }
                $add.focus();
            }, this));
        }
    },

    setup_autocomplete: function () {
        var self = this;
        var $add = this.$('.NB-add-url');

        $add.autocomplete({
            minLength: 1,
            appendTo: ".NB-add-form",
            source: function (request, response) {
                $add.addClass('NB-autocomplete-loading');
                $.getJSON('/discover/autocomplete', { term: request.term })
                    .done(function (data) {
                        response(data.slice(0, 10));
                    })
                    .fail(function () {
                        response([]);
                    })
                    .always(function () {
                        $add.removeClass('NB-autocomplete-loading');
                    });
            },
            position: {
                my: "left bottom",
                at: "left top",
                collision: "none"
            },
            select: function (e, ui) {
                $add.val(ui.item.value);
                return false;
            },
            search: function (e, ui) {
            },
            open: function (e, ui) {
                if (!$add.is(":focus")) {
                    e.preventDefault();
                    $add.autocomplete('close');
                    return false;
                }
            },
            close: function (e, ui) {
            },
            change: function (e, ui) {
            }
        }).data("ui-autocomplete")._renderItem = function (ul, item) {
            var feed = new NEWSBLUR.Models.Feed(item);
            var freshness = self.make_freshness_indicator(item.last_story_date);
            var num_subscribers = Math.max(0, item.num_subscribers);
            var subscriber_text = interpolate(ngettext("%(count)s subscriber", "%(count)s subscribers", num_subscribers), {count: Inflector.commas(num_subscribers)}, true);
            return $.make('li', [
                $.make('a', { className: 'NB-autocomplete-item' }, [
                    $.favicon_el(feed, {
                        image_class: 'NB-add-autocomplete-favicon',
                        emoji_class: 'NB-add-autocomplete-favicon NB-feed-emoji',
                        colored_class: 'NB-add-autocomplete-favicon NB-feed-icon-colored'
                    }),
                    $.make('div', { className: 'NB-autocomplete-content' }, [
                        $.make('div', { className: 'NB-autocomplete-top-row' }, [
                            $.make('div', { className: 'NB-add-autocomplete-title' }, item.label),
                            $.make('div', { className: 'NB-add-autocomplete-subscribers' }, subscriber_text)
                        ]),
                        $.make('div', { className: 'NB-autocomplete-bottom-row' }, [
                            $.make('div', { className: 'NB-add-autocomplete-address' }, item.value),
                            freshness
                        ])
                    ])
                ])
            ]).data("ui-autocomplete-item", item).prependTo(ul);
        };
        $add.data("ui-autocomplete")._resizeMenu = function () {
            var ul = this.menu.element;
            ul.outerWidth(self.$('.NB-add-url').outerWidth());
        };
    },

    handle_focus_add_site: function () {
        var $add = this.$('.NB-add-url');
        $add.autocomplete('search');
    },

    handle_blur_add_site: function () {
        var $add = this.$('.NB-add-url');
        $add.autocomplete('close');
    },

    handle_keystrokes: function () {
        var self = this;

        this.$('.NB-add-url').bind('keyup', 'return', function (e) {
            e.preventDefault();
            self.save_add_url();
        });

        this.$('.NB-add-folder-input').bind('keyup', 'return', function (e) {
            e.preventDefault();
            self.save_add_folder();
        });
    },

    make_freshness_indicator: function (last_story_date) {
        if (!last_story_date) {
            return $.make('div', { className: 'NB-autocomplete-freshness NB-freshness-none' }, [
                $.make('span', { className: 'NB-freshness-dot' }),
                $.make('span', { className: 'NB-freshness-label' }, gettext('No stories'))
            ]);
        }

        var last_date = new Date(last_story_date);
        if (isNaN(last_date.getTime())) return null;

        var now = new Date();
        var days_ago = Math.floor((now - last_date) / (1000 * 60 * 60 * 24));
        var freshness_class = 'NB-autocomplete-freshness';
        var label;

        if (days_ago < 365) {
            freshness_class += ' NB-freshness-active';
            // reader_add_feed.js: Abbreviated ages keep plural forms for languages that inflect them.
            if (days_ago < 1) {
                label = gettext('Updated today');
            } else if (days_ago < 7) {
                label = interpolate(ngettext("%(count)sd ago", "%(count)sd ago", days_ago), {count: days_ago}, true);
            } else if (days_ago < 30) {
                var weeks_ago = Math.floor(days_ago / 7);
                label = interpolate(ngettext("%(count)sw ago", "%(count)sw ago", weeks_ago), {count: weeks_ago}, true);
            } else {
                var months_ago = Math.floor(days_ago / 30);
                label = interpolate(ngettext("%(count)smo ago", "%(count)smo ago", months_ago), {count: months_ago}, true);
            }
        } else {
            freshness_class += ' NB-freshness-stale';
            label = interpolate(gettext("Stale %(date)s"), {date: last_date.toLocaleDateString(document.documentElement.lang || undefined, { month: 'short', year: 'numeric' })}, true);
        }

        return $.make('div', { className: freshness_class }, [
            $.make('span', { className: 'NB-freshness-dot' }),
            $.make('span', { className: 'NB-freshness-label' }, label)
        ]);
    },

    // ===========
    // = Actions =
    // ===========

    save_add_url: function () {
        var $submit = this.$('.NB-add-url-submit');
        var $error = this.$('.NB-error');
        var $loading = this.$('.NB-add-site .NB-loading');

        var url = this.$('.NB-add-url').val();
        var folder = this.$('.NB-folders').val();

        $error.slideUp(300);
        $loading.addClass('NB-active');
        $submit.addClass('NB-disabled').text(gettext('Adding site...'));

        NEWSBLUR.reader.flags['reloading_feeds'] = true;
        this.model.save_add_url(url, folder, $.rescope(this.post_save_add_url, this), $.rescope(this.error, this));
    },

    post_save_add_url: function (e, data) {
        NEWSBLUR.log(['Data', data]);
        var $submit = this.$('.NB-add-url-submit');
        var $loading = this.$('.NB-add-site .NB-loading');
        $loading.removeClass('NB-active');
        NEWSBLUR.reader.flags['reloading_feeds'] = false;

        if (data.code > 0) {
            NEWSBLUR.assets.load_feeds(function () {
                if (data.feed) {
                    NEWSBLUR.reader.open_feed(data.feed.id);
                }
            });
            NEWSBLUR.reader.handle_mouse_indicator_hover();
            $submit.text(gettext('Added!'));
            this.close();
            this.model.preference('has_setup_feeds', true);
            NEWSBLUR.reader.check_hide_getting_started();
        } else {
            var url = this.$('.NB-add-url').val();
            this.handle_add_failure(url, data);
            $submit.removeClass('NB-disabled');
        }
    },

    handle_add_failure: function (input, data) {
        input = (input || '').trim();
        if (input) {
            // reader_add_feed.js: the Add Site modal has a single search tab now,
            // which resolves URLs and search terms alike.
            this.close(function () {
                NEWSBLUR.reader.open_add_site({ tab: 'search', initial_query: input });
            });
        } else {
            this.error(data);
        }
    },

    error: function (data) {
        var $submit = this.$('.NB-add-url-submit');
        var $error = this.$('.NB-error');

        $(".NB-error-message", $error).text(data.message || gettext("Oh no, there was a problem grabbing that URL and there's no good explanation for what happened."));
        $error.slideDown(300);
        $submit.text(gettext('Add site'));
        NEWSBLUR.reader.flags['reloading_feeds'] = false;
    },

    update_folder_placeholder: function () {
        var parent_folder = this.$('.NB-folders option:selected').text().trim() || gettext('Top Level');
        this.$('.NB-add-folder-input').attr('placeholder', interpolate(gettext("New folder under %(folder)s..."), {folder: parent_folder}, true));
    },

    open_add_folder: function () {
        var $folder = this.$(".NB-add-folder");
        var $icon = this.$(".NB-add-folder-icon");

        if (this._open_folder) {
            $folder.slideUp(300);
            $icon.removeClass('NB-active');
            this._open_folder = false;
        } else {
            this._open_folder = true;
            $icon.addClass('NB-active');
            this.update_folder_placeholder();
            $folder.slideDown(300);
        }
    },

    save_add_folder: function () {
        var $submit = this.$('.NB-add-folder-submit');
        var $error = this.$('.NB-error');
        var $loading = this.$('.NB-add-folder .NB-loading');

        var folder = $('.NB-add-folder-input').val();
        var parent_folder = this.$('.NB-folders').val();

        $error.slideUp(300);
        $loading.addClass('NB-active');
        $submit.addClass('NB-disabled').text(gettext('Adding site...'));

        this.model.save_add_folder(folder, parent_folder, $.rescope(this.post_save_add_folder, this));
    },

    post_save_add_folder: function (e, data) {
        var $submit = this.$('.NB-add-folder-submit');
        var $error = this.$('.NB-error');
        var $loading = this.$('.NB-add-folder .NB-loading');
        var $folder = $('.NB-add-folder-input');
        $loading.removeClass('NB-active');
        $submit.removeClass('NB-disabled');

        if (data.code > 0) {
            $submit.text(gettext('Added!'));
            NEWSBLUR.assets.load_feeds(_.bind(function () {
                var $folders = NEWSBLUR.utils.make_folders($folder.val());
                this.$(".NB-folders").replaceWith($folders);
                this.open_add_folder();
                $submit.text(gettext('Add Folder'));
                $folder.val('');
                this.$('.NB-add-url').focus();
            }, this));
        } else {
            $(".NB-error-message", $error).text(data.message);
            $error.slideDown(300);
            $submit.text(gettext('Add Folder'));
        }
    }

});
