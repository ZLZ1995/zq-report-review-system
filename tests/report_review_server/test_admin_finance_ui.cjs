const {readFileSync} = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const elements = new Map();
function element() {
  return {value: '', type: '', checked: false, disabled: false, events: {}, children: [],
    addEventListener(name, fn) { this.events[name] = fn; },
    replaceChildren() { this.children = []; }, append(x) { this.children.push(x); },
    querySelector() { return get('save-finance'); }, querySelectorAll() { return []; }, reset() {}};
}
const get = id => { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); };
const calls = [];
const context = vm.createContext({
  document: {getElementById: get, createElement: element, querySelectorAll: () => []},
  fetch: async (url, options) => {
    calls.push({url, options});
    return {ok: true, status: 200, json: async () => ({api_key_configured: true})};
  }, console, TypeError,
});
vm.runInContext(readFileSync('src/asset_based_agent/report_review_server/admin_assets/app.js', 'utf8'), context);
(async () => {
  vm.runInContext("token = 'synthetic-admin-token'", context);
  get('finance-key').value = 'synthetic-key';
  get('finance-key').events.input();
  assert.match(get('finance-key-count').textContent, /13/);
  get('finance-key-visible').checked = true;
  get('finance-key-visible').events.change();
  assert.equal(get('finance-key').type, 'text');
  await get('finance-key-form').events.submit({preventDefault() {}, currentTarget: get('finance-key-form')});
  assert.equal(calls[0].options.method, 'PUT');
  assert.equal(JSON.parse(calls[0].options.body).api_key, 'synthetic-key');
  assert.equal(get('finance-key').value, '');
  assert.equal(get('finance-key').type, 'password');
  assert.equal(get('finance-key-visible').checked, false);
  assert.match(get('finance-status').textContent, /已配置/);
  assert.ok(!get('finance-status').textContent.includes('synthetic-key'));
  console.log('PASS: finance key count, reveal, encrypted-save contract, input clearing and status');
})().catch(error => { console.error(error); process.exitCode = 1; });
