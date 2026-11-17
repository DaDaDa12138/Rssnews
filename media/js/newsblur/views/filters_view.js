// ======================================
// = Story filters (media/js/newsblur/views/filters_view.js) =
// ======================================

// Rules run when a story is ingested (apps/rss_feeds/filters.py), so this dialog
// only manages the list. "Run now" replays a rule over the reader's recent
// stories, which is how a rule added after the fact still catches old stories.
NEWSBLUR.Views.FilterDialog = {

    dialog: null,
    data: null,

    open: function () {
        if ($('.NB-filters-dialog').length) return;

        var html = this.template();

        $.modal(html, {
            minWidth: 560,
            maxWidth: 560,
            overlayClose: true,
            // simplemodal skips showing the overlay, container and data when an
            // onOpen callback is supplied, so show all three here. Without this the
            // dialog is built in the DOM but stays display:none (jquery.simplemodal-1.4.js:645-655).
            onOpen: function (dialog) {
                dialog.container.addClass('NB-modal');
                $(dialog.overlay[0]).show();
                $(dialog.container[0]).show();
                $(dialog.data[0]).show();
                NEWSBLUR.Views.FilterDialog.dialog = dialog;
                NEWSBLUR.Views.FilterDialog.bind(dialog);
                NEWSBLUR.Views.FilterDialog.load();
                // The container was hidden while simplemodal measured it, so recenter
                // and resize once the browser has laid the dialog out.
                _.defer(function () { $.modal.resize(); });
            }
        });
    },

    template: function () {
        return '' +
            '<div class="NB-filters-dialog">' +
            '  <div class="NB-filters-header">' +
            '    <h2 class="NB-filters-title">' + _.escape(gettext('Filters')) + '</h2>' +
            '    <p class="NB-filters-hint">' +
                   _.escape(gettext('Rules run on new stories. Matching stories are marked read, starred, tagged or hidden.')) +
            '    </p>' +
            '  </div>' +
            '  <ul class="NB-filters-list"></ul>' +
            '  <div class="NB-filters-form">' +
            '    <div class="NB-filters-form-row">' +
            '      <label class="NB-filters-label" for="NB-filter-pattern">' + _.escape(gettext('Match')) + '</label>' +
            '      <input id="NB-filter-pattern" class="NB-filter-pattern" type="text" ' +
                     'placeholder="' + _.escape(gettext('Text to look for')) + '" />' +
            '      <select class="NB-filter-field"></select>' +
            '    </div>' +
            '    <div class="NB-filters-form-row">' +
            '      <label class="NB-filters-label" for="NB-filter-scope">' + _.escape(gettext('Where')) + '</label>' +
            '      <select id="NB-filter-scope" class="NB-filter-scope"></select>' +
            '      <input class="NB-filter-folder NB-hidden" type="text" ' +
                     'placeholder="' + _.escape(gettext('Folder name')) + '" />' +
            '      <select class="NB-filter-action"></select>' +
            '      <input class="NB-filter-tag NB-hidden" type="text" ' +
                     'placeholder="' + _.escape(gettext('Tag name')) + '" />' +
            '      <button type="button" class="NB-filter-add">' + _.escape(gettext('Add filter')) + '</button>' +
            '    </div>' +
            '  </div>' +
            '  <div class="NB-filters-footer">' +
            '    <button type="button" class="NB-modal-submit-button NB-modal-submit-grey NB-filters-close">' +
                   _.escape(gettext('Close')) + '</button>' +
            '  </div>' +
            '</div>';
    },

    bind: function (dialog) {
        var self = this;
        var $dialog = $(dialog.data[0]);

        $dialog.on('click', '.NB-filters-close', function () { $.modal.close(); });
        $dialog.on('click', '.NB-filter-add', function () { self.add(); });
        $dialog.on('change', '.NB-filter-scope', function () { self.sync_form(); });
        $dialog.on('change', '.NB-filter-action', function () { self.sync_form(); });
        $dialog.on('click', '.NB-filter-toggle', function (e) { self.toggle(e); });
        $dialog.on('click', '.NB-filter-delete', function (e) { self.remove(e); });
        $dialog.on('click', '.NB-filter-run', function (e) { self.run(e); });
    },

    load: function () {
        var self = this;

        $.get(NEWSBLUR.URLs['load-story-filters'], function (data) {
            if (!data || data.code !== 0) return;
            self.data = data;
            self.render_options();
            self.render_list();
            self.sync_form();
        });
    },

    render_options: function () {
        var $dialog = $('.NB-filters-dialog');

        var options = function (items) {
            return _.map(items || [], function (item) {
                return '<option value="' + _.escape(item.value) + '">' + _.escape(item.label) + '</option>';
            }).join('');
        };

        $dialog.find('.NB-filter-scope').html(options(this.data.scopes));
        $dialog.find('.NB-filter-field').html(options(this.data.fields));
        $dialog.find('.NB-filter-action').html(options(this.data.actions));
    },

    // Folder and tag inputs only apply to their own scope and action.
    sync_form: function () {
        var $dialog = $('.NB-filters-dialog');
        var scope = $dialog.find('select.NB-filter-scope').val();
        var action = $dialog.find('select.NB-filter-action').val();

        $dialog.find('.NB-filter-folder').toggleClass('NB-hidden', scope !== 'folder');
        $dialog.find('.NB-filter-tag').toggleClass('NB-hidden', action !== 'tag');
    },

    render_list: function () {
        var $list = $('.NB-filters-list');
        var fields = {};
        var actions = {};
        var html = '';

        _.each(this.data.fields, function (item) { fields[item.value] = item.label; });
        _.each(this.data.actions, function (item) { actions[item.value] = item.label; });

        _.each(this.data.filters, function (rule) {
            var where = rule.feed_title || rule.folder || gettext('All sites');

            html += '<li class="NB-filter-row' + (rule.enabled ? '' : ' NB-filter-disabled') + '" data-id="' + rule.id + '">' +
                '<span class="NB-filter-pattern-text" dir="auto">' + _.escape(rule.pattern) + '</span>' +
                '<span class="NB-filter-where" dir="auto">' + _.escape(where) + '</span>' +
                '<span class="NB-filter-action-text">' + _.escape(actions[rule.action] || rule.action) +
                    (rule.tag ? ' ' + _.escape(rule.tag) : '') + '</span>' +
                '<span class="NB-filter-hits">' + rule.hits + '</span>' +
                '<button type="button" class="NB-filter-run" data-id="' + rule.id + '" ' +
                    'title="' + _.escape(gettext('Run now')) + '">&#x21bb;</button>' +
                '<button type="button" class="NB-filter-toggle" data-id="' + rule.id + '" ' +
                    'title="' + _.escape(gettext('Enable or disable')) + '">' +
                    (rule.enabled ? '&#x25cf;' : '&#x25cb;') + '</button>' +
                '<button type="button" class="NB-filter-delete" data-id="' + rule.id + '" ' +
                    'title="' + _.escape(gettext('Delete')) + '">&times;</button>' +
                '</li>';
        });

        if (!html) {
            html = '<li class="NB-filter-empty">' + _.escape(gettext('No filters yet.')) + '</li>';
        }

        $list.html(html);
    },

    add: function () {
        var self = this;
        var $dialog = $('.NB-filters-dialog');
        var pattern = $dialog.find('input.NB-filter-pattern').val();
        var payload = {
            scope: $dialog.find('select.NB-filter-scope').val(),
            field: $dialog.find('select.NB-filter-field').val(),
            action: $dialog.find('select.NB-filter-action').val(),
            pattern: pattern,
            folder: $dialog.find('.NB-filter-folder').val(),
            tag: $dialog.find('.NB-filter-tag').val(),
            feed_id: (NEWSBLUR.reader && NEWSBLUR.reader.active_feed) || ''
        };

        if (!pattern) return;

        $.post(NEWSBLUR.URLs['save-story-filter'], payload, function (data) {
            if (data && data.code === 0) {
                $dialog.find('input.NB-filter-pattern').val('');
                self.load();
            } else if (data && data.message) {
                NEWSBLUR.utils.show_message(data.message);
            }
        });
    },

    toggle: function (e) {
        var self = this;
        $.post(NEWSBLUR.URLs['toggle-story-filter'], { id: $(e.currentTarget).attr('data-id') }, function () {
            self.load();
        });
    },

    remove: function (e) {
        var self = this;
        $.post(NEWSBLUR.URLs['delete-story-filter'], { id: $(e.currentTarget).attr('data-id') }, function () {
            self.load();
        });
    },

    run: function (e) {
        var self = this;
        var $button = $(e.currentTarget);

        $button.addClass('NB-filter-running');

        $.post(NEWSBLUR.URLs['run-story-filter'], { id: $button.attr('data-id') }, function (data) {
            $button.removeClass('NB-filter-running');
            if (data && data.message) {
                NEWSBLUR.utils.show_message(data.message);
            }
            self.load();
        });
    }
};
