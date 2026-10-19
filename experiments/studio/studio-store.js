/* clstrfck Studio: workspace persistence (browser only).
 *
 * IndexedDB database "clstrfck-studio", object store "kv":
 *   workspace          {rev, savedAt, writer, json}   the live workspace
 *   legacy-localStorage {at, json}   copy of the pre-IndexedDB localStorage state, kept on migration
 *   before-restore     {at, json}   the workspace as it was before a restore / reset / blank start
 *   rejected-write     {at, json}   a change from this window refused because another window saved first
 *   unreadable         {at, json}   a stored workspace that failed validation at startup
 *
 * Writes are revision-checked: a window only writes if the stored revision is
 * the one it last loaded or wrote. Other windows are told via BroadcastChannel.
 * If IndexedDB cannot be opened the store falls back to localStorage.
 */
(function(root){
'use strict';
const DB_NAME='clstrfck-studio',STORE='kv',LEGACY_KEY='clstrfck.studio.v1',CHANNEL='clstrfck-studio';
const RECOVERY_KEYS=['legacy-localStorage','before-restore','rejected-write','unreadable'];
const windowId=Math.random().toString(36).slice(2);

let db=null,mode='memory',rev=0,baseJson=null,pending=null,inflight=false,again=false,timer=0,status={state:'idle'},channel=null;
const listeners={status:[],remote:[],conflict:[]};
const emit=(type,...args)=>listeners[type].forEach(fn=>{try{fn(...args);}catch(err){console.error(err);}});
const setStatus=(state,detail)=>{status={state,detail,at:Date.now()};emit('status',status);};

function openDb(){
  return new Promise((resolve,reject)=>{
    if(!root.indexedDB)return reject(new Error('IndexedDB is unavailable.'));
    const req=indexedDB.open(DB_NAME,1);
    req.onupgradeneeded=()=>{if(!req.result.objectStoreNames.contains(STORE))req.result.createObjectStore(STORE);};
    req.onsuccess=()=>resolve(req.result);
    req.onerror=()=>reject(req.error||new Error('IndexedDB open failed.'));
    req.onblocked=()=>reject(new Error('IndexedDB is blocked by another tab.'));
  });
}
/* Run fn(store, tx) in one transaction; resolve with fn's result after commit. */
function transact(modeName,fn){
  return new Promise((resolve,reject)=>{
    let result,tx;
    try{tx=db.transaction(STORE,modeName);}catch(err){return reject(err);}
    const store=tx.objectStore(STORE);
    tx.oncomplete=()=>resolve(result);
    tx.onerror=()=>reject(tx.error||new Error('Storage transaction failed.'));
    tx.onabort=()=>reject(tx.error||Object.assign(new Error('Storage transaction aborted.'),{aborted:true,result}));
    Promise.resolve(fn(store,tx,v=>{result=v;})).catch(err=>{try{tx.abort();}catch{}reject(err);});
  });
}
const req=r=>new Promise((res,rej)=>{r.onsuccess=()=>res(r.result);r.onerror=()=>rej(r.error);});
async function getKey(key){if(mode!=='idb')return null;return transact('readonly',async(store,tx,set)=>set(await req(store.get(key))));}

/* Load the workspace. validate(state) and migrate(state) come from StudioModel. */
async function boot({valid,migrate,seed}){
  const parse=json=>{try{const s=JSON.parse(json);return valid(s)?migrate(s):null;}catch{return null;}};
  try{db=await openDb();mode='idb';}
  catch(err){
    mode='local';
    try{const s=parse(localStorage.getItem(LEGACY_KEY)||'null');setStatus('saved');return {state:s||seed(),origin:s?'local':'new',warning:'IndexedDB unavailable ('+err.message+'); saving to localStorage, which holds only a few MB.'};}
    catch{mode='memory';setStatus('failed','No browser storage available.');return {state:seed(),origin:'memory',warning:'Browser storage is unavailable. Changes last only for this session; export your workspace to keep it.'};}
  }
  channel=root.BroadcastChannel?new BroadcastChannel(CHANNEL):null;
  if(channel)channel.onmessage=e=>onMessage(e.data);
  const rec=await getKey('workspace');
  if(rec){
    const s=parse(rec.json);
    if(s){rev=rec.rev;baseJson=rec.json;setStatus('saved');return {state:s,origin:'idb'};}
    await transact('readwrite',store=>{store.put({at:new Date().toISOString(),json:rec.json},'unreadable');});
    rev=rec.rev;setStatus('idle');
    return {state:seed(),origin:'new',warning:'The saved workspace could not be read. A copy was kept under Recovery copies in Settings; starting from the sample.'};
  }
  let legacy=null;try{legacy=localStorage.getItem(LEGACY_KEY);}catch{}
  const migrated=legacy&&parse(legacy);
  if(migrated){
    const json=JSON.stringify(migrated);
    await transact('readwrite',store=>{store.put({at:new Date().toISOString(),json:legacy},'legacy-localStorage');store.put({rev:1,savedAt:new Date().toISOString(),writer:windowId,json},'workspace');});
    rev=1;baseJson=json;setStatus('saved');
    return {state:migrated,origin:'migrated',notice:'Moved your saved workspace from localStorage to IndexedDB. The original copy is kept under Recovery copies in Settings.'};
  }
  setStatus('idle');
  return {state:seed(),origin:'new'};
}

async function commit(json){
  return transact('readwrite',async(store,tx,set)=>{
    const cur=await req(store.get('workspace')),curRev=cur?.rev||0;
    if(curRev!==rev){set({conflict:true,remoteRev:curRev});return;}
    const next={rev:rev+1,savedAt:new Date().toISOString(),writer:windowId,json};
    store.put(next,'workspace');set({rev:next.rev});
  });
}
async function flush(){
  clearTimeout(timer);timer=0;
  if(inflight){again=true;return;}
  if(!pending)return;
  const state=pending;pending=null;inflight=true;
  let json;
  try{json=JSON.stringify(state);}catch(err){inflight=false;setStatus('failed','Could not serialise the workspace: '+err.message);return;}
  try{
    if(mode==='local'){localStorage.setItem(LEGACY_KEY,json);setStatus('saved');}
    else if(mode==='memory'){setStatus('failed','Browser storage is unavailable.');}
    else if(json===baseJson){setStatus('saved');}
    else{
      const result=await commit(json);
      if(result?.conflict&&navigationOnly(baseJson,json)){await reloadFromStore('remote');setStatus('saved');}
      else if(result?.conflict){
        await transact('readwrite',store=>{store.put({at:new Date().toISOString(),json},'rejected-write');}).catch(()=>{});
        setStatus('conflict','Another window saved first. This window’s latest change was kept as a recovery copy.');
        await reloadFromStore('conflict');
      }else{rev=result.rev;baseJson=json;setStatus(pending?'saving':'saved');channel?.postMessage({type:'saved',rev,writer:windowId});}
    }
  }catch(err){
    const quota=err?.name==='QuotaExceededError'||/quota/i.test(err?.message||'');
    pending||=state;
    setStatus('failed',quota?'Browser storage is full. Export your workspace, then remove unused documents.':'Saving failed: '+(err?.message||err));
  }finally{
    inflight=false;
    if(again||(pending&&status.state!=='failed')){again=false;flush();}
  }
}
function save(state,{immediate=false}={}){
  pending=state;setStatus('saving');
  clearTimeout(timer);
  if(immediate)return flush();
  timer=setTimeout(flush,180);
}
/* A change that only moved this window's selected project is not worth a conflict. */
function navigationOnly(before,after){
  if(!before)return false;
  try{const a=JSON.parse(before),b=JSON.parse(after);delete a.activeProject;delete b.activeProject;return JSON.stringify(a)===JSON.stringify(b);}catch{return false;}
}
async function reloadFromStore(reason){
  const rec=await getKey('workspace');if(!rec)return;
  rev=rec.rev;baseJson=rec.json;
  emit(reason==='conflict'?'conflict':'remote',rec.json);
}
function onMessage(msg){
  if(msg?.type!=='saved'||msg.writer===windowId||msg.rev<=rev)return;
  if(pending||inflight){flush();return;}   // our unsaved change will meet the conflict check
  reloadFromStore('remote');
}
/* Replace the whole workspace in one transaction, keeping the old one as before-restore. */
async function replace(state){
  clearTimeout(timer);pending=null;
  const json=JSON.stringify(state);
  if(mode==='local'){try{localStorage.setItem(LEGACY_KEY+'.before-restore',localStorage.getItem(LEGACY_KEY)||'');}catch{}localStorage.setItem(LEGACY_KEY,json);setStatus('saved');return;}
  if(mode!=='idb')throw new Error('Browser storage is unavailable.');
  const result=await transact('readwrite',async(store,tx,set)=>{
    const cur=await req(store.get('workspace'));
    if(cur)store.put({at:new Date().toISOString(),json:cur.json},'before-restore');
    const next={rev:(cur?.rev||0)+1,savedAt:new Date().toISOString(),writer:windowId,json};
    store.put(next,'workspace');set(next.rev);
  });
  rev=result;baseJson=json;setStatus('saved');channel?.postMessage({type:'saved',rev,writer:windowId});
}
async function recoveryCopies(){
  if(mode!=='idb')return [];
  const out=[];for(const key of RECOVERY_KEYS){const rec=await getKey(key);if(rec?.json)out.push({key,at:rec.at,bytes:rec.json.length});}
  return out;
}
async function estimate(){try{return await navigator.storage?.estimate?.();}catch{return null;}}
async function persist(){try{return await navigator.storage?.persist?.();}catch{return false;}}
const hasUnsaved=()=>!!pending||inflight||status.state==='failed';

root.StudioStore={boot,save,flush,replace,getKey,recoveryCopies,estimate,persist,hasUnsaved,
  get mode(){return mode;},get status(){return status;},get rev(){return rev;},windowId,LEGACY_KEY,
  on(type,fn){listeners[type].push(fn);}};
})(globalThis);
