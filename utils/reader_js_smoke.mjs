#!/usr/bin/env node
// ======================================
// = Reader JavaScript smoke test (utils/reader_js_smoke.mjs) =
// ======================================

// The reader has no JavaScript test harness, so the regressions that matter
// most (a view that never loads, a null dereference in a deferred callback)
// only show up in a real browser. This script drives headless Chrome over the
// DevTools protocol, runs a short list of navigation scenarios against a
// running server, and fails if a scenario throws or leaves the reader in the
// wrong state.
//
//   node utils/reader_js_smoke.mjs
//   node utils/reader_js_smoke.mjs --base http://localhost --user sam
//
// Requires DEBUG=True on the server: it logs in through /reader/dev/autologin/.
// Node 18+ only, no dependencies (global fetch and WebSocket).

import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const args = process.argv.slice(2);
const arg = (name, fallback) => {
    const i = args.indexOf(name);
    return i >= 0 && args[i + 1] ? args[i + 1] : fallback;
};

const BASE = arg("--base", "http://localhost:8080").replace(/\/$/, "");
const USER = arg("--user", "reader");
const PORT = Number(arg("--port", "9366"));
const CHROME = arg("--chrome", "google-chrome");
const SETTLE = Number(arg("--settle", "2200"));

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Each scenario loads a path, optionally runs a snippet, then asserts a
// predicate. The predicates read the reader's own state instead of pixels so
// the checks stay stable across themes and breakpoints.
const SCENARIOS = [
    {
        name: "tryfeed-view-shows-subscribe-banner",
        path: "/site/11",
        expect: "NEWSBLUR.reader.flags['showing_feed_in_tryfeed_view'] === true && $('.NB-tryfeed-subscribe-banner').length === 1"
    },
    {
        name: "saved-refresh-stays-on-saved",
        path: "/saved",
        run: "NEWSBLUR.app.toolbar.open_current_view({}); 1",
        expect: "NEWSBLUR.reader.active_feed === 'starred' && !NEWSBLUR.reader.flags['showing_feed_in_tryfeed_view']"
    },
    {
        name: "saved-search-stays-on-saved",
        path: "/saved",
        run: "NEWSBLUR.app.toolbar.perform_search('linux'); 1",
        expect: "NEWSBLUR.reader.active_feed === 'starred' && !NEWSBLUR.reader.flags['showing_feed_in_tryfeed_view'] && NEWSBLUR.reader.flags.searching === true"
    },
    {
        name: "read-refresh-stays-on-read",
        path: "/read",
        run: "NEWSBLUR.app.toolbar.open_current_view({}); 1",
        expect: "NEWSBLUR.reader.active_feed === 'read' && !NEWSBLUR.reader.flags['showing_feed_in_tryfeed_view']"
    },
    {
        name: "add-site-refresh-does-not-enter-tryfeed",
        path: "/add",
        run: "NEWSBLUR.app.toolbar.open_current_view({}); 1",
        expect: "!NEWSBLUR.reader.flags['showing_feed_in_tryfeed_view']"
    },
    {
        name: "river-open-from-tryfeed-view",
        path: "/site/11",
        run: "NEWSBLUR.reader.open_feed('river:'); 1",
        expect: "String(NEWSBLUR.reader.active_feed).indexOf('river:') === 0 && !NEWSBLUR.reader.flags['showing_feed_in_tryfeed_view']"
    },
    {
        // reader.js used to read the ?add= URL into add_url and then pass an
        // undefined variable to open_add_feed_modal, so the whole deferred
        // post-load block threw a ReferenceError.
        name: "add-param-opens-add-feed-modal",
        path: "/reader/",
        run: "(function(){ window.history.replaceState({}, '', '/reader/?add=https%3A%2F%2Fexample.com%2Ffeed&test=1'); NEWSBLUR.reader.flags['loaded_next_after_load'] = false; NEWSBLUR.reader.load_next_after_load(); return 1; })()",
        expect: "!!NEWSBLUR.ReaderPopover._popover && NEWSBLUR.ReaderPopover._popover.options.url === 'https://example.com/feed'"
    },
    {
        // Space bar upward in split/full layout used to reference an undefined
        // split_layout variable before it could reach show_previous_story.
        name: "space-up-in-split-layout-does-not-throw",
        path: "/site/35",
        run: "(function(){ var story = NEWSBLUR.assets.stories.first(); story.set('selected', true); NEWSBLUR.reader.active_story = story; var origPref = NEWSBLUR.assets.preference, origView = NEWSBLUR.assets.view_setting; NEWSBLUR.assets.preference = function(k){ if (k === 'space_bar_action') return 'next_unread_50'; return origPref.apply(this, arguments); }; NEWSBLUR.assets.view_setting = function(){ return 'split'; }; try { NEWSBLUR.reader.page_in_story(50, -1); } finally { NEWSBLUR.assets.preference = origPref; NEWSBLUR.assets.view_setting = origView; } return 1; })()",
        expect: "true"
    }
];

class Session {
    constructor(socket) {
        this.socket = socket;
        this.id = 0;
        this.pending = new Map();
        this.exceptions = [];
        socket.addEventListener("message", (event) => {
            const message = JSON.parse(event.data);
            if (message.id && this.pending.has(message.id)) {
                const { resolve, reject } = this.pending.get(message.id);
                this.pending.delete(message.id);
                if (message.error) reject(new Error(JSON.stringify(message.error)));
                else resolve(message.result);
            }
            if (message.method === "Runtime.exceptionThrown") {
                const details = message.params.exceptionDetails;
                const text = (details.exception && details.exception.description) || details.text || "";
                this.exceptions.push(text.split("\n").slice(0, 2).join(" | ").slice(0, 300));
            }
        });
    }

    send(method, params = {}) {
        return new Promise((resolve, reject) => {
            const id = ++this.id;
            this.pending.set(id, { resolve, reject });
            this.socket.send(JSON.stringify({ id, method, params }));
        });
    }

    async evaluate(expression) {
        const result = await this.send("Runtime.evaluate", {
            expression,
            returnByValue: true,
            awaitPromise: true
        });
        if (result.exceptionDetails) {
            const details = result.exceptionDetails;
            throw new Error((details.exception && details.exception.description) || details.text);
        }
        return result.result && result.result.value;
    }

    async goto(path) {
        await this.send("Page.navigate", { url: BASE + path });
        // The reader boots before it has opened the view, so waiting for
        // NEWSBLUR alone races with the first open_feed(): an action that runs
        // too early gets undone when the initial navigation lands.
        for (let i = 0; i < 80; i++) {
            await sleep(250);
            const ready = await this.evaluate(
                "Boolean(window.NEWSBLUR && NEWSBLUR.reader && NEWSBLUR.reader.flags && " +
                    "NEWSBLUR.reader.active_feed && !NEWSBLUR.reader.flags['opening_feed'])"
            ).catch(() => false);
            if (ready) {
                await sleep(600);
                return;
            }
        }
        throw new Error("reader did not finish opening " + path);
    }
}

async function connect() {
    const profile = mkdtempSync(join(tmpdir(), "nb-smoke-"));
    const chrome = spawn(
        CHROME,
        [
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--hide-scrollbars",
            // Without this headless Chrome cannot persist the session cookie.
            "--password-store=basic",
            "--user-data-dir=" + profile,
            "--remote-debugging-port=" + PORT,
            "about:blank"
        ],
        { stdio: "ignore" }
    );

    let target = null;
    for (let i = 0; i < 80 && !target; i++) {
        try {
            const response = await fetch("http://127.0.0.1:" + PORT + "/json/list");
            const list = await response.json();
            target = list.find((entry) => entry.type === "page");
        } catch (error) {
            // Chrome is still starting.
        }
        if (!target) await sleep(250);
    }
    if (!target) {
        chrome.kill("SIGKILL");
        throw new Error("could not reach Chrome on port " + PORT);
    }

    const socket = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => {
        socket.addEventListener("open", resolve);
        socket.addEventListener("error", reject);
    });

    const session = new Session(socket);
    await session.send("Page.enable");
    await session.send("Runtime.enable");
    await session.send("Network.setCacheDisabled", { cacheDisabled: true });
    await session.send("Emulation.setDeviceMetricsOverride", {
        width: 1440,
        height: 900,
        deviceScaleFactor: 1,
        mobile: false
    });

    await session.send("Page.navigate", { url: BASE + "/reader/dev/autologin/" + USER + "/?next=/" });
    await sleep(3000);
    const logged_in = await session.evaluate(
        "Boolean(window.NEWSBLUR && NEWSBLUR.reader && NEWSBLUR.reader.flags)"
    ).catch(() => false);
    if (!logged_in) {
        socket.close();
        chrome.kill("SIGKILL");
        throw new Error(
            "not logged in: /reader/dev/autologin/ only works with DEBUG=True, and the user " +
                USER +
                " has to exist"
        );
    }

    return {
        session,
        close() {
            socket.close();
            chrome.kill("SIGKILL");
            // Chrome keeps writing to its profile for a moment after the kill,
            // so a failed cleanup must not fail the run.
            try {
                rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
            } catch (error) {
                // The temporary profile is left for the OS to clean up.
            }
        }
    };
}

const failures = [];
const browser = await connect();

try {
    for (const scenario of SCENARIOS) {
        browser.session.exceptions.length = 0;
        await browser.session.goto(scenario.path);
        // A scenario whose setup throws has to fail on its own, not abort the
        // run: the ReferenceError this harness exists to catch happens inside
        // run(), and the remaining scenarios still need to be checked.
        let detail = "";
        if (scenario.run) {
            try {
                await browser.session.evaluate(scenario.run);
            } catch (error) {
                detail = error.message.split("\n")[0];
            }
        }
        await sleep(SETTLE);

        let passed = false;
        if (!detail) {
            try {
                passed = Boolean(await browser.session.evaluate(scenario.expect));
            } catch (error) {
                detail = error.message.split("\n")[0];
            }
        }
        const exceptions = browser.session.exceptions.slice(0, 2);
        if (exceptions.length) {
            passed = false;
            detail = exceptions[0];
        }

        const state = await browser.session
            .evaluate(
                "JSON.stringify({feed: String(NEWSBLUR.reader.active_feed), tryfeed: NEWSBLUR.reader.flags['showing_feed_in_tryfeed_view']})"
            )
            .catch(() => "{}");

        console.log((passed ? "PASS " : "FAIL ") + scenario.name + " " + state + (detail ? " :: " + detail : ""));
        if (!passed) failures.push(scenario.name);
    }
} finally {
    browser.close();
}

if (failures.length) {
    console.log("\n" + failures.length + " scenario(s) failed: " + failures.join(", "));
    process.exit(1);
}
console.log("\nall " + SCENARIOS.length + " scenarios passed");