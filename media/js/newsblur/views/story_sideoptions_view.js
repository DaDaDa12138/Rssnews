NEWSBLUR.Views.StorySideoptionsView = Backbone.View.extend({

    initialize: function () {
        this.save_view = new NEWSBLUR.Views.StorySaveView({
            model: this.model,
            el: this.el,
            sideoptions_view: this
        });
    }

});
