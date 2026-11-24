const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../web/public/site-visit-preference.js'), 'utf8');
const clientImport = "import('/.well-known/site-visits/client.mjs')";
const origin = 'https://videotrans.app';

class Element {
  constructor() { this.events = new Map(); this.children = []; }
  append(...elements) { this.children.push(...elements); }
  addEventListener(type, listener) { this.events.set(type, listener); }
}
function storage() {
  const values = new Map();
  return {
    getItem(key) { return values.get(key) || null; },
    setItem(key, value) { values.set(key, value); },
    removeItem(key) { values.delete(key); },
  };
}
function fixture(status = 204, browser = {}) {
  const document = new Element();
  const window = new Element();
  const localStorage = storage();
  const sessionStorage = storage();
  Object.assign(document, {
    currentScript: { dataset: { siteOrigin: origin, context: 'server' } },
    documentElement: { lang: 'tr' }, visibilityState: 'visible', body: new Element(),
    createElement: () => new Element(), getElementById: () => null, createTextNode: text => text,
  });
  const calls = { context: 0, client: 0, records: 0, clear: 0 };
  const fixtureClient = async () => {
    calls.client++;
    return {
      recordPageVisit({ hasAnalyticsConsent, isOwner }) {
        assert.equal(hasAnalyticsConsent(), true);
        assert.equal(isOwner(), false);
        calls.records++;
      },
      clearVisitIdentifier() { calls.clear++; },
    };
  };
  assert.ok(source.includes(clientImport));
  vm.runInNewContext(source.replace(clientImport, 'fixtureClient()'), {
    document, window, sessionStorage, localStorage, navigator: browser,
    location: { origin, pathname: '/' }, fixtureClient,
    fetch: async (url, options) => {
      assert.equal(url, '/api/site-visit-context');
      assert.equal(options.credentials, 'same-origin');
      calls.context++;
      return { status };
    },
  });
  const toggle = document.body.children[0].children[1].children[0];
  return { calls, localStorage, sessionStorage, window, toggle };
}
const flush = () => new Promise(resolve => setImmediate(resolve));
for (const [name, status, browser, expected] of [
  ['anonymous', 204, {}, 1], ['credentials present', 409, {}, 0], ['unknown context', 503, {}, 0],
  ['GPC', 204, { globalPrivacyControl: true }, 0], ['DNT', 204, { doNotTrack: '1' }, 0],
  ['automation', 204, { webdriver: true }, 0],
]) {
  test(name, async () => {
    const f = fixture(status, browser);
    await flush();
    assert.deepEqual(f.calls, { context: 0, client: 0, records: 0, clear: 0 });
    f.toggle.checked = true;
    f.toggle.events.get('change')();
    await flush();
    assert.equal(f.calls.records, expected);
  });
}
test('withdrawal stops an existing opt-in when persistent storage cannot be changed', async () => {
  const f = fixture();
  f.toggle.checked = true;
  f.toggle.events.get('change')();
  await flush();
  assert.equal(f.calls.records, 1);
  f.localStorage.removeItem = () => { throw new Error('blocked'); };
  f.toggle.checked = false;
  f.toggle.events.get('change')();
  await flush();
  f.window.events.get('pageshow')();
  await flush();
  assert.equal(f.calls.records, 1);
  assert.equal(f.calls.clear, 1);
  assert.equal(f.sessionStorage.getItem('site-visits:analytics-choice:v1:withdrawn'), '1');
});
