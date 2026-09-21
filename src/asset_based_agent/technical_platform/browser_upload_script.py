"""Fixed isolated-world file transfer; data only, no model paths or JavaScript.

Native callers must gate every invocation by live task/page/upload authorization.
Delivery may trigger site-side automatic upload. Dispatched is not business success.
"""
import base64
import json
import re

from .browser_file_control import FILE_CONTROL_POLICY
from .browser_policy import credential_origin


def upload_script(operation, token, *, origin='', nonce='', target='', name='', size=0,
                  sha256='', data='', offset=0):
    if operation not in {'begin', 'chunk', 'finish', 'commit', 'status', 'abort'}:
        raise ValueError('Unknown upload operation')
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', token):
        raise ValueError('Invalid native upload token')
    args = {'op': operation, 'token': token}
    if operation == 'begin':
        if (credential_origin(origin) != origin or not isinstance(nonce, str) or not 1 <= len(nonce) <= 128
                or not isinstance(target, str) or not re.fullmatch(r'[1-9][0-9]{0,2}', target)
                or not isinstance(name, str) or not 1 <= len(name) <= 180 or name in {'.', '..'}
                or any(ord(c) < 32 or c in '/\\' for c in name)
                or type(size) is not int or not 0 <= size <= 64 * 1024 * 1024
                or not re.fullmatch(r'[0-9a-f]{64}', sha256)):
            raise ValueError('Invalid upload description')
        args.update(origin=origin, nonce=nonce, target=target, name=name, size=size, sha256=sha256)
    elif operation == 'chunk':
        if (not isinstance(data, str) or not 1 <= len(data) <= 87384
                or type(offset) is not int or offset < 0):
            raise ValueError('Invalid upload chunk')
        decoded = base64.b64decode(data, validate=True)
        if not 1 <= len(decoded) <= 65536:
            raise ValueError('Upload chunk exceeds limit')
        args.update(data=data, offset=offset)
    return _SCRIPT + '(' + json.dumps(args) + ')'


_SCRIPT = r'''(function(a){
 __FILE_CONTROL_POLICY__
 const out=status=>JSON.stringify({status});
 let u=globalThis.__zqUpload;
 const reject=()=>{if(u){u.status='rejected';u.chunks=[];u.bytes=null;u.snapshot.watcher.disconnect();}return out('rejected');};
 const valid=()=>{
  if(!u || window!==window.top || location.protocol!=='https:' || location.origin!==u.origin ||
     Date.now()>u.expires || globalThis.__zqObservation!==null || u.snapshot.dirty ||
     u.snapshot.watcher.takeRecords().length) return false;
  for(const [field,value] of u.snapshot.fields)
   if(!field.isConnected || (field.isContentEditable?field.textContent:field.value)!==value) return false;
  const n=uploadAnchor(u.node);
  if(!n || n!==u.anchor) return false;
  const r=n.getBoundingClientRect(),hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);
  return r.width>0 && r.height>0 && (hit===n || n.contains(hit));
 };
 if(a.op==='begin'){
  if(u && ['ready','verifying','verified'].includes(u.status)) return reject();
  const s=globalThis.__zqObservation;globalThis.__zqObservation=null;
  if(!s || s.nonce!==a.nonce || Date.now()>s.expires){if(s)s.watcher.disconnect();return out('rejected');}
  const node=s.refs.get(a.target);
  if(!node){s.watcher.disconnect();return out('rejected');}
  u={token:a.token,origin:a.origin,node,anchor:s.uploadAnchors?.get(a.target),snapshot:s,chunks:[],received:0,status:'ready',
     name:a.name,size:a.size,sha256:a.sha256,expires:Date.now()+120000};
  globalThis.__zqUpload=u;
  if(!valid()) return reject();
  setTimeout(()=>{if(globalThis.__zqUpload===u && u.status!=='dispatched')reject();},120000);
  return out('ready');
 }
 if(!u || u.token!==a.token) return out('rejected');
 if(a.op==='abort') return reject();
 if(a.op==='status') return out(u.status);
 if(a.op==='commit'){
  if(u.status!=='verified' || !u.bytes || !valid()) return reject();
  const transfer=new DataTransfer();transfer.items.add(new File([u.bytes],u.name,{type:'application/octet-stream'}));
  u.bytes=null;u.snapshot.watcher.disconnect();
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'files').set.call(u.node,transfer.files);
  u.status='dispatched';
  u.node.dispatchEvent(new Event('input',{bubbles:true}));u.node.dispatchEvent(new Event('change',{bubbles:true}));
  return out('dispatched');
 }
 if(u.status!=='ready' || !valid()) return reject();
 if(a.op==='chunk'){
  const raw=atob(a.data);
  if(a.offset!==u.received || raw.length>65536 || u.received+raw.length>u.size) return reject();
  u.chunks.push(Uint8Array.from(raw,c=>c.charCodeAt(0)));u.received+=raw.length;
  return out('ready');
 }
 if(a.op!=='finish' || u.received!==u.size) return reject();
 u.status='verifying';
 const bytes=new Uint8Array(u.size);let at=0;for(const chunk of u.chunks){bytes.set(chunk,at);at+=chunk.length;}
 u.chunks=[];
 crypto.subtle.digest('SHA-256',bytes).then(hash=>{
  const digest=Array.from(new Uint8Array(hash),v=>v.toString(16).padStart(2,'0')).join('');
  if(globalThis.__zqUpload!==u || u.status!=='verifying' || digest!==u.sha256 || !valid()){reject();return;}
  u.bytes=bytes;u.status='verified';
 }).catch(()=>reject());
 return out('verifying');
})'''.replace('__FILE_CONTROL_POLICY__', FILE_CONTROL_POLICY)
