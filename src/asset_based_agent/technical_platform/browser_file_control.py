"""Fixed DOM policy for native inputs and visible, uniquely bound SPA upload widgets."""

FILE_CONTROL_POLICY = r'''
 const uploadAnchor=(n,inspection=false)=>{
  if(!n || !n.isConnected || n.tagName!=='INPUT' || n.type!=='file' || n.multiple || n.webkitdirectory ||
     (!inspection && (n.disabled || n.readOnly || n.value || n.closest('[aria-disabled="true"]'))) ||
     n.closest('[hidden],[inert],[aria-hidden="true"]')) return null;
  let anchor=n;
  if(getComputedStyle(n).display==='none'){
   anchor=n.parentElement;
   if(!anchor || anchor.getAttribute('role')!=='button' ||
      anchor.querySelectorAll('input[type="file"]').length!==1 ||
      anchor.querySelectorAll('button').length!==1) return null;
   const button=anchor.querySelector('button');
   if(button.type!=='button' || (!inspection && (button.disabled || button.getAttribute('aria-disabled')==='true'))) return null;
  }
  for(let p=anchor;p;p=p.parentElement){const s=getComputedStyle(p);
   if(s.display==='none'||s.visibility!=='visible'||Number(s.opacity)===0) return null;}
  if(anchor.getClientRects().length===0) return null;
  if(n.form && !inspection){const url=new URL(n.form.action,location.href);
   if(url.protocol!=='https:'||url.origin!==location.origin||url.username||url.password||
      (n.form.target||'_self')!=='_self') return null;
   const passiveWidget=anchor!==n && !n.form.hasAttribute('method') && !n.form.hasAttribute('action');
   if(n.form.method.toLowerCase()!=='post' && !passiveWidget) return null;
  }
  return anchor;
 };
'''
