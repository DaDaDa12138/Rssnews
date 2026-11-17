// Browser smoke tests for the reader shell.
//
// These drive a real Chrome over the DevTools protocol instead of Django's test
// client, so the things only a browser can catch fail the build: a pane that
// covers the feed list (media/css/reader/core/07-panes.css), a layout switch
// that leaves the reading pane off screen, a theme that does not survive a
// reload, and any uncaught exception from media/js/newsblur/reader/reader.js.
//
// There is no npm dependency on purpose: this repo ships no node_modules, and
// the protocol surface used here is small. Chrome is whatever CHROME_BIN points
// at, or the first of the usual names found on PATH.
//
// Usage:
//   make smoke
//   SMOKE_BASE_URL=https://newsblur.example.com SMOKE_USER=reader node tests/browser/smoke.mjs
//
// The reader must be reachable and DEBUG must be on so /reader/dev/autologin/
// can sign the user in; see apps/reader/views/pages.py.

import { spawn } from 'node:child_process';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const BASE_URL = (process.env.SMOKE_BASE_URL || 'http://localhost:8080').replace(/\/$/, '');
const USER = process.env.SMOKE_USER || 'reader';
const HEADLESS = process.env.SMOKE_HEADLESS !== '0';
const SHOT_DIR = process.env.SMOKE_SHOTS || '';
const CHROME_CANDIDATES = [
  process.env.CHROME_BIN,
  'google-chrome',
  'google-chrome-stable',
  'chromium',
  'chromium-browser',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
].filter(Boolean);

const READER_URL = `${BASE_URL}/reader/dev/autologin/${USER}/?next=/reader/`;
const VIEWPORT = { width: 1440, height: 900 };
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

class Failure extends Error {}

function assert(condition, message) {
  if (!condition) throw new Failure(message);
}

function rgb(value) {
  const parts = String(value).match(/\d+/g);
  return parts ? parts.slice(0, 3).map(Number) : [0, 0, 0];
}

function luma(value) {
  const [r, g, b] = rgb(value);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

// Launches Chrome and returns a session that speaks the few CDP methods the
// flows need. Everything is awaited in order, so a failed navigation surfaces
// as the assertion that follows it rather than a timeout somewhere else.
async function openBrowser() {
  const port = 9500 + Math.floor(Math.random() * 400);
  const profile = mkdtempSync(join(tmpdir(), 'nb-smoke-'));
  const args = [
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profile}`,
    `--window-size=${VIEWPORT.width},${VIEWPORT.height}`,
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-gpu',
    '--disable-dev-shm-usage',
    '--hide-scrollbars',
    ...(HEADLESS ? ['--headless=new'] : []),
    'about:blank',
  ];

  let child = null;
  let lastError = null;
  for (const binary of CHROME_CANDIDATES) {
    try {
      child = spawn(binary, args, { stdio: ['ignore', 'ignore', 'pipe'] });
      await new Promise((resolve, reject) => {
        child.once('error', reject);
        child.once('spawn', resolve);
      });
      break;
    } catch (error) {
      lastError = error;
      child = null;
    }
  }
  if (!child) {
    throw new Failure(`could not start Chrome (${lastError && lastError.message}); set CHROME_BIN`);
  }

  let target = null;
  for (let attempt = 0; attempt < 80 && !target; attempt += 1) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      target = list.find((entry) => entry.type === 'page');
    } catch (error) {
      // Chrome has not opened the debugging port yet.
    }
    if (!target) await sleep(250);
  }
  if (!target) {
    child.kill('SIGKILL');
    throw new Failure('Chrome never opened its debugging port');
  }

  const ws = new WebSocket(target.webSocketDebuggerUrl);
  const pending = new Map();
  const consoleErrors = [];
  let nextId = 0;

  ws.addEventListener('message', (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
      return;
    }
    if (message.method === 'Runtime.exceptionThrown') {
      const details = message.params.exceptionDetails;
      consoleErrors.push((details.exception && details.exception.description) || details.text);
    }
    if (message.method === 'Runtime.consoleAPICalled' && message.params.type === 'error') {
      const text = message.params.args.map((arg) => arg.value || arg.description || '').join(' ');
      if (!/favicon\.ico/.test(text)) consoleErrors.push(text);
    }
  });
  await new Promise((resolve) => ws.addEventListener('open', resolve));

  const send = (method, params = {}, sessionId = undefined) => new Promise((resolve) => {
    const id = ++nextId;
    pending.set(id, resolve);
    const message = { id, method, params };
    if (sessionId) message.sessionId = sessionId;
    ws.send(JSON.stringify(message));
  });

  const evaluate = async (expression) => {
    const reply = await send('Runtime.evaluate', {
      expression,
      returnByValue: true,
      awaitPromise: true,
    });
    const result = reply.result && reply.result.result;
    if (reply.result && reply.result.exceptionDetails) {
      throw new Failure(`page threw: ${reply.result.exceptionDetails.text} in ${expression.slice(0, 80)}`);
    }
    return result ? result.value : undefined;
  };

  const waitFor = async (expression, { timeout = 15000, interval = 150, describe = expression } = {}) => {
    const deadline = Date.now() + timeout;
    let value;
    while (Date.now() < deadline) {
      value = await evaluate(expression);
      if (value) return value;
      await sleep(interval);
    }
    throw new Failure(`timed out waiting for ${describe}`);
  };

  const navigate = async (url) => {
    const loaded = new Promise((resolve) => {
      const listener = (event) => {
        const message = JSON.parse(event.data);
        if (message.method === 'Page.loadEventFired') {
          ws.removeEventListener('message', listener);
          resolve();
        }
      };
      ws.addEventListener('message', listener);
    });
    await send('Page.navigate', { url });
    await Promise.race([loaded, sleep(20000)]);
  };

  const click = async (x, y) => {
    const point = { x: Math.round(x), y: Math.round(y) };
    await send('Input.dispatchMouseEvent', { type: 'mouseMoved', ...point, button: 'none' });
    await send('Input.dispatchMouseEvent', { type: 'mousePressed', ...point, button: 'left', clickCount: 1 });
    await send('Input.dispatchMouseEvent', { type: 'mouseReleased', ...point, button: 'left', clickCount: 1 });
  };

  const screenshot = async (name) => {
    if (!SHOT_DIR) return;
    const reply = await send('Page.captureScreenshot', { format: 'png' });
    writeFileSync(join(SHOT_DIR, `smoke-${name}.png`), Buffer.from(reply.result.data, 'base64'));
  };

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');
  await send('Target.setDiscoverTargets', { discover: true });

  let serviceWorkerSession = null;
  const attachServiceWorker = async () => {
    const targets = await send('Target.getTargets');
    const worker = (targets.result.targetInfos || []).find(
      (info) => info.type === 'service_worker' && info.url.indexOf('/service-worker.js') !== -1,
    );
    if (!worker) return null;
    const attached = await send('Target.attachToTarget', { targetId: worker.targetId, flatten: true });
    const sessionId = attached.result && attached.result.sessionId;
    if (!sessionId) return null;
    await send('Network.enable', {}, sessionId);
    return sessionId;
  };

  const blockUrls = async (urls) => {
    await send('Network.setBlockedURLs', { urls });
    if (urls.length && !serviceWorkerSession) {
      serviceWorkerSession = await attachServiceWorker();
    }
    if (serviceWorkerSession) {
      await send('Network.setBlockedURLs', { urls }, serviceWorkerSession);
    }
  };

  const setViewport = async (width, height, mobile = false) => {
    await send('Emulation.setDeviceMetricsOverride', {
      width,
      height,
      mobile,
      deviceScaleFactor: 1,
    });
  };

  return {
    evaluate,
    waitFor,
    navigate,
    click,
    screenshot,
    setViewport,
    blockUrls,
    consoleErrors,
    close() {
      try { ws.close(); } catch (error) { /* already gone */ }
      child.kill('SIGKILL');
    },
  };
}

// Waits for the reader shell to finish its first story load. #story_titles is
// filled by media/js/newsblur/reader/story_titles.js.
async function openReader(browser) {
  await browser.navigate(READER_URL);
  await browser.waitFor('document.body && document.body.classList.contains("NB-is-authenticated")', {
    describe: 'the reader to sign in (is DEBUG on?)',
  });
  await browser.waitFor('document.querySelectorAll("#story_titles .NB-story-title").length > 0', {
    describe: 'story titles',
  });
}

const flows = [];
const flow = (name, run) => flows.push({ name, run });

flow('static login page loads without the reader bundle', async (browser) => {
  await browser.navigate(`${BASE_URL}/account/login/`);
  await browser.waitFor('document.querySelector(".NB-static-card")', {
    describe: 'the login card',
  });
  const state = await browser.evaluate(`(() => ({
    scripts: Array.from(document.querySelectorAll("script[src]")).map((script) => script.getAttribute("src")),
    focused: document.activeElement && document.activeElement.name,
    toggles: document.querySelectorAll(".NB-theme-toggle").length,
    modules: Boolean(window.NEWSBLUR_MODULES && window.NEWSBLUR_MODULES.theme),
  }))()`);
  assert(state.scripts.some((src) => /\/js\/static\.[^/]+\.js/.test(src)), 'login page did not load the static bundle');
  assert(!state.scripts.some((src) => /\/js\/common(_vendor)?\./.test(src)), 'login page still loads the reader bundle');
  assert(state.focused === 'username', 'the username field did not receive focus');
  assert(state.toggles === 1, 'the theme toggle is missing');
  assert(state.modules, 'the static bundle did not expose the theme module');

  // The top splash is hidden on public pages, so click the toggle in the DOM
  // instead of at screen coordinates. The handler is the part under test.
  await browser.evaluate('document.querySelector(".NB-theme-toggle").click()');
  await browser.waitFor('document.body.classList.contains("NB-dark")', {
    describe: 'the dark theme',
  });

  await browser.navigate(`${BASE_URL}/account/login/`);
  await browser.waitFor('document.body.classList.contains("NB-dark")', {
    describe: 'the stored dark theme after reload',
  });

  // These pages share base_static.html and the strict style-src policy. A
  // blocked inline style shows up as a console error, and a missing stylesheet
  // leaves the card at 0px wide, so check the rendered result instead of just
  // the element's presence.
  for (const path of ['/account/signup/', '/welcome/', '/profile/forgot_password/']) {
    await browser.navigate(`${BASE_URL}${path}`);
    const card = await browser.waitFor(`(() => {
      const element = document.querySelector(".NB-static-card");
      if (!element) return null;
      const box = element.getBoundingClientRect();
      const radius = getComputedStyle(element).borderRadius;
      return box.width > 300 && radius !== "0px" ? { width: box.width, radius } : null;
    })()`, { describe: `the styled static card on ${path}` });
    assert(card.width > 300, `${path} card collapsed to ${card.width}px`);
    assert(card.radius !== '0px', `${path} card lost its rounded corners`);
  }
});

flow('reader shell loads', async (browser) => {
  await openReader(browser);
  const state = await browser.evaluate(`(() => ({
    feeds: document.querySelectorAll("#feed_list li.feed").length,
    titles: document.querySelectorAll("#story_titles .NB-story-title").length,
    layout: document.querySelector("#story_titles").className,
    dark: document.body.classList.contains("NB-dark"),
  }))()`);
  assert(state.feeds > 0, 'the feed list is empty');
  assert(state.titles > 0, 'no story titles rendered');
  assert(/NB-layout-/.test(state.layout), `#story_titles is missing its layout class: ${state.layout}`);
  await browser.screenshot('reader');
});

// The regression this suite exists for: the hidden reading pane used to sit on
// top of the feed list at the same coordinates, so a real mouse click landed on
// an invisible element and the story list never changed.
flow('feed list takes the click', async (browser) => {
  await openReader(browser);
  const target = await browser.evaluate(`(() => {
    const item = document.querySelector("#feed_list li.feed");
    if (!item) return null;
    const title = item.querySelector(".feed_title") || item;
    const box = title.getBoundingClientRect();
    const hit = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2);
    return {
      id: Number(item.dataset.id),
      x: box.x + box.width / 2,
      y: box.y + box.height / 2,
      hit: hit ? hit.tagName + "." + String(hit.className).split(" ").slice(0, 2).join(".") : "none",
      inside: Boolean(hit && item.contains(hit)),
    };
  })()`);
  assert(target, 'no feed in the sidebar to click');
  assert(target.inside, `another element covers the feed list: ${target.hit}`);
  await browser.click(target.x, target.y);
  await browser.waitFor(
    `window.NEWSBLUR.reader.active_feed === ${target.id} && document.querySelectorAll("#story_titles .NB-story-title").length > 0`,
    { describe: `feed ${target.id} to load its stories` },
  );
  await browser.screenshot('feed');
});

flow('layout switch keeps both panes on screen', async (browser) => {
  await openReader(browser);
  await browser.evaluate('NEWSBLUR.reader.switch_story_layout("split")');
  const split = await browser.waitFor(`(() => {
    const pane = document.querySelector("#story_pane");
    const titles = document.querySelector("#story_titles");
    const paneBox = pane.getBoundingClientRect();
    const titleBox = titles.getBoundingClientRect();
    if (getComputedStyle(pane).display === "none" || paneBox.width < 300) return null;
    return {
      pane: [Math.round(paneBox.x), Math.round(paneBox.y), Math.round(paneBox.width), Math.round(paneBox.height)],
      titles: [Math.round(titleBox.x), Math.round(titleBox.y), Math.round(titleBox.width), Math.round(titleBox.height)],
    };
  })()`, { describe: 'the split layout to place the reading pane' });
  assert(split.titles[2] > 200, `the title column collapsed to ${split.titles[2]}px`);
  assert(split.pane[0] >= split.titles[0] + split.titles[2], 'the reading pane overlaps the title column');
  assert(split.pane[1] >= 0 && split.pane[1] < VIEWPORT.height, 'the reading pane sits off screen');
  await browser.screenshot('split');

  await browser.evaluate('NEWSBLUR.reader.switch_story_layout("list")');
  const list = await browser.waitFor(`(() => {
    const pane = document.querySelector("#story_pane");
    const titles = document.querySelector("#story_titles");
    if (getComputedStyle(pane).display !== "none") return null;
    return { width: Math.round(titles.getBoundingClientRect().width) };
  })()`, { describe: 'the list layout to hide the reading pane' });
  assert(list.width > 600, `the title column is only ${list.width}px wide in list layout`);
});

flow('theme survives a reload', async (browser) => {
  await openReader(browser);
  await browser.evaluate('NEWSBLUR.reader.switch_theme("dark")');
  // The theme crossfades for a second (media/css/reader/dark/01-base.css), so
  // wait for the painted colour rather than for the class alone.
  const dark = await browser.waitFor(`(() => {
    if (!document.body.classList.contains("NB-dark")) return null;
    const colour = getComputedStyle(document.body).backgroundColor;
    const [r, g, b] = colour.match(/\\d+/g).map(Number);
    return r + g + b < 200 ? colour : null;
  })()`, { describe: 'the dark theme to paint', timeout: 8000 });
  assert(/^rgb/.test(dark), `unexpected dark background: ${dark}`);

  await browser.navigate(READER_URL);
  await browser.waitFor('document.body && document.body.classList.contains("NB-is-authenticated")', {
    describe: 'the reader after reload',
  });
  await browser.waitFor('document.body.classList.contains("NB-dark")', {
    describe: 'the dark theme after a reload (see apps/profile/preferences.py)',
  });

  await browser.evaluate('NEWSBLUR.reader.switch_theme("light")');
  await browser.waitFor('!document.body.classList.contains("NB-dark")', { describe: 'the light theme' });
});

// The dark stylesheet is a separate 3,000 line layer over the reader. A rule
// that is deleted there does not fail any Python test, so paint the surfaces
// that share those selectors and assert they stay dark and legible.
flow('dark theme keeps reader and dialogs legible', async (browser) => {
  await openReader(browser);
  await browser.evaluate('NEWSBLUR.reader.switch_theme("dark")');
  await browser.waitFor(`(() => {
    if (!document.body.classList.contains("NB-dark")) return false;
    const colour = getComputedStyle(document.body).backgroundColor;
    const [r, g, b] = colour.match(/\\d+/g).map(Number);
    return r + g + b < 200;
  })()`, { describe: 'the dark reader to paint', timeout: 8000 });
  // The theme crossfades for a second (media/css/reader/dark/01-base.css).
  await sleep(1200);

  const reader = await browser.evaluate(`(() => {
    const read = (selector) => {
      const node = document.querySelector(selector);
      if (!node) return null;
      const style = getComputedStyle(node);
      return { background: style.backgroundColor, colour: style.color };
    };
    return {
      body: read("body"),
      feedList: read("#feed_list"),
      titles: read("#story_titles"),
      story: read("#story_pane"),
    };
  })()`);
  assert(luma(reader.body.background) < 120, `the dark reader body is ${reader.body.background}`);
  assert(luma(reader.feedList.background) < 140, `the dark feed list is ${reader.feedList.background}`);
  assert(luma(reader.body.colour) > 140, `the dark reader text is ${reader.body.colour}`);
  await browser.screenshot('dark-reader');

  await browser.evaluate('NEWSBLUR.reader.open_preferences_modal()');
  await browser.waitFor('document.querySelector(".simplemodal-container")', {
    describe: 'the preferences modal in dark mode',
  });
  await sleep(600);
  const modal = await browser.evaluate(`(() => {
    const dialog = document.querySelector(".simplemodal-container");
    const title = dialog.querySelector(".NB-modal-title");
    const read = (node) => {
      if (!node) return null;
      const style = getComputedStyle(node);
      return { background: style.backgroundColor, colour: style.color };
    };
    return { dialog: read(dialog), title: read(title) };
  })()`);
  assert(luma(modal.dialog.background) < 100, `the dark dialog is ${modal.dialog.background}`);
  assert(luma(modal.dialog.colour) > 140, `the dark dialog text is ${modal.dialog.colour}`);
  assert(luma(modal.title.colour) > 140, `the dark dialog title is ${modal.title.colour}`);
  await browser.screenshot('dark-preferences');
  await browser.evaluate('$.modal.close()');
  await browser.waitFor('!document.querySelector(".simplemodal-container")', {
    describe: 'the preferences modal to close',
  });

  await browser.evaluate('NEWSBLUR.reader.open_add_feed_modal()');
  await browser.waitFor('document.querySelector(".NB-add-popover-container")', {
    describe: 'the add feed popover in dark mode',
  });
  await sleep(400);
  const popover = await browser.evaluate(`(() => {
    const node = document.querySelector(".NB-add-popover-container");
    const style = getComputedStyle(node);
    return { background: style.backgroundColor, colour: style.color };
  })()`);
  assert(luma(popover.background) < 100, `the dark add feed popover is ${popover.background}`);
  assert(luma(popover.colour) > 140, `the dark add feed text is ${popover.colour}`);
  await browser.screenshot('dark-add-feed');
  await browser.evaluate('NEWSBLUR.add_feed.close()');

  await browser.evaluate('NEWSBLUR.reader.switch_story_layout("split")');
  await browser.waitFor('getComputedStyle(document.querySelector("#story_pane")).display !== "none"', {
    describe: 'the dark split layout',
  });
  await sleep(400);
  await browser.screenshot('dark-split');

  await browser.setViewport(390, 844, true);
  await browser.navigate(READER_URL);
  await browser.waitFor('document.body && document.body.classList.contains("NB-is-authenticated")', {
    describe: 'the mobile reader',
  });
  await browser.evaluate('NEWSBLUR.reader.switch_theme("dark")');
  await browser.waitFor('document.body.classList.contains("NB-dark")', { describe: 'the mobile dark theme' });
  await browser.evaluate('NEWSBLUR.reader.switch_story_layout("list")');
  await sleep(400);
  await browser.screenshot('dark-mobile');
  await browser.setViewport(1440, 900, false);

  await browser.evaluate('NEWSBLUR.reader.switch_theme("light")');
  await browser.waitFor('!document.body.classList.contains("NB-dark")', { describe: 'the light theme' });
});

// The installable shell is an enhancement, but its failure modes are silent:
// a worker that never activates, a cache that misses a bundle, or a navigation
// that shows a blank page instead of the offline shell. Drive the real browser
// through install, a controlled reload, and an offline navigation.
flow('installable shell registers and falls back offline', async (browser) => {
  const pwaUrl = `${BASE_URL}/reader/dev/autologin/${USER}/?next=${encodeURIComponent('/reader/?pwa=1')}`;
  await browser.navigate(pwaUrl);
  await browser.waitFor('document.body && document.body.classList.contains("NB-is-authenticated")', {
    describe: 'the reader to sign in for the PWA check',
  });
  await browser.waitFor(
    'navigator.serviceWorker.ready.then((registration) => Boolean(registration.active))',
    { describe: 'the service worker to activate', timeout: 30000 },
  );
  await browser.waitFor(
    'caches.keys().then((names) => names.some((name) => name.indexOf("newsblur-shell-") === 0))',
    { describe: 'the shell cache to be created', timeout: 30000 },
  );

  const cached = await browser.evaluate(`caches.keys().then(async (names) => {
    const name = names.find((entry) => entry.indexOf("newsblur-shell-") === 0);
    const cache = await caches.open(name);
    const requests = await cache.keys();
    return requests.map((request) => new URL(request.url).pathname);
  })`);
  assert(cached.some((path) => path.indexOf('/static/css/common.') === 0), 'common CSS is not precached');
  assert(cached.some((path) => path.indexOf('/static/js/common.') === 0), 'common JS is not precached');
  assert(cached.includes('/offline'), 'the offline shell is not precached');

  // Reload once so clients.claim() takes effect for this page.
  await browser.navigate(`${BASE_URL}/reader/`);
  await browser.waitFor('navigator.serviceWorker.controller !== null', {
    describe: 'the service worker to control the reader',
  });

  // A real HTTP error is not an offline state. If the worker treats every
  // non-OK response as a network failure, a missing page tells the reader to
  // check a connection that is working.
  await browser.navigate(`${BASE_URL}/pwa-404-probe-${Date.now()}/`);
  await browser.waitFor('document.title.indexOf("Page not found") === 0', {
    describe: 'the 404 page to pass through the worker',
    timeout: 15000,
  });
  assert(
    await browser.evaluate('document.querySelector(".NB-offline") === null'),
    'a 404 was replaced with the offline shell',
  );

  // A navigation that redirects must keep working while the worker controls
  // the page. The autologin route is a deterministic same-origin 302, so this
  // catches a worker that mistakes an opaqueredirect for a network failure.
  await browser.navigate(`${BASE_URL}/reader/dev/autologin/${USER}/?next=${encodeURIComponent('/reader/')}`);
  await browser.waitFor('document.body && document.body.classList.contains("NB-is-authenticated")', {
    describe: 'the reader after a redirect through the service worker',
  });
  const redirected_path = await browser.evaluate('location.pathname');
  assert(redirected_path === '/reader/', `redirect ended at ${redirected_path}`);

  // Only a rejected fetch should show the offline shell. DevTools offline
  // emulation does not fail the service worker's own fetch, so block the probe
  // URL at the network layer instead. That makes the worker's fetch reject the
  // same way an unreachable network does.
  await browser.blockUrls(['*pwa-offline-probe*']);
  try {
    await browser.navigate(`${BASE_URL}/pwa-offline-probe-${Date.now()}/`);
    await browser.waitFor('document.querySelector(".NB-offline")', {
      describe: 'the offline shell when the network is unavailable',
      timeout: 15000,
    });
    const radius = await browser.evaluate(
      'getComputedStyle(document.querySelector(".NB-offline")).borderRadius',
    );
    assert(radius === '18px', `offline shell CSS did not load (border-radius ${radius})`);
  } finally {
    await browser.blockUrls([]);
  }

  await browser.navigate(`${BASE_URL}/reader/`);
  await browser.waitFor('document.body && document.body.classList.contains("NB-is-authenticated")', {
    describe: 'the reader after the offline shell',
  });
});

flow('add feed popover opens without the removed chosen plugin', async (browser) => {
  await openReader(browser);
  await browser.evaluate('NEWSBLUR.reader.open_add_feed_modal()');
  await browser.waitFor('document.querySelectorAll(".NB-add-popover-container .NB-add-url").length > 0', {
    describe: 'the add feed popover',
  });
  const input = await browser.evaluate(`(() => {
    const field = document.querySelector('.NB-add-url');
    return { tag: field.tagName, autocomplete: field.getAttribute('autocomplete') };
  })()`);
  assert(input.tag === 'INPUT', `add feed field is ${input.tag}, not an input`);
  await browser.evaluate('NEWSBLUR.add_feed.close()');
  await browser.waitFor('document.querySelector(".NB-add-popover-container") === null', {
    describe: 'the add feed popover to close',
  });
});

flow('preferences modal opens and closes', async (browser) => {
  await openReader(browser);
  await browser.evaluate(`(() => {
    const trigger = document.querySelector("#feed_list li.feed .feed_title");
    trigger.tabIndex = 0;
    trigger.focus();
    NEWSBLUR.reader.open_preferences_modal();
  })()`);
  await browser.waitFor('document.querySelector(".simplemodal-container")', {
    describe: 'the preferences modal',
  });

  const opened = await browser.evaluate(`(() => {
    const dialog = document.querySelector(".simplemodal-container");
    const labelledby = dialog.getAttribute("aria-labelledby");
    const label = labelledby && document.getElementById(labelledby);
    return {
      modal: dialog.getAttribute("aria-modal"),
      label: label ? label.textContent.trim() : "",
      focusInside: dialog.contains(document.activeElement),
      readerInert: Boolean(document.querySelector("#feed_list").closest("[inert]")),
    };
  })()`);
  assert(opened.modal === 'true', 'the dialog is missing aria-modal="true": ' + JSON.stringify(opened));
  assert(opened.label.length > 0, 'the dialog has no accessible name');
  assert(opened.focusInside, 'focus did not move into the dialog');
  assert(opened.readerInert === true, 'the page behind the dialog is still reachable');

  await browser.evaluate('$.modal.close()');
  await browser.waitFor('!document.querySelector(".simplemodal-container")', {
    describe: 'the preferences modal to close',
  });

  const closed = await browser.evaluate(`(() => {
    const trigger = document.querySelector("#feed_list li.feed .feed_title");
    return {
      focusRestored: document.activeElement === trigger,
      readerInert: Boolean(document.querySelector("#feed_list").closest("[inert]")),
    };
  })()`);
  assert(closed.focusRestored, 'focus did not return to the control that opened the dialog');
  assert(closed.readerInert === false, 'the page behind the dialog is still inert');
});

async function main() {
  const browser = await openBrowser();
  const failures = [];
  let passed = 0;
  try {
    for (const { name, run } of flows) {
      const before = browser.consoleErrors.length;
      try {
        await run(browser);
        const noise = browser.consoleErrors.slice(before);
        assert(noise.length === 0, `console errors: ${noise.slice(0, 3).join(' | ')}`);
        passed += 1;
        console.log(`ok   ${name}`);
      } catch (error) {
        const message = error instanceof Failure ? error.message : (error && error.stack) || String(error);
        failures.push({ name, message });
        console.log(`FAIL ${name}: ${message.split('\n')[0]}`);
        await browser.screenshot(`fail-${name.replace(/[^a-z0-9]+/gi, '-')}`).catch(() => {});
      }
    }
  } finally {
    browser.close();
  }

  console.log(`\n${passed}/${flows.length} browser flows passed against ${BASE_URL}`);
  if (failures.length) {
    for (const failure of failures) console.error(`\n${failure.name}\n${failure.message}`);
    process.exit(1);
  }
}

main().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  process.exit(1);
});
