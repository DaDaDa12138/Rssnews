NEWSBLUR.ReaderMarkRead = function (options) {
    var defaults = {
        days: 1,
        modal_container_class: "NB-full-container"
    };

    this.flags = {};
    this.options = $.extend({}, defaults, options);
    this.model = NEWSBLUR.assets;
    this.is_mac = navigator.platform.indexOf('Mac') !== -1;
    this.runner();
};

NEWSBLUR.ReaderMarkRead.prototype = new NEWSBLUR.Modal;
NEWSBLUR.ReaderMarkRead.prototype.constructor = NEWSBLUR.ReaderMarkRead;

_.extend(NEWSBLUR.ReaderMarkRead.prototype, {

    runner: function () {
        this.make_modal();
        this.setup_read_slider();
        this.setup_unread_slider();
        this.handle_cancel();
        this.open_modal();

        $(document).bind('keydown.mark_read', 'return', _.bind(this.save_mark_read, this));
        $(document).bind('keydown.mark_read', 'ctrl+return', _.bind(this.save_mark_read, this));
        $(document).bind('keydown.mark_read', 'meta+return', _.bind(this.save_mark_read, this));
    },

    make_modal: function () {
        var self = this;
        var saved_read_days = this.model.preference('mark_read_days');
        var saved_unread_days = this.model.preference('mark_unread_days');
        var shortcut_key = this.is_mac ? '⌘↵' : 'Ctrl+↵';

        this.$modal = $.make('div', { className: 'NB-modal-markread NB-modal' }, [
            $.make('h2', { className: 'NB-modal-title' }, [
                $.make('div', { className: 'NB-icon' }),
                gettext('Mark Everything Read / Unread'),
                $.make('div', { className: 'NB-icon-dropdown' })
            ]),
            $.make('div', { className: 'NB-fieldset NB-markread-section-read' }, [
                $.make('h5', gettext('Mark Stories as Read')),
                $.make('div', { className: 'NB-fieldset-fields' }, [
                    $.make('form', { className: 'NB-markread-form' }, [
                        $.make('div', { className: 'NB-markread-slider-container' }, [
                            $.make('input', {
                                type: 'range',
                                className: 'NB-markread-slider',
                                min: '0',
                                max: '30',
                                value: String(saved_read_days != null ? saved_read_days : 1)
                            }),
                            $.make('div', { className: 'NB-markread-slider-value' })
                        ]),
                        $.make('div', { className: 'NB-modal-submit' }, [
                            $.make('div', { className: 'NB-markread-submit-wrapper' }, [
                                $.make('input', { type: 'submit', className: 'NB-modal-submit-button NB-modal-submit-green NB-markread-submit', value: gettext('Mark as read') }),
                                $.make('span', { className: 'NB-markread-shortcut-hint' }, shortcut_key)
                            ])
                        ])
                    ]).bind('submit', function (e) {
                        e.preventDefault();
                        self.save_mark_read();
                        return false;
                    })
                ])
            ]),
            $.make('div', { className: 'NB-fieldset NB-markread-section-unread' }, [
                $.make('h5', gettext('Mark Stories as Unread')),
                $.make('div', { className: 'NB-fieldset-fields' }, [
                    $.make('form', { className: 'NB-markunread-form' }, [
                        $.make('div', { className: 'NB-mark-unread-slider-container' }, [
                            $.make('input', {
                                type: 'range',
                                className: 'NB-mark-unread-slider',
                                min: '1',
                                max: String(NEWSBLUR.Globals.default_days_of_unread),
                                value: String(saved_unread_days != null ? saved_unread_days : 14)
                            }),
                            $.make('div', { className: 'NB-mark-unread-slider-value' })
                        ]),
                        $.make('div', { className: 'NB-modal-submit' }, [
                            $.make('input', { type: 'submit', className: 'NB-modal-submit-button NB-modal-submit-green NB-markunread-submit', value: gettext('Mark as unread') })
                        ])
                    ]).bind('submit', function (e) {
                        e.preventDefault();
                        self.save_mark_unread();
                        return false;
                    })
                ])
            ])
        ]);
    },

    // ========================
    // = Mark Stories as Read =
    // ========================

    setup_read_slider: function () {
        var self = this;
        var $slider = $('.NB-markread-slider', this.$modal);
        var value = parseInt($slider.val(), 10);

        this.update_read_slider(value);

        $slider.on('input', function () {
            self.update_read_slider(parseInt($(this).val(), 10));
        });
    },

    update_read_slider: function (value) {
        var $slider = $('.NB-markread-slider', this.$modal);
        var $slider_value = $('.NB-markread-slider-value', this.$modal);
        var min = parseInt($slider.attr('min'), 10) || 0;
        var max = parseInt($slider.attr('max'), 10) || 30;
        var percent = ((value - min) / (max - min)) * 100;

        $slider.css('background', 'linear-gradient(to right, #4a90d9 0%, #4a90d9 ' + percent + '%, #e0e0e0 ' + percent + '%, #e0e0e0 100%)');

        if (value == 0) {
            $slider_value.html(gettext('Mark <b>every story</b> as read'));
        } else {
            $slider_value.html(interpolate(ngettext("Mark all stories older than <b>%(value_1)s day</b> old as read", "Mark all stories older than <b>%(value_1)s days</b> old as read", value), {value_1: value}, true));
        }
    },

    save_mark_read: function () {
        if (this.flags.saving) return;

        var $save = $('.NB-markread-submit', this.$modal);
        var $slider = $('.NB-markread-slider', this.$modal);
        var days = parseInt($slider.val(), 10);

        this.model.preference('mark_read_days', days);
        this.flags.saving = true;
        $save.attr('value', gettext('Marking as read...')).addClass('NB-disabled').attr('disabled', true);
        if (NEWSBLUR.Globals.is_authenticated) {
            this.model.save_mark_read(days, _.bind(function () {
                $.modal.close();
                NEWSBLUR.reader.force_feeds_refresh(function () {
                    NEWSBLUR.reader.finish_count_unreads_after_import();
                }, true);
                NEWSBLUR.reader.start_count_unreads_after_import();
                this.flags.saving = false;
            }, this));
        } else {
            this.flags.saving = false;
            $.modal.close();
        }
    },

    // ==========================
    // = Mark Stories as Unread =
    // ==========================

    // Every account keeps the same unread window now that tiers are gone.
    get_max_unread_days: function () {
        return NEWSBLUR.Globals.default_days_of_unread;
    },

    setup_unread_slider: function () {
        var self = this;
        var $slider = $('.NB-mark-unread-slider', this.$modal);
        var max_days = this.get_max_unread_days();
        var saved_days = this.model.preference('mark_unread_days') || 14;

        $slider.val(Math.min(saved_days, max_days));
        this.update_unread_slider(parseInt($slider.val(), 10));

        $slider.on('input', function () {
            self.update_unread_slider(parseInt($(this).val(), 10));
        });
    },

    update_unread_slider: function (value) {
        var $slider = $('.NB-mark-unread-slider', this.$modal);
        var $slider_value = $('.NB-mark-unread-slider-value', this.$modal);
        var $button = $('.NB-markunread-submit', this.$modal);
        var min = parseInt($slider.attr('min'), 10) || 1;
        var max = parseInt($slider.attr('max'), 10) || 365;
        var percent = ((value - min) / (max - min)) * 100;

        $slider.css('background', 'linear-gradient(to right, #4a90d9 0%, #4a90d9 ' + percent + '%, #e0e0e0 ' + percent + '%, #e0e0e0 100%)');
        $slider_value.html(interpolate(ngettext("Mark stories from the last <b>%(value_1)s day</b> as unread", "Mark stories from the last <b>%(value_1)s days</b> as unread", value), {value_1: value}, true));
        $button.removeClass('NB-disabled').removeAttr('disabled');
    },

    save_mark_unread: function () {
        if (this.flags.saving_unread) return;

        var $button = $('.NB-markunread-submit', this.$modal);
        var $slider = $('.NB-mark-unread-slider', this.$modal);
        var days = parseInt($slider.val(), 10);
        var max_days = this.get_max_unread_days();

        if (days > max_days) return;

        this.model.preference('mark_unread_days', days);
        this.flags.saving_unread = true;
        $button.attr('value', gettext('Marking as unread...')).addClass('NB-disabled').attr('disabled', true);

        NEWSBLUR.assets.mark_stories_as_unread(days, null, null, _.bind(function (data) {
            if (data.code === -1) {
                $button.attr('value', data.message).removeClass('NB-disabled').removeAttr('disabled');
                this.flags.saving_unread = false;
                return;
            }
            $.modal.close();
            if (data.async) {
                // Celery task dispatched. Show progress bar and wait for pubsub reload.
                NEWSBLUR.reader.flags['pause_feed_refreshing'] = true;
                NEWSBLUR.reader.flags['waiting_for_mark_unread'] = true;
                NEWSBLUR.reader.start_count_unreads_after_import();
            } else {
                // Synchronous (single feed). Refresh immediately.
                NEWSBLUR.reader.force_feeds_refresh(function () {
                    NEWSBLUR.reader.finish_count_unreads_after_import();
                }, true);
                NEWSBLUR.reader.start_count_unreads_after_import();
            }
            this.flags.saving_unread = false;
        }, this), _.bind(function () {
            $button.attr('value', gettext('Error. Try again.')).removeClass('NB-disabled').removeAttr('disabled');
            this.flags.saving_unread = false;
        }, this));
    },

    // ===========
    // = Actions =
    // ===========

    handle_cancel: function () {
        var $cancel = $('.NB-modal-cancel', this.$modal);

        $cancel.click(function (e) {
            e.preventDefault();
            $.modal.close();
        });
    }

});
