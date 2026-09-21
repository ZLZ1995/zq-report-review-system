// Dependency-free interaction tests for the actual shipped browser script.
const {readFileSync} = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const elements = new Map();
function element() {
  return {value:'', disabled:false, children:[], events:{},
    addEventListener(name, fn) {this.events[name] = fn;},
    replaceChildren() {this.children=[]; this.value='';},
    append(child) {this.children.push(child);},
    querySelectorAll() {return [];}, reset() {}};
}
const get = id => {if (!elements.has(id)) elements.set(id, element()); return elements.get(id);};
let resolveRequest;
const context = vm.createContext({
  document: {getElementById:get, createElement:element, querySelectorAll:()=>[]},
  fetch: () => new Promise(resolve => {resolveRequest=resolve;}),
  console, TypeError,
});
vm.runInContext(readFileSync('src/asset_based_agent/report_review_server/admin_assets/app.js','utf8'), context);
function response(models) {resolveRequest({ok:true,status:200,json:async()=>({models,discovery_token:'ticket'})});}
(async () => {
  get('channel-url').value='https://api.deepseek.com';
  get('channel-url').events.input();
  assert.equal(get('test-connection').disabled,true);
  get('channel-key').value='secret'; get('channel-key').events.input();
  assert.equal(get('test-connection').disabled,false);
  let request=get('test-connection').events.click();
  assert.equal(get('test-connection').disabled,true);
  response(['one','two']); await request;
  assert.deepEqual(get('model-choice').children.map(x=>x.value),['','one','two']);
  assert.equal(get('save-channel').disabled,true); // no automatic selection
  get('model-choice').value='two'; get('model-choice').events.change();
  assert.equal(get('save-channel').disabled,false);
  get('channel-key').value='changed'; get('channel-key').events.input();
  assert.equal(get('model-choice').disabled,true);
  assert.equal(get('save-channel').disabled,true);
  request=get('test-connection').events.click();
  get('channel-url').value='https://new.example.com'; get('channel-url').events.input();
  response(['stale']); await request;
  assert.equal(get('model-choice').disabled,true); // late response ignored
  assert.equal(get('model-choice').children.some(x=>x.value==='stale'),false);
  request=get('test-connection').events.click();
  resolveRequest({ok:false,status:502,json:async()=>({error:{code:'discovery_failed',message:'Denied'}})});
  await request;
  assert.equal(get('connection-status').textContent,'Denied');
  assert.equal(get('save-channel').disabled,true);
  console.log('PASS: missing credentials, discovery, manual selection, invalidation, stale response, safe failure');
})().catch(error => {console.error(error); process.exitCode=1;});
