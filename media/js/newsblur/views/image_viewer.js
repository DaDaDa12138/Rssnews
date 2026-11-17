/* Full screen image viewer for story content.
 *
 * StoryDetailView delegates the click to NEWSBLUR.Views.ImageViewer.open() with
 * the gallery collected by NEWSBLUR.story_media.collect_images(). The view lives
 * on <body> so it clears the grid reader overlay (z-index 1200) and survives any
 * re-render of the story underneath.
 *
 * Keyboard handling runs in the capture phase and stops propagation, otherwise
 * the grid reader (Escape, arrows) and the reader hotkeys (j/k/s) would react to
 * the same keystrokes.
 */

NEWSBLUR.Views.ImageViewer = Backbone.View.extend({

    className: 'NB-image-viewer',

    template: [
        '<div class="NB-image-viewer-backdrop"></div>',
        '<button type="button" class="NB-image-viewer-close">',
        '    <span class="NB-image-viewer-close-glyph"></span>',
        '</button>',
        '<button type="button" class="NB-image-viewer-nav NB-image-viewer-prev"></button>',
        '<button type="button" class="NB-image-viewer-nav NB-image-viewer-next"></button>',
        '<div class="NB-image-viewer-stage">',
        '    <img class="NB-image-viewer-image" alt="">',
        '    <div class="NB-image-viewer-error"></div>',
        '</div>',
        '<div class="NB-image-viewer-caption">',
        '    <span class="NB-image-viewer-count"></span>',
        '    <span class="NB-image-viewer-text"></span>',
        '</div>'
    ].join(''),

    events: {
        // The stage is inset:0 and sits above the backdrop, so clicks on the
        // dark area beside the image land on the stage, not the backdrop.
        'click': 'handle_click',
        'click .NB-image-viewer-backdrop': 'close',
        'click .NB-image-viewer-close': 'close',
        'click .NB-image-viewer-prev': 'previous',
        'click .NB-image-viewer-next': 'next',
        'click .NB-image-viewer-image': 'toggle_zoom'
    },

    initialize: function () {
        _.bindAll(this, 'handle_keydown', 'handle_click', 'handle_pointerdown', 'handle_pointerup',
            'handle_image_load', 'handle_image_error',
            'close', 'previous', 'next', 'show', 'toggle_zoom');

        this.images = [];
        this.index = 0;

        this.$el.html(this.template);
        this.$el.attr({
            role: 'dialog',
            'aria-modal': 'true',
            'aria-hidden': 'true'
        });
        this.$el.attr('aria-label', gettext('Image viewer'));

        this.$stage = this.$('.NB-image-viewer-stage');
        this.$image = this.$('.NB-image-viewer-image');

        this.$('.NB-image-viewer-close').attr('aria-label', gettext('Close'));
        this.$('.NB-image-viewer-prev').attr('aria-label', gettext('Previous image'));
        this.$('.NB-image-viewer-next').attr('aria-label', gettext('Next image'));
        this.$('.NB-image-viewer-error').text(gettext('Image could not be loaded'));

        this.$el.appendTo(document.body);

        this.$image.on('load', this.handle_image_load);
        this.$image.on('error', this.handle_image_error);
        this.$stage.on('pointerdown', this.handle_pointerdown);
        this.$stage.on('pointerup', this.handle_pointerup);
    },

    handle_click: function (e) {
        var target = e.target;
        if (target === this.el || $(target).is('.NB-image-viewer-backdrop, .NB-image-viewer-stage')) {
            this.close();
        }
    },

    // ===========
    // = Opening =
    // ===========

    open: function (images, index, $origin) {
        if (!images || !images.length) return;

        this.images = images;
        this.$origin = $origin || null;
        this.focus_restore = document.activeElement;
        this.swiped_at = 0;

        $('body').addClass('NB-image-viewer-open');
        this.$el.addClass('NB-open').attr('aria-hidden', 'false');
        this.$el.toggleClass('NB-image-viewer-single', images.length < 2);
        this.show(index || 0);
        this.$('.NB-image-viewer-close').trigger('focus');

        document.addEventListener('keydown', this.handle_keydown, true);
    },

    close: function (e) {
        if (e) e.preventDefault();
        if (!this.$el.hasClass('NB-open')) return;

        document.removeEventListener('keydown', this.handle_keydown, true);
        this.$el.removeClass('NB-open').attr('aria-hidden', 'true');
        this.$stage.removeClass('NB-zoomed');
        this.$image.removeClass('NB-image-viewer-upscaled').removeAttr('style').removeAttr('src');
        $('body').removeClass('NB-image-viewer-open');

        if (this.focus_restore && this.focus_restore.focus) {
            try {
                this.focus_restore.focus();
            } catch (err) {
                // The element may have been re-rendered while the viewer was open.
            }
        }
        this.focus_restore = null;
    },

    show: function (index) {
        var total = this.images.length;
        if (!total) return;

        this.index = ((index % total) + total) % total;
        var image = this.images[this.index];

        this.$el.removeClass('NB-image-viewer-error-state');
        this.$stage.removeClass('NB-zoomed');
        this.$image.removeClass('NB-image-viewer-upscaled').css('width', '');
        this.$image.attr('alt', image.alt || '');
        this.$('.NB-image-viewer-text').text(image.caption || '').toggle(Boolean(image.caption));
        this.$('.NB-image-viewer-count').text(interpolate(
            gettext('Image %(current)s of %(total)s'),
            { current: this.index + 1, total: total },
            true
        ));

        this.$image.attr('src', image.src);
        this.preload_neighbors();
    },

    previous: function (e) {
        if (e) e.preventDefault();
        this.show(this.index - 1);
    },

    next: function (e) {
        if (e) e.preventDefault();
        this.show(this.index + 1);
    },

    preload_neighbors: function () {
        var total = this.images.length;
        if (total < 2) return;

        var neighbors = [this.index - 1, this.index + 1];
        for (var i = 0; i < neighbors.length; i++) {
            var image = this.images[((neighbors[i] % total) + total) % total];
            if (image && image.src) {
                var preloader = new Image();
                preloader.src = image.src;
            }
        }
    },

    // ==========
    // = Zoom =
    // ==========

    handle_image_load: function () {
        var image = this.$image[0];
        this.$el.removeClass('NB-image-viewer-error-state');
        if (!image || !image.naturalWidth) return;

        // A 480px GIF inside a 1440px window would look smaller than it does in
        // the story, so small images get a readable 2x bump (capped at 88vw).
        if (image.naturalWidth < window.innerWidth * 0.5) {
            var width = Math.min(image.naturalWidth * 2, window.innerWidth * 0.88);
            this.$image.css('width', Math.round(width) + 'px').addClass('NB-image-viewer-upscaled');
        } else {
            this.$image.removeClass('NB-image-viewer-upscaled').css('width', '');
        }
    },

    handle_image_error: function () {
        this.$el.addClass('NB-image-viewer-error-state');
    },

    toggle_zoom: function () {
        // A horizontal swipe also fires a click; do not zoom in that case.
        if (this.swiped_at && Date.now() - this.swiped_at < 300) return;

        var zoomed = this.$stage.toggleClass('NB-zoomed').hasClass('NB-zoomed');
        if (zoomed) {
            this.$image.css('width', '');
        } else {
            this.handle_image_load();
        }
    },

    // ============
    // = Keyboard =
    // ============

    handle_keydown: function (e) {
        if (!this.$el.hasClass('NB-open')) return;

        e.stopPropagation();

        if (e.key === 'Escape' || e.key === 'Esc') {
            e.preventDefault();
            this.close();
        } else if (e.key === 'ArrowLeft') {
            e.preventDefault();
            this.previous();
        } else if (e.key === 'ArrowRight') {
            e.preventDefault();
            this.next();
        }
    },

    // ==========
    // = Touch =
    // ==========

    handle_pointerdown: function (e) {
        this.pointer_start = { x: e.clientX, y: e.clientY };
    },

    handle_pointerup: function (e) {
        if (!this.pointer_start) return;

        var dx = e.clientX - this.pointer_start.x;
        var dy = e.clientY - this.pointer_start.y;
        this.pointer_start = null;

        if (Math.abs(dx) < 40 || Math.abs(dx) < Math.abs(dy)) return;
        this.swiped_at = Date.now();
        if (dx < 0) {
            this.next();
        } else {
            this.previous();
        }
    }

});

NEWSBLUR.Views.ImageViewer.open = function (images, index, $origin) {
    if (!NEWSBLUR.app) return;
    if (!NEWSBLUR.app.image_viewer) {
        NEWSBLUR.app.image_viewer = new NEWSBLUR.Views.ImageViewer();
    }
    NEWSBLUR.app.image_viewer.open(images, index, $origin);
};
