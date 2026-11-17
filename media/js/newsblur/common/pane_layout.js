/* ====================== */
/* = CSS Grid Pane Layout = */
/* ====================== */

/* A small stand-in for jquery.layout (media/js/vendor/jquery.layout.js).
 *
 * jquery.layout measured every pane in JavaScript, positioned it absolutely and
 * kept the sizes in sync by hand. This version hands the same job to CSS grid:
 * the container gets an explicit track list (edge panes, their resizers, and a
 * 1fr centre) and every pane is pinned to its own grid line. Only the resizer
 * drag still needs script, because that is a pixel size the user is choosing.
 *
 * The option names and the public surface (panes, resizers, state, open, hide,
 * close, show, sizePane, resizeAll, destroy) mirror the jquery.layout calls in
 * media/js/newsblur/reader/reader.js, so the reader code reads the same. As in
 * jquery.layout, panes/resizers/state always carry all four edges: reader.js
 * reads panes.north of a layout that has no north pane and expects an empty
 * jQuery object, not undefined.
 *
 * Edge names stay physical, like jquery.layout: reader.js maps the logical
 * sidebar and story titles anchors through NEWSBLUR.utils.layout_edge().
 */

(function ($, _) {
    'use strict';

    var EDGES = ['west', 'east', 'north', 'south'];
    var LEADING_EDGES = ['west', 'north'];
    var RESIZER_MIN = 5;
    var MIN_CENTER = 120;

    function empty_panes() {
        return { north: $(), south: $(), east: $(), west: $(), center: $() };
    }

    function empty_resizers() {
        return { north: $(), south: $(), east: $(), west: $() };
    }

    function empty_container_state() {
        return {
            innerWidth: 0,
            innerHeight: 0,
            outerWidth: 0,
            outerHeight: 0,
            layoutWidth: 0,
            layoutHeight: 0
        };
    }

    function empty_state() {
        var state = {
            initialized: false,
            container: empty_container_state(),
            center: { size: 0, isHidden: false, isClosed: false, auto: false, exists: false }
        };
        _.each(EDGES, function (edge) {
            state[edge] = { size: 0, isHidden: false, isClosed: false, auto: false, exists: false };
        });
        return state;
    }

    function is_leading(edge) {
        return _.contains(LEADING_EDGES, edge);
    }

    // West and east resize horizontally, north and south vertically. A layout can
    // carry both kinds of edge; the grid tracks for each kind are independent.
    function edge_axis(edge) {
        return (edge === 'west' || edge === 'east') ? 'x' : 'y';
    }

    function PaneLayout($container, options) {
        this.$container = $container;
        this.options = options || {};
        this.panes = empty_panes();
        this.resizers = empty_resizers();
        this.state = empty_state();
        this.edges = [];
        this.center = $();
        // Replaced in init() once the configured edges are known. A layout with
        // only north/south is just as valid as one with west/east.
        this.axis = 'y';
        this.ns = '.' + _.uniqueId('nb-pane-layout-');
        this.drag = null;
        this.init();
    }

    PaneLayout.prototype.init = function () {
        var self = this;
        var options = this.options;

        if (options.center__paneSelector) {
            this.center = this.$container.find(options.center__paneSelector).first();
        }

        _.each(EDGES, function (edge) {
            var selector = options[edge + '__paneSelector'];
            if (!selector) return;

            var $pane = self.$container.find(selector).first();
            if (!$pane.length) return;

            var hidden = !!options[edge + '__initHidden'];
            self.edges.push(edge);
            self.panes[edge] = $pane;
            self.state[edge] = {
                size: self.read_size_option(edge),
                isHidden: hidden,
                isClosed: hidden,
                auto: options[edge + '__size'] === 'auto',
                exists: true
            };
            $pane.addClass('NB-pane').attr('data-nb-pane', edge);
            $pane.toggleClass('NB-pane-hidden', hidden);
            self.make_resizer(edge);
        });

        if (this.center.length) {
            this.center.addClass('NB-pane NB-pane-center');
            this.panes.center = this.center;
            this.state.center = { size: 0, isHidden: false, isClosed: false, auto: false, exists: true };
        }

        if (!this.edges.length && !this.center.length) return;

        var has_x = _.some(this.edges, function (edge) { return edge_axis(edge) === 'x'; });
        var has_y = _.some(this.edges, function (edge) { return edge_axis(edge) === 'y'; });
        this.axis = has_x && has_y ? 'xy' : (has_x ? 'x' : 'y');
        this.$container.addClass('NB-pane-layout NB-pane-layout-' + this.axis);
        this.apply();
        this.state.initialized = true;
        $(window).on('resize' + this.ns, _.bind(this.on_window_resize, this));
    };

    PaneLayout.prototype.read_size_option = function (edge) {
        var size = this.options[edge + '__size'];
        if (size === 'auto') return 0;
        var number = parseFloat(size);
        return isNaN(number) ? 0 : Math.round(number);
    };

    PaneLayout.prototype.spacing = function (edge) {
        var spacing = this.options[edge + '__spacing_open'];
        if (spacing === undefined) spacing = this.options.spacing_open;
        return spacing;
    };

    PaneLayout.prototype.make_resizer = function (edge) {
        var self = this;

        if (!this.spacing(edge)) return;
        if (this.options[edge + '__resizable'] === false) return;
        // jquery.layout's option name, kept so the reader options still apply.
        if (this.options[edge + '__resizeable'] === false) return;

        var axis = edge_axis(edge);
        var $resizer = $('<div>')
            .addClass('NB-pane-resizer NB-pane-resizer-' + edge + ' NB-pane-resizer-' + axis)
            .attr('data-nb-pane-resizer', edge)
            .attr('role', 'separator')
            .attr('aria-orientation', axis === 'x' ? 'vertical' : 'horizontal');

        $resizer.on('pointerdown' + this.ns, function (event) {
            self.start_drag(edge, event);
        });

        this.resizers[edge] = $resizer;
        this.$container.append($resizer);
    };

    // 0px when the pane is closed, auto for content-sized panes (the progress
    // footer), otherwise the pixel size the user dragged to.
    PaneLayout.prototype.track_size = function (edge) {
        var state = this.state[edge];
        if (state.isHidden) return '0px';
        if (state.auto) return 'auto';
        return Math.max(0, Math.round(state.size)) + 'px';
    };

    PaneLayout.prototype.resizer_size = function (edge) {
        return Math.max(RESIZER_MIN, parseInt(this.spacing(edge), 10) || RESIZER_MIN) + 'px';
    };

    // The resizer only takes a track while it is visible, so a closed pane does
    // not leave a gap behind it.
    PaneLayout.prototype.visible_resizer = function (edge) {
        var $resizer = this.resizers[edge];
        if (!$resizer || !$resizer.length) return null;
        if (this.state[edge].isHidden) return null;
        return $resizer;
    };

    PaneLayout.prototype.apply = function () {
        var self = this;
        var columns = [];
        var rows = [];
        var placements = [];
        var center_column = 0;
        var center_row = 0;

        function place($item, column_start, column_end, row_start, row_end) {
            if (!$item || !$item.length) return;
            placements.push({
                $item: $item,
                column: column_start + ' / ' + column_end,
                row: row_start + ' / ' + row_end
            });
        }

        // Vertical tracks first: a west or east pane should sit beside the centre
        // row, not cover a north header or a south footer. Building the rows first
        // gives those panes the exact centre row instead of guessing from -1.
        function add_vertical_edge(edge) {
            var $pane = self.panes[edge];
            var $resizer = self.visible_resizer(edge);
            var pane_row;

            if (edge === 'south') {
                if ($resizer) {
                    rows.push(self.resizer_size(edge));
                    place($resizer, 1, -1, rows.length, rows.length + 1);
                }
                rows.push(self.track_size(edge));
                pane_row = rows.length;
            } else {
                rows.push(self.track_size(edge));
                pane_row = rows.length;
                if ($resizer) {
                    rows.push(self.resizer_size(edge));
                    place($resizer, 1, -1, rows.length, rows.length + 1);
                }
            }
            place($pane, 1, -1, pane_row, pane_row + 1);
        }

        // Horizontal tracks: west, centre, east. The centre track is always
        // present so an edge pane never leaves an implicit track behind it.
        function add_horizontal_edge(edge) {
            var $pane = self.panes[edge];
            var $resizer = self.visible_resizer(edge);
            var pane_column;

            if (edge === 'east') {
                if ($resizer) {
                    columns.push(self.resizer_size(edge));
                    place($resizer, columns.length, columns.length + 1, center_row, center_row + 1);
                }
                columns.push(self.track_size(edge));
                pane_column = columns.length;
            } else {
                columns.push(self.track_size(edge));
                pane_column = columns.length;
                if ($resizer) {
                    columns.push(self.resizer_size(edge));
                    place($resizer, columns.length, columns.length + 1, center_row, center_row + 1);
                }
            }
            place($pane, pane_column, pane_column + 1, center_row, center_row + 1);
        }

        if (this.panes.north.length) add_vertical_edge('north');
        rows.push('minmax(0, 1fr)');
        center_row = rows.length;
        if (this.panes.south.length) add_vertical_edge('south');

        if (this.panes.west.length) add_horizontal_edge('west');
        columns.push('minmax(0, 1fr)');
        center_column = columns.length;
        if (this.panes.east.length) add_horizontal_edge('east');

        if (this.center.length) {
            place(this.center, center_column, center_column + 1, center_row, center_row + 1);
        }

        _.each(placements, function (placement) {
            placement.$item.css({
                'grid-column': placement.column,
                'grid-row': placement.row
            });
        });

        this.$container.css({
            'grid-template-columns': columns.join(' '),
            'grid-template-rows': rows.join(' ')
        });

        this.update_container_state();
        this.position_resizer_handles();
    };

    // jquery.layout exposed state.container as a hash of measurements, and
    // reader.js position_mouse_indicator reads its innerHeight. Keep the same
    // shape so that reader code does not have to change.
    PaneLayout.prototype.update_container_state = function () {
        var element = this.$container[0];
        if (!element) return;

        var innerWidth = this.$container.innerWidth() || 0;
        var innerHeight = this.$container.innerHeight() || 0;
        this.state.container = {
            innerWidth: innerWidth,
            innerHeight: innerHeight,
            outerWidth: element.offsetWidth || 0,
            outerHeight: element.offsetHeight || 0,
            layoutWidth: innerWidth,
            layoutHeight: innerHeight
        };
    };

    PaneLayout.prototype.position_resizer_handles = function () {
        _.each(this.resizers, function ($resizer, edge) {
            $resizer.toggleClass('NB-pane-resizer-hidden', !!this.state[edge].isHidden);
        }, this);
    };

    PaneLayout.prototype.open = function (edge, no_animation) {
        var state = this.state[edge];
        if (!state || !state.exists || !state.isHidden) return;

        if (this.options[edge + '__onopen_start']) {
            this.options[edge + '__onopen_start']();
        }
        state.isHidden = false;
        state.isClosed = false;
        this.panes[edge].removeClass('NB-pane-hidden');
        this.apply();
        this.after_change(no_animation);

        if (this.options[edge + '__onopen']) {
            this.options[edge + '__onopen']();
        }
    };

    PaneLayout.prototype.hide = function (edge, no_animation) {
        var state = this.state[edge];
        if (!state || !state.exists || state.isHidden) return;

        if (this.options[edge + '__onclose_start']) {
            this.options[edge + '__onclose_start']();
        }
        state.isHidden = true;
        state.isClosed = true;
        this.apply();
        this.panes[edge].addClass('NB-pane-hidden');
        this.after_change(no_animation);

        if (this.options[edge + '__onclose']) {
            this.options[edge + '__onclose']();
        }
    };

    PaneLayout.prototype.show = function (edge, no_animation) {
        this.open(edge, no_animation);
    };

    PaneLayout.prototype.close = function (edge, no_animation) {
        this.hide(edge, no_animation);
    };

    PaneLayout.prototype.toggle = function (edge) {
        if (this.state[edge] && this.state[edge].isHidden) {
            this.open(edge);
        } else {
            this.hide(edge);
        }
    };

    PaneLayout.prototype.sizePane = function (edge, size) {
        var state = this.state[edge];
        if (!state || !state.exists) return;

        // An auto pane (the progress footer) is sized by its content.
        if (state.auto) return;

        if (size === undefined || size === null) {
            var element = this.panes[edge][0];
            if (!element) return;
            size = edge_axis(edge) === 'x' ? element.offsetWidth : element.offsetHeight;
        }
        if (!size) return;

        state.size = Math.round(size);
        this.apply();
    };

    PaneLayout.prototype.resizeAll = function () {
        this.apply();
        this.$container.trigger('nb-pane-resize');
    };

    PaneLayout.prototype.after_change = function (no_animation) {
        this.$container.trigger('nb-pane-resize');
        if (!no_animation) {
            this.$container.addClass('NB-pane-animating');
            clearTimeout(this.animation_timer);
            this.animation_timer = _.delay(_.bind(function () {
                this.$container.removeClass('NB-pane-animating');
            }, this), 320);
        }
    };

    PaneLayout.prototype.start_drag = function (edge, event) {
        var state = this.state[edge];
        if (!state || state.isHidden) return;

        event.preventDefault();
        this.drag = {
            edge: edge,
            start: edge_axis(edge) === 'x' ? event.clientX : event.clientY,
            size: state.size,
            direction: is_leading(edge) ? 1 : -1
        };
        this.$container.addClass('NB-pane-dragging');
        $(document).on('pointermove' + this.ns, _.bind(this.move_drag, this));
        $(document).on('pointerup' + this.ns, _.bind(this.end_drag, this));
    };

    PaneLayout.prototype.move_drag = function (event) {
        if (!this.drag) return;

        var edge = this.drag.edge;
        var current = edge_axis(edge) === 'x' ? event.clientX : event.clientY;
        var delta = (current - this.drag.start) * this.drag.direction;
        var size = this.clamp_size(edge, this.drag.size + delta);

        this.state[edge].size = size;
        this.state[edge].auto = false;
        this.apply();
    };

    // The rendered size of another pane on the same axis. Auto panes (the
    // progress footer) have no numeric state.size, so measure them.
    PaneLayout.prototype.visible_edge_size = function (edge) {
        var state = this.state[edge];
        if (!state || !state.exists || state.isHidden) return 0;
        if (!state.auto) return Math.max(0, Math.round(state.size));

        var element = this.panes[edge][0];
        if (!element) return 0;
        return edge_axis(edge) === 'x' ? element.offsetWidth : element.offsetHeight;
    };

    PaneLayout.prototype.clamp_size = function (edge, size) {
        var axis = edge_axis(edge);
        var minimum = parseInt(this.options[edge + '__minSize'], 10) || 0;
        var container = axis === 'x' ? this.$container.width() : this.$container.height();
        var used = 0;

        // Leave room for every other pane and every resizer on this axis. The
        // old clamp only subtracted MIN_CENTER, so a two-edge layout could push
        // the centre below its minimum by the width of the opposite pane.
        _.each(this.edges, function (other) {
            if (other === edge || edge_axis(other) !== axis) return;
            used += this.visible_edge_size(other);
        }, this);
        _.each(this.edges, function (other) {
            if (edge_axis(other) !== axis) return;
            if (!this.visible_resizer(other)) return;
            used += parseFloat(this.resizer_size(other)) || 0;
        }, this);

        var maximum = Math.max(minimum, container - used - MIN_CENTER);
        return Math.round(Math.min(Math.max(size, minimum), maximum));
    };

    PaneLayout.prototype.end_drag = function () {
        if (!this.drag) return;

        var edge = this.drag.edge;
        this.drag = null;
        this.$container.removeClass('NB-pane-dragging');
        $(document).off('pointermove' + this.ns);
        $(document).off('pointerup' + this.ns);

        if (this.options[edge + '__onresize_end']) {
            this.options[edge + '__onresize_end']();
        }
    };

    PaneLayout.prototype.reclamp_sizes = function () {
        _.each(this.edges, function (edge) {
            var state = this.state[edge];
            if (!state || !state.exists || state.isHidden || state.auto) return;
            state.size = this.clamp_size(edge, state.size);
        }, this);
    };

    PaneLayout.prototype.on_window_resize = function () {
        // The centre track is 1fr, so the browser already re-flowed. A pixel
        // sized edge does not shrink with the window though, so re-clamp it
        // before the centre is squeezed below MIN_CENTER.
        clearTimeout(this.resize_timer);
        this.resize_timer = _.delay(_.bind(function () {
            this.reclamp_sizes();
            this.apply();
        }, this), 80);
    };

    PaneLayout.prototype.destroy = function () {
        $(window).off('resize' + this.ns);
        $(document).off('pointermove' + this.ns);
        $(document).off('pointerup' + this.ns);
        clearTimeout(this.animation_timer);
        clearTimeout(this.resize_timer);

        _.each(this.resizers, function ($resizer) {
            $resizer.off(this.ns).remove();
        }, this);
        _.each(this.panes, function ($pane) {
            $pane.removeClass('NB-pane NB-pane-center NB-pane-hidden')
                .removeAttr('data-nb-pane')
                .css({ 'grid-column': '', 'grid-row': '' });
        }, this);

        this.$container
            .removeClass('NB-pane-layout NB-pane-layout-x NB-pane-layout-y NB-pane-animating NB-pane-dragging')
            .css({ 'grid-template-columns': '', 'grid-template-rows': '' })
            .removeData('nb-pane-layout');

        this.panes = empty_panes();
        this.resizers = empty_resizers();
        this.state = empty_state();
        this.edges = [];
        this.center = $();
    };

    $.fn.nbLayout = function (options) {
        if (options === 'destroy') {
            return this.each(function () {
                var layout = $(this).data('nb-pane-layout');
                if (layout) layout.destroy();
            });
        }
        if (!options) {
            return this.first().data('nb-pane-layout');
        }

        // jquery.layout handed back the layout instance, and reader.js stores
        // the return value in this.layout.*, so mirror that instead of jQuery.
        var layout = null;
        this.each(function () {
            var $container = $(this);
            var existing = $container.data('nb-pane-layout');
            if (existing) existing.destroy();
            existing = new PaneLayout($container, options);
            $container.data('nb-pane-layout', existing);
            if (!layout) layout = existing;
        });
        return layout || this;
    };

    window.NEWSBLUR = window.NEWSBLUR || {};
    window.NEWSBLUR.PaneLayout = PaneLayout;
})(jQuery, _);
