// translator.js: one-click translation of headlines and story bodies.
//
// The reader posts batches of plain text to /reader/translate and the server keeps a
// translation cache, so a headline that already appeared is never sent twice. Two
// things matter here: never run more than a couple of requests at a time, and stop
// asking for a minute after a few failures. The upstream rate-limits by IP, and a
// blocked network would otherwise turn every scroll into a retry storm.

NEWSBLUR.translator = {

    TARGET_LANG: 'ZH',
    MAX_BATCH_TEXTS: 20,
    MAX_BATCH_CHARS: 5000,
    MAX_CONCURRENCY: 2,
    FAILURES_BEFORE_PAUSE: 3,
    PAUSE_MS: 60 * 1000,
    STORAGE_KEY: 'nb-translate:feed',

    cache: {},
    queue: [],
    inflight: {},
    active_requests: 0,
    failures: 0,
    paused_until: 0,
    enabled_feed: null,

    initialize: function () {
        this.enabled_feed = this.read_stored_feed();
    },

    // ========
    // = Feed =
    // ========

    read_stored_feed: function () {
        try {
            return window.localStorage.getItem(this.STORAGE_KEY) || null;
        } catch (e) {
            return null;
        }
    },

    is_enabled: function (feed_id) {
        if (this.enabled_feed === null || feed_id === null || feed_id === undefined) return false;
        return String(this.enabled_feed) === String(feed_id);
    },

    enable: function (feed_id) {
        this.enabled_feed = String(feed_id);
        this.failures = 0;
        this.paused_until = 0;
        try {
            window.localStorage.setItem(this.STORAGE_KEY, this.enabled_feed);
        } catch (e) {}
    },

    disable: function () {
        this.enabled_feed = null;
        try {
            window.localStorage.removeItem(this.STORAGE_KEY);
        } catch (e) {}
    },

    // ===========
    // = Batching =
    // ===========

    is_paused: function () {
        return this.paused_until > new Date().getTime();
    },

    // Resolves with one entry per input: the translation, or '' when the upstream could
    // not be reached. Callers treat '' as "leave the original text alone".
    translate: function (texts) {
        var self = this;
        var deferred = $.Deferred();
        var results = new Array(texts.length);
        var waiting = 0;

        if (!texts.length) {
            deferred.resolve([]);
            return deferred.promise();
        }
        if (this.is_paused()) {
            deferred.resolve(_.map(texts, function () { return ''; }));
            return deferred.promise();
        }

        _.each(texts, function (text, index) {
            var key = text;
            if (!key) { results[index] = ''; return; }
            if (_.has(self.cache, key)) { results[index] = self.cache[key]; return; }
            waiting += 1;
            self.enqueue(key, function (translation) {
                results[index] = translation || '';
                waiting -= 1;
                if (waiting === 0) deferred.resolve(results);
            });
        });

        if (waiting === 0) deferred.resolve(results);
        return deferred.promise();
    },

    enqueue: function (text, callback) {
        if (_.has(this.inflight, text)) {
            this.inflight[text].push(callback);
            return;
        }
        this.inflight[text] = [callback];
        this.queue.push(text);
        this.pump();
    },

    pump: function () {
        var self = this;
        if (!this.queue.length) return;
        if (this.active_requests >= this.MAX_CONCURRENCY) return;
        if (this.is_paused()) {
            this.flush_queue();
            return;
        }

        var batch = this.take_batch();
        if (!batch.length) return;

        this.active_requests += 1;
        $.ajax({
            url: NEWSBLUR.URLs['translate-text'],
            type: 'POST',
            dataType: 'json',
            contentType: 'application/json',
            data: JSON.stringify({ texts: batch, target_lang: this.TARGET_LANG }),
            success: function (response) {
                self.active_requests -= 1;
                if (response && response.code === 0) {
                    self.failures = 0;
                    self.resolve_batch(batch, response.translations || []);
                } else {
                    self.note_failure();
                    self.resolve_batch(batch, null);
                }
                self.pump();
            },
            error: function () {
                self.active_requests -= 1;
                self.note_failure();
                self.resolve_batch(batch, null);
                self.pump();
            }
        });
    },

    take_batch: function () {
        var batch = [];
        var chars = 0;
        while (this.queue.length && batch.length < this.MAX_BATCH_TEXTS) {
            var text = this.queue[0];
            if (batch.length && chars + text.length > this.MAX_BATCH_CHARS) break;
            this.queue.shift();
            batch.push(text);
            chars += text.length;
        }
        return batch;
    },

    resolve_batch: function (batch, translations) {
        var self = this;
        _.each(batch, function (text, index) {
            var translation = translations ? translations[index] : '';
            if (translation) self.cache[text] = translation;
            var callbacks = self.inflight[text] || [];
            delete self.inflight[text];
            _.each(callbacks, function (callback) {
                callback(translation || '');
            });
        });
    },

    flush_queue: function () {
        var self = this;
        var queued = this.queue;
        this.queue = [];
        _.each(queued, function (text) {
            var callbacks = self.inflight[text] || [];
            delete self.inflight[text];
            _.each(callbacks, function (callback) { callback(''); });
        });
    },

    note_failure: function () {
        this.failures += 1;
        if (this.failures >= this.FAILURES_BEFORE_PAUSE) {
            this.paused_until = new Date().getTime() + this.PAUSE_MS;
            this.failures = 0;
        }
    }
};
