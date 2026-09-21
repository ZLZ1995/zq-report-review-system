// Real Edge rendering of shipped assets with explicitly synthetic API responses.
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
const {chromium} = require(path.join(process.argv[2], 'playwright'));
const output = path.resolve(process.argv[3]);
const allowed = path.resolve('outputs/nl_acceptance') + path.sep;
assert(output.startsWith(allowed) && !output.toLowerCase().startsWith('c:'));
assert(!fs.existsSync(output), 'Evidence directory must be new');
fs.mkdirSync(output, {recursive:true});
const assets = path.resolve('src/asset_based_agent/report_review_server/admin_assets');
const server = http.createServer((req,res)=>{
  const name = {'/admin':'index.html','/admin/app.js':'app.js','/admin/style.css':'style.css'}[req.url];
  if(!name){res.writeHead(404);res.end();return;}
  res.setHeader('Content-Type', name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : 'text/html; charset=utf-8');
  res.end(fs.readFileSync(path.join(assets,name)));
});
(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  let browser;
  try {
    browser=await chromium.launchPersistentContext(path.join(output,'browser_profile'),
      {channel:'msedge',headless:true,chromiumSandbox:true,viewport:{width:1440,height:1100}});
    const page=await browser.newPage();
    let submits=0;
    const receipt={reconciliation_id:'SYNTHETIC-RECEIPT',hold_id:'SYNTHETIC-HOLD',confirmed_amount:'0.12'};
    await page.route('**/api/v1/**',async route=>{
      const url=new URL(route.request().url());
      let data={};
      if(url.pathname.endsWith('/auth/login')) data={access_token:'synthetic-token',user:{role:'admin',must_change_password:false}};
      else if(url.pathname.endsWith('/admin/overview')) data={users:[],models:[],routes:[]};
      else if(url.pathname.endsWith('/billing-holds')) data={items:[{hold_id:'SYNTHETIC-HOLD',user_id:'TEST-USER',client_request_id:'TEST-REQUEST',known_amount:'0.00'}],next_offset:null};
      else if(url.pathname.endsWith('/reconciliation')) {
        if(route.request().method()==='POST') {submits++;assert.equal(route.request().postDataJSON().confirmed_amount,'0.12');}
        data=receipt;
      }
      await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
    });
    await page.goto(`http://127.0.0.1:${server.address().port}/admin`);
    await page.locator('#login [name=username]').fill('synthetic-admin');
    await page.locator('#login [name=password]').fill('synthetic-not-a-real-password');
    await page.locator('#login button').click();
    await page.locator('#desk').waitFor({state:'visible'});
    await page.locator('#billing-load').click();
    await page.locator('#billing-choice').selectOption('SYNTHETIC-HOLD');
    await page.locator('[name=confirmed_amount]').fill('0.12');
    await page.locator('[name=evidence_sha256]').fill('a'.repeat(64));
    await page.locator('[name=evidence_reference]').fill('SYNTHETIC-TICKET');
    await page.locator('#billing').screenshot({path:path.join(output,'billing-before.png')});
    page.once('dialog', async dialog=>{assert.match(dialog.message(),/总费用|总额/);await dialog.accept();});
    await page.locator('#billing-reconcile button[type=submit], #billing-reconcile button:not([type])').click();
    await page.waitForFunction(()=>document.getElementById('billing-result').textContent.includes('SYNTHETIC-RECEIPT'));
    assert.equal(submits,1);
    await page.locator('#billing-query').click();
    assert.equal(submits,1);
    await page.locator('#billing').screenshot({path:path.join(output,'billing-receipt.png')});
    await page.locator('#logout').click();
    await page.locator('#login-panel').waitFor({state:'visible'});
    assert.equal(await page.locator('#billing-result').textContent(),'');
    fs.writeFileSync(path.join(output,'result.json'),JSON.stringify({status:'passed',mode:'real_edge_mock_api',submits,
      checks:['render','select','form','confirmation','receipt','logout'],live_server:false},null,2),{flag:'wx'});
    console.log('PASS: real Edge admin billing UI; mock API only; '+output);
  } finally {if(browser) await browser.close();server.close();}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
