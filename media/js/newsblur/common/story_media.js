/* Story media enhancements.
 *
 * StoryDetailView calls NEWSBLUR.story_media.enhance() from attach_handlers(),
 * which runs for the detail pane, the grid reader overlay and the Text view, so
 * everything here has to be idempotent: re-rendering a story calls it again.
 *
 * Loaded through newsblur_web/assets.yml as part of js/newsblur/common/*.js,
 * before js/newsblur/views/*.js, so NEWSBLUR.Views.ImageViewer only gets touched
 * at click time.
 */

NEWSBLUR.story_media = {

    // A story with a dozen links should not turn into a wall of players.
    MAX_EMBEDS: 3,

    // Avatars in comment threads are 48x48 and must stay unclickable.
    MIN_VIEWABLE_WIDTH: 120,
    MIN_VIEWABLE_HEIGHT: 72,

    IMAGE_LINK: /\.(gif|webp|apng)(?:[?#].*)?$/i,
    VIDEO_LINK: /\.(mp4|webm|ogv|mov)(?:[?#].*)?$/i,

    VIDEO_PROVIDERS: [
        {
            name: 'YouTube',
            pattern: /(?:youtube\.com\/(?:watch\?(?:[^#]*&)?v=|shorts\/|embed\/|live\/|v\/)|youtu\.be\/)([\w-]{11})/i,
            embed_url: function (id) {
                return 'https://www.youtube.com/embed/' + id + '?autoplay=1&rel=0';
            },
            poster_url: function (id) {
                return 'https://i.ytimg.com/vi/' + id + '/hqdefault.jpg';
            }
        },
        {
            name: 'Vimeo',
            pattern: /vimeo\.com\/(?:video\/)?(\d{6,})/i,
            embed_url: function (id) {
                return 'https://player.vimeo.com/video/' + id + '?autoplay=1';
            }
        },
        {
            name: 'Bilibili',
            pattern: /bilibili\.com\/video\/(BV[\w]+|av\d+)/i,
            embed_url: function (id) {
                var query = id.charAt(0).toLowerCase() === 'b' ? 'bvid=' + id : 'aid=' + id.replace(/^av/i, '');
                return 'https://player.bilibili.com/player.html?' + query + '&autoplay=1&high_quality=1';
            }
        }
    ],

    enhance: function ($content) {
        if (!$content || !$content.length) return;
        this.convert_video_links($content);
        this.convert_media_links($content);
        this.normalize_videos($content);
        this.mark_viewable_images($content);
    },

    // ==========
    // = Videos =
    // ==========

    convert_video_links: function ($content) {
        var self = this;
        var converted = 0;

        $content.find('a[href]').each(function () {
            if (converted >= self.MAX_EMBEDS) return false;
            var $link = $(this);
            if (!self.is_standalone_link($link)) return;

            var href = $.trim($link.attr('href') || '');
            var parsed = self.parse_video_url(href) || self.parse_video_url($.trim($link.text()));
            if (!parsed) return;

            $link.replaceWith(self.build_video_embed(parsed));
            converted += 1;
        });
    },

    parse_video_url: function (url) {
        if (!url) return null;
        for (var i = 0; i < this.VIDEO_PROVIDERS.length; i++) {
            var provider = this.VIDEO_PROVIDERS[i];
            var match = url.match(provider.pattern);
            if (match) {
                return { provider: provider, id: match[1] };
            }
        }
        return null;
    },

    build_video_embed: function (parsed) {
        var $embed = $(
            '<div class="NB-video-embed" data-nb-media="video">' +
                // Not lazy: imagesLoaded() waits for every image in the story, so
                // an offscreen poster would hold back the layout pass.
                '<img class="NB-video-embed-poster" data-nb-media-poster="1" alt="">' +
                '<button type="button" class="NB-video-embed-play"><span class="NB-video-embed-glyph"></span></button>' +
                '<span class="NB-video-embed-badge"></span>' +
            '</div>'
        );

        $embed.attr('data-provider', parsed.provider.name);
        $embed.attr('data-embed-url', parsed.provider.embed_url(parsed.id));
        $embed.find('.NB-video-embed-play').attr('aria-label', gettext('Play video'));
        $embed.find('.NB-video-embed-badge').text(parsed.provider.name);

        if (parsed.provider.poster_url) {
            $embed.find('.NB-video-embed-poster').attr('src', parsed.provider.poster_url(parsed.id));
        } else {
            $embed.addClass('NB-video-embed-no-poster');
            $embed.find('.NB-video-embed-poster').remove();
        }

        return $embed;
    },

    play_embed: function ($embed) {
        if (!$embed || !$embed.length) return;
        if ($embed.hasClass('NB-video-embed-playing')) return;

        var url = $embed.attr('data-embed-url');
        if (!url) return;

        var $frame = $('<iframe>').attr({
            src: url,
            title: $embed.attr('data-provider') + ' video',
            frameborder: '0',
            allow: 'accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share',
            allowfullscreen: 'allowfullscreen',
            loading: 'lazy',
            referrerpolicy: 'strict-origin-when-cross-origin'
        });

        $embed.empty().append($frame).addClass('NB-video-embed-playing');
    },

    // ==================
    // = Inline media =
    // ==================

    convert_media_links: function ($content) {
        var self = this;
        var converted = 0;

        $content.find('a[href]').each(function () {
            if (converted >= self.MAX_EMBEDS) return false;
            var $link = $(this);
            if (!self.is_standalone_link($link)) return;

            var href = $.trim($link.attr('href') || '');
            var $media;

            if (self.IMAGE_LINK.test(href)) {
                $media = $('<img class="NB-inline-media" loading="lazy" alt="">').attr('src', href);
            } else if (self.VIDEO_LINK.test(href)) {
                $media = $('<video class="NB-inline-media" controls autoplay loop muted playsinline preload="metadata">').attr('src', href);
            } else {
                return;
            }

            $link.replaceWith($media);
            converted += 1;
        });
    },

    normalize_videos: function ($content) {
        $content.find('video').each(function () {
            var $video = $(this);

            // Feeds ship width="100%", which browsers ignore and then fall back to 300x150.
            $.each(['width', 'height'], function (i, attribute) {
                var value = $video.attr(attribute);
                if (value && value.indexOf('%') !== -1) $video.removeAttr(attribute);
            });

            if (!$video.attr('controls')) $video.attr('controls', 'controls');
            if (!$video.attr('preload')) $video.attr('preload', 'metadata');
            if (!$video.attr('playsinline')) $video.attr('playsinline', 'playsinline');
            $video.addClass('NB-inline-video');
        });
    },

    // ==========
    // = Images =
    // ==========

    mark_viewable_images: function ($content) {
        var self = this;

        $content.find('img').each(function () {
            var $image = $(this);
            if ($image.is('.NB-score-icon, [data-nb-media-poster]')) return;
            if ($image.closest('.NB-feed-story-header, .NB-feed-story-sideoptions-container').length) return;

            $image.attr('data-nb-viewer-candidate', '1');
            if (self.is_viewable_image(this)) $image.addClass('NB-viewable-image');

            // Lazy images report 0x0 until they load, and comment avatars only
            // reveal their 48x48 size once loaded, so settle the class then.
            if (!this.complete) {
                $image.off('load.nb-viewer').on('load.nb-viewer', function () {
                    $image.toggleClass('NB-viewable-image', self.is_viewable_image(this));
                });
            }
        });
    },

    is_viewable_image: function (image) {
        if (!image) return false;
        var width = Math.max(image.naturalWidth || 0, image.width || 0);
        var height = Math.max(image.naturalHeight || 0, image.height || 0);
        // Lazy images report 0x0 until they load, and the viewer has to know
        // about the rest of the gallery before the reader scrolls that far.
        // Trackers and spacers always declare 1x1, so 0x0 means "not loaded".
        if (!width && !height) return true;
        return width >= this.MIN_VIEWABLE_WIDTH && height >= this.MIN_VIEWABLE_HEIGHT;
    },

    collect_images: function ($content) {
        var self = this;
        var images = [];
        var seen = {};

        $content.find('img').each(function () {
            var $image = $(this);
            if ($image.is('.NB-score-icon, [data-nb-media-poster]')) return;
            if ($image.closest('.NB-feed-story-header, .NB-feed-story-sideoptions-container').length) return;
            // offsetParent is null inside a display:none branch of the feed HTML.
            if (!this.offsetParent) return;
            if (!self.is_viewable_image(this)) return;

            var src = this.currentSrc || this.src || $image.attr('src');
            if (!src || seen[src]) return;
            seen[src] = true;

            images.push({
                src: src,
                alt: $image.attr('alt') || '',
                caption: self.image_caption($image)
            });
        });

        return images;
    },

    image_caption: function ($image) {
        var caption = $.trim($image.closest('figure').find('figcaption').first().text());
        if (!caption) caption = $.trim($image.attr('alt') || '');
        // No filename fallback: proxied URLs end in "imageproxy" or "webp".
        return caption.length > 120 ? caption.substr(0, 117) + '\u2026' : caption;
    },

    // ==========
    // = Utils =
    // ==========

    is_standalone_link: function ($link) {
        if (!$link || !$link.length) return false;
        if ($link.closest('[data-nb-media], blockquote, figcaption, .NB-feed-story-header').length) return false;
        if ($link.find('img, video, iframe, picture').length) return false;

        var href = $.trim($link.attr('href') || '');
        var text = $.trim($link.text());
        if (!href || !text) return false;
        if (this.normalize_url(text) !== this.normalize_url(href)) return false;

        // The anchor has to be alone in its block so surrounding prose is not swallowed.
        var $parent = $link.parent();
        if (!$parent.is('p, div, li, td')) return false;
        var leftover = $.trim($parent.clone().find('a').remove().end().text());
        return leftover === '' || leftover === '\u00a0';
    },

    normalize_url: function (url) {
        return $.trim(url || '')
            .replace(/^https?:\/\//i, '')
            .replace(/^www\./i, '')
            .replace(/\/+$/, '')
            .toLowerCase();
    }

};
