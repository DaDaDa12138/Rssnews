/* Settings transfer: restore a newsblur-settings.json bundle from the manage card.
 *
 * The server merges additively (apps/reader/views/export.py), so a stale bundle
 * cannot unsubscribe anything; this view only uploads the file and reports what
 * changed.
 */

NEWSBLUR.Views.SettingsTransfer = Backbone.View.extend({

    el: 'body',

    events: {
        'change .NB-menu-manage-import-file': 'handle_file'
    },

    handle_file: function(e) {
        var file = e.currentTarget.files && e.currentTarget.files[0];
        var self = this;
        var data;

        if (!file) return;

        data = new FormData();
        data.append('file', file);

        $.ajax({
            url: NEWSBLUR.URLs['import-settings'],
            type: 'POST',
            data: data,
            processData: false,
            contentType: false,
            success: function(counts) { self.report(counts); },
            error: function() { alert(gettext('Import failed')); }
        });

        e.currentTarget.value = '';
    },

    report: function(counts) {
        var message = interpolate(
            gettext('Imported %(sites)s sites, %(rules)s rules, %(searches)s saved searches'),
            {
                sites: counts.subscriptions_added || 0,
                rules: counts.filters_added || 0,
                searches: counts.saved_searches_added || 0
            },
            true
        );

        alert(message);
        window.location.reload();
    }

});
