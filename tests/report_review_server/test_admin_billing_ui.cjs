const {readFileSync} = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const elements = new Map();
function element() {return {value:'', textContent:'', children:[], events:{},
  addEventListener(k,v){this.events[k]=v;}, replaceChildren(){this.children=[];this.value='';},
  append(v){this.children.push(v);}, querySelectorAll(){return [];}, reset(){}};}
const get = id => {if(!elements.has(id)) elements.set(id,element());return elements.get(id);};
let accepted=false, calls=[], reply;
const ctx=vm.createContext({document:{getElementById:get,createElement:element,querySelectorAll:()=>[]},
  confirm:()=>accepted, TypeError, console, fetch:async(url, opts)=>{calls.push([url,opts.method]);return reply(url,opts);}});
vm.runInContext(readFileSync('src/asset_based_agent/report_review_server/admin_assets/app.js','utf8'),ctx);
const run=code=>vm.runInContext(code,ctx);
const ok=data=>({ok:true,status:200,json:async()=>data});
(async()=>{
  run("token='admin-session'");
  const data={hold_id:'hold-1',confirmed_amount:'0.12',evidence_sha256:'a'.repeat(64),evidence_reference:'REF'};
  ctx.data=data;
  reply=async()=>ok({reconciliation_id:'r',hold_id:'hold-1',confirmed_amount:'0.12'});
  await run('submitReconciliation(data)');
  assert.equal(calls.length,0); // cancelled confirmation never posts
  accepted=true;
  reply=async()=>({ok:false,status:422,json:async()=>({})});
  await run('submitReconciliation(data)');
  assert.match(get('billing-result').textContent,/输入/);
  calls=[];
  reply=async()=>{throw new TypeError('synthetic-network-secret');};
  await run('submitReconciliation(data)');
  assert.equal(calls.length,1);
  await run('submitReconciliation(data)');
  assert.equal(calls.length,1); // unknown outcome cannot blindly repeat
  assert.match(get('billing-result').textContent,/查询回执/);
  assert(!get('billing-result').textContent.includes('secret'));
  get('billing-hold').value='hold-1';
  reply=async()=>ok({reconciliation_id:'r',hold_id:'hold-1',confirmed_amount:'0.12'});
  await run('queryReconciliation()');
  assert.equal(calls.at(-1)[1],'GET');
  assert.match(get('billing-result').textContent,/r/);
  await run('submitReconciliation(data)');
  assert.equal(calls.at(-1)[1],'POST');
  assert.match(get('billing-result').textContent,/已确认总费用/);
  let release;
  reply=()=>new Promise(resolve=>{release=resolve;});
  const loading=run('loadBillingHolds(0)');
  run('clearSession()');
  release(ok({items:[{hold_id:'stale',user_id:'private'}],next_offset:null}));
  await loading;
  assert.equal(get('billing-choice').children.length,0);
  assert.equal(get('billing-result').textContent,'');
  console.log('PASS: confirmation, unknown write, receipt GET, logout and stale response');
})().catch(e=>{console.error(e);process.exitCode=1;});
