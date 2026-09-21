"""Fixed trusted scripts for ApplicationWorld only; never expose as Agent eval.

Default fill never submits. No frame traversal or password in returned values. Callers must
also check native page ownership, epoch, HTTPS origin and actual user consent.
"""
import json

_CHECKS = r'''
const visible = e => e.isConnected && !e.disabled && !e.readOnly &&
  e.getClientRects().length > 0 && getComputedStyle(e).visibility === 'visible' &&
  getComputedStyle(e).display !== 'none';
const actionOf = f => new URL(f.getAttribute('action') || location.href, document.baseURI);
const modeOf = f => !f.hasAttribute('action') && !f.hasAttribute('method') ? 'script' : 'post';
const valid = (f,u,p) => {
  if (window !== window.top || location.protocol !== 'https:' || !f.isConnected ||
      !u.isConnected || !p.isConnected || u.form !== f || p.form !== f ||
      !visible(u) || !visible(p) || p.type !== 'password' ||
      !['text','email','tel'].includes(u.type) ||
      p.autocomplete === 'new-password' ||
      (modeOf(f) !== 'script' && (f.getAttribute('method') || 'get').toLowerCase() !== 'post') ||
      !['','_self'].includes(f.getAttribute('target') || '')) return false;
  const action = actionOf(f);
  if (action.origin !== location.origin || action.protocol !== 'https:' || action.username || action.password) return false;
  for (const b of Array.from(f.elements).filter(e=>e.tagName==='BUTTON'||['submit','image'].includes(e.type))) {
    if (b.hasAttribute('formaction') && new URL(b.getAttribute('formaction'),document.baseURI).href !== action.href) return false;
    if (b.hasAttribute('formmethod') && b.getAttribute('formmethod').toLowerCase() !== 'post') return false;
    if (b.hasAttribute('formtarget') && !['','_self'].includes(b.getAttribute('formtarget'))) return false;
  }
  return true;
};
'''


def probe_script(nonce: str) -> str:
    return '(function(nonce){try{' + _CHECKS + r'''
delete globalThis.__zqLoginProbe;
delete globalThis.__zqLoginSubmit;
const candidates=[];
for (const f of document.querySelectorAll('form')) {
  const passwords=Array.from(f.querySelectorAll('input[type=password]')).filter(visible);
  const inputs=Array.from(f.querySelectorAll('input')).filter(e=>visible(e)&&['text','email','tel'].includes(e.type));
  const named=inputs.filter(e=>e.autocomplete==='username');
  const users=named.length ? named : inputs;
  if (passwords.length===1 && users.length===1 && valid(f,users[0],passwords[0]))
    candidates.push({f,u:users[0],p:passwords[0]});
}
if (candidates.length!==1) return JSON.stringify({ok:false});
const s=candidates[0];
s.nonce=nonce; s.origin=location.origin; s.action=actionOf(s.f).href;
s.mode=modeOf(s.f);
s.oldUser=s.u.value; s.oldPassword=s.p.value;
s.deadline=performance.now()+60000;
globalThis.__zqLoginProbe=s;
setTimeout(()=>{if(globalThis.__zqLoginProbe?.nonce===nonce) delete globalThis.__zqLoginProbe;},60000);
return JSON.stringify({ok:true,origin:s.origin,action:s.action,nonce});
}catch(_){return JSON.stringify({ok:false});}})(''' + json.dumps(nonce) + ')'


def fill_script(nonce: str, origin: str, username: str, password: str, *, prepare_submit: bool = False) -> str:
    data = json.dumps([nonce, origin, username, password, prepare_submit is True], ensure_ascii=True)
    return '(function(data){try{' + _CHECKS + r'''
const s=globalThis.__zqLoginProbe;
delete globalThis.__zqLoginProbe;
delete globalThis.__zqLoginSubmit;
if (!s || s.nonce!==data[0] || s.origin!==data[1] || location.origin!==data[1] ||
    performance.now()>s.deadline || !valid(s.f,s.u,s.p) || actionOf(s.f).href!==s.action || modeOf(s.f)!==s.mode ||
    s.u.value!==s.oldUser || s.p.value!==s.oldPassword) return JSON.stringify({ok:false});
// A method-less SPA form must never fall back to native GET with a filled
// password in the URL. JS handlers still run; we never replay or submit.
if (s.mode==='script') s.f.addEventListener('submit', event=>{
  if ((s.f.getAttribute('method') || 'get').toLowerCase() !== 'post') event.preventDefault();
}, {capture:true});
const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
setter.call(s.u,data[2]); setter.call(s.p,data[3]);
for (const e of [s.u,s.p]) {
  e.dispatchEvent(new Event('input',{bubbles:true}));
  e.dispatchEvent(new Event('change',{bubbles:true}));
}
// Opt-in preparation only. A separate native authorization must precede submit_script.
if (data[4] && valid(s.f,s.u,s.p) && actionOf(s.f).href===s.action && modeOf(s.f)===s.mode) {
  const buttons=Array.from(s.f.elements).filter(e=>['submit','image'].includes(e.type) && visible(e));
  if (buttons.length===1 && buttons[0].tagName==='BUTTON') {
    s.button=buttons[0]; s.filledUser=s.u.value; s.filledPassword=s.p.value;
    globalThis.__zqLoginSubmit=s;
    setTimeout(()=>{if(globalThis.__zqLoginSubmit===s) delete globalThis.__zqLoginSubmit;},60000);
  }
}
return JSON.stringify({ok:true});
}catch(_){return JSON.stringify({ok:false});}})(''' + data + ')'


def submit_script(nonce: str, origin: str) -> str:
    """Trusted local caller only, after separate consent. Dispatch is not authentication."""
    return '(function(data){try{' + _CHECKS + r'''
const s=globalThis.__zqLoginSubmit;
delete globalThis.__zqLoginSubmit;
if (!s || !HTMLFormElement.prototype.checkValidity.call(s.f))
  return JSON.stringify({dispatched:false});
if (!s || s.nonce!==data[0] || s.origin!==data[1] || location.origin!==data[1] ||
    performance.now()>s.deadline || !valid(s.f,s.u,s.p) || actionOf(s.f).href!==s.action ||
    modeOf(s.f)!==s.mode || s.u.value!==s.filledUser || s.p.value!==s.filledPassword)
  return JSON.stringify({dispatched:false});
const buttons=Array.from(s.f.elements).filter(e=>['submit','image'].includes(e.type) && visible(e));
if (buttons.length!==1 || buttons[0]!==s.button || s.button.form!==s.f)
  return JSON.stringify({dispatched:false});
HTMLFormElement.prototype.requestSubmit.call(s.f,s.button);
return JSON.stringify({dispatched:true});
}catch(_){return JSON.stringify({dispatched:false});}})(''' + json.dumps([nonce, origin]) + ')'
