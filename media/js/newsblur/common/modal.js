NEWSBLUR.Modal = function (options) {
    var defaults = {
        width: 600,
        overlayClose: true
    };

    this.options = _.extend({}, defaults, options);
    this.model = NEWSBLUR.assets;
    this.runner();
    this.flags = {};
};

NEWSBLUR.Modal.prototype = {

    runner: function () { },

    open_modal: function (callback) {
        var self = this;

        // modal.js: remember what opened the dialog so Escape, the overlay and
        // the close button all return focus to the same place. Capturing this
        // inside onOpen is too late: simplemodal has already moved focus into
        // the dialog by then.
        var active = document.activeElement;
        this.$previously_focused = active && active !== document.body && !this.$modal[0].contains(active)
            ? $(active)
            : null;

        this.simplemodal = this.$modal.modal({
            'minWidth': this.options.width || 600,
            'maxWidth': this.options.width || 600,
            'overlayClose': this.options.overlayClose,
            'onOpen': function (dialog) {
                self.flags.open = true;
                dialog.container.addClass(self.options.modal_container_class);
                self.prepare_dialog_accessibility(dialog);

                // modal.js: reveal the dialog in one pass and fade it with a single
                // compositor-only opacity transition. Three nested jQuery fadeIn calls
                // used to keep the content hidden for 400ms, finish at 600ms and cost
                // ~10ms of main thread work per frame on a 500 node dialog, which is
                // what made opening a settings window feel like a stall.
                // simplemodal sets the overlay to opacity 0.5 inline, so fade each
                // part towards whatever opacity it already had, never a hard coded 1.
                // modal.js: the overlay is a full-viewport translucent layer, so fading
                // its opacity blends the entire screen on every frame. Show the dim
                // instantly and fade only the dialog card, which is what the eye tracks.
                // Without GPU compositing this removes nine full-screen blends per open.
                $(dialog.overlay[0]).show();
                var parts = [dialog.container[0], dialog.data[0]];
                var restore = [];
                $(parts).show().each(function () {
                    restore.push([this, this.style.opacity || '1']);
                    this.style.opacity = '0';
                });
                // modal.js: start the fade on the next frame. Writing opacity 0 and
                // the target in the same task made the browser skip the transition,
                // so the dialog popped in and the fade never ran.
                window.requestAnimationFrame(function () {
                    for (var i = 0; i < restore.length; i++) {
                        restore[i][0].style.transition = 'opacity 150ms ease-out';
                        restore[i][0].style.opacity = restore[i][1];
                    }
                });

                setTimeout(function () {
                    // $(window).resize();
                    self.resize();
                    self.flags.modal_loaded = true;
                }, 0);

                setTimeout(function () {
                    for (var i = 0; i < restore.length; i++) {
                        restore[i][0].style.transition = '';
                        restore[i][0].style.opacity = restore[i][1] === '1' ? '' : restore[i][1];
                    }
                    // modal.js: a dialog closed inside the fade must not run its
                    // onOpen callback against elements that are already gone.
                    if (!self.flags.open) return;
                    if (self.options.onOpen) {
                        self.options.onOpen();
                    }
                    if (callback) {
                        callback();
                    }
                }, 160);
            },
            'onShow': function (dialog) {
                $('#simplemodal-container').corner('6px');
                if (self.options.onShow) {
                    self.options.onShow();
                }
            },
            'onClose': function (dialog, callback) {
                self.flags.open = false;
                self.release_background_inert();
                dialog.data.hide().empty().remove();
                dialog.container.hide().empty().remove();
                // modal.js: drop the dim in the same frame as the card, instead of a
                // 200ms fade that leaves the page dimmed after the dialog is gone.
                dialog.overlay.empty().remove();
                if (self.options.onClose) {
                    self.options.onClose();
                }
                $.modal.close(callback);
                $('.NB-modal-holder').empty().remove();

                // modal.js: an onClose handler may open the next dialog (the
                // preferences window links to premium, for example). In that
                // case the new dialog owns focus and must keep it.
                if (!self.flags.open && !$('.simplemodal-container').length) {
                    self.restore_focus();
                }
            }
        });
    },

    resize: function () {
        // $(window).trigger('resize.simplemodal');
        $.modal.resize();
    },

    prepare_dialog_accessibility: function (dialog) {
        var $container = dialog.container;
        var $data = dialog.data;

        // modal.js: simplemodal already sets role="dialog" and traps Tab. The
        // missing pieces for the ARIA dialog pattern are the modal flag, an
        // accessible name, and making the page behind the overlay inert so a
        // screen reader cannot wander out of the dialog.
        $container.attr('aria-modal', 'true');
        dialog.overlay.attr('aria-hidden', 'true');

        var $title = $data.find('.NB-modal-title').filter(function () {
            return $.trim($(this).text()).length > 0;
        }).first();
        if (!$title.length) {
            $title = $data.find('h1, h2, h3').filter(function () {
                return $.trim($(this).text()).length > 0;
            }).first();
        }

        if ($title.length) {
            var title_id = $title.attr('id');
            if (!title_id) {
                NEWSBLUR.Modal._next_title_id = (NEWSBLUR.Modal._next_title_id || 0) + 1;
                title_id = 'NB-modal-title-' + NEWSBLUR.Modal._next_title_id;
                $title.attr('id', title_id);
            }
            $container.attr('aria-labelledby', title_id);
        } else if (this.options.aria_label) {
            $container.attr('aria-label', this.options.aria_label);
        }

        $container.find('.simplemodal-close').attr('aria-label', gettext('Close'));

        this.inert_elements = [];
        var body = document.body;
        for (var i = 0; i < body.children.length; i++) {
            var element = body.children[i];
            if (element === $container[0] || element === dialog.overlay[0]) continue;
            if (/^(SCRIPT|STYLE|LINK|META|NOSCRIPT|TEMPLATE)$/.test(element.tagName)) continue;
            if (element.classList && (element.classList.contains('simplemodal-container') ||
                    element.classList.contains('simplemodal-overlay') ||
                    element.classList.contains('simplemodal-iframe'))) continue;
            this.inert_elements.push([element, element.inert]);
            element.inert = true;
        }
    },

    release_background_inert: function () {
        _.each(this.inert_elements || [], function (entry) {
            entry[0].inert = entry[1];
        });
        this.inert_elements = [];
    },

    restore_focus: function () {
        var $target = this.$previously_focused;
        this.$previously_focused = null;

        if ($target && $target.length && $.contains(document.documentElement, $target[0]) && $target.is(':visible')) {
            $target.focus();
            return;
        }

        // modal.js: the trigger can disappear while the dialog is open (a feed
        // row that was deleted, a menu item that was rebuilt). Fall back to the
        // feed list so keyboard users are not dropped back on <body>.
        var $reader = $('#feed_list');
        if ($reader.length && $reader.is(':visible')) {
            if (!$reader.attr('tabindex')) {
                $reader.attr('tabindex', '-1');
            }
            $reader.focus();
        }
    },

    close: function (callback) {
        $('.NB-modal-loading', this.$modal).removeClass('NB-active');
        $.modal.close(callback);
    },

    make_feed_chooser: function (options) {
        options = options || {};
        options.selected_folder_title = this.model.folder_title;
        options.feed_id = this.feed_id;

        return NEWSBLUR.utils.make_feed_chooser(options);
    },

    initialize_feed: function (feed_id) {
        this.feed_id = feed_id;
        if (this.options.embedded) {
            this.feed = NEWSBLUR.stats_feed;
        } else {
            this.feed = this.model.get_feed(feed_id);
        }
        var $feed_icon = $.favicon_el(this.feed, {
            image_class: 'NB-modal-feed-image feed_favicon',
            emoji_class: 'NB-modal-feed-image NB-feed-emoji',
            colored_class: 'NB-modal-feed-image NB-feed-icon-colored'
        });
        var $feed_icon_container = $('.NB-modal-subtitle .NB-modal-feed-image', this.$modal).first();
        if ($feed_icon) {
            if ($feed_icon_container.length) {
                $feed_icon_container.replaceWith($feed_icon);
            } else {
                $('.NB-modal-subtitle', this.$modal).prepend($feed_icon);
            }
        }
        $('.NB-modal-subtitle .NB-modal-feed-title', this.$modal).html(this.feed.get('feed_title'));
        // Hide subscriber count for starred/saved tags
        if (this.feed.is_starred()) {
            $('.NB-modal-subtitle .NB-modal-feed-subscribers', this.$modal).hide();
        } else {
            var num_subscribers = this.feed.get('num_subscribers');
            $('.NB-modal-subtitle .NB-modal-feed-subscribers', this.$modal).html(interpolate(ngettext("%(count)s subscriber", "%(count)s subscribers", num_subscribers), { count: Inflector.commas(num_subscribers) }, true)).show();
        }
    },

    initialize_folder: function (folder_title) {
        this.folder_title = folder_title;
        this.folder = this.model.get_folder(folder_title);

        var $folder_icon = $.favicon_el('river:' + folder_title, {
            image_class: 'NB-modal-feed-image feed_favicon',
            emoji_class: 'NB-modal-feed-image NB-folder-emoji',
            colored_class: 'NB-modal-feed-image NB-folder-icon-colored'
        });
        var $folder_icon_container = $('.NB-modal-subtitle .NB-modal-feed-image', this.$modal).first();
        if ($folder_icon) {
            if ($folder_icon_container.length) {
                $folder_icon_container.replaceWith($folder_icon);
            } else {
                $('.NB-modal-subtitle', this.$modal).prepend($folder_icon);
            }
        }
        $('.NB-modal-subtitle .NB-modal-feed-title', this.$modal).html(this.folder_title);
        $('.NB-modal-subtitle .NB-modal-feed-subscribers', this.$modal).hide();
    },

    switch_tab: function (newtab) {
        var $modal_tabs = $('.NB-modal-tab', this.$modal);
        var $tabs = $('.NB-tab', this.$modal);

        $modal_tabs.removeClass('NB-active');
        $tabs.removeClass('NB-active');

        $modal_tabs.filter('.NB-modal-tab-' + newtab).addClass('NB-active');
        $tabs.filter('.NB-tab-' + newtab).addClass('NB-active');
    }

};
