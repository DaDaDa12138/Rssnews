NEWSBLUR.ReaderPopover = Backbone.View.extend({

    _open: false,

    events: {
        "click .NB-modal-cancel": "close"
    },

    initialize: function (options) {
        _.bindAll(this, 'handle_esc');
        this.options = _.extend({}, {
            width: 236,
            animate: true,
            // A full-viewport translucent overlay forces the browser to repaint the whole
            // page behind the popover on every frame. Anchored popovers already close on
            // outside clicks through autohide, so they do not need a dimming layer.
            overlay: false,
            offset: {
                top: 0,
                left: 0
            }
        }, this.options, options);
        this.$anchor = this.anchor();
        $(document).bind('keydown', 'esc', this.handle_esc);
    },

    render: function ($content) {
        var self = this;
        this._open = true;
        this._closing = false;

        this.$popover = $.make("div", { className: "NB-popover popover fade" }, [
            $.make('div', { className: "arrow" }),
            $.make('div', { className: "popover-inner" }, [
                $.make('div', { className: "popover-content" }, $content || this.$el)
            ])
        ]);

        this.$overlay = this.options.overlay ?
            $.make('div', { className: 'NB-overlay fade ' + (this.options.overlay_top && "NB-top") }) :
            $();
        $('body').append(this.$overlay);

        this.$popover.width(this.options.width);

        $('body').append(this.$popover);

        this.$popover.addClass(this.options.placement.replace('-', '').replace(' ', '-'));
        this.$popover.addClass(this.options.popover_class);
        this.$popover.align(this.anchor(), this.options.placement, this.options.offset);
        // reader_popover.js: in RTL, flip the popover around its anchor. The arrow keeps
        // its placement class and the mirrored CSS (utils/rtl_css.py) moves it to the other side.
        NEWSBLUR.utils.mirror_aligned_element(this.$popover, this.anchor());
        this.autohide = this.$popover.autohide({
            clickable: true,
            onHide: _.bind(this.close, this)
        });

        if (this.options.animate) {
            this.$popover.addClass("in");
            this.$overlay.addClass("in");
        }

        // Need time to let animation begin so height registers as non-zero
        this.check_height();
        // The box grows to fit its content after align() has run, so put the
        // settled box back inside the viewport.
        _.defer(_.bind(this.constrain_to_viewport, this));

        // reader_popover.js: the control that opened the popover advertises the state.
        if (this.$anchor && this.$anchor.attr('aria-expanded')) {
            this.$anchor.attr('aria-expanded', 'true');
        }

        return this;
    },

    // reader_popover.js: $.fn.align constrains the width it measures, but a
    // popover sizes itself from its content a frame later. On a phone the feed
    // options popover ended up 20px past the left edge of the screen.
    constrain_to_viewport: function () {
        var el = this.$popover && this.$popover[0];
        if (!el || !el.parentNode) return;
        var rect = el.getBoundingClientRect();
        var viewport_width = window.innerWidth;
        if (rect.left >= 0 && rect.right <= viewport_width) return;
        var left = Math.min(Math.max(0, rect.left), Math.max(0, viewport_width - rect.width));
        this.$popover.css({ left: left + 'px', right: 'auto' });
    },

    check_height: function () {
        _.defer(_.bind(function () {
            if ($(window).height() < (this.$popover.height() + 100)) {
                this.$popover.addClass('NB-popover-scroll');
                $(".popover-content", this.$popover).css('max-height', $(window).height() - 100);
                this.$popover.width(this.options.width + 18);
            }
        }, this));
    },

    close: function (e, hide_callback) {
        if (this._closing) return false;
        this._closing = true;
        if (this.$anchor && this.$anchor.attr('aria-expanded')) {
            this.$anchor.attr('aria-expanded', 'false');
        }
        var $el = window.a = this.$popover;
        var self = this;
        if (_.isFunction(e)) hide_callback = e;
        hide_callback = hide_callback || $.noop;
        this.$popover.removeClass('in');
        this.$overlay.removeClass('in');
        $(document).unbind('keydown', this.handle_esc);
        this.options.on_hide && this.options.on_hide();

        function removeWithAnimation() {
            var timeout = setTimeout(function () {
                $el.off($.support.transition.end);
                if (!self._open) return;
                self._open = false;
                self._closing = false;
                $el.remove();
                self.$overlay.remove();
                self.autohide.removeHide();
                self.remove();
                hide_callback();
            }, 500);

            $el.one($.support.transition.end, function () {
                clearTimeout(timeout);
                if (!self._open) return;
                self._open = false;
                self._closing = false;
                $el.remove();
                self.$overlay.remove();
                self.autohide.removeHide();
                self.remove();
                hide_callback();
            });
        }

        if ($.support.transition && this.$popover.hasClass('fade')) {
            removeWithAnimation();
        } else {
            this._open = false;
            this._closing = false;
            this.$popover.remove();
            this.$overlay.remove();
            this.autohide.removeHide();
            this.remove();
            hide_callback();
        }

        return false;
    },

    anchor: function () {
        if (_.isFunction(this.options.anchor)) {
            return this.options.anchor();
        } else {
            return $(this.options.anchor);
        }
    },

    handle_esc: function (e) {
        if (this._open) {
            e.preventDefault();
            e.stopPropagation();

            this.close();

            return false;
        }
    }

}, {

    create: function (options) {
        var current = NEWSBLUR.ReaderPopover._popover;
        var anchor = options && options.anchor;
        var $anchor = anchor ? $(_.isFunction(anchor) ? anchor() : anchor) : $();

        // reader_popover.js: tapping the control that opened a popover closes it
        // again. Closing and immediately rebuilding the same popover made every
        // toolbar button look stuck open on touch screens.
        if (current && current._open && !current._closing && $anchor.length &&
            current.$anchor && current.$anchor[0] === $anchor[0]) {
            current.close();
            return;
        }

        if (current && current._open) {
            current.close();
        }

        NEWSBLUR.ReaderPopover._popover = new this(options);
        return NEWSBLUR.ReaderPopover._popover;
    },

    close: function () {
        if (NEWSBLUR.ReaderPopover._popover && NEWSBLUR.ReaderPopover._popover._open) {
            NEWSBLUR.ReaderPopover._popover.close();
        }
    },

    is_open: function () {
        return NEWSBLUR.ReaderPopover._popover && NEWSBLUR.ReaderPopover._popover._open;
    }

});
