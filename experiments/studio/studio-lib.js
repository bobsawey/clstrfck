/* clstrfck Studio: pure document and workspace operations.
 *
 * No DOM, no storage, no network. Loaded by index.html and by the Node tests.
 * Offsets are JavaScript string indices (UTF-16 code units) into the stored
 * source text, with an exclusive end, matching the existing Workbench records.
 */
(function(root){
'use strict';

const LIMITS={
  maxSegmentsPerDocument:5000,   // beyond this, the full text is kept but not split into material
  maxTextChars:8000000,          // extracted text per document
  maxTextFileBytes:20*1024*1024, // .txt / .md
  maxBinaryFileBytes:80*1024*1024, // .pdf / .docx
  maxWorkspaceBytes:400*1024*1024
};
const EXTENSIONS={txt:'txt',text:'txt',md:'md',markdown:'md',pdf:'pdf',docx:'docx'};
const WORKSPACE_FORMAT='clstrfck-studio-workspace',WORKSPACE_VERSION=1;

function formatOf(path){const m=/\.([a-z0-9]+)$/i.exec(String(path||''));return m?EXTENSIONS[m[1].toLowerCase()]||null:null;}
function isHiddenPath(path){return String(path).split('/').some(part=>part.startsWith('.')||part==='__MACOSX');}
function normalizePath(path){return String(path||'').replace(/\\/g,'/').replace(/\/{2,}/g,'/').replace(/^\.?\//,'').replace(/^\/+/,'');}

const HEADING=/^[ \t]{0,3}#{1,6}[ \t]+\S/;
const LIST_ITEM=/^[ \t]*(?:[-*+•‣◦▪●○■□➢►–—]|\d{1,3}[.)])[ \t]+\S/;
const MEANINGFUL=/[\p{L}\p{N}]/u;

/* Split text into source-anchored segments.
 * - blank lines end a block
 * - each Markdown heading is its own segment
 * - each list item is its own segment; following unmarked lines continue it
 * - other consecutive lines form one paragraph
 * Segment text is always exactly text.slice(start,end). */
function segment(text,{maxSegments=LIMITS.maxSegmentsPerDocument}={}){
  text=String(text);
  const segments=[];let skipped=0,overflow=0,current=null;
  const push=(start,end,kind)=>{
    while(start<end&&/\s/.test(text[start]))start++;
    while(end>start&&/\s/.test(text[end-1]))end--;
    if(start>=end)return;
    const body=text.slice(start,end);
    if(!MEANINGFUL.test(body)){skipped++;return;}
    if(segments.length>=maxSegments){overflow++;return;}
    segments.push({start,end,kind,text:body});
  };
  const flush=()=>{if(current){push(current.start,current.end,current.kind);current=null;}};
  let i=0;
  while(i<=text.length){
    let j=text.indexOf('\n',i);if(j<0)j=text.length;
    let end=j;if(end>i&&text[end-1]==='\r')end--;
    const line=text.slice(i,end);
    if(!line.trim())flush();
    else if(HEADING.test(line)){flush();push(i,end,'heading');}
    else if(LIST_ITEM.test(line)){flush();current={start:i,end,kind:'item'};}
    else if(current)current.end=end;
    else current={start:i,end,kind:'paragraph'};
    if(j>=text.length)break;
    i=j+1;
  }
  flush();
  return {segments,skipped,overflow};
}
function stripMarkers(body){return String(body).replace(/^[ \t]{0,3}#{1,6}[ \t]+/,'').replace(/^[ \t]*(?:[-*+•‣◦▪●○■□➢►–—]|\d{1,3}[.)])[ \t]+/,'');}
function titleFor(body){const t=stripMarkers(body).replace(/\s+/g,' ').trim();return t.length>80?t.slice(0,79).trimEnd()+'…':t;}
function materialKey(body){return stripMarkers(body).replace(/\s+/g,' ').trim().toLowerCase();}
function pageAt(pages,offset){if(!Array.isArray(pages))return null;const p=pages.find(p=>offset>=p.start&&offset<p.end);return p?p.page:null;}

function liveSource(s,id){return !!id&&s.sources.some(d=>d.id===id);}
function isSuperseded(s,d){return liveSource(s,d.supersededBy);}
function textMatches(d,doc){return d.textHash?d.textHash===doc.textHash:d.text===doc.text;}

/* Add one extracted document to the workspace.
 * doc: {path, format, text, size, modified, byteHash, textHash, pages?, warnings?}
 * Returns {status, sid?, count, merged, skipped, overflow, detail}.
 * status: imported | updated | unchanged | duplicate | blocked | empty | too-large */
function importDocument(s,doc,{concepts=()=>[],bump=()=>{},now=new Date()}={}){
  const path=normalizePath(doc.path),text=String(doc.text??'');
  if(!text.trim())return {status:'empty',count:0,detail:'No text found.'};
  if(text.length>LIMITS.maxTextChars)return {status:'too-large',count:0,detail:'Extracted text is longer than '+LIMITS.maxTextChars.toLocaleString('en-US')+' characters.'};
  s.tombstones||=[];
  if(doc.textHash&&s.tombstones.some(t=>t.type==='source'&&t.hash===doc.textHash))
    return {status:'blocked',count:0,detail:'This exact text was permanently removed earlier. Its deletion record blocks re-import.'};
  const imported=s.sources.filter(d=>d.imported);
  const current=imported.filter(d=>d.path===path&&!isSuperseded(s,d)).at(-1)||null;
  if(current&&((doc.byteHash&&current.byteHash===doc.byteHash)||textMatches(current,doc)))
    return {status:'unchanged',sid:current.id,count:0,detail:'Already imported; content unchanged.'};
  if(!current){
    const twin=imported.find(d=>!isSuperseded(s,d)&&textMatches(d,doc));
    if(twin){
      twin.aliases||=[];
      const added=twin.path!==path&&!twin.aliases.includes(path);
      if(added){twin.aliases.push(path);bump(s,'ingest','Alias '+path+' → '+twin.path);}
      return {status:'duplicate',sid:twin.id,count:0,detail:'Same text as '+twin.path+(added?'; path recorded as an alias.':'.')};
    }
  }
  const serial=s.nextImport++,sid='i'+serial,stamp=now.toISOString();
  const src={id:sid,path,date:stamp.slice(0,10),text,disabled:false,imported:true,
    format:doc.format||formatOf(path)||'txt',size:doc.size??null,modified:doc.modified||null,importedAt:stamp,
    byteHash:doc.byteHash||null,textHash:doc.textHash||null,aliases:[],warnings:[...(doc.warnings||[])]};
  if(Array.isArray(doc.pages)&&doc.pages.length)src.pages=doc.pages.map(p=>({page:p.page,start:p.start,end:p.end}));
  if(current){
    src.supersedes=current.id;current.supersededBy=sid;
    if(!current.archived&&!current.queued){current.archived=true;current.archivedReason='superseded';}
  }
  s.sources.push(src);
  // Reuse a material family when identical wording already exists in imported documents.
  const importedIds=new Set(imported.map(d=>d.id)),famById=new Map(s.families.map(f=>[f.id,f])),byKey=new Map();
  for(const f of s.facts){if(!importedIds.has(f.source))continue;const fam=famById.get(f.family);if(fam&&!fam.queued&&!byKey.has(materialKey(f.text)))byKey.set(materialKey(f.text),fam.id);}
  const {segments,skipped,overflow}=segment(text);
  let count=0,merged=0;
  segments.forEach((seg,k)=>{
    const key=materialKey(seg.text),eid='ie'+serial+'_'+k;let fid=byKey.get(key);
    if(fid)merged++;
    else{fid='if'+serial+'_'+k;s.families.push({id:fid,title:titleFor(seg.text)||'Untitled',tags:concepts(seg.text),conflict:false});byKey.set(key,fid);}
    const fact={id:eid,family:fid,source:sid,text:seg.text,start:seg.start,end:seg.end,kind:seg.kind};
    const page=pageAt(src.pages,seg.start);if(page)fact.page=page;
    s.facts.push(fact);count++;
  });
  if(overflow)src.warnings.push(overflow+' further passages were kept in the stored text but not split into material (limit '+LIMITS.maxSegmentsPerDocument+').');
  src.segmentStats={count,skipped,overflow,merged};
  bump(s,'ingest',path+' / '+count+' passages'+(current?' (new snapshot)':''));
  return {status:current?'updated':'imported',sid,count,merged,skipped,overflow,detail:current?'New snapshot; the earlier version was archived and its links kept.':''};
}

/* Workspace file: a portable, versioned copy of everything in this prototype. */
function exportWorkspace(s,{now=new Date(),app='studio-prototype'}={}){
  return {format:WORKSPACE_FORMAT,formatVersion:WORKSPACE_VERSION,exportedAt:now.toISOString(),app,
    includes:['source text extracted at import','source metadata, hashes and aliases','material, tags and source offsets','projects, briefs, collections and order','editor blocks including project edits','drafts','preferences, notes and saved searches','archive, removal queue and deletion records','settings and counters'],
    excludes:['original file bytes (PDF/DOCX/text files stay on your computer; re-import to relink)'],
    counts:summarize(s),workspace:s};
}
function summarize(s){return {sources:s.sources.length,importedSources:s.sources.filter(d=>d.imported).length,material:s.families.length,passages:s.facts.length,projects:(s.projects||[]).length,editorBlocks:(s.projects||[]).reduce((n,p)=>n+(p.editor?.blocks?.length||0),0)};}

function validateWorkspace(file,{valid}={}){
  const errors=[],warnings=[];
  if(!file||typeof file!=='object')return {errors:['This is not a JSON object.'],warnings};
  if(file.format!==WORKSPACE_FORMAT)errors.push('This file is not a clstrfck Studio workspace export.');
  if(file.formatVersion!==WORKSPACE_VERSION)errors.push('Unsupported workspace format version: '+file.formatVersion+'.');
  const s=file.workspace;
  if(errors.length)return {errors,warnings};
  if(valid&&!valid(s)){errors.push('The workspace structure is incomplete or damaged.');return {errors,warnings};}
  const unique=(list,label)=>{const seen=new Set();for(const x of list){if(seen.has(x.id))errors.push('Duplicate '+label+' id '+x.id+'.');seen.add(x.id);}return seen;};
  const sids=unique(s.sources,'source'),fids=unique(s.families,'material'),eids=unique(s.facts,'passage');unique(s.projects,'project');
  const srcById=new Map(s.sources.map(d=>[d.id,d]));
  for(const d of s.sources)if(typeof d.text!=='string'||typeof d.path!=='string')errors.push('Source '+d.id+' has no text or path.');
  for(const f of s.facts){
    if(!fids.has(f.family))errors.push('Passage '+f.id+' points to missing material '+f.family+'.');
    const d=srcById.get(f.source);
    if(!d){errors.push('Passage '+f.id+' points to missing source '+f.source+'.');continue;}
    if(typeof d.text==='string'&&d.text.slice(f.start,f.end)!==f.text)errors.push('Passage '+f.id+' no longer matches its source text at '+f.start+'–'+f.end+'.');
  }
  for(const p of s.projects){
    for(const id of p.ids)if(!fids.has(id))errors.push('Project “'+p.name+'” collects missing material '+id+'.');
    for(const b of p.editor?.blocks||[]){
      if(typeof b.text!=='string')errors.push('An editor block in “'+p.name+'” has no text.');
      if(b.fid&&!fids.has(b.fid))warnings.push('An editor block in “'+p.name+'” links to missing material; its text is kept.');
      if(b.sid&&!sids.has(b.sid))warnings.push('An editor block in “'+p.name+'” links to a missing source; its text is kept.');
    }
  }
  for(const [fid,eid] of Object.entries(s.preferred||{}))if(!eids.has(eid))warnings.push('A preference for '+fid+' points to a missing passage.');
  return {errors:[...new Set(errors)].slice(0,50),warnings:[...new Set(warnings)].slice(0,50),counts:summarize(s)};
}

root.StudioLib={LIMITS,WORKSPACE_FORMAT,WORKSPACE_VERSION,formatOf,isHiddenPath,normalizePath,segment,titleFor,materialKey,pageAt,importDocument,exportWorkspace,validateWorkspace,summarize};
})(globalThis);
