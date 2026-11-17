const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function load(file) {
    let submitted;
    let unload;
    const element = { off() { return this; }, on(event, callback) { unload = callback; return this; } };
    const $ = () => element;
    $.extend = Object.assign;
    $.ajax = options => { submitted = options.data; };
    const context = {
        NEWSBLUR: { Views: {}, Modal: function () {} },
        Backbone: { View: { extend: methods => methods } },
        _: { extend: Object.assign },
        $,
        window: {},
        navigator: { sendBeacon(url, data) { submitted = data; } },
        FormData,
        // test_web.js deliberately changes every message to expose translated protocol identifiers.
        gettext: message => 'übersetzt:' + message,
    };
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', file), 'utf8'), context);
    return { context, submitted: () => submitted, unload: () => unload() };
}

test('icon uploads keep feed and folder field names in a non-English interface', () => {
    const fixture = load('media/js/newsblur/reader/reader_feed_exception.js');
    const upload = fixture.context.NEWSBLUR.ReaderFeedException.prototype.upload_icon_file;
    const file = new Blob(['icon']);
    upload.call({ feed: true, feed_id: 123 }, file);
    assert.deepEqual([...fixture.submitted().keys()], ['feed_id', 'photo']);
    assert.equal(fixture.submitted().get('feed_id'), '123');
    upload.call({ folder: true, folder_title: 'My folder' }, file);
    assert.deepEqual([...fixture.submitted().keys()], ['folder_title', 'photo']);
    assert.equal(fixture.submitted().get('folder_title'), 'My folder');
});

