"""Fixed, bounded main-frame observation script; no caller-provided JavaScript.

Website text is untrusted data, never task authority. This excludes field values
and masks their visible repetitions, not a general guarantee against a site
encoding or displaying secrets elsewhere. No network transmission occurs here.
"""
import json

from .browser_file_control import FILE_CONTROL_POLICY
from .browser_policy import credential_origin


def observation_script(nonce: str, *, include_files: bool = False) -> str:
    if not isinstance(nonce, str) or not nonce or len(nonce) > 128:
        raise ValueError('Invalid observation nonce')
    if type(include_files) is not bool:
        raise ValueError('Invalid file observation flag')
    return _OBSERVE + '(' + json.dumps(nonce) + (',true' if include_files else '') + ')'


def click_script(nonce: str, origin: str, control_id: str) -> str:
    return action_script(nonce, origin, control_id, 'click', '')


def action_script(nonce: str, origin: str, control_id: str, operation: str, value: str) -> str:
    if (not isinstance(nonce, str) or not nonce or len(nonce) > 128
            or not isinstance(control_id, str) or not control_id.isascii()
            or not control_id.isdigit() or not 1 <= int(control_id) <= 200
            or credential_origin(origin) != origin):
        raise ValueError('Invalid action target')
    if (operation not in {'click', 'fill', 'select', 'scroll', 'download', 'download_button'} or not isinstance(value, str)
            or len(value) > 4000 or (operation in {'click', 'download', 'download_button'} and value)
            or (operation == 'scroll' and value not in {'up', 'down'})):
        raise ValueError('Invalid form action')
    return _CLICK + '(' + json.dumps([nonce, origin, control_id, operation, value]) + ')'


_FIELD_POLICY = r'''
  const fieldAllowed=(node)=>{
    const hint=[node.id,node.name,node.autocomplete,node.getAttribute('aria-label')||'',
      Array.from(node.labels||[],label=>label.innerText).join(' ')].join(' ');
    if(/password|passwd|pwd|token|secret|one-time|username|验证码|密码|密钥/i.test(hint)) return false;
    if(node.readOnly || node.disabled || node.isContentEditable) return false;
    return node.tagName==='TEXTAREA' || (node.tagName==='SELECT' && !node.multiple) ||
      (node.tagName==='INPUT' && ['text','search','email','tel','url'].includes(node.type));
  };
'''


_OBSERVE = r'''(function(nonce,includeFiles){
  __FIELD_POLICY__
  __FILE_CONTROL_POLICY__
  const previous=globalThis.__zqObservation;
  if(previous && previous.watcher) previous.watcher.disconnect();
  globalThis.__zqObservation=null;
  if (window!==window.top || !document.body || location.protocol!=='https:') return null;
  const fields=document.querySelectorAll('input,textarea,select,[contenteditable]');
  if (fields.length>2000) return null;
  const secrets=[]; let secretSize=0;
  for (const field of fields) {
    const value=field.isContentEditable ? field.textContent : field.value;
    if (value) {secretSize+=value.length; if(secretSize>50000) return null; secrets.push(value);}
  }
  secrets.sort((a,b)=>b.length-a.length);
  const clean=(value)=>{
    let text=String(value||'');
    for (const secret of secrets) text=text.split(secret).join('[redacted]');
    return text.replace(/\s+/g,' ').trim();
  };
  const visible=(element,field=false)=>{
    if (!element || element.closest('script,style,noscript,template,iframe,[contenteditable],[hidden],[aria-hidden="true"]') ||
        (!field && element.closest('input,textarea,select'))) return false;
    for(let node=element;node;node=node.parentElement){
      const style=getComputedStyle(node);
      if(style.display==='none'||style.visibility==='hidden'||style.visibility==='collapse'||Number(style.opacity)===0) return false;
    }
    return element.getClientRects().length>0;
  };
  const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
  let text='',count=0,node,truncated=false;
  while((node=walker.nextNode())) {
    if(++count>5000){truncated=true;break;}
    if(!visible(node.parentElement)) continue;
    const chunk=clean(node.textContent);
    if(!chunk) continue;
    if(text.length+chunk.length+1>12000){text=(text+'\n'+chunk).slice(0,12000);truncated=true;break;}
    text+=(text?'\n':'')+chunk;
  }
  const controls=[],refs=new Map(),uploadAnchors=new Map();
  const elements=document.querySelectorAll('button,a,[role="button"],input,textarea,select');
  if(elements.length>5000) return null;
  for(const element of elements){
    const field=['INPUT','TEXTAREA','SELECT'].includes(element.tagName);
    const anchor=includeFiles===true ? uploadAnchor(element,true) : null;
    const file=anchor!==null;
    if(!visible(anchor||element,field) || (field && !fieldAllowed(element) && !file)) continue;
    if(controls.length>=200){truncated=true;break;}
    // Collect only visible text nodes, not hidden descendants or attributes.
    const words=[],tw=document.createTreeWalker(anchor||element,NodeFilter.SHOW_TEXT);
    let child,n=0;
    while((child=tw.nextNode()) && n++<100){if(visible(child.parentElement))words.push(child.textContent);}
    let label=clean(words.join(' ')).slice(0,160);
    if(field && !(file && anchor!==element)){
      const labels=Array.from(element.labels||[]).filter(e=>visible(e));
      label=clean(labels.map(e=>e.innerText).join(' ') || element.getAttribute('aria-label') || '').slice(0,160);
      if(!label) continue;
    }
    const id=String(controls.length+1);
    refs.set(id,element);
    if(file) uploadAnchors.set(id,anchor);
    const control={id,kind:file?'file':field?(element.tagName==='SELECT'?'select':'textfield'):(element.tagName==='A'?'link':'button'),text:label,disabled:!!element.disabled || (file && uploadAnchor(element)===null)};
    if(element.tagName==='SELECT'){
      if(element.options.length>100){truncated=true;refs.delete(id);continue;}
      control.options=Array.from(element.options,(option,index)=>({option,index}))
        .filter(({option})=>!option.disabled&&!option.hidden&&!option.parentElement.disabled)
        .map(({option,index})=>({id:String(index+1),text:clean(option.text).slice(0,160)}));
    }
    controls.push(control);
  }
  // References live only in the isolated application world, not in output.
  const state={nonce,refs,uploadAnchors,dirty:false,expires:Date.now()+30000,
    fields:Array.from(fields,field=>[field,field.isContentEditable?field.textContent:field.value])};
  state.watcher=new MutationObserver(()=>{state.dirty=true;});
  state.watcher.observe(document.documentElement,{subtree:true,childList:true,attributes:true,characterData:true});
  globalThis.__zqObservation=state;
  return JSON.stringify({nonce,origin:location.origin,text,controls,truncated});
})'''.replace('__FIELD_POLICY__', _FIELD_POLICY).replace('__FILE_CONTROL_POLICY__', FILE_CONTROL_POLICY)


_CLICK = r'''(function(args){
  __FIELD_POLICY__
  const [nonce,origin,id,operation,value]=args,state=globalThis.__zqObservation;
  const reject=()=>JSON.stringify({status:'rejected'});
  globalThis.__zqObservation=null;
  if(!state) return reject();
  const pending=state.watcher.takeRecords().length;state.watcher.disconnect();
  if(window!==window.top || location.origin!==origin || location.protocol!=='https:' ||
     state.nonce!==nonce || state.dirty || pending || Date.now()>state.expires) return reject();
  for(const [field,value] of state.fields){
    if(!field.isConnected || (field.isContentEditable?field.textContent:field.value)!==value) return reject();
  }
  if(operation==='scroll'){
    if(value!=='up' && value!=='down') return reject();
    window.scrollBy({top:Math.max(1,Math.min(innerHeight*0.8,1000))*(value==='down'?1:-1),left:0,behavior:'instant'});
    return JSON.stringify({status:'dispatched'});
  }
  const node=state.refs.get(id);
  if(!node || !node.isConnected || node.disabled || node.getAttribute('aria-disabled')==='true' ||
     node.closest('[hidden],[inert],[aria-hidden="true"]')) return reject();
  for(let parent=node;parent;parent=parent.parentElement){
    const style=getComputedStyle(parent);
    if(style.display==='none'||style.visibility!=='visible'||Number(style.opacity)===0) return reject();
  }
  if(node.tagName==='A'){
    const url=new URL(node.href,location.href);
    if(url.protocol!=='https:' || url.origin!==origin || url.username || url.password ||
       (node.target && node.target!=='_self') || (operation!=='download' && node.hasAttribute('download'))) return reject();
  }
  if(operation==='click' && node.form){
    const url=new URL(node.formAction||node.form.action,location.href);
    if(url.protocol!=='https:' || url.origin!==origin || url.username || url.password ||
       (node.formTarget||node.form.target||'_self')!=='_self' ||
       (node.formMethod||node.form.method).toLowerCase()!=='post') return reject();
  }
  const rect=node.getBoundingClientRect(),x=rect.left+rect.width/2,y=rect.top+rect.height/2;
  const hit=document.elementFromPoint(x,y);
  if(rect.width<=0 || rect.height<=0 || !hit || !(hit===node||node.contains(hit))) return reject();
  if(operation==='download_button'){
    if(!(node.tagName==='BUTTON' && node.type==='button') &&
       !(node.getAttribute('role')==='button' && !node.matches('a,input,textarea,select,button') && !node.closest('form'))) return reject();
    node.click();
    return JSON.stringify({status:'dispatched'});
  }else if(operation==='download'){
    if(node.tagName!=='A' || node.href.length>8192) return reject();
    return JSON.stringify({status:'resolved',url:node.href});
  }else if(operation==='click'){
    if(!node.matches('button,a,[role="button"]') || node.matches('input,textarea,select')) return reject();
    node.click();
  }else if(operation==='fill'){
    if(!fieldAllowed(node)||!node.matches('input,textarea')||typeof value!=='string'||value.length>4000) return reject();
    const proto=node.tagName==='INPUT'?HTMLInputElement.prototype:HTMLTextAreaElement.prototype;
    Object.getOwnPropertyDescriptor(proto,'value').set.call(node,value);
    node.dispatchEvent(new Event('input',{bubbles:true}));node.dispatchEvent(new Event('change',{bubbles:true}));
  }else if(operation==='select'){
    if(!fieldAllowed(node)||node.tagName!=='SELECT'||!/^\d{1,3}$/.test(value)) return reject();
    const index=Number(value)-1,option=node.options[index];
    if(!option||option.disabled||option.hidden||option.parentElement.disabled) return reject();
    node.selectedIndex=index;
    node.dispatchEvent(new Event('input',{bubbles:true}));node.dispatchEvent(new Event('change',{bubbles:true}));
  }else return reject();
  return JSON.stringify({status:'dispatched'});
})'''.replace('__FIELD_POLICY__', _FIELD_POLICY)
