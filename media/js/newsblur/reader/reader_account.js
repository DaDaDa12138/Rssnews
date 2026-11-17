NEWSBLUR.ReaderAccount = function (options) {
    var defaults = {
        'width': 800,
        'modal_container_class': 'NB-account-container',
        'animate_email': false,
        'change_password': false,
        'onOpen': _.bind(function () {
            this.animate_fields();
            $(window).trigger('resize.simplemodal');
        }, this)
    };

    this.options = $.extend({}, defaults, options);
    this.model = NEWSBLUR.assets;

    this.runner();
};

NEWSBLUR.ReaderAccount.prototype = new NEWSBLUR.Modal;
NEWSBLUR.ReaderAccount.prototype.constructor = NEWSBLUR.ReaderAccount;

_.extend(NEWSBLUR.ReaderAccount.prototype, {

    runner: function () {
        this.options.onOpen = _.bind(function () {
            // $(window).resize();
        }, this);
        this.make_modal();
        this.open_modal();

        this.$modal.bind('click', $.rescope(this.handle_click, this));
        this.handle_change();
        this.select_preferences();
        this.fetch_email_status();

        this.render_dates();
        this.fetch_classifiers_count();
        this.handle_classifier_pill_change();

        if (this.options.tab) {
            this.switch_tab(this.options.tab);
        }
    },

    make_modal: function () {
        var self = this;

        this.$modal = $.make('div', { className: 'NB-modal-preferences NB-modal-account NB-modal' }, [
            $.make('div', { className: 'NB-modal-tabs' }, [
                $.make('div', { className: 'NB-modal-loading' }),
                $.make('div', { className: 'NB-modal-tab NB-active NB-modal-tab-account' }, gettext('Account')),
                $.make('div', { className: 'NB-modal-tab NB-modal-tab-emails' }, gettext('Emails')),
                $.make('div', { className: 'NB-modal-tab NB-modal-tab-custom' }, gettext('Custom CSS/JavaScript'))
            ]),
            $.make('h2', { className: 'NB-modal-title' }, [
                $.make('div', { className: 'NB-icon' }),
                gettext('Account'),
                $.make('div', { className: 'NB-icon-dropdown' })
            ]),
            $.make('form', { className: 'NB-preferences-form' }, [
                $.make('div', { className: 'NB-tab NB-tab-account NB-active' }, [
                    $.make('div', { className: 'NB-preference NB-preference-username' }, [
                        $.make('div', { className: 'NB-preference-options' }, [
                            $.make('div', { className: 'NB-preference-option' }, [
                                $.make('input', { id: 'NB-preference-username', type: 'text', name: 'username', value: NEWSBLUR.Globals.username })
                            ])
                        ]),
                        $.make('div', { className: 'NB-preference-label' }, [
                            $.make('label', { 'for': 'NB-preference-username' }, gettext('Username')),

                            $.make('div', { className: 'NB-preference-error' })
                        ])
                    ]),
                    $.make('div', { className: 'NB-preference NB-preference-email' }, [
                        $.make('div', { className: 'NB-preference-options' }, [
                            $.make('div', { className: 'NB-preference-option' }, [
                                $.make('input', { id: 'NB-preference-email', type: 'text', name: 'email', value: NEWSBLUR.Globals.email })
                            ])
                        ]),
                        $.make('div', { className: 'NB-preference-label' }, [
                            $.make('label', { 'for': 'NB-preference-email' }, gettext('Email address')),

                            $.make('div', { className: 'NB-preference-error' })
                        ])
                    ]),
                    $.make('div', { className: 'NB-preference NB-preference-password' }, [
                        $.make('div', { className: 'NB-preference-options' }, [
                            $.make('div', { className: 'NB-preference-option', style: (this.options.change_password ? 'opacity: .2' : '') }, [
                                $.make('label', { 'for': 'NB-preference-password-old' }, gettext('Old password')),
                                $.make('input', { id: 'NB-preference-password-old', type: 'password', name: 'old_password', value: '' })
                            ]),
                            $.make('div', { className: 'NB-preference-option' }, [
                                $.make('label', { 'for': 'NB-preference-password-new' }, gettext('New password')),
                                $.make('input', { id: 'NB-preference-password-new', type: 'password', name: 'new_password', value: '' })
                            ])
                        ]),
                        $.make('div', { className: 'NB-preference-label' }, [
                            gettext('Change password'),
                            $.make('div', { className: 'NB-preference-error' })
                        ])
                    ]),
                    $.make('div', { className: 'NB-preference NB-preference-opml' }, [
                        $.make('div', { className: 'NB-preference-options' }, [
                            $.make('a', { className: 'NB-modal-submit-button NB-modal-submit-green', href: NEWSBLUR.URLs['opml-export'] }, gettext('Download OPML'))
                        ]),
                        $.make('div', { className: 'NB-preference-label' }, [
                            gettext('Backup your sites'),
                            $.make('div', { className: 'NB-preference-sublabel' }, gettext('Download this XML file as a backup'))
                        ])
                    ]),
                    $.make('div', { className: 'NB-preference NB-preference-delete NB-preference-delete-saved' }, [
                        $.make('div', { className: 'NB-preference-options' }, [
                            $.make('div', { className: 'NB-preference-saved-stories-date' }),
                            $.make('div', { className: 'NB-preference-stories-count NB-preference-saved-stories-count' }),
                            $.make('div', { className: 'NB-modal-submit-button NB-modal-submit-red NB-account-delete-saved-stories' }, gettext('Delete my saved stories'))
                        ]),
                        $.make('div', { className: 'NB-preference-label' }, [
                            gettext('Erase your saved stories')
                        ])
                    ]),
                    $.make('div', { className: 'NB-preference NB-preference-delete NB-preference-delete-classifiers' }, [
                        $.make('div', { className: 'NB-preference-options' }, [
                            $.make('div', { className: 'NB-preference-classifier-pills' },
                                [$.make('label', { className: 'NB-classifier-pill NB-classifier-pill-all' }, [
                                    $.make('input', { type: 'checkbox', name: 'classifier_all', value: 'all' }),
                                    $.make('span', { className: 'NB-classifier-pill-label' }, gettext('All')),
                                    $.make('span', { className: 'NB-classifier-pill-count' })
                                ])].concat(_.map([
                                    { key: 'title', label: gettext('Title') },
                                    { key: 'title_regex', label: gettext('Title Regex') },
                                    { key: 'author', label: gettext('Author') },
                                    { key: 'author_regex', label: gettext('Author Regex') },
                                    { key: 'tag', label: gettext('Tag') },
                                    { key: 'text', label: gettext('Text') },
                                    { key: 'text_regex', label: gettext('Text Regex') },
                                    { key: 'feed', label: gettext('Feed') },
                                    { key: 'url', label: gettext('URL') },
                                    { key: 'url_regex', label: gettext('URL Regex') }
                                ], function (type) {
                                    return $.make('label', { className: 'NB-classifier-pill NB-classifier-pill-' + type.key }, [
                                        $.make('input', { type: 'checkbox', name: 'classifier_type', value: type.key }),
                                        $.make('span', { className: 'NB-classifier-pill-label' }, type.label),
                                        $.make('span', { className: 'NB-classifier-pill-count' })
                                    ]);
                                }))
                            ),
                            $.make('div', { className: 'NB-preference-stories-count NB-preference-classifiers-count' }),
                            $.make('div', { className: 'NB-modal-submit-button NB-modal-submit-red NB-account-delete-classifiers NB-disabled' }, gettext('Delete my intelligence training classifiers'))
                        ]),
                        $.make('div', { className: 'NB-preference-label' }, [
                            gettext('Erase your intelligence training classifiers')
                        ])
                    ]),
                    $.make('div', { className: 'NB-preference NB-preference-delete' }, [
                        $.make('div', { className: 'NB-preference-options' }, [
                            $.make('div', { className: 'NB-modal-submit-button NB-modal-submit-red NB-account-delete-all-sites' }, gettext('Delete all of my sites'))
                        ]),
                        $.make('div', { className: 'NB-preference-label' }, [
                            gettext('Erase yourself'),
                            $.make('div', { className: 'NB-preference-sublabel' }, gettext('Friendly note: You will be emailed a backup of your sites'))
                        ])
                    ]),
                    $.make('div', { className: 'NB-preference NB-preference-delete' }, [
                        $.make('div', { className: 'NB-preference-options' }, [
                            $.make('a', { className: 'NB-modal-submit-button NB-modal-submit-red', href: NEWSBLUR.URLs['profile-delete-account'] }, gettext('Delete my account'))
                        ]),
                        $.make('div', { className: 'NB-preference-label' }, [
                            gettext('Erase yourself permanently'),
                            $.make('div', { className: 'NB-preference-sublabel' }, gettext('Warning: This is actually permanent'))
                        ])
                    ])
                ]),
                $.make('div', { className: 'NB-tab NB-tab-emails' }, [
                    $.make('div', { className: 'NB-preferences-unsubscribed' }, [
                        gettext('You are unsubscribed from all NewsBlur emails. Choose to receive emails below and save to resubscribe.')
                    ]).toggle(!NEWSBLUR.assets.preference('send_emails')),
                    $.make('div', { className: 'NB-preference NB-preference-emails' }, [
                        $.make('div', { className: 'NB-preference-options' }, [
                            $.make('div', [
                                $.make('input', { id: 'NB-preference-emails-1', type: 'radio', name: 'send_emails', value: 'true' }),
                                $.make('label', { 'for': 'NB-preference-emails-1' }, [
                                    gettext('Email me replies, re-shares, new followers, and account notices')
                                ])
                            ]),
                            $.make('div', [
                                $.make('input', { id: 'NB-preference-emails-2', type: 'radio', name: 'send_emails', value: 'false' }),
                                $.make('label', { 'for': 'NB-preference-emails-2' }, [
                                    gettext('Never ever send me an email')
                                ])
                            ])
                        ]),
                        $.make('div', { className: 'NB-preference-label' }, [
                            gettext('Emails')
                        ])
                    ])
                ]),
                $.make('div', { className: 'NB-tab NB-tab-custom' }, [
                    $.make('fieldset', [
                        $.make('legend', gettext('Custom CSS')),
                        $.make('div', { className: 'NB-modal-section NB-profile-editor-blurblog-custom-css' }, [
                            $.make('textarea', { 'className': 'NB-account-custom-css', name: 'custom_css' }, _.string.trim($("#NB-custom-css").text()))
                        ])
                    ]),
                    $.make('fieldset', [
                        $.make('legend', gettext('Custom JavaScript')),
                        $.make('div', { className: 'NB-modal-section NB-profile-editor-blurblog-custom-js' }, [
                            $.make('textarea', { 'className': 'NB-account-custom-javascript', name: 'custom_js' }, _.string.trim($("#NB-custom-js").text()))
                        ])
                    ])
                ]),
                $.make('div', { className: 'NB-modal-submit' }, [
                    $.make('input', { type: 'submit', disabled: 'true', className: 'NB-modal-submit-button NB-modal-submit-green NB-disabled', value: gettext('Change what you like above...') })
                ])
            ]).bind('submit', function (e) {
                e.preventDefault();
                self.save_account_settings();
                return false;
            })
        ]);
    },

    render_dates: function () {
        var self = this;
        var now = new Date();
        var this_year = now.getFullYear();
        var this_month = now.getMonth();
        var this_day = now.getDate();

        var make_date_selectors = function (prefix) {
            var $months = $.make('select', { name: prefix + '_month', className: 'NB-date-month' });
            _.each(NEWSBLUR.utils.monthNames, function (name, i) {
                var $option = $.make('option', { value: i + "" }, name);
                if (this_month == i) $option.prop('selected', true);
                $months.append($option);
            });

            var $days = $.make('select', { name: prefix + '_day', className: 'NB-date-day' });
            _.each(_.range(0, 31), function (name, i) {
                var $option = $.make('option', { value: i + 1 + "" }, i + 1);
                if (this_day == i + 1) $option.prop('selected', true);
                $days.append($option);
            });

            var $years = $.make('select', { name: prefix + '_year', className: 'NB-date-year' });
            _.each(_.range(2009, this_year + 1), function (name, i) {
                var $option = $.make('option', { value: name + "" }, name);
                if (this_year == name) $option.prop('selected', true);
                $years.append($option);
            });

            return { $months: $months, $days: $days, $years: $years };
        };

        // reader_account.js: "Older than: [month] [day] [year]" as one translated
        // sentence, so each language can order the date selects its own way. The
        // row is a flex container, so text goes in spans and the whitespace
        // between selects is dropped (the CSS gap spaces them).
        var make_older_than = function (selectors) {
            return NEWSBLUR.utils.interpolate_nodes(gettext('Older than: %(month)s %(day)s %(year)s'), {
                month: selectors.$months,
                day: selectors.$days,
                year: selectors.$years
            }, function (text) {
                return $.trim(text) ? $.make('span', text) : null;
            });
        };

        // Saved stories date selector
        var $saved_dates = $(".NB-preference-saved-stories-date", this.$modal);
        $saved_dates.append(make_older_than(make_date_selectors('saved')));

        // Bind date change events to fetch counts
        $saved_dates.find('select').on('change', _.bind(this.fetch_saved_stories_count, this));

        // Initial count fetch
        this.fetch_saved_stories_count();
    },

    animate_fields: function () {
        if (this.options.animate_email) {
            this.switch_tab('emails');
            _.delay(_.bind(function () {
                var $emails = $('.NB-preference-emails', this.$modal);
                var bgcolor = $emails.css('backgroundColor');
                $emails.css('backgroundColor', bgcolor).animate({
                    'backgroundColor': 'orange'
                }, {
                    'queue': false,
                    'duration': 1200,
                    'easing': 'easeInQuad',
                    'complete': function () {
                        $emails.animate({
                            'backgroundColor': bgcolor
                        }, {
                            'queue': false,
                            'duration': 650,
                            'easing': 'easeOutQuad'
                        });
                    }
                });
            }, this), 200);
        } else if (this.options.change_password) {
            _.delay(_.bind(function () {
                var $emails = $('.NB-preference-password', this.$modal);
                var bgcolor = $emails.css('backgroundColor');
                $emails.css('backgroundColor', bgcolor).animate({
                    'backgroundColor': 'orange'
                }, {
                    'queue': false,
                    'duration': 1200,
                    'easing': 'easeInQuad',
                    'complete': function () {
                        $emails.animate({
                            'backgroundColor': bgcolor
                        }, {
                            'queue': false,
                            'duration': 650,
                            'easing': 'easeOutQuad'
                        });
                    }
                });
            }, this), 200);
        }

    },

    delete_all_sites: function () {
        var $link = $(".NB-account-delete-all-sites", this.$modal);

        if (window.confirm(gettext("Positive you want to delete everything?"))) {
            NEWSBLUR.assets.delete_all_sites(_.bind(function () {
                NEWSBLUR.assets.load_feeds();
                $link.replaceWith($.make('div', gettext('Everything has been deleted.')));
            }, this), _.bind(function () {
                $link.replaceWith($.make('div', { className: 'NB-error' }, gettext('There was a problem deleting your sites.')));
            }, this));
        }
    },

    get_saved_timestamp: function () {
        var year = parseInt($("select[name=saved_year]", this.$modal).val(), 10);
        var month = parseInt($("select[name=saved_month]", this.$modal).val(), 10);
        var day = parseInt($("select[name=saved_day]", this.$modal).val(), 10);
        return (new Date(year, month, day)).getTime() / 1000;
    },

    fetch_saved_stories_count: function () {
        var $count = $('.NB-preference-saved-stories-count', this.$modal);
        var timestamp = this.get_saved_timestamp();

        $count.text(gettext('Counting...'));

        NEWSBLUR.assets.count_saved_stories(timestamp, _.bind(function (data) {
            if (data.count === 0) {
                $count.text(gettext('No stories to delete'));
            } else {
                $count.text(interpolate(ngettext("%(count)s story will be deleted", "%(count)s stories will be deleted", data.count), {count: Inflector.commas(data.count)}, true));
            }
        }, this), _.bind(function () {
            $count.text('');
        }, this));
    },

    delete_saved_stories: function () {
        var $link = $(".NB-account-delete-saved-stories", this.$modal);
        var $count = $('.NB-preference-saved-stories-count', this.$modal);
        var $loading = $('.NB-modal-loading', this.$modal);
        var timestamp = this.get_saved_timestamp();

        if (window.confirm(gettext("Positive you want to delete your saved stories?"))) {
            $loading.addClass('NB-active');
            $link.attr('disabled', 'disabled');
            $link.text(gettext("Deleting..."));

            NEWSBLUR.assets.delete_saved_stories(timestamp, _.bind(function (data) {
                $loading.removeClass('NB-active');
                NEWSBLUR.reader.update_starred_count();
                $link.replaceWith($.make('div', interpolate(ngettext("%(count)s story has been deleted.", "%(count)s stories have been deleted.", data.stories_deleted), {count: Inflector.commas(data.stories_deleted)}, true)));
                $count.text('');
            }, this), _.bind(function () {
                $loading.removeClass('NB-active');
                NEWSBLUR.reader.update_starred_count();
                $link.replaceWith($.make('div', { className: 'NB-error' }, gettext('There was a problem deleting your saved stories.'))).show();
            }, this));
        }
    },

    fetch_classifiers_count: function () {
        var self = this;
        var $count = $('.NB-preference-classifiers-count', this.$modal);
        var $pills = $('.NB-preference-classifier-pills', this.$modal);
        var $button = $('.NB-account-delete-classifiers', this.$modal);

        $pills.hide();
        $button.hide();
        $count.text(gettext('Loading classifiers...')).addClass('NB-empty').removeClass('NB-has-selection');

        NEWSBLUR.assets.count_classifiers(_.bind(function (data) {
            $pills.show();
            $button.show();
            self.classifier_counts = data.counts;

            // Update individual pill counts and hide 0-count pills
            _.each(data.counts, function (count, category) {
                var $pill = $('.NB-classifier-pill-' + category, self.$modal);
                $pill.find('.NB-classifier-pill-count').text(count);
                if (count === 0) {
                    $pill.hide();
                } else {
                    $pill.show();
                }
            });

            // Update "All" pill count
            var $all_pill = $('.NB-classifier-pill-all', self.$modal);
            $all_pill.find('.NB-classifier-pill-count').text(data.total);

            self.update_classifiers_count_display();
        }, this), _.bind(function () {
            $count.text('');
        }, this));
    },

    update_classifiers_count_display: function () {
        var $count = $('.NB-preference-classifiers-count', this.$modal);
        var $button = $('.NB-account-delete-classifiers', this.$modal);
        var counts = this.classifier_counts || {};
        var total = 0;

        $('input[name=classifier_type]:checked', this.$modal).each(function () {
            var category = $(this).val();
            total += (counts[category] || 0);
        });

        if (total === 0) {
            $count.text(gettext('Select classifiers to remove')).addClass('NB-empty').removeClass('NB-has-selection');
            $button.addClass('NB-disabled').attr('disabled', 'disabled');
        } else {
            $count.text(interpolate(ngettext("%(count)s classifier will be deleted", "%(count)s classifiers will be deleted", total), {count: total}, true)).removeClass('NB-empty').addClass('NB-has-selection');
            $button.removeClass('NB-disabled').removeAttr('disabled');
        }
    },

    handle_classifier_pill_change: function () {
        var self = this;

        // "All" checkbox logic
        this.$modal.on('change', 'input[name=classifier_all]', function () {
            var is_checked = $(this).is(':checked');
            $('input[name=classifier_type]', self.$modal).each(function () {
                var $pill = $(this).closest('.NB-classifier-pill');
                if ($pill.is(':visible')) {
                    $(this).prop('checked', is_checked);
                    $pill.toggleClass('NB-checked', is_checked);
                }
            });
            $(this).closest('.NB-classifier-pill').toggleClass('NB-checked', is_checked);
            self.update_classifiers_count_display();
        });

        // Individual checkbox logic
        this.$modal.on('change', 'input[name=classifier_type]', function () {
            var $pill = $(this).closest('.NB-classifier-pill');
            $pill.toggleClass('NB-checked', $(this).is(':checked'));

            // Check if all visible individuals are checked
            var $visible = $('input[name=classifier_type]', self.$modal).filter(function () {
                return $(this).closest('.NB-classifier-pill').is(':visible');
            });
            var all_checked = $visible.length === $visible.filter(':checked').length;
            $('input[name=classifier_all]', self.$modal).prop('checked', all_checked);
            $('.NB-classifier-pill-all', self.$modal).toggleClass('NB-checked', all_checked);

            self.update_classifiers_count_display();
        });
    },

    delete_classifiers: function () {
        var $link = $(".NB-account-delete-classifiers", this.$modal);
        var $count = $('.NB-preference-classifiers-count', this.$modal);
        var $loading = $('.NB-modal-loading', this.$modal);

        var categories = [];
        $('input[name=classifier_type]:checked', this.$modal).each(function () {
            categories.push($(this).val());
        });

        if (!categories.length) return;

        if (window.confirm(gettext("Positive you want to delete your intelligence training classifiers?"))) {
            $loading.addClass('NB-active');
            $link.attr('disabled', 'disabled');
            $link.text(gettext("Deleting..."));

            NEWSBLUR.assets.delete_classifiers(categories, _.bind(function (data) {
                $loading.removeClass('NB-active');
                $link.replaceWith($.make('div',
                    interpolate(ngettext("%(count)s classifier has been deleted.", "%(count)s classifiers have been deleted.", data.total_deleted), {count: data.total_deleted}, true)));
                $count.text('');
                NEWSBLUR.assets.load_feeds();
            }, this), _.bind(function () {
                $loading.removeClass('NB-active');
                $link.replaceWith($.make('div', { className: 'NB-error' },
                    gettext('There was a problem deleting your classifiers.'))).show();
            }, this));
        }
    },

    handle_cancel: function () {
        var $cancel = $('.NB-modal-cancel', this.$modal);

        $cancel.click(function (e) {
            e.preventDefault();
            $.modal.close();
        });
    },

    select_preferences: function () {
        var pref = this.model.preference;
        $('input[name=send_emails]', this.$modal).each(function () {
            if ($(this).val() == "" + pref('send_emails')) {
                $(this).prop('checked', true);
                return false;
            }
        });
        $('#NB-preference-renewal-notify', this.$modal).prop('checked', !!pref('notify_before_renewal'));
    },

    fetch_email_status: function () {
        // The page-load preferences can be stale if emails were unsubscribed on
        // another page (e.g. the email unsubscribe link), so fetch a fresh value.
        var self = this;
        this.model.make_request(NEWSBLUR.URLs['profile-get-preference'], { 'preference': 'send_emails' }, function (data) {
            if (!data || _.isUndefined(data.payload) || _.isNull(data.payload)) return;
            NEWSBLUR.Preferences['send_emails'] = data.payload;
            self.select_preferences();
            $('.NB-preferences-unsubscribed', self.$modal).toggle(!data.payload);
        }, $.noop);
    },

    serialize_preferences: function () {
        var preferences = {};

        $('input[type=radio]:checked, select, textarea, input[type=text], input[type=password]', this.$modal).each(function () {
            var name = $(this).attr('name');
            var preference = preferences[name] = $(this).val();
            if (preference == 'true') preferences[name] = true;
            else if (preference == 'false') preferences[name] = false;
        });
        $('input[type=checkbox]', this.$modal).each(function () {
            preferences[$(this).attr('name')] = $(this).is(':checked');
        });

        return preferences;
    },

    save_account_settings: function () {
        var self = this;
        var form = this.serialize_preferences();
        $('.NB-preference-error', this.$modal).text('');
        $('input[type=submit]', this.$modal).val(gettext('Saving...')).attr('disabled', true).addClass('NB-disabled');

        NEWSBLUR.log(["form['send_emails']", form['send_emails']]);
        this.model.preference('send_emails', form['send_emails']);
        this.model.preference('notify_before_renewal', form['notify_before_renewal']);

        this.model.save_account_settings(form, _.bind(function (data) {
            if (data.code == -1) {
                $('.NB-preference-username .NB-preference-error', this.$modal).text(data.message);
                return self.disable_save();
            } else if (data.code == -2) {
                $('.NB-preference-email .NB-preference-error', this.$modal).text(data.message);
                return self.disable_save();
            } else if (data.code == -3) {
                $('.NB-preference-password .NB-preference-error', this.$modal).text(data.message);
                return self.disable_save();
            }

            NEWSBLUR.Globals.username = data.payload.username;
            NEWSBLUR.Globals.email = data.payload.email;
            $('.NB-module-account-username').text(NEWSBLUR.Globals.username);
            $('.NB-feeds-header-user-name').text(NEWSBLUR.Globals.username);
            self.close();
        }, this));
    },

    // ===========
    // = Actions =
    // ===========

    handle_click: function (elem, e) {
        var self = this;

        $.targetIs(e, { tagSelector: '.NB-modal-tab' }, function ($t, $p) {
            e.preventDefault();
            var newtab;
            if ($t.hasClass('NB-modal-tab-account')) {
                newtab = 'account';
            } else if ($t.hasClass('NB-modal-tab-emails')) {
                newtab = 'emails';
            } else if ($t.hasClass('NB-modal-tab-custom')) {
                newtab = 'custom';
            }
            self.switch_tab(newtab);
        });
        $.targetIs(e, { tagSelector: '.NB-account-delete-all-sites' }, function ($t, $p) {
            e.preventDefault();

            self.delete_all_sites();
        });
        $.targetIs(e, { tagSelector: '.NB-account-delete-saved-stories' }, function ($t, $p) {
            e.preventDefault();

            self.delete_saved_stories();
        });
        $.targetIs(e, { tagSelector: '.NB-account-delete-classifiers' }, function ($t, $p) {
            e.preventDefault();

            self.delete_classifiers();
        });
        $.targetIs(e, { tagSelector: '.NB-modal-cancel' }, function ($t, $p) {
            e.preventDefault();

            self.close();
        });
    },

    handle_change: function () {
        $('input[type=radio],input[type=checkbox],select,input', this.$modal).not('.NB-preference-delete-classifiers input').bind('change', _.bind(this.enable_save, this));
        $('input', this.$modal).not('.NB-preference-delete-classifiers input').bind('keydown', _.bind(this.enable_save, this));
        $('.NB-tab-custom', this.$modal).delegate('input[type=text],textarea', 'keydown', _.bind(this.enable_save, this));
        $('.NB-tab-custom', this.$modal).delegate('input,textarea', 'change', _.bind(this.enable_save, this));
    },

    enable_save: function () {
        $('input[type=submit]', this.$modal).removeAttr('disabled').removeClass('NB-disabled').val(gettext('Save My Account'));
    },

    disable_save: function () {
        this.resize();
        $('input[type=submit]', this.$modal).attr('disabled', true).addClass('NB-disabled').val(gettext('Change what you like above...'));
    }

});
