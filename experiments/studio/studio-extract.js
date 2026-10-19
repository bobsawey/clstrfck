/* clstrfck Studio: local file reading and text extraction (browser only).
 * Everything runs in this page. PDF.js and Mammoth are vendored under ./vendor
 * and loaded only when a PDF or DOCX is first imported.
 */
(function(root){
'use strict';
const L=root.StudioLib;
const PDFJS_DIR='vendor/pdfjs-4.10.38/',MAMMOTH_SRC='vendor/mammoth-1.8.0/mammoth.browser.min.js';

class ExtractError extends Error{constructor(status,message){super(message);this.status=status;}}

async function sha256(data){
  if(!root.crypto?.subtle)throw new ExtractError('failed','Secure hashing is unavailable in this context. Open Studio over http://127.0.0.1 or https.');
  const bytes=typeof data==='string'?new TextEncoder().encode(data):data;
  const buf=await root.crypto.subtle.digest('SHA-256',bytes);
  return Array.from(new Uint8Array(buf)).map(b=>b.toString(16).padStart(2,'0')).join('');
}

function decodeText(bytes){
  const u8=new Uint8Array(bytes),warnings=[];
  if(u8[0]===0xFF&&u8[1]===0xFE)return {text:new TextDecoder('utf-16le').decode(u8.subarray(2)),warnings:['Decoded as UTF-16 (little-endian).']};
  if(u8[0]===0xFE&&u8[1]===0xFF)return {text:new TextDecoder('utf-16be').decode(u8.subarray(2)),warnings:['Decoded as UTF-16 (big-endian).']};
  try{return {text:new TextDecoder('utf-8',{fatal:true,ignoreBOM:false}).decode(u8),warnings};}
  catch{return {text:new TextDecoder('windows-1252').decode(u8),warnings:['Not valid UTF-8; decoded as Windows-1252. Check accented characters.']};}
}

let pdfjsPromise=null;
function loadPdfjs(){
  pdfjsPromise||=import(new URL(PDFJS_DIR+'pdf.min.mjs',location.href).href).then(lib=>{lib.GlobalWorkerOptions.workerSrc=new URL(PDFJS_DIR+'pdf.worker.min.mjs',location.href).href;return lib;}).catch(err=>{pdfjsPromise=null;throw new ExtractError('failed','The PDF reader could not load ('+err.message+').');});
  return pdfjsPromise;
}
/* Rebuild readable lines from positioned text runs. Large vertical gaps and
 * column jumps become blank lines so paragraphs and sections separate. */
function pageText(items){
  const lines=[];let cur=null;
  for(const it of items){
    if(typeof it.str!=='string')continue;
    const x=it.transform[4],y=it.transform[5],h=Math.abs(it.height||it.transform[3])||10;
    if(cur&&Math.abs(y-cur.y)>h*0.5){lines.push(cur);cur=null;}
    if(!cur)cur={text:'',y,h,endX:x};
    else if(it.str&&!/^\s/.test(it.str)&&!/\s$/.test(cur.text)&&x-cur.endX>h*0.18)cur.text+=' ';
    cur.text+=it.str;cur.endX=x+(it.width||0);cur.h=Math.max(cur.h,h);
    if(it.hasEOL){lines.push(cur);cur=null;}
  }
  if(cur)lines.push(cur);
  const kept=lines.filter(l=>l.text.trim());
  const heights=kept.map(l=>l.h).sort((a,b)=>a-b),median=heights[Math.floor(heights.length/2)]||10;
  let out='';
  kept.forEach((l,i)=>{
    if(i){const prev=kept[i-1],gap=prev.y-l.y;out+=(gap>median*1.75||gap<-median)?'\n\n':'\n';}
    out+=l.text.replace(/\s+$/,'');
  });
  return out;
}
async function extractPdf(bytes){
  const lib=await loadPdfjs();let doc;
  try{doc=await lib.getDocument({data:new Uint8Array(bytes),isEvalSupported:false,useSystemFonts:false,disableFontFace:true}).promise;}
  catch(err){
    if(err?.name==='PasswordException')throw new ExtractError('encrypted','This PDF is password-protected. Remove the password and import it again.');
    throw new ExtractError('failed','This PDF could not be read ('+(err?.message||err)+').');
  }
  try{
    let text='';const pages=[];
    for(let n=1;n<=doc.numPages;n++){
      const page=await doc.getPage(n),content=await page.getTextContent();
      const body=pageText(content.items);
      if(text&&body)text+='\n\n';
      const start=text.length;text+=body;pages.push({page:n,start,end:text.length});
      page.cleanup();
    }
    const warnings=[];
    if(!text.trim())throw new ExtractError('no-text','No extractable text. This may be a scanned image; OCR is not supported yet.');
    const blank=pages.filter(p=>p.end===p.start).length;
    if(blank)warnings.push(blank+' of '+pages.length+' pages had no extractable text (possibly scanned).');
    if((text.match(/�/g)||[]).length>text.length*0.02)warnings.push('Many characters could not be decoded; check the extracted text.');
    warnings.push('PDF text order and line breaks are reconstructed; multi-column layouts may need review.');
    return {text,pages,warnings};
  }finally{doc.destroy();}
}

let mammothPromise=null;
function loadMammoth(){
  if(root.mammoth)return Promise.resolve(root.mammoth);
  mammothPromise||=new Promise((resolve,reject)=>{const s=document.createElement('script');s.src=MAMMOTH_SRC;s.onload=()=>root.mammoth?resolve(root.mammoth):reject(new Error('Mammoth did not initialise'));s.onerror=()=>reject(new Error('could not load '+MAMMOTH_SRC));document.head.append(s);}).catch(err=>{mammothPromise=null;throw new ExtractError('failed','The Word reader could not load ('+err.message+').');});
  return mammothPromise;
}
/* Convert Mammoth's HTML into plain text with Markdown-style headings and
 * bullets. The HTML is parsed inertly and only textContent is read. */
function htmlToText(html){
  const doc=new DOMParser().parseFromString('<body>'+html+'</body>','text/html');
  doc.querySelectorAll('br').forEach(br=>br.replaceWith('\n'));
  const clean=el=>el.textContent.replace(/[ \t ]+/g,' ').replace(/ *\n */g,'\n').trim();
  const blocks=[];
  const list=(el,depth)=>{
    const lines=[];let n=1;
    for(const li of el.children){
      if(li.tagName!=='LI')continue;
      const nested=[...li.children].filter(c=>c.tagName==='UL'||c.tagName==='OL');
      nested.forEach(c=>c.remove());
      const t=clean(li);
      if(t)lines.push('  '.repeat(depth)+(el.tagName==='OL'?(n++)+'. ':'- ')+t.replace(/\n/g,' '));
      nested.forEach(c=>lines.push(...list(c,depth+1)));
    }
    return lines;
  };
  for(const el of doc.body.children){
    const tag=el.tagName;
    if(/^H[1-6]$/.test(tag)){const t=clean(el);if(t)blocks.push('#'.repeat(Number(tag[1]))+' '+t.replace(/\n/g,' '));}
    else if(tag==='UL'||tag==='OL'){const lines=list(el,0);if(lines.length)blocks.push(lines.join('\n'));}
    else if(tag==='TABLE'){
      const rows=[...el.querySelectorAll('tr')].map(tr=>[...tr.children].map(clean).filter(Boolean).join(' | ')).filter(Boolean);
      rows.forEach(r=>blocks.push(r));
    }
    else{const t=clean(el);if(t)blocks.push(t);}
  }
  return blocks.join('\n\n');
}
async function extractDocx(bytes){
  const mammoth=await loadMammoth();let result;
  try{result=await mammoth.convertToHtml({arrayBuffer:bytes},{convertImage:mammoth.images.imgElement(()=>({src:''})),ignoreEmptyParagraphs:true});}
  catch(err){throw new ExtractError('failed','This Word document could not be read ('+(err?.message||err)+'). Only .docx is supported, not .doc.');}
  const text=htmlToText(result.value),warnings=[];
  if(!text.trim())throw new ExtractError('no-text','No text found in this Word document.');
  const notes=(result.messages||[]).filter(m=>m.type==='warning').length;
  if(notes)warnings.push(notes+' formatting notes from the Word reader; text was kept.');
  warnings.push('Word layout (columns, text boxes, headers) is flattened to text.');
  return {text,warnings};
}

/* Read one file into an import record. Throws ExtractError with a status. */
async function readFile(file,path){
  const format=L.formatOf(path);
  if(!format)throw new ExtractError('unsupported','Unsupported type. Use .txt, .md, .pdf or .docx.');
  const binary=format==='pdf'||format==='docx',limit=binary?L.LIMITS.maxBinaryFileBytes:L.LIMITS.maxTextFileBytes;
  if(file.size>limit)throw new ExtractError('too-large','Larger than '+Math.round(limit/1048576)+' MB.');
  if(!file.size)throw new ExtractError('empty','The file is empty.');
  const bytes=await file.arrayBuffer(),byteHash=await sha256(bytes);
  let out;
  if(format==='pdf')out=await extractPdf(bytes);
  else if(format==='docx')out=await extractDocx(bytes);
  else out=decodeText(bytes);
  const text=out.text.replace(/^﻿/,'');
  if(!text.trim())throw new ExtractError('empty','No text in this file.');
  return {path,format,text,pages:out.pages,warnings:out.warnings||[],size:file.size,modified:file.lastModified?new Date(file.lastModified).toISOString():null,byteHash,textHash:await sha256(text)};
}

/* Collect {file,path} from a drop. Directory readers return results in
 * batches, so each reader is drained until it returns an empty batch. */
async function filesFromDrop(dataTransfer){
  const entries=[...(dataTransfer.items||[])].filter(i=>i.kind==='file').map(i=>i.webkitGetAsEntry?.()).filter(Boolean);
  if(!entries.length)return {files:[...(dataTransfer.files||[])].map(file=>({file,path:'imports/'+file.name})),errors:[],ignored:[]};
  const files=[],errors=[],ignored=[];
  const walk=async(entry,prefix)=>{
    const path=prefix+entry.name;
    if(entry.name.startsWith('.')||entry.name==='__MACOSX'){ignored.push(path+(entry.isDirectory?'/':''));return;}
    try{
      if(entry.isFile){files.push({file:await new Promise((res,rej)=>entry.file(res,rej)),path:prefix?path:'imports/'+entry.name});return;}
      if(!entry.isDirectory)return;
      const reader=entry.createReader();let batch;
      do{batch=await new Promise((res,rej)=>reader.readEntries(res,rej));for(const child of batch)await walk(child,path+'/');}while(batch.length);
    }catch(err){errors.push({path,message:err?.message||'Could not read this item.'});}
  };
  for(const e of entries)await walk(e,'');
  return {files,errors,ignored};
}
function filesFromInput(input){
  const files=[],ignored=[];
  for(const file of input.files){
    const rel=L.normalizePath(file.webkitRelativePath||'');
    const path=rel||'imports/'+file.name;
    if(rel&&L.isHiddenPath(rel)){ignored.push(rel);continue;}
    files.push({file,path});
  }
  return {files,errors:[],ignored};
}

root.StudioExtract={ExtractError,sha256,decodeText,pageText,htmlToText,readFile,filesFromDrop,filesFromInput,loadPdfjs,loadMammoth};
})(globalThis);
