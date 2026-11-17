NEWSBLUR.StoryLayoutPopover = NEWSBLUR.ReaderPopover.extend({

    className: "NB-layout-popover",

    options: {
        'width': 208,
        'anchor': '.NB-toolbar-layout-toggle',
        'placement': 'bottom right',
        'offset': {
            top: 10,
            left: 0
        },
        'popover_class': 'NB-layout-popover-container'
    },

    events: {
        "click .NB-layout-option": "choose_layout",
        "keydown .NB-layout-option": "handle_keydown"
    },

    initialize: function (options) {
        this.options = _.extend({}, this.options, options);
        NEWSBLUR.ReaderPopover.prototype.initialize.call(this, this.options);
        this.render();
        this.$anchor.addClass('NB-active');
    },

    close: function () {
        this.$anchor && this.$anchor.removeClass('NB-active');
        NEWSBLUR.ReaderPopover.prototype.close.apply(this, arguments);
    },

    render: function () {
        var self = this;
        NEWSBLUR.ReaderPopover.prototype.render.call(this);

        // story_layout_popover.js: the toolbar already renders one translated
        // copy of the layout list. Cloning it keeps the labels and glyphs in
        // sync with the desktop switch instead of duplicating every string in
        // the JavaScript catalog.
        var $menu = $('.NB-feedbar .NB-taskbar-layout').first().clone();
        $menu.removeClass('NB-taskbar-layout NB-taskbar segmented-control')
            .addClass('NB-layout-menu')
            .removeAttr('style');

        $menu.find('.NB-taskbar-button').each(function () {
            var $button = $(this);
            var layout = self.layout_name($button);
            if (!layout) {
                $button.remove();
                return;
            }

            // A phone renders full and split as list (see assetmodel.view_setting),
            // so offering them here would silently keep the layout on screen.
            if (self.is_phone_width() && (layout == 'full' || layout == 'split')) {
                $button.remove();
                return;
            }

            $button.addClass('NB-layout-option')
                .attr('data-layout', layout)
                .attr('role', 'button')
                .attr('tabindex', '0')
                .removeClass('NB-tipsy')
                .removeAttr('tipsy-title');
        });

        this.$el.empty().append($menu);
    },

    layout_name: function ($button) {
        var match = ($button.attr('class') || '').match(/NB-task-layout-(\w+)/);
        return match && match[1];
    },

    is_phone_width: function () {
        return NEWSBLUR.reader.is_phone_width();
    },

    choose_layout: function (e) {
        e.preventDefault();
        e.stopPropagation();
        var layout = $(e.currentTarget).attr('data-layout');
        if (layout) {
            NEWSBLUR.reader.switch_story_layout(layout);
        }
        this.close();
    },

    handle_keydown: function (e) {
        if (e.key != 'Enter' && e.key != ' ') return;
        this.choose_layout(e);
    }
});
