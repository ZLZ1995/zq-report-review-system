const {readFileSync} = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const elements = new Map();
function element() { return {value:'', disabled:false, textContent:'', children:[], events:{},
  addEventListener(k,v){this.events[k]=v;}, replaceChildren(){this.children=[];this.value='';},
  append(v){this.children.push(v);}, querySelectorAll(){return [];}, reset(){}}; }
const get = id => {if(!elements.has(id)) elements.set(id,element());return elements.get(id);};
let replies=[];
const ctx=vm.createContext({document:{getElementById:get,createElement:element,querySelectorAll:()=>[]},
  confirm:()=>true, TypeError, console, fetch:async()=>({ok:true,status:200,json:async()=>replies.shift()})});
vm.runInContext(readFileSync('src/asset_based_agent/report_review_server/admin_assets/app.js','utf8'),ctx);
const run=code=>vm.runInContext(code,ctx);
(async()=>{
  run("token='admin-session'");
  replies=[[{release_id:'r1',skill_id:'example.review',version:'1.0.0',status:'draft',package_sha256:'a'.repeat(64)}]];
  await run('refreshSkillReleases()');
  assert.equal(get('skill-release-choice').children.length,2);
  get('skill-release-choice').value='r1'; get('skill-release-choice').events.change();
  assert.equal(get('skill-release-approve').disabled,false);
  assert.equal(get('skill-release-stable').disabled,true);
  run("skillReleaseItems[0].status='approved'; updateSkillReleaseButtons()");
  assert.equal(get('skill-release-approve').disabled,true);
  assert.equal(get('skill-release-stable').disabled,false);
  run("skillReleaseItems[0].status='withdrawn'; updateSkillReleaseButtons()");
  assert.equal(get('skill-release-approve').disabled,false);
  assert.equal(get('skill-release-stable').disabled,true);
  console.log('PASS: staged Skill approval, stable gate and rollback approval');
})().catch(e=>{console.error(e);process.exitCode=1;});
